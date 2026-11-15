"""Interface graphique de Sillon."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from pathlib import Path

from mutagen.mp4 import MP4
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__, core, iphone, updater

ASSETS = core.APP_DIR / "assets"

# --------------------------------------------------------------------------- identité visuelle
C = {
    "bg": "#0F0E13",
    "surface": "#17151D",
    "surface2": "#201D28",
    "hover": "#29253300",
    "border": "#2B2735",
    "text": "#F3EFE9",
    "muted": "#8E8799",
    "accent": "#FF7A3D",
    "accent_hi": "#FF9460",
    "accent_soft": "#3A2219",
    "ok": "#6BD69A",
    "ok_soft": "#173225",
    "danger": "#FF6170",
}

QSS = f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; color: {C['text']}; }}
QWidget#root {{ background: {C['bg']}; }}
QLabel#brand {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#tagline {{ color: {C['muted']}; font-size: 12px; }}
QLabel#h2 {{ font-size: 15px; font-weight: 600; }}
QLabel#muted, QLabel.muted {{ color: {C['muted']}; font-size: 12px; }}
QLabel#empty {{ color: {C['muted']}; font-size: 13px; }}

QLineEdit#search {{
    background: {C['surface2']}; border: 1px solid {C['border']}; border-radius: 14px;
    padding: 12px 18px; font-size: 15px; selection-background-color: {C['accent']};
}}
QLineEdit#search:focus {{ border: 1px solid {C['accent']}; }}

QPushButton {{
    background: {C['surface2']}; border: 1px solid {C['border']}; border-radius: 10px;
    padding: 8px 14px; font-size: 13px;
}}
QPushButton:hover {{ border-color: {C['muted']}; }}
QPushButton:disabled {{ color: {C['muted']}; }}
QPushButton#primary {{
    background: {C['accent']}; border: none; color: #1A0E08; font-weight: 700; font-size: 14px; padding: 13px 18px;
}}
QPushButton#primary:hover {{ background: {C['accent_hi']}; }}
QPushButton#primary:disabled {{ background: {C['accent_soft']}; color: {C['muted']}; }}
QPushButton#add {{
    background: transparent; border: 1px solid {C['border']}; border-radius: 17px;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0; font-size: 18px;
}}
QPushButton#add:hover {{ border-color: {C['accent']}; color: {C['accent']}; }}
QPushButton#add[state="queued"] {{ background: {C['accent']}; border-color: {C['accent']}; color: #1A0E08; }}
QPushButton#add[state="owned"] {{ background: {C['ok_soft']}; border-color: {C['ok_soft']}; color: {C['ok']}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {C['muted']}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ color: {C['text']}; }}
QPushButton#tab {{
    background: transparent; border: none; border-radius: 9px; padding: 8px 16px; color: {C['muted']}; font-weight: 600;
}}
QPushButton#tab:checked {{ background: {C['surface2']}; color: {C['text']}; }}

QFrame#panel {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 18px; }}
QFrame#chip {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 16px; }}
QFrame#update {{ background: {C['accent_soft']}; border: 1px solid {C['accent']}; border-radius: 16px; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border: none; border-radius: 12px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {C['surface2']}; }}
QListWidget::item:selected {{ background: {C['surface2']}; }}

QProgressBar {{ background: {C['surface2']}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMessageBox {{ background: {C['surface']}; }}
"""


# --------------------------------------------------------------------------- threads

class WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, with_progress: bool = False):
        super().__init__()
        self.fn, self.args, self.with_progress = fn, args, with_progress
        self.signals = WorkerSignals()

    def _emit(self, signal, value):
        try:
            signal.emit(value)
        except RuntimeError:  # fenêtre fermée pendant que la tâche tournait
            pass

    def run(self):
        try:
            if self.with_progress:
                res = self.fn(*self.args, lambda v: self._emit(self.signals.progress, v))
            else:
                res = self.fn(*self.args)
            self._emit(self.signals.done, res)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._emit(self.signals.error, str(exc))


def rounded(pix: QPixmap, w: int, h: int, radius: int) -> QPixmap:
    pix = pix.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (pix.width() - w) // 2, (pix.height() - h) // 2
    pix = pix.copy(x, y, w, h)
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


def elide(label: QLabel, text: str):
    label.setToolTip(text)
    label.setText(text)


