"""Application entry point launching the prototype PyQt6 UI.

Future enhancement steps (after phased approvals):
  - Configuration loading
  - Service wiring (OCR, translation, dictionary, similarity)
  - Persistent workspace handling
  - Graceful shutdown / resource cleanup
"""
from __future__ import annotations

import sys

try:
  from PyQt6.QtWidgets import QApplication
except Exception as e:  # pragma: no cover - environment guard
  raise RuntimeError("PyQt6 is required to run the UI. Ensure it is installed.") from e

from .ui.main_window import create_app_window


def main() -> None:
  app = QApplication(sys.argv)
  win = create_app_window()
  win.show()
  sys.exit(app.exec())


if __name__ == "__main__":
  main()
