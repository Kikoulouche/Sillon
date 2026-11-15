"""Transfert vers VLC sur l'iPhone, en USB, via pymobiledevice3 (house_arrest / AFC).

Nécessite le service « Apple Mobile Device » (fourni par iTunes ou l'app Appareils Apple).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from pymobiledevice3.exceptions import (
    AppNotInstalledError,
    ConnectionFailedToUsbmuxdError,
    NoDeviceConnectedError,
    NotPairedError,
    PairingDialogResponsePendingError,
    PasswordRequiredError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.house_arrest import HouseArrestService

from . import core

VLC_BUNDLE_ID = "org.videolan.vlc-ios"
REMOTE_DIR = "/Documents"  # VLC scanne son dossier Documents au lancement
CHUNK = 1024 * 1024


@dataclass
class DeviceStatus:
    connected: bool
    name: str = ""
    ios: str = ""
    vlc: bool = False
    message: str = ""


def _friendly(exc: BaseException) -> str:
    if isinstance(exc, ConnectionFailedToUsbmuxdError):
        return "Service Apple introuvable : lance iTunes une fois (ou installe « Appareils Apple »)."
    if isinstance(exc, NoDeviceConnectedError):
        return "Aucun iPhone branché."
    if isinstance(exc, (PasswordRequiredError,)):
        return "Déverrouille ton iPhone."
    if isinstance(exc, (PairingDialogResponsePendingError, NotPairedError)):
        return "Sur l'iPhone, appuie sur « Se fier à cet ordinateur »."
    if isinstance(exc, AppNotInstalledError):
        return "VLC n'est pas installé sur l'iPhone."
    return f"{type(exc).__name__}: {exc}"


async def _status() -> DeviceStatus:
    try:
        lockdown = await create_using_usbmux()
    except Exception as exc:  # noqa: BLE001
        return DeviceStatus(False, message=_friendly(exc))
    try:
        name = lockdown.display_name or "iPhone"
        try:
            name = (await lockdown.get_value(key="DeviceName")) or name
        except Exception:
            pass
        st = DeviceStatus(True, name=name, ios=lockdown.product_version)
        try:
            ha = await HouseArrestService.create(lockdown, VLC_BUNDLE_ID, documents_only=True)
            await ha.close()
            st.vlc = True
        except Exception as exc:  # noqa: BLE001
            st.message = _friendly(exc)
        return st
    finally:
        await lockdown.close()


# --------------------------------------------------------------------------- scan de l'iPhone

CACHE_FILE = core.DATA_DIR / "iphone.json"
COVERS_DIR = core.DATA_DIR / "covers"
HEAD_SIZES = (256 * 1024, 1024 * 1024, 4 * 1024 * 1024)


@dataclass
class RemoteTrack:
    path: str  # chemin sur l'iPhone, ex. /Documents/Artiste - Titre.m4a
    size: int
    title: str
    artist: str
    video_id: str = ""
    duration: int = 0
    cover: str = ""  # chemin local de la pochette en cache

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)


def load_cache() -> dict[str, RemoteTrack]:
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return {k: RemoteTrack(**v) for k, v in raw.items()}
    except Exception:
        return {}


def save_cache(tracks: dict[str, RemoteTrack]) -> None:
    core.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({k: asdict(v) for k, v in tracks.items()}, ensure_ascii=False, indent=1),
                          encoding="utf-8")


async def _read_meta(ha: HouseArrestService, path: str, size: int) -> RemoteTrack:
    name = posixpath.basename(path)
    meta = None
    handle = await ha.fopen(path, "r")
    try:
        data = b""
        for want in HEAD_SIZES:
            want = min(want, size)
            while len(data) < want:
                chunk = await ha.fread(handle, min(CHUNK, want - len(data)))
                if not chunk:
                    break
                data += chunk
            try:
                meta = core.read_tags(data, name)
                break
            except Exception:
                if want >= size:
                    break
    finally:
        await ha.fclose(handle)
    if meta is None:
        artist, title = core.guess_from_filename(name)
        meta = {"title": title, "artist": artist, "video_id": "", "cover": None, "duration": 0}
    cover_path = ""
    if meta["cover"]:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(f"{path}|{size}".encode()).hexdigest()[:16]
        cp = COVERS_DIR / f"{key}.jpg"
        cp.write_bytes(meta["cover"])
        cover_path = str(cp)
    return RemoteTrack(path=path, size=size, title=meta["title"], artist=meta["artist"],
                       video_id=meta["video_id"], duration=meta["duration"], cover=cover_path)


ScanCb = Callable[[int, int, str], None]


async def _scan(progress: ScanCb | None) -> list[RemoteTrack]:
    lockdown = await create_using_usbmux()
    try:
        ha = await HouseArrestService.create(lockdown, VLC_BUNDLE_ID, documents_only=True)
        try:
            found: list[tuple[str, int]] = []
            async for root, dirs, files in ha.walk(REMOTE_DIR):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.startswith(".") or posixpath.splitext(f)[1].lower() not in core.AUDIO_EXT:
                        continue
                    p = posixpath.join(root, f)
                    found.append((p, int((await ha.stat(p))["st_size"])))
            cache = load_cache()
            result: dict[str, RemoteTrack] = {}
            for i, (p, size) in enumerate(found):
                if progress:
                    progress(i, len(found), posixpath.basename(p))
                c = cache.get(p)
                if c and c.size == size and (not c.cover or Path(c.cover).exists()):
                    result[p] = c
                else:
                    result[p] = await _read_meta(ha, p, size)
            save_cache(result)
            return list(result.values())
        finally:
            await ha.close()
    finally:
        await lockdown.close()


ProgressCb = Callable[[int, int, float, str], None]  # (index, total, fraction fichier, nom)


async def _push(files: list[Path], progress: ProgressCb | None) -> list[Path]:
    sent: list[Path] = []
    lockdown = await create_using_usbmux()
    try:
        ha = await HouseArrestService.create(lockdown, VLC_BUNDLE_ID, documents_only=True)
        try:
            for i, f in enumerate(files):
                remote = f"{REMOTE_DIR}/{f.name}"
                data = f.read_bytes()
                tmp = remote + ".part"
                handle = await ha.fopen(tmp, "w")
                try:
                    for off in range(0, len(data), CHUNK):
                        await ha.fwrite(handle, data[off:off + CHUNK])
                        if progress:
                            progress(i, len(files), min((off + CHUNK) / max(len(data), 1), 1.0), f.name)
                finally:
                    await ha.fclose(handle)
                if await ha.exists(remote):
                    await ha.rm_single(remote, force=True)
                await ha.rename(tmp, remote)
                sent.append(f)
                _remember_sent(f, remote, len(data))
        finally:
            await ha.close()
    finally:
        await lockdown.close()
    return sent


def _remember_sent(local: Path, remote: str, size: int) -> None:
    """Ajoute au cache un fichier qu'on vient d'envoyer (évite de le relire au prochain scan)."""
    try:
        cache = load_cache()
        data = local.read_bytes()[: HEAD_SIZES[-1]]
        meta = core.read_tags(data, local.name)
        cover = ""
        if meta["cover"]:
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            cp = COVERS_DIR / (hashlib.sha1(f"{remote}|{size}".encode()).hexdigest()[:16] + ".jpg")
            cp.write_bytes(meta["cover"])
            cover = str(cp)
        cache[remote] = RemoteTrack(remote, size, meta["title"], meta["artist"], meta["video_id"],
                                    meta["duration"], cover)
        save_cache(cache)
    except Exception:
        pass


async def _delete(paths: list[str]) -> None:
    lockdown = await create_using_usbmux()
    try:
        ha = await HouseArrestService.create(lockdown, VLC_BUNDLE_ID, documents_only=True)
        try:
            for p in paths:
                if not p.startswith("/"):
                    p = f"{REMOTE_DIR}/{p}"
                if await ha.exists(p):
                    await ha.rm_single(p, force=True)
        finally:
            await ha.close()
    finally:
        await lockdown.close()
    cache = load_cache()
    for p in paths:
        c = cache.pop(p if p.startswith("/") else f"{REMOTE_DIR}/{p}", None)
        if c and c.cover:
            Path(c.cover).unlink(missing_ok=True)
    save_cache(cache)


# --------------------------------------------------------------------------- API synchrone

def status() -> DeviceStatus:
    return asyncio.run(_status())


def scan(progress: ScanCb | None = None) -> list[RemoteTrack]:
    try:
        return asyncio.run(_scan(progress))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(_friendly(exc)) from exc


def known_video_ids() -> set[str]:
    """Identifiants YouTube présents sur l'iPhone (d'après le dernier scan)."""
    return {t.video_id for t in load_cache().values() if t.video_id}


def push(files: list[Path], progress: ProgressCb | None = None) -> list[Path]:
    try:
        return asyncio.run(_push(files, progress))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(_friendly(exc)) from exc


def delete(names: list[str]) -> None:
    try:
        asyncio.run(_delete(names))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(_friendly(exc)) from exc