# --------------------------------------------------------------------------- lignes

class ResultRow(QWidget):
    toggled = Signal(object)

    def __init__(self, result: core.SearchResult, owned: bool):
        super().__init__()
        self.result = result
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setFixedSize(112, 63)
        self.thumb.setStyleSheet(f"background:{C['surface2']}; border-radius:8px;")
        lay.addWidget(self.thumb)

        artist, title = core.clean_metadata(result.title, result.channel)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("font-size:14px; font-weight:600;")
        t.setToolTip(result.title)
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub = QLabel(f"{artist}   ·   {result.duration_text}")
        sub.setProperty("class", "muted")
        sub.setObjectName("muted")
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        src = QLabel(f"YouTube · {result.channel}")
        src.setObjectName("muted")
        src.setStyleSheet("font-size:11px;")
        src.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addStretch()
        col.addWidget(t)
        col.addWidget(sub)
        col.addWidget(src)
        col.addStretch()
        lay.addLayout(col, 1)

        self.btn = QPushButton("+")
        self.btn.setObjectName("add")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(lambda: self.toggled.emit(self.result))
        lay.addWidget(self.btn)
        self.set_state("owned" if owned else "idle")

    def set_thumb(self, pix: QPixmap):
        self.thumb.setPixmap(rounded(pix, 112, 63, 8))

    def set_state(self, state: str):
        self.btn.setProperty("state", state)
        self.btn.setText({"idle": "+", "queued": "✓", "owned": "✓"}[state])
        self.btn.setToolTip({"idle": "Ajouter à la file", "queued": "Retirer de la file",
                             "owned": "Déjà dans ta bibliothèque"}[state])
        self.btn.setEnabled(state != "owned")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)


class QueueRow(QWidget):
    remove = Signal(str)

    def __init__(self, result: core.SearchResult):
        super().__init__()
        self.vid = result.video_id
        artist, title = core.clean_metadata(result.title, result.channel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 8, 9)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("font-size:13px; font-weight:600;")
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        a = QLabel(artist)
        a.setObjectName("muted")
        a.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(t)
        col.addWidget(a)
        top.addLayout(col, 1)
        self.status = QLabel("En attente")
        self.status.setObjectName("muted")
        self.status.setMinimumWidth(120)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.status)
        self.x = QPushButton("✕")
        self.x.setObjectName("ghost")
        self.x.setCursor(Qt.PointingHandCursor)
        self.x.clicked.connect(lambda: self.remove.emit(self.vid))
        top.addWidget(self.x)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

    def set_progress(self, frac: float, text: str, color: str | None = None):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};" if color else "")


class Entry:
    """Un morceau de la bibliothèque : sur le PC, sur l'iPhone, ou les deux."""

    def __init__(self, local: core.Track | None = None, remote: iphone.RemoteTrack | None = None):
        self.local, self.remote = local, remote

    @property
    def title(self) -> str:
        return (self.local or self.remote).title

    @property
    def artist(self) -> str:
        return (self.local or self.remote).artist or "Artiste inconnu"

    def cover(self) -> QPixmap:
        pix = QPixmap()
        if self.remote and self.remote.cover:
            pix.load(self.remote.cover)
        if pix.isNull() and self.local:
            try:
                data = MP4(self.local.path).tags.get("covr")
                if data:
                    pix.loadFromData(bytes(data[0]))
            except Exception:
                pass
        return pix if not pix.isNull() else QPixmap(str(ASSETS / "sillon-256.png"))


def build_entries() -> list[Entry]:
    hist = core.History.load()
    remote = iphone.load_cache()
    by_name = {Path(r.path).name.lower(): r for r in remote.values()}
    entries, used = [], set()
    for t in hist.tracks.values():
        r = by_name.get(Path(t.path).name.lower())
        if r:
            used.add(r.path)
        entries.append(Entry(t, r))
    entries += [Entry(None, r) for r in remote.values() if r.path not in used]
    entries.sort(key=lambda e: (e.artist.lower(), e.title.lower()))
    return entries


