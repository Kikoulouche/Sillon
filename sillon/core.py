"""Moteur de Sillon : recherche YouTube, téléchargement M4A, tags et bibliothèque locale."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yt_dlp
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

APP_DIR = Path(__file__).resolve().parent.parent  # dossier _internal une fois compilé
LIBRARY_DIR = Path.home() / "Music" / "Sillon"
HISTORY_FILE = LIBRARY_DIR / ".sillon.json"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Sillon"
BIN_DIR = DATA_DIR / "bin"


# --------------------------------------------------------------------------- ffmpeg

def ffmpeg_path() -> Path:
    """Copie le ffmpeg fourni par imageio-ffmpeg dans bin/ffmpeg.exe (une seule fois)."""
    target = BIN_DIR / "ffmpeg.exe"
    if not target.exists():
        import imageio_ffmpeg

        BIN_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target)
    return target


# --------------------------------------------------------------------------- modèles

@dataclass
class SearchResult:
    video_id: str
    title: str
    channel: str
    duration: int  # secondes
    thumbnail: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "–"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class Track:
    video_id: str
    title: str
    artist: str
    path: str
    on_iphone: bool = False
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- nettoyage des titres

_NOISE = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*?\b("
    r"official|officiel|officielle|video|vidéo|clip|audio|lyrics?|paroles|visuali[sz]er|"
    r"hd|hq|4k|remaster(ed)?|music\s*video|mv|live\s*session"
    r")\b[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_TAIL = re.compile(r"\s*[|｜]\s*.*$")


def clean_metadata(raw_title: str, channel: str) -> tuple[str, str]:
    """Devine (artiste, titre) à partir du titre YouTube et de la chaîne."""
    title = _NOISE.sub("", raw_title)
    title = _TAIL.sub("", title)
    title = re.sub(r"\s{2,}", " ", title).strip(" -–—")

    artist = re.sub(r"\s*-\s*Topic$|VEVO$|\s+Officiel$|\s+Official$", "", channel or "", flags=re.I).strip()
    for sep in (" - ", " – ", " — ", " ~ "):
        if sep in title:
            left, right = title.split(sep, 1)
            artist, title = left.strip(), right.strip()
            break
    title = title.strip(' "\'“”«»')
    return artist or "Artiste inconnu", title or raw_title


def safe_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".")[:120] or "morceau"


# --------------------------------------------------------------------------- recherche

def search(query: str, limit: int = 20) -> list[SearchResult]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    results = []
    for e in info.get("entries") or []:
        if not e or e.get("ie_key") not in (None, "Youtube"):
            continue
        vid = e.get("id")
        if not vid or len(vid) != 11:
            continue
        thumbs = e.get("thumbnails") or []
        thumb = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
        results.append(
            SearchResult(
                video_id=vid,
                title=e.get("title") or "",
                channel=e.get("channel") or e.get("uploader") or "",
                duration=int(e.get("duration") or 0),
                thumbnail=thumb,
            )
        )
    return results


def fetch_bytes(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------- téléchargement

ProgressCb = Callable[[float, str], None]


def download(result: SearchResult, progress: ProgressCb | None = None) -> Track:
    """Télécharge l'audio en M4A, ajoute titre/artiste/pochette, renvoie le Track."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    artist, title = clean_metadata(result.title, result.channel)
    final = LIBRARY_DIR / f"{safe_filename(artist)} - {safe_filename(title)}.m4a"
    tmp_base = LIBRARY_DIR / f".dl-{result.video_id}"

    def hook(d):
        if not progress:
            return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            progress(min(done / total, 1.0) * 0.85 if total else 0.0, "Téléchargement…")
        elif d["status"] == "finished":
            progress(0.88, "Conversion…")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(tmp_base) + ".%(ext)s",
        "ffmpeg_location": str(ffmpeg_path()),
        "progress_hooks": [hook],
        "overwrites": True,
        "retries": 5,
        "fragment_retries": 5,
    }
    # YouTube renvoie parfois un 403 passager sur l'URL du flux : on ré-extrait et on réessaie
    for attempt in range(4):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(result.url, download=True)
                src = Path(ydl.prepare_filename(info))
            break
        except yt_dlp.utils.DownloadError as exc:
            if attempt == 3 or not any(c in str(exc) for c in ("403", "429", "timed out", "Connection")):
                raise
            if progress:
                progress(0.0, f"Nouvel essai ({attempt + 2}/4)…")
            time.sleep(1.5 * (attempt + 1))
    if not src.exists():  # yt-dlp a pu changer l'extension
        candidates = list(LIBRARY_DIR.glob(f".dl-{result.video_id}.*"))
        if not candidates:
            raise RuntimeError("Fichier téléchargé introuvable")
        src = candidates[0]

    # Remux (ou conversion si la source n'est pas de l'AAC) vers un M4A propre
    codec = ["-c:a", "copy"] if src.suffix.lower() in (".m4a", ".mp4") else ["-c:a", "aac", "-b:a", "192k"]
    tmp_out = tmp_base.with_suffix(".out.m4a")
    subprocess.run(
        [str(ffmpeg_path()), "-y", "-loglevel", "error", "-i", str(src), "-vn", *codec,
         "-movflags", "+faststart", str(tmp_out)],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    src.unlink(missing_ok=True)
    tmp_out.replace(final)

    if progress:
        progress(0.94, "Pochette et infos…")
    tag(final, title=title, artist=artist, video_id=result.video_id,
        album=(info.get("album") or ""), year=str(info.get("release_year") or info.get("upload_date", "")[:4] or ""))

    if progress:
        progress(1.0, "Prêt")
    track = Track(video_id=result.video_id, title=title, artist=artist, path=str(final))
    History.load().add(track)
    return track


def square_cover(video_id: str) -> bytes | None:
    for name in ("maxresdefault", "hqdefault", "mqdefault"):
        try:
            data = fetch_bytes(f"https://i.ytimg.com/vi/{video_id}/{name}.jpg")
        except Exception:
            continue
        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        if w < 200:
            continue
        # les miniatures 4:3 (hq) ont des bandes noires : on recadre le centre 16:9 puis le carré
        if abs(w / h - 4 / 3) < 0.05:
            band = int((h - w * 9 / 16) / 2)
            img = img.crop((0, band, w, h - band))
            w, h = img.size
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((600, 600), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    return None


def tag(path: Path, *, title: str, artist: str, video_id: str, album: str = "", year: str = "") -> None:
    audio = MP4(str(path))
    audio["\xa9nam"] = [title]
    audio["\xa9ART"] = [artist]
    audio["aART"] = [artist]
    audio["\xa9alb"] = [album or title]
    if year:
        audio["\xa9day"] = [year]
    audio["\xa9cmt"] = [f"youtube:{video_id}"]
    cover = square_cover(video_id)
    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


# --------------------------------------------------------------------------- lecture des tags

AUDIO_EXT = {".m4a", ".mp3", ".aac", ".flac", ".wav", ".ogg", ".opus", ".alac", ".aiff", ".wma"}


def read_tags(data: bytes, name: str) -> dict:
    """Lit titre/artiste/pochette/id YouTube depuis le début d'un fichier audio.

    Lève une exception si les données sont trop tronquées pour être analysées.
    """
    import mutagen

    f = mutagen.File(io.BytesIO(data))
    if f is None:
        raise ValueError("format inconnu")
    title = artist = video_id = ""
    cover: bytes | None = None
    tags = f.tags or {}
    if hasattr(tags, "getall"):  # ID3 (mp3)
        title = str(tags.get("TIT2") or "")
        artist = str(tags.get("TPE1") or "")
        pics = tags.getall("APIC")
        cover = pics[0].data if pics else None
    elif "\xa9nam" in tags or "\xa9ART" in tags or "covr" in tags:  # MP4
        title = (tags.get("\xa9nam") or [""])[0]
        artist = (tags.get("\xa9ART") or [""])[0]
        cmt = (tags.get("\xa9cmt") or [""])[0]
        if cmt.startswith("youtube:"):
            video_id = cmt.split(":", 1)[1]
        covr = tags.get("covr")
        cover = bytes(covr[0]) if covr else None
    else:  # Vorbis / FLAC / autres
        try:
            title = (tags.get("title") or [""])[0]
            artist = (tags.get("artist") or [""])[0]
        except Exception:
            pass
        pics = getattr(f, "pictures", None)
        cover = pics[0].data if pics else None
    guess_artist, guess_title = guess_from_filename(name)
    return {
        "title": title or guess_title,
        "artist": artist or guess_artist,
        "video_id": video_id,
        "cover": cover,
        "duration": int(getattr(f.info, "length", 0) or 0),
    }


def guess_from_filename(name: str) -> tuple[str, str]:
    stem = Path(name).stem
    if " - " in stem:
        a, t = stem.split(" - ", 1)
        return a.strip(), t.strip()
    return "", stem


# --------------------------------------------------------------------------- réglages

SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_SETTINGS = {"auto_sync": True}


def load_settings() -> dict:
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_setting(key: str, value) -> None:
    s = load_settings()
    s[key] = value
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- historique

class History:
    def __init__(self, tracks: dict[str, Track]):
        self.tracks = tracks

    @classmethod
    def load(cls) -> History:
        try:
            raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            tracks = {k: Track(**v) for k, v in raw.items()}
        except Exception:
            tracks = {}
        # on oublie les fichiers supprimés à la main
        return cls({k: t for k, t in tracks.items() if Path(t.path).exists()})

    def save(self) -> None:
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps({k: asdict(t) for k, t in self.tracks.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, track: Track) -> None:
        self.tracks[track.video_id] = track
        self.save()

    def mark_on_iphone(self, video_id: str, value: bool = True) -> None:
        if video_id in self.tracks:
            self.tracks[video_id].on_iphone = value
            self.save()

    def has(self, video_id: str) -> bool:
        return video_id in self.tracks
