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
    from PyQt6.QtCore import Qt, QCoreApplication
except Exception as e:  # pragma: no cover - environment guard
    raise RuntimeError("PyQt6 is required to run the UI. Ensure it is installed.") from e

# Ensure required OpenGL context sharing attribute is set BEFORE QApplication.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

# Import QtWebEngineWidgets module early (before QApplication instance) so that
# its initialization requirements are satisfied. If the import fails, we proceed;
# the UI will show a placeholder explaining the missing dependency.
try:  # pragma: no cover - environment dependent
    import PyQt6.QtWebEngineWidgets  # noqa: F401
except Exception:
    pass

from ui.main_window import create_app_window


def main() -> None:
    app = QApplication(sys.argv)
    win = create_app_window()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