class LibraryRow(QWidget):
    delete = Signal(object)

    def __init__(self, entry: Entry):
        super().__init__()
        self.entry = entry
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(14)
        cover = QLabel()
        cover.setFixedSize(46, 46)
        cover.setPixmap(rounded(entry.cover(), 46, 46, 8))
        lay.addWidget(cover)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(entry.title)
        t.setStyleSheet("font-size:13px; font-weight:600;")
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        a = QLabel(entry.artist)
        a.setObjectName("muted")
        a.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(t)
        col.addWidget(a)
        lay.addLayout(col, 1)
        if entry.remote and entry.local:
            text, bg, fg = "iPhone + PC", C["ok_soft"], C["ok"]
        elif entry.remote:
            text, bg, fg = "iPhone", C["ok_soft"], C["ok"]
        else:
            text, bg, fg = "PC seulement", C["surface2"], C["muted"]
        pill = QLabel(text)
        pill.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:10px; padding:3px 10px;"
                           "font-size:11px; font-weight:600;")
        pill.setFixedHeight(22)
        lay.addWidget(pill, 0, Qt.AlignVCenter)
        d = QPushButton("Supprimer")
        d.setObjectName("ghost")
        d.setCursor(Qt.PointingHandCursor)
        d.clicked.connect(lambda: self.delete.emit(self.entry))
        lay.addWidget(d)


# --------------------------------------------------------------------------- fenêtre

def pipeline(items: list[core.SearchResult], emit):
    """Télécharge la file, puis envoie sur l'iPhone tout ce qui n'y est pas encore."""
    hist = core.History.load()
    on_phone = iphone.known_video_ids()
    failed = 0
    for r in items:
        if r.video_id in on_phone and not hist.has(r.video_id):
            emit(("sent", r.video_id))
            continue
        if hist.has(r.video_id):
            emit(("dl", r.video_id, 1.0, "Déjà téléchargé"))
            continue
        emit(("dl", r.video_id, 0.02, "Démarrage…"))
        try:
            core.download(r, lambda p, m, vid=r.video_id: emit(("dl", vid, p, m)))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            emit(("err", r.video_id, str(exc)))

    hist = core.History.load()
    pending = [t for t in hist.tracks.values() if not t.on_iphone]
    if not pending:
        return {"sent": 0, "failed": failed, "device": True}
    st = iphone.status()
    if not (st.connected and st.vlc):
        return {"sent": 0, "failed": failed, "device": False, "msg": st.message, "pending": len(pending)}

    by_name = {Path(t.path).name: t for t in pending}
    emit(("push", 0, len(pending), 0.0, ""))
    sent = iphone.push([Path(t.path) for t in pending],
                       lambda i, n, f, name: emit(("push", i, n, f, name, by_name[name].video_id)))
    for f in sent:
        hist.mark_on_iphone(by_name[f.name].video_id)
        emit(("sent", by_name[f.name].video_id))
    return {"sent": len(sent), "failed": failed, "device": True}


def scan_iphone(emit):
    """Scanne VLC sur l'iPhone et met à jour l'état « sur l'iPhone » des morceaux du PC."""
    remote = iphone.scan(lambda i, n, name: emit((i, n, name)))
    names = {Path(r.path).name.lower() for r in remote}
    hist = core.History.load()
    for t in hist.tracks.values():
        t.on_iphone = Path(t.path).name.lower() in names
    hist.save()
    return len(remote)


