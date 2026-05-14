"""
cognia_writing.py
=================
Cognia Writing — desktop GUI entry point for the writing/editing Shattering variant.

Loads the cognia_writing manifest (RHETOR shards bundled, LOGOS on-demand)
and provides a PyQt6 writing assistant window.

Requires: pip install PyQt6
Falls back to a CLI mode if PyQt6 is not installed.

Usage:
    python cognia_writing.py                   # launch GUI
    python cognia_writing.py --status          # print status, no GUI
    python cognia_writing.py --coordinator URL # use distributed swarm
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shattering.orchestrator import ShatteringOrchestrator, InferResult

_MANIFEST = str(_ROOT / "shattering" / "manifests" / "cognia_writing.json")
_APP_TITLE = "Cognia Writing - Shattering v1"


def _build_orch(coordinator_url: str | None) -> ShatteringOrchestrator:
    return ShatteringOrchestrator(
        manifest_path=_MANIFEST,
        coordinator_url=coordinator_url,
        mode="auto",
    )


# ── CLI helpers (used by --status and fallback mode) ──────────────────

def _print_status(orch: ShatteringOrchestrator) -> None:
    s = orch.status()
    print(f"Manifest : {s['manifest']}")
    print(f"Mode     : {s['mode']}")
    frags = s["fragments"]
    print(f"Loaded   : {frags['loaded_sub_models']}  ({len(frags['loaded_fragments'])} shards)")
    for sm, ids in s["bundles"].items():
        print(f"  {sm:8s} -> {ids}")


# ── Qt worker (runs inference off the GUI thread) ─────────────────────

def _build_gui(orch: ShatteringOrchestrator) -> None:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QTextEdit, QLabel, QStatusBar, QMenuBar, QMenu,
        QSizePolicy, QSplitter,
    )
    from PyQt6.QtGui import QAction, QFont, QKeySequence

    class InferWorker(QThread):
        result_ready = pyqtSignal(object)   # InferResult
        error        = pyqtSignal(str)

        def __init__(self, orch: ShatteringOrchestrator, prompt: str):
            super().__init__()
            self._orch   = orch
            self._prompt = prompt

        def run(self) -> None:
            try:
                result = self._orch.infer(self._prompt)
                self.result_ready.emit(result)
            except Exception as exc:
                self.error.emit(str(exc))

    class RouteWorker(QThread):
        route_ready = pyqtSignal(object)    # RouteDecision
        error       = pyqtSignal(str)

        def __init__(self, orch: ShatteringOrchestrator, prompt: str):
            super().__init__()
            self._orch   = orch
            self._prompt = prompt

        def run(self) -> None:
            try:
                decision = self._orch.route_only(self._prompt)
                self.route_ready.emit(decision)
            except Exception as exc:
                self.error.emit(str(exc))

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self._orch   = orch
            self._worker = None
            self.setWindowTitle(_APP_TITLE)
            self.setMinimumSize(800, 600)
            self.resize(900, 680)
            self._build_menu()
            self._build_body()
            self._build_statusbar()

        # ── Menu ──────────────────────────────────────────────────────

        def _build_menu(self) -> None:
            bar = self.menuBar()

            file_menu = bar.addMenu("File")
            act_exit = QAction("Exit", self)
            act_exit.setShortcut(QKeySequence("Ctrl+Q"))
            act_exit.triggered.connect(self.close)
            file_menu.addAction(act_exit)

            help_menu = bar.addMenu("Help")
            act_about = QAction("About", self)
            act_about.triggered.connect(self._show_about)
            help_menu.addAction(act_about)

        # ── Central widget ────────────────────────────────────────────

        def _build_body(self) -> None:
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)

            splitter = QSplitter(Qt.Orientation.Vertical)

            # --- Prompt area ---
            prompt_wrap = QWidget()
            pw_layout = QVBoxLayout(prompt_wrap)
            pw_layout.setContentsMargins(0, 0, 0, 0)
            pw_layout.setSpacing(4)
            pw_layout.addWidget(QLabel("Prompt:"))
            self._prompt_edit = QTextEdit()
            self._prompt_edit.setPlaceholderText(
                "Type your writing request here...\n"
                "e.g. 'Draft a formal email declining a job offer'"
            )
            self._prompt_edit.setFont(QFont("Segoe UI", 10))
            self._prompt_edit.setFixedHeight(130)
            pw_layout.addWidget(self._prompt_edit)

            # --- Buttons ---
            btn_row = QHBoxLayout()
            self._btn_generate = QPushButton("Generate")
            self._btn_generate.setDefault(True)
            self._btn_generate.clicked.connect(self._on_generate)
            self._btn_route = QPushButton("Route only")
            self._btn_route.setToolTip("Show which sub-model would handle this prompt")
            self._btn_route.clicked.connect(self._on_route)
            btn_clear = QPushButton("Clear")
            btn_clear.clicked.connect(self._on_clear)
            btn_row.addWidget(self._btn_generate)
            btn_row.addWidget(self._btn_route)
            btn_row.addStretch()
            btn_row.addWidget(btn_clear)
            pw_layout.addLayout(btn_row)

            splitter.addWidget(prompt_wrap)

            # --- Response area ---
            resp_wrap = QWidget()
            rw_layout = QVBoxLayout(resp_wrap)
            rw_layout.setContentsMargins(0, 0, 0, 0)
            rw_layout.setSpacing(4)
            rw_layout.addWidget(QLabel("Response:"))
            self._response_edit = QTextEdit()
            self._response_edit.setReadOnly(True)
            self._response_edit.setFont(QFont("Segoe UI", 10))
            rw_layout.addWidget(self._response_edit)

            splitter.addWidget(resp_wrap)
            splitter.setSizes([220, 380])
            layout.addWidget(splitter)

        def _build_statusbar(self) -> None:
            self._status = QStatusBar()
            self.setStatusBar(self._status)
            self._status.showMessage("Ready")

        # ── Slots ─────────────────────────────────────────────────────

        def _on_generate(self) -> None:
            prompt = self._prompt_edit.toPlainText().strip()
            if not prompt:
                self._status.showMessage("Enter a prompt first.")
                return
            self._set_busy(True)
            self._response_edit.setPlainText("Generating...")
            self._worker = InferWorker(self._orch, prompt)
            self._worker.result_ready.connect(self._on_result)
            self._worker.error.connect(self._on_error)
            self._worker.finished.connect(lambda: self._set_busy(False))
            self._worker.start()

        def _on_route(self) -> None:
            prompt = self._prompt_edit.toPlainText().strip()
            if not prompt:
                self._status.showMessage("Enter a prompt first.")
                return
            self._set_busy(True)
            self._worker = RouteWorker(self._orch, prompt)
            self._worker.route_ready.connect(self._on_route_result)
            self._worker.error.connect(self._on_error)
            self._worker.finished.connect(lambda: self._set_busy(False))
            self._worker.start()

        def _on_clear(self) -> None:
            self._prompt_edit.clear()
            self._response_edit.clear()
            self._status.showMessage("Cleared.")

        def _on_result(self, result: InferResult) -> None:
            self._response_edit.setPlainText(result.text)
            self._status.showMessage(
                f"[{result.sub_model.upper()}  {result.confidence:.0%}  "
                f"{result.mode}  {result.latency_ms:.0f}ms]"
            )

        def _on_route_result(self, decision) -> None:
            self._response_edit.setPlainText(
                f"Routing decision:\n"
                f"  sub_model  : {decision.sub_model}\n"
                f"  confidence : {decision.confidence:.0%}\n"
                f"  scores     : {decision.scores}\n"
                f"  reason     : {decision.reason}"
            )
            self._status.showMessage(
                f"Route: {decision.sub_model}  ({decision.confidence:.0%})"
            )

        def _on_error(self, msg: str) -> None:
            self._response_edit.setPlainText(f"Error: {msg}")
            self._status.showMessage(f"Error: {msg}")

        def _set_busy(self, busy: bool) -> None:
            self._btn_generate.setEnabled(not busy)
            self._btn_route.setEnabled(not busy)
            if busy:
                self._status.showMessage("Working...")

        def _show_about(self) -> None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "About",
                f"{_APP_TITLE}\n\n"
                "Powered by Shattering architecture v1.\n"
                "Sub-models: RHETOR (writing), LOGOS (reasoning).\n"
                "Base model: Llama 3.2-3B Q4_K_M.",
            )

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


# ── Entry point ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cognia_writing",
        description="Cognia Writing - writing-focused Shattering AI GUI",
    )
    parser.add_argument("--status", action="store_true", help="Print status and exit (no GUI)")
    parser.add_argument(
        "--coordinator", metavar="URL",
        default=os.environ.get("COGNIA_COORDINATOR_URL"),
        help="Swarm coordinator URL (default: $COGNIA_COORDINATOR_URL)",
    )
    args = parser.parse_args()

    orch = _build_orch(args.coordinator)

    if args.status:
        _print_status(orch)
        return

    try:
        _build_gui(orch)
    except ImportError:
        print("PyQt6 not installed. Install with:  pip install PyQt6")
        print()
        print("Falling back to CLI mode. Type your prompt, Ctrl+C to exit.")
        print()
        while True:
            try:
                prompt = input("cognia_writing> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nBye.")
                return
            if not prompt:
                continue
            if prompt in ("/exit", "exit", "quit"):
                print("Bye.")
                return
            result = orch.infer(prompt)
            print(f"\n{result.text}")
            print(f"  [{result.sub_model.upper()}  {result.confidence:.0%}  {result.mode}  {result.latency_ms:.0f}ms]\n")


if __name__ == "__main__":
    main()
