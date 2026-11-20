"""Qt view: install Unity Mod Manager for Pathfinder: Kingmaker / Wrath.

UMM is only published on Nexus Mods (site mod 21) and its file id changes
with every release, so the archive is downloaded by hand and picked up from
Downloads.  The install itself is native (``Games.Owlcat.umm_install``) and
offers the same destinations as the SMAPI wizard, defaulting to a managed
root-flagged mod.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from gui_qt.runtime.safe_emit import safe_emit
from gui_qt.appearance.theme import active_palette, _c
from wizards_qt._view_base import GREEN, RED, WizardViewBase

if TYPE_CHECKING:
    from Games.base_game import BaseGame

_PG_ARCHIVE, _PG_INSTALL = range(2)
_NEXUS_URL = "https://www.nexusmods.com/site/mods/21?tab=files"
_KEYWORDS = ["unitymodmanager"]


class UmmView(WizardViewBase):
    """Locate the UMM archive, pick a destination, install."""

    _install_status_sig = Signal(str, str)
    _install_done_sig = Signal(bool)

    def __init__(self, game: "BaseGame", log_fn=None, on_close=None, ctx=None,
                 **_extra):
        super().__init__(game, log_fn, on_close, ctx,
                         title=self.tr("Install Unity Mod Manager - {0}").format(game.name))
        self._installed_mode = ""
        self._install_status_sig.connect(self._guard(
            lambda t, c: self._set_status(self._run_status, t, c)))
        self._install_done_sig.connect(self._guard(self._on_install_done))

        self._stack.addWidget(self._build_archive_page())
        self._stack.addWidget(self._build_install_page())
        self._stack.setCurrentIndex(_PG_ARCHIVE)
        self._scan_downloads()

    # ---- page 1: download / locate + destination ---------------------------------
    def _build_mode_box(self) -> QWidget:
        p = active_palette()
        box = QFrame()
        box.setStyleSheet(
            f"QFrame{{background:{_c(p,'BG_PANEL')}; border-radius:6px;}}")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(12, 10, 12, 10)
        bv.setSpacing(4)
        head = QLabel(self.tr("Install destination"))
        head.setStyleSheet(f"color:{_c(p,'TEXT_MAIN')}; font-weight:600;")
        bv.addWidget(head)
        self._mode_group = QButtonGroup(self)
        for val, label in (
                ("game", self.tr("Game folder (restores to vanilla first)")),
                ("root", self.tr("Root_Folder (staging)")),
                ("mod", self.tr("As a managed mod (root-flagged)"))):
            rb = QRadioButton(label)
            rb.setProperty("mode", val)
            if val == "mod":
                rb.setChecked(True)
            self._mode_group.addButton(rb)
            bv.addWidget(rb)
        return box

    def _selected_mode(self) -> str:
        btn = self._mode_group.checkedButton()
        return btn.property("mode") if btn is not None else "mod"

    def _build_archive_page(self) -> QWidget:
        page, lay = self._step_page(self.tr("Step 1: Get Unity Mod Manager"))
        self._make_note(lay, self.tr(
            "Download Unity Mod Manager from Nexus Mods (Files tab, main file),\n"
            "then come back here. The archive is found in your Downloads\n"
            "folder automatically, or use Browse to select it."))
        lay.addSpacing(8)
        open_btn = self._orange_btn(self.tr("Open Download Page"))
        open_btn.clicked.connect(lambda: self._open_url(_NEXUS_URL))
        lay.addWidget(open_btn, 0, Qt.AlignHCenter)
        lay.addSpacing(8)
        self._dl_status = self._make_status(lay)
        lay.addWidget(self._build_mode_box())
        lay.addStretch(1)
        row = QWidget()
        rh = QHBoxLayout(row); rh.setContentsMargins(0, 8, 0, 0); rh.setSpacing(8)
        rh.addStretch(1)
        browse = QPushButton(self.tr("Browse…"))
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        rh.addWidget(browse)
        retry = QPushButton(self.tr("Try Again"))
        retry.setCursor(Qt.PointingHandCursor)
        retry.clicked.connect(self._scan_downloads)
        rh.addWidget(retry)
        self._dl_next_btn = self._accent_btn(self.tr("Next →"))
        self._dl_next_btn.setEnabled(False)
        self._dl_next_btn.clicked.connect(self._goto_install)
        rh.addWidget(self._dl_next_btn)
        rh.addStretch(1)
        lay.addWidget(row)
        return page

    def _scan_downloads(self):
        from Utils.wizards.archives import find_archive, get_downloads_dir
        found = find_archive(get_downloads_dir(), _KEYWORDS)
        if found is not None:
            self._use_archive(found, self.tr("Found: {0}").format(found.name))
            return
        self._archive_path = None
        self._dl_next_btn.setEnabled(False)
        self._set_status(self._dl_status, self.tr(
            "Unity Mod Manager archive not found in Downloads.\n"
            "Download it, then press Try Again, or use Browse."), RED)

    def _browse(self):
        from Utils.ui.portal import pick_file
        pick_file(self.tr("Select the Unity Mod Manager archive"),
                  lambda p: safe_emit(self._picked_sig, p))

    def _on_picked(self, path):
        """Base portal-picker override: this view has no separate locate page."""
        if path and Path(path).is_file():
            self._use_archive(Path(path), self.tr("Selected: {0}").format(Path(path).name))

    def _use_archive(self, path: Path, label: str):
        self._archive_path = path
        self._set_status(self._dl_status, self.tr(
            "{0}\nChoose the install destination, then click Next.").format(label), GREEN)
        self._dl_next_btn.setEnabled(True)

    # ---- page 2: install ---------------------------------------------------------
    def _build_install_page(self) -> QWidget:
        page, lay = self._step_page(self.tr("Step 2: Install Unity Mod Manager"))
        self._run_status = self._make_status(lay)
        self._install_bar = QProgressBar()
        self._install_bar.setRange(0, 0)
        self._install_bar.setTextVisible(False)
        lay.addWidget(self._install_bar)
        lay.addStretch(1)
        self._done_btn = self._green_btn(self.tr("Done"))
        self._done_btn.setEnabled(False)
        self._done_btn.clicked.connect(self._finish)
        lay.addWidget(self._done_btn, 0, Qt.AlignHCenter)
        return page

    def _goto_install(self):
        if self._archive_path is None or not Path(self._archive_path).is_file():
            return
        self._installed_mode = self._selected_mode()
        self._stack.setCurrentIndex(_PG_INSTALL)
        self._install_bar.setVisible(True)
        if self._installed_mode == "game":
            # Files written into a deployed game would post-date the deploy
            # snapshot; restore to vanilla through the app first.
            self._run_ctx_restore(self._run_status, on_ok=self._start_install,
                                  on_fail=self._on_restore_failed)
            return
        self._start_install()

    def _start_install(self):
        self._set_status(self._run_status, self.tr("Installing Unity Mod Manager…"))
        threading.Thread(target=self._do_install, daemon=True,
                         name="umm-install").start()

    def _on_restore_failed(self):
        self._install_bar.setVisible(False)
        self._done_btn.setEnabled(True)

    def _do_install(self):
        from Games.Owlcat.umm_install import install_umm
        mode = self._installed_mode
        try:
            dest_label, file_count, _mod = install_umm(
                self._game, self._archive_path, mode, log_fn=self._log)
            extra = ("" if mode == "game" else
                     self.tr("\n\nDeploy your mods to activate it."))
            safe_emit(self._install_status_sig,
                      self.tr("Unity Mod Manager installed successfully!\n"
                              "{0} file(s) installed into the {1}.{2}\n\n"
                              "Click Done to close.")
                      .format(file_count, dest_label, extra), GREEN)
            safe_emit(self._install_done_sig, True)
        except Exception as exc:
            safe_emit(self._install_status_sig, self.tr("Error: {0}").format(exc), RED)
            self._log(f"UMM Wizard error: {exc}")
            safe_emit(self._install_done_sig, False)

    def _on_install_done(self, ok: bool):
        self._install_bar.setVisible(False)
        self._done_btn.setEnabled(True)
        if ok and self._installed_mode == "mod":
            self._ran = True    # modlist.txt changed; _finish() reloads it
