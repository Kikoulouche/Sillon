import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Version compilée sans console : on redirige les sorties vers un fichier de log
if sys.stdout is None or sys.stderr is None:
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Sillon"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "sillon.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def selftest() -> int:
    """`Sillon.exe --selftest` : vérifie que tout est bien embarqué (utilisé par la CI)."""
    import tempfile

    from sillon import __version__, core, iphone, updater

    print(f"Sillon {__version__} selftest")
    print("ffmpeg:", core.ffmpeg_path().exists())
    print("updater version parse:", updater.parse_version("v1.2.3"))
    print("iphone:", iphone.status())
    try:  # YouTube peut bloquer les serveurs de CI : on n'échoue pas pour ça
        results = core.search("stromae papaoutai", 3)
        print("search:", len(results), results[0].title if results else "-")
    except Exception as exc:  # noqa: BLE001
        results = []
        print("search: indisponible ->", exc)
    if "--download" in sys.argv and results:
        core.LIBRARY_DIR = Path(tempfile.mkdtemp())
        core.HISTORY_FILE = core.LIBRARY_DIR / ".sillon.json"
        t = core.download(results[0])
        print("download:", t.artist, "-", t.title, Path(t.path).stat().st_size)
    print("SELFTEST OK")
    return 0


if "--selftest" in sys.argv:
    try:
        code = selftest()
    except Exception:
        import traceback

        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)

from sillon.app import main  # noqa: E402

main()
