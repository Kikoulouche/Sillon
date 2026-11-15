"""Mises à jour automatiques via les GitHub Releases.

Fonctionnement :
1. au démarrage (puis toutes les 6 h) Sillon interroge l'API GitHub pour la dernière release ;
2. si elle est plus récente, l'archive Windows est téléchargée et décompressée en arrière-plan ;
3. au redémarrage (bouton dans l'app, ou simple fermeture), un petit script PowerShell attend
   la fin de Sillon, remplace les fichiers du programme, puis relance l'app si demandé.

Les données de l'utilisateur (musiques, historique, cache iPhone) ne sont jamais dans le dossier
du programme, une mise à jour ne les touche donc pas.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "Kikoulouche/Sillon"
ASSET_SUFFIX = "windows-x64.zip"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
STAGING = Path(tempfile.gettempdir()) / "sillon-update"


@dataclass
class Update:
    version: str
    notes: str
    url: str
    size: int
    page: str


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_frozen() -> bool:
    """True quand Sillon tourne depuis l'exécutable (version installée), pas depuis le code source."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def check(current: str = __version__) -> Update | None:
    req = urllib.request.Request(API, headers={"User-Agent": "Sillon-updater",
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # pas encore de release publiée
            return None
        raise
    tag = data.get("tag_name", "")
    if parse_version(tag) <= parse_version(current):
        return None
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(ASSET_SUFFIX)), None)
    if not asset:
        return None
    return Update(version=tag.lstrip("v"), notes=data.get("body") or "", url=asset["browser_download_url"],
                  size=int(asset.get("size") or 0), page=data.get("html_url", ""))


def download(update: Update, progress: Callable[[float], None] | None = None) -> Path:
    """Télécharge et décompresse la mise à jour. Renvoie le dossier prêt à copier."""
    shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True)
    archive = STAGING / "update.zip"
    req = urllib.request.Request(update.url, headers={"User-Agent": "Sillon-updater"})
    with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as f:
        total = int(r.headers.get("Content-Length") or update.size or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    out = STAGING / "new"
    with zipfile.ZipFile(archive) as z:
        for m in z.namelist():  # protection contre les chemins hors du dossier
            if m.startswith("/") or ".." in Path(m).parts:
                raise RuntimeError("Archive de mise à jour invalide")
        z.extractall(out)
    archive.unlink()
    root = out / "Sillon" if (out / "Sillon" / "Sillon.exe").exists() else out
    if not (root / "Sillon.exe").exists():
        raise RuntimeError("Sillon.exe absent de la mise à jour")
    (STAGING / "ready.json").write_text(json.dumps({"version": update.version, "dir": str(root)}), encoding="utf-8")
    return root


def pending() -> dict | None:
    """Mise à jour déjà téléchargée et prête à installer."""
    try:
        info = json.loads((STAGING / "ready.json").read_text(encoding="utf-8"))
        if parse_version(info["version"]) > parse_version(__version__) and Path(info["dir"], "Sillon.exe").exists():
            return info
    except Exception:
        pass
    return None


def apply(relaunch: bool) -> bool:
    """Lance le script de remplacement ; l'app doit quitter juste après. Renvoie False si impossible."""
    info = pending()
    if not info or not is_frozen():
        return False
    target = install_dir()
    script = STAGING / "apply.ps1"
    script.write_text(
        f"""$ErrorActionPreference = 'SilentlyContinue'
Wait-Process -Id {os.getpid()} -Timeout 60
Start-Sleep -Milliseconds 500
robocopy "{info['dir']}" "{target}" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS | Out-Null
Remove-Item -Recurse -Force "{STAGING / 'new'}"
Remove-Item -Force "{STAGING / 'ready.json'}"
{f'Start-Process "{target / "Sillon.exe"}"' if relaunch else ''}
""",
        encoding="utf-8-sig",
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    return True