def delete_entries(entries: list[Entry]):
    remote = [e.remote.path for e in entries if e.remote]
    if remote:
        st = iphone.status()
        if not (st.connected and st.vlc):
            raise RuntimeError("Branche l'iPhone pour supprimer le morceau de VLC.")
        iphone.delete(remote)
    hist = core.History.load()
    for e in entries:
        if e.local:
            Path(e.local.path).unlink(missing_ok=True)
            hist.tracks.pop(e.local.video_id, None)
    hist.save()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Sillon")
        self.setWindowIcon(QIcon(str(ASSETS / "sillon.ico")))
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        self.pool = QThreadPool.globalInstance()
        self.net = QNetworkAccessManager(self)
        self.queue: dict[str, core.SearchResult] = {}
        self.queue_rows: dict[str, QueueRow] = {}
        self.result_rows: dict[str, ResultRow] = {}
        self.busy = False
        self.polling = False
        self.scanning = False
        self.device = iphone.DeviceStatus(False, message="Recherche de l'iPhone…")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(18)
        root.addLayout(self._header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._search_page())
        self.stack.addWidget(self._library_page())
        root.addWidget(self.stack, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_device)
        self.timer.start(3000)
        self.poll_device()
        self.search_input.setFocus()

        self.update_info: updater.Update | None = None
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.check_updates)
        self.update_timer.start(6 * 3600 * 1000)
        if updater.pending():
            self._show_update_ready(updater.pending()["version"])
        else:
            QTimer.singleShot(4000, self.check_updates)

    # ----------------------------------------------------------------- mises à jour
    def check_updates(self):
        if updater.pending():
            return
        w = Worker(updater.check)
        w.signals.done.connect(self._on_update_found)
        w.signals.error.connect(lambda m: print("update check:", m))
        self.pool.start(w)

    def _on_update_found(self, upd):
        if not upd:
            return
        self.update_info = upd
        if not updater.is_frozen():  # lancé depuis le code source : on signale seulement
            self.upd_label.setText(f"Version {upd.version} disponible")
            self.upd_btn.setText("Voir")
            self.upd.show()
            return
        self.upd_label.setText(f"Téléchargement de la version {upd.version}…")
        self.upd_btn.hide()
        self.upd.show()
        w = Worker(updater.download, upd)
        w.signals.done.connect(lambda _p: self._show_update_ready(upd.version))
        w.signals.error.connect(lambda m: self.upd.hide())
        self.pool.start(w)

    def _show_update_ready(self, version: str):
        self.upd_label.setText(f"Sillon {version} est prête")
        self.upd_btn.setText("Redémarrer")
        self.upd_btn.show()
        self.upd.show()

    def _update_clicked(self):
        if not updater.is_frozen():
            if self.update_info:
                QDesktopServices.openUrl(QUrl(self.update_info.page))
            return
        if self.busy or self.scanning:
            self.upd_label.setText("Attends la fin de l'envoi…")
            return
        if updater.apply(relaunch=True):
            QApplication.quit()

    def closeEvent(self, event):
        # mise à jour prête : on l'installe discrètement en fermant
        if updater.pending() and updater.is_frozen():
            updater.apply(relaunch=False)
        super().closeEvent(event)

    # ----------------------------------------------------------------- en-tête
    def _header(self):
        h = QHBoxLayout()
        h.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ASSETS / "sillon-256.png")).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        h.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        b = QLabel("Sillon")
        b.setObjectName("brand")
        tg = QLabel("Ta musique, gravée sur ton iPhone.")
        tg.setObjectName("tagline")
        col.addWidget(b)
        col.addWidget(tg)
        h.addLayout(col)
        h.addSpacing(24)

        tabs = QFrame()
        tabs.setObjectName("chip")
        b.setToolTip(f"Sillon {__version__}")
        tl = QHBoxLayout(tabs)
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(2)
        self.tab_search = QPushButton("Rechercher")
        self.tab_lib = QPushButton("Ma bibliothèque")
        for i, btn in enumerate((self.tab_search, self.tab_lib)):
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=i: self.show_page(i))
            tl.addWidget(btn)
        self.tab_search.setChecked(True)
        h.addWidget(tabs)
        h.addStretch()

        # bandeau de mise à jour (caché tant qu'il n'y a rien)
        self.upd = QFrame()
        self.upd.setObjectName("update")
        ul = QHBoxLayout(self.upd)
        ul.setContentsMargins(14, 6, 6, 6)
        ul.setSpacing(10)
        self.upd_label = QLabel()
        self.upd_label.setStyleSheet(f"color:{C['accent']}; font-weight:600; font-size:12px;")
        ul.addWidget(self.upd_label)
        self.upd_btn = QPushButton()
        self.upd_btn.setObjectName("primary")
        self.upd_btn.setStyleSheet("padding:6px 12px; font-size:12px;")
        self.upd_btn.setCursor(Qt.PointingHandCursor)
        self.upd_btn.clicked.connect(self._update_clicked)
        ul.addWidget(self.upd_btn)
        self.upd.hide()
        h.addWidget(self.upd)
        h.addSpacing(8)

        chip = QFrame()
        chip.setObjectName("chip")
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(14, 8, 16, 8)
        cl.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        cl.addWidget(self.dot)
        dc = QVBoxLayout()
        dc.setSpacing(0)
        self.dev_name = QLabel()
        self.dev_name.setStyleSheet("font-weight:600; font-size:13px;")
        self.dev_sub = QLabel()
        self.dev_sub.setObjectName("muted")
        self.dev_sub.setStyleSheet("font-size:11px;")
        dc.addWidget(self.dev_name)
        dc.addWidget(self.dev_sub)
        cl.addLayout(dc)
        h.addWidget(chip)
        self._render_device()
        return h

    def show_page(self, i: int):
        self.stack.setCurrentIndex(i)
        self.tab_search.setChecked(i == 0)
        self.tab_lib.setChecked(i == 1)
        if i == 1:
            self.load_library()

    # ----------------------------------------------------------------- page recherche
    def _search_page(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(14)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("search")
        self.search_input.setPlaceholderText("Rechercher un titre, un artiste…   (Entrée)")
        self.search_input.returnPressed.connect(self.do_search)
        self.search_input.setClearButtonEnabled(True)
        left.addWidget(self.search_input)

        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 10, 10, 10)
        self.results_stack = QStackedWidget()
        self.results_empty = QLabel("Tape le nom d'un morceau pour commencer.")
        self.results_empty.setObjectName("empty")
        self.results_empty.setAlignment(Qt.AlignCenter)
        self.results = QListWidget()
        self.results.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.results.itemDoubleClicked.connect(lambda it: self.toggle_queue(it.data(Qt.UserRole)))
        self.results_stack.addWidget(self.results_empty)
        self.results_stack.addWidget(self.results)
        pl.addWidget(self.results_stack)
        left.addWidget(panel, 1)
        lay.addLayout(left, 62)

        side = QFrame()
        side.setObjectName("panel")
        side.setMinimumWidth(330)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 18, 18, 18)
        sl.setSpacing(12)
        hh = QHBoxLayout()
        self.q_title = QLabel("File d'attente")
        self.q_title.setObjectName("h2")
        hh.addWidget(self.q_title)
        hh.addStretch()
        self.clear_btn = QPushButton("Vider")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_queue)
        hh.addWidget(self.clear_btn)
        sl.addLayout(hh)

        self.q_stack = QStackedWidget()
        qe = QLabel("Ajoute des morceaux avec  +\nils seront téléchargés puis\nenvoyés dans VLC sur ton iPhone.")
        qe.setObjectName("empty")
        qe.setAlignment(Qt.AlignCenter)
        self.qlist = QListWidget()
        self.qlist.setSelectionMode(QListWidget.NoSelection)
        self.qlist.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.q_stack.addWidget(qe)
        self.q_stack.addWidget(self.qlist)
        sl.addWidget(self.q_stack, 1)

        self.global_status = QLabel("")
        self.global_status.setObjectName("muted")
        self.global_status.setWordWrap(True)
        sl.addWidget(self.global_status)
        self.go = QPushButton("Télécharger et envoyer sur l'iPhone")
        self.go.setObjectName("primary")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.clicked.connect(self.start)
        sl.addWidget(self.go)
        lay.addWidget(side, 38)
        self._refresh_queue_ui()
        return page

    # ----------------------------------------------------------------- page bibliothèque
    def _library_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        self.lib_title = QLabel("Ma bibliothèque")
        self.lib_title.setObjectName("h2")
        bar.addWidget(self.lib_title)
        bar.addStretch()
        b1 = QPushButton("Ouvrir le dossier")
        b1.clicked.connect(lambda: (core.LIBRARY_DIR.mkdir(parents=True, exist_ok=True),
                                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.LIBRARY_DIR)))))
        self.verify_btn = QPushButton("Scanner l'iPhone")
        self.verify_btn.clicked.connect(self.verify_iphone)
        self.sync_btn = QPushButton("Envoyer ce qui manque")
        self.sync_btn.clicked.connect(self.start)
        for b in (b1, self.verify_btn, self.sync_btn):
            b.setCursor(Qt.PointingHandCursor)
            bar.addWidget(b)
        lay.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(12)
        self.lib_filter = QLineEdit()
        self.lib_filter.setObjectName("search")
        self.lib_filter.setPlaceholderText("Filtrer par titre ou artiste…")
        self.lib_filter.setClearButtonEnabled(True)
        self.lib_filter.textChanged.connect(lambda _t: self.load_library())
        bar2.addWidget(self.lib_filter, 1)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("muted")
        bar2.addWidget(self.scan_status)
        lay.addLayout(bar2)
        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 10, 10, 10)
        self.lib_stack = QStackedWidget()
        e = QLabel("Ta bibliothèque est vide pour l'instant.")
        e.setObjectName("empty")
        e.setAlignment(Qt.AlignCenter)
        self.lib = QListWidget()
        self.lib.setSelectionMode(QListWidget.NoSelection)
        self.lib.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.lib_stack.addWidget(e)
        self.lib_stack.addWidget(self.lib)
        pl.addWidget(self.lib_stack)
        lay.addWidget(panel, 1)
        return page

    # ----------------------------------------------------------------- iPhone
    def poll_device(self):
        if self.polling or self.busy:
            return
        self.polling = True
        w = Worker(iphone.status)
        w.signals.done.connect(self._on_device)
        w.signals.error.connect(lambda _m: setattr(self, "polling", False))
        self.pool.start(w)

    def _on_device(self, st: iphone.DeviceStatus):
        self.polling = False
        was_ready = self.device.connected and self.device.vlc
        self.device = st
        self._render_device()
        if st.connected and st.vlc and not was_ready:
            self.verify_iphone()  # iPhone tout juste branché : on scanne son contenu

    def owned(self, vid: str) -> bool:
        return core.History.load().has(vid) or vid in iphone.known_video_ids()

    def _render_device(self):
        st = self.device
        if st.connected and st.vlc:
            color, name, sub = C["ok"], st.name, f"iOS {st.ios} · VLC prêt"
        elif st.connected:
            color, name, sub = C["accent"], st.name, st.message or "VLC introuvable"
        else:
            msg = st.message if st.message and "Aucun iPhone" not in st.message else ""
            color, name, sub = C["muted"], "iPhone non branché", msg or "Branche-le en USB"
        self.dot.setStyleSheet(f"background:{color}; border-radius:5px;")
        self.dev_name.setText(name)
        self.dev_sub.setText(sub)

    # ----------------------------------------------------------------- recherche
    def do_search(self):
        q = self.search_input.text().strip()
        if not q:
            return
        self.results_empty.setText("Recherche…")
        self.results_stack.setCurrentIndex(0)
        w = Worker(core.search, q, 20)
        w.signals.done.connect(self._on_results)
        w.signals.error.connect(lambda m: self.results_empty.setText(f"Recherche impossible : {m}"))
        self.pool.start(w)

    def _on_results(self, results: list[core.SearchResult]):
        self.results.clear()
        self.result_rows.clear()
        if not results:
            self.results_empty.setText("Aucun résultat.")
            return
        hist = core.History.load()
        phone = iphone.known_video_ids()
        for r in results:
            row = ResultRow(r, hist.has(r.video_id) or r.video_id in phone)
            if r.video_id in self.queue:
                row.set_state("queued")
            row.toggled.connect(self.toggle_queue)
            it = QListWidgetItem()
            it.setData(Qt.UserRole, r)
            it.setSizeHint(QSize(0, 80))
            self.results.addItem(it)
            self.results.setItemWidget(it, row)
            self.result_rows[r.video_id] = row
            self._load_thumb(r, row)
        self.results.scrollToTop()
        self.results_stack.setCurrentIndex(1)

    def _load_thumb(self, r: core.SearchResult, row: ResultRow):
        url = f"https://i.ytimg.com/vi/{r.video_id}/mqdefault.jpg"
        reply = self.net.get(QNetworkRequest(QUrl(url)))

        def done():
            if reply.error() == QNetworkReply.NoError:
                pix = QPixmap()
                if pix.loadFromData(reply.readAll()):
                    try:
                        row.set_thumb(pix)
                    except RuntimeError:  # la ligne a été détruite entre-temps
                        pass
            reply.deleteLater()

        reply.finished.connect(done)

    # ----------------------------------------------------------------- file d'attente
    def toggle_queue(self, r: core.SearchResult):
        if self.busy or self.owned(r.video_id):
            return
        if r.video_id in self.queue:
            self.remove_from_queue(r.video_id)
            return
        self.queue[r.video_id] = r
        row = QueueRow(r)
        row.remove.connect(self.remove_from_queue)
        it = QListWidgetItem()
        it.setData(Qt.UserRole, r.video_id)
        it.setSizeHint(QSize(0, 68))
        self.qlist.addItem(it)
        self.qlist.setItemWidget(it, row)
        self.queue_rows[r.video_id] = row
        if r.video_id in self.result_rows:
            self.result_rows[r.video_id].set_state("queued")
        self._refresh_queue_ui()

    def remove_from_queue(self, vid: str):
        if self.busy:
            return
        self.queue.pop(vid, None)
        self.queue_rows.pop(vid, None)
        for i in range(self.qlist.count()):
            if self.qlist.item(i).data(Qt.UserRole) == vid:
                self.qlist.takeItem(i)
                break
        if vid in self.result_rows:
            self.result_rows[vid].set_state("owned" if self.owned(vid) else "idle")
        self._refresh_queue_ui()

    def clear_queue(self):
        for vid in list(self.queue):
            self.remove_from_queue(vid)

    def _refresh_queue_ui(self):
        n = len(self.queue)
        self.q_title.setText(f"File d'attente  ·  {n}" if n else "File d'attente")
        self.q_stack.setCurrentIndex(1 if n else 0)
        self.clear_btn.setVisible(n > 0 and not self.busy)
        if not self.busy:
            self.go.setText(f"Télécharger et envoyer  ({n})" if n else "Télécharger et envoyer sur l'iPhone")

    # ----------------------------------------------------------------- traitement
    def start(self):
        if self.busy or self.scanning:
            return
        items = list(self.queue.values())
        if not items and not any(not t.on_iphone for t in core.History.load().tracks.values()):
            self.global_status.setText("Ajoute d'abord des morceaux à la file.")
            return
        self.busy = True
        for b in (self.go, self.sync_btn, self.verify_btn):
            b.setEnabled(False)
        self.clear_btn.setVisible(False)
        for row in self.queue_rows.values():
            row.x.setVisible(False)
        self.go.setText("En cours…")
        self.global_status.setText("")
        w = Worker(pipeline, items, with_progress=True)
        w.signals.progress.connect(self._on_progress)
        w.signals.done.connect(self._on_finished)
        w.signals.error.connect(self._on_failed)
        self.pool.start(w)

    def _on_progress(self, ev):
        kind = ev[0]
        if kind == "dl":
            _, vid, frac, msg = ev
            if vid in self.queue_rows:
                self.queue_rows[vid].set_progress(frac * 0.6, msg)
        elif kind == "err":
            _, vid, msg = ev
            if vid in self.queue_rows:
                self.queue_rows[vid].set_progress(0, "Échec", C["danger"])
                self.queue_rows[vid].setToolTip(msg)
        elif kind == "push":
            if len(ev) == 5:
                self.global_status.setText(f"Envoi de {ev[2]} morceau(x) vers VLC…")
                for row in self.queue_rows.values():
                    if row.bar.value() >= 590:
                        row.set_progress(0.6, "Prêt à envoyer")
                return
            _, i, n, frac, name, vid = ev
            self.global_status.setText(f"Envoi vers l'iPhone  {i + 1}/{n}")
            if vid in self.queue_rows:
                self.queue_rows[vid].set_progress(0.6 + 0.4 * frac, "Envoi…")
        elif kind == "sent":
            vid = ev[1]
            if vid in self.queue_rows:
                self.queue_rows[vid].set_progress(1.0, "Sur l'iPhone ✓", C["ok"])

    def _end_busy(self):
        self.busy = False
        for b in (self.go, self.sync_btn, self.verify_btn):
            b.setEnabled(True)
        # on retire de la file ce qui a réussi
        for vid in list(self.queue):
            if self.owned(vid):
                self.queue.pop(vid)
        QTimer.singleShot(2500, self._prune_queue)
        self._refresh_queue_ui()
        for vid, row in self.result_rows.items():
            if self.owned(vid):
                row.set_state("owned")
        if self.stack.currentIndex() == 1:
            self.load_library()

    def _prune_queue(self):
        if self.busy:
            return
        for i in reversed(range(self.qlist.count())):
            vid = self.qlist.item(i).data(Qt.UserRole)
            if vid not in self.queue:
                self.qlist.takeItem(i)
                self.queue_rows.pop(vid, None)
        for row in self.queue_rows.values():
            row.x.setVisible(True)
        self._refresh_queue_ui()

    def _on_finished(self, res: dict):
        self._end_busy()
        parts = []
        if res.get("sent"):
            parts.append(f"✓ {res['sent']} morceau(x) envoyé(s). Ouvre VLC sur l'iPhone pour les voir.")
        if res.get("failed"):
            parts.append(f"{res['failed']} échec(s) de téléchargement.")
        if not res.get("device"):
            parts.append(f"Téléchargé sur le PC. {res.get('msg') or ''} "
                         f"{res.get('pending', 0)} morceau(x) partiront au prochain envoi.")
        if not parts:
            parts.append("Tout est déjà sur l'iPhone.")
        self.global_status.setText(" ".join(parts))
        self.poll_device()

    def _on_failed(self, msg: str):
        self._end_busy()
        self.global_status.setText(f"Erreur : {msg}")
        self.global_status.setStyleSheet(f"color:{C['danger']};")
        QTimer.singleShot(8000, lambda: self.global_status.setStyleSheet(""))

    # ----------------------------------------------------------------- bibliothèque
    def load_library(self):
        self.lib.clear()
        entries = build_entries()
        n = len(entries)
        on = sum(1 for e in entries if e.remote)
        only_pc = n - on
        txt = f"Ma bibliothèque  ·  {on} sur l'iPhone"
        if only_pc:
            txt += f"  ·  {only_pc} pas encore envoyé{'s' if only_pc > 1 else ''}"
        self.lib_title.setText(txt)
        if not self.scanning:
            self.scan_status.setText(self._last_scan_text())
        q = self.lib_filter.text().strip().lower()
        shown = [e for e in entries if not q or q in e.title.lower() or q in e.artist.lower()]
        for e in shown:
            row = LibraryRow(e)
            row.delete.connect(self.delete_entry)
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, 62))
            self.lib.addItem(it)
            self.lib.setItemWidget(it, row)
        self.lib_stack.setCurrentIndex(1 if shown else 0)

    @staticmethod
    def _last_scan_text() -> str:
        if not iphone.CACHE_FILE.exists():
            return "iPhone jamais scanné"
        from datetime import datetime
        d = datetime.fromtimestamp(iphone.CACHE_FILE.stat().st_mtime)
        day = "aujourd'hui" if d.date() == datetime.now().date() else d.strftime("le %d/%m")
        return f"Dernier scan {day} à {d:%H:%M}"

    def verify_iphone(self):
        if self.busy or self.scanning:
            return
        if not (self.device.connected and self.device.vlc):
            self.scan_status.setText("Branche l'iPhone pour le scanner")
            return
        self.scanning = True
        self.verify_btn.setEnabled(False)
        self.go.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.scan_status.setText("Scan de l'iPhone…")
        w = Worker(scan_iphone, with_progress=True)
        w.signals.progress.connect(lambda p: self.scan_status.setText(f"Scan de l'iPhone…  {p[0] + 1}/{p[1]}"))
        w.signals.done.connect(self._on_scanned)
        w.signals.error.connect(self._on_scan_failed)
        self.pool.start(w)

    def _scan_end(self):
        self.scanning = False
        for b in (self.verify_btn, self.go, self.sync_btn):
            b.setEnabled(True)

    def _on_scanned(self, n: int):
        self._scan_end()
        self.load_library()
        for vid, row in self.result_rows.items():
            if self.owned(vid) and vid not in self.queue:
                row.set_state("owned")

    def _on_scan_failed(self, msg: str):
        self._scan_end()
        self.scan_status.setText(f"Scan impossible : {msg}")

    def delete_entry(self, e: Entry):
        if e.remote and e.local:
            where = "de VLC sur l'iPhone et de ton PC"
        elif e.remote:
            where = "de VLC sur l'iPhone"
        else:
            where = "de ton PC"
        if QMessageBox.question(self, "Supprimer", f"Supprimer « {e.title} » {where} ?") != QMessageBox.Yes:
            return
        w = Worker(delete_entries, [e])
        w.signals.done.connect(lambda _: self.load_library())
        w.signals.error.connect(lambda m: QMessageBox.warning(self, "Sillon", m))
        self.pool.start(w)


def main():
    # Depuis le code source (pythonw.exe), on se donne un identifiant pour avoir notre icône dans la barre
    # des tâches. La version installée garde celui de Sillon.exe, qui correspond à ses raccourcis.
    if sys.platform == "win32" and not updater.is_frozen():
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sillon.App")
        except Exception:
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("Sillon")
    app.setWindowIcon(QIcon(str(ASSETS / "sillon.ico")))
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
