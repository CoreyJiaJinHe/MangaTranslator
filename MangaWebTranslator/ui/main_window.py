"""Primary application window implementation.

Enhancements in this revision:
  - Panel area dominates window; side panel fixed narrow width.
  - Embedded web browsing via QWebEngineView (if available) with URL open action.
  - Capture current web view as screenshot panel card.
  - Selenium stub action: launches external Selenium-controlled browser and imports initial screenshot.

If PyQt6-WebEngine is missing, a placeholder widget informs the user to install it.
"""
from __future__ import annotations

from typing import List, Optional
import os

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolBar,
    QFileDialog,
    QScrollArea,
    QGridLayout,
    QSplitter,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)


class PanelCard(QWidget):
    """Visual card representing a manga panel image.

    Displays the image (scaled) and stores an identifier used for
    downstream operations (OCR, translation, etc.).
    """
    clicked = pyqtSignal(str)

    def __init__(self, panel_id: str, pixmap: QPixmap, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.panel_id = panel_id
        self._pixmap = pixmap
        layout = QVBoxLayout(self)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(pixmap)
        layout.addWidget(self.label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(160)

    def setPixmap(self, pm: QPixmap):
        # Scale for card representation while preserving aspect.
        scaled = pm.scaled(QSize(160, 220), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(scaled)

    def mousePressEvent(self, event):  # noqa: D401 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.panel_id)
        super().mousePressEvent(event)


class PanelGrid(QScrollArea):
    """Scrollable grid of ``PanelCard`` instances."""
    panelSelected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._container = QWidget(self)
        self._layout = QGridLayout(self._container)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self._cards: List[PanelCard] = []

    def addPanel(self, panel_id: str, pixmap: QPixmap):
        card = PanelCard(panel_id, pixmap, self._container)
        card.clicked.connect(self.panelSelected)
        position = len(self._cards)
        row, col = divmod(position, 4)  # 4 columns for now
        self._layout.addWidget(card, row, col)
        self._cards.append(card)


class SidePanel(QWidget):
    """Right-side detail pane showing OCR text blocks and translations."""
    requestOcr = pyqtSignal(str)
    requestTranslate = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)

        self.title = QLabel("No panel selected")
        self.title.setObjectName("panelTitle")
        outer.addWidget(self.title)

        # OCR text blocks list
        self.blocksList = QListWidget(self)
        outer.addWidget(QLabel("Extracted Text Blocks:"))
        outer.addWidget(self.blocksList, 2)

        # Translation output
        outer.addWidget(QLabel("Translation:"))
        self.translationEdit = QTextEdit(self)
        self.translationEdit.setReadOnly(True)
        outer.addWidget(self.translationEdit, 1)

        # Dictionary / similarity placeholders
        outer.addWidget(QLabel("Dictionary Lookup (stub):"))
        self.dictEdit = QTextEdit(self)
        self.dictEdit.setPlaceholderText("Kanji definitions will appear here.")
        self.dictEdit.setReadOnly(True)
        outer.addWidget(self.dictEdit, 1)

        outer.addWidget(QLabel("Similarity Suggestions (stub):"))
        self.similarityList = QListWidget(self)
        outer.addWidget(self.similarityList, 1)

        # Action buttons (local to selected panel)
        actionRow = QHBoxLayout()
        self.ocrBtn = QPushButton("OCR")
        self.txBtn = QPushButton("Translate")
        actionRow.addWidget(self.ocrBtn)
        actionRow.addWidget(self.txBtn)
        outer.addLayout(actionRow)

        self.current_panel: Optional[str] = None
        self.ocrBtn.clicked.connect(self._emit_ocr)
        self.txBtn.clicked.connect(self._emit_translate)

    def setPanel(self, panel_id: str):
        self.current_panel = panel_id
        self.title.setText(f"Panel: {panel_id}")
        self.blocksList.clear()
        self.translationEdit.clear()
        self.dictEdit.clear()
        self.similarityList.clear()

    def setOcrBlocks(self, panel_id: str, blocks: List[str]):
        if panel_id != self.current_panel:
            return
        self.blocksList.clear()
        for b in blocks:
            QListWidgetItem(b, self.blocksList)

    def setTranslation(self, panel_id: str, translated: str):
        if panel_id != self.current_panel:
            return
        self.translationEdit.setPlainText(translated)

    def setDictionaryResult(self, panel_id: str, text: str):
        if panel_id != self.current_panel:
            return
        self.dictEdit.setPlainText(text)

    def setSimilarity(self, panel_id: str, items: List[str]):
        if panel_id != self.current_panel:
            return
        self.similarityList.clear()
        for s in items:
            QListWidgetItem(s, self.similarityList)

    def _emit_ocr(self):
        if self.current_panel:
            self.requestOcr.emit(self.current_panel)

    def _emit_translate(self):
        if self.current_panel:
            self.requestTranslate.emit(self.current_panel)


class MainWindow(QMainWindow):
    """Main application window with panel grid and detail side panel."""

    panelSelected = pyqtSignal(str)
    ocrCompleted = pyqtSignal(str, list)  # panel id, blocks
    translationCompleted = pyqtSignal(str, str)  # panel id, translated text

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Manga Translator (Prototype UI)")
        self.resize(1400, 900)
        self._createActions()
        self._createToolbar()
        self._createLayout()
        self._connectSignals()

    # ----------------------- UI Construction -----------------------
    def _createActions(self):
        self.actLoad = QAction("Load Images", self)
        self.actOcrAll = QAction("OCR Panels", self)
        self.actTranslateSel = QAction("Translate Selected", self)
        self.actExport = QAction("Export Text", self)
        self.actOpenUrl = QAction("Open URL", self)
        self.actCaptureWeb = QAction("Capture WebView", self)
        self.actSelenium = QAction("Open Selenium", self)

    def _createToolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(16, 16))
        tb.addAction(self.actLoad)
        tb.addAction(self.actOcrAll)
        tb.addAction(self.actTranslateSel)
        tb.addAction(self.actExport)
        tb.addSeparator()
        tb.addAction(self.actOpenUrl)
        tb.addAction(self.actCaptureWeb)
        tb.addAction(self.actSelenium)
        self.addToolBar(tb)

    def _createLayout(self):
        # Left composite area: stacked panel (grid vs web browser)
        self._stack = QWidget(self)
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        self.panelGrid = PanelGrid(self._stack)
        # Web view (conditional import)
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
            self.webView = QWebEngineView(self._stack)
            self.webView.setObjectName("webView")
        except Exception:
            self.webView = QWidget(self._stack)
            placeholder = QLabel("PyQt6-WebEngine not installed. Install to enable embedded browsing.")
            ph_layout = QVBoxLayout(self.webView)
            ph_layout.addWidget(placeholder)
        # Initially show panel grid only.
        stack_layout.addWidget(self.panelGrid, 1)
        stack_layout.addWidget(self.webView, 1)
        self.webView.hide()

        self.sidePanel = SidePanel(self)
        self.sidePanel.setFixedWidth(340)
        splitter = QSplitter(self)
        splitter.addWidget(self._stack)
        splitter.addWidget(self.sidePanel)
        splitter.setStretchFactor(0, 8)  # Dominant left side
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _connectSignals(self):
        self.panelGrid.panelSelected.connect(self._onPanelSelected)
        self.sidePanel.requestOcr.connect(self._onRequestOcr)
        self.sidePanel.requestTranslate.connect(self._onRequestTranslate)
        self.actLoad.triggered.connect(self._onLoadImages)
        self.actOcrAll.triggered.connect(self._onOcrAll)
        self.actTranslateSel.triggered.connect(self._onTranslateSelected)
        self.actExport.triggered.connect(self._onExport)
        self.actOpenUrl.triggered.connect(self._onOpenUrl)
        self.actCaptureWeb.triggered.connect(self._onCaptureWebView)
        self.actSelenium.triggered.connect(self._onOpenSelenium)

        # Forward internal signals outward for future service integration.
        self.ocrCompleted.connect(self.sidePanel.setOcrBlocks)
        self.translationCompleted.connect(self.sidePanel.setTranslation)

    # ----------------------- Actions -----------------------
    def _onLoadImages(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select panel images", os.getcwd(), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not files:
            return
        for fp in files:
            pm = QPixmap(fp)
            if pm.isNull():
                continue
            panel_id = os.path.basename(fp)
            self.panelGrid.addPanel(panel_id, pm)
        QMessageBox.information(self, "Load", f"Loaded {len(files)} image(s).")

    def _onPanelSelected(self, panel_id: str):
        self.sidePanel.setPanel(panel_id)
        self.panelSelected.emit(panel_id)

    def _onRequestOcr(self, panel_id: str):
        # Placeholder: simulate OCR result.
        dummy_blocks = ["示例テキスト", "サンプル", "テスト"]  # Example Japanese strings
        self.ocrCompleted.emit(panel_id, dummy_blocks)

    def _onRequestTranslate(self, panel_id: str):
        # Placeholder translation echo.
        translated = "(EN) " + "; ".join(["example", "sample", "test"])
        self.translationCompleted.emit(panel_id, translated)

    def _onOcrAll(self):
        # Iterate all panels and emit dummy OCR results.
        for card in self.panelGrid._cards:
            self.ocrCompleted.emit(card.panel_id, ["全体OCR", "ダミー"])

    def _onTranslateSelected(self):
        if not self.sidePanel.current_panel:
            return
        self._onRequestTranslate(self.sidePanel.current_panel)

    def _onExport(self):
        # Placeholder: aggregate text blocks + translation.
        if not self.sidePanel.current_panel:
            QMessageBox.information(self, "Export", "No panel selected.")
            return
        blocks = [self.sidePanel.blocksList.item(i).text() for i in range(self.sidePanel.blocksList.count())]
        translation = self.sidePanel.translationEdit.toPlainText()
        summary = f"Panel: {self.sidePanel.current_panel}\nBlocks: {blocks}\nTranslation:\n{translation}"
        QMessageBox.information(self, "Export (stub)", summary)

    # ----------------------- Web / Selenium -----------------------
    def _ensureWebVisible(self):
        if self.webView.isHidden():
            self.webView.show()
            self.panelGrid.hide()

    def _ensureGridVisible(self):
        if self.panelGrid.isHidden():
            self.panelGrid.show()
            self.webView.hide()

    def _onOpenUrl(self):
        # Simple URL input dialog
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "Open URL", "Enter URL:", text="https://")
        if not ok or not url.strip():
            return
        if hasattr(self.webView, "load"):
            self._ensureWebVisible()
            try:
                from PyQt6.QtCore import QUrl
                self.webView.load(QUrl(url.strip()))
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Load Failed",
                    f"Could not load URL: {e}\nInstall PyQt6-WebEngine for browsing support."
                )
        else:
            QMessageBox.information(self, "WebEngine Missing", "PyQt6-WebEngine not installed.")

    def _onCaptureWebView(self):
        if self.webView.isHidden():
            QMessageBox.information(self, "Capture", "Web view not visible.")
            return
        pm = self.webView.grab()  # Visible region screenshot
        if pm.isNull():
            QMessageBox.warning(self, "Capture", "Failed to grab web view.")
            return
        panel_id = f"web_{len(self.panelGrid._cards)+1}"
        self._ensureGridVisible()
        self.panelGrid.addPanel(panel_id, pm)
        QMessageBox.information(self, "Capture", f"Captured web view as panel {panel_id}.")

    def _onOpenSelenium(self):
        # Stub: launches Selenium, grabs initial screenshot, import as panel.
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            opts.add_argument("--headless=new")
            driver = webdriver.Chrome(options=opts)
            driver.set_window_size(1280, 900)
            driver.get("https://example.org")
            screenshot_path = os.path.join(os.getcwd(), "_selenium_temp.png")
            driver.save_screenshot(screenshot_path)
            driver.quit()
            pm = QPixmap(screenshot_path)
            if not pm.isNull():
                panel_id = f"selenium_{len(self.panelGrid._cards)+1}"
                self.panelGrid.addPanel(panel_id, pm)
                QMessageBox.information(self, "Selenium", f"Imported screenshot as panel {panel_id}.")
            else:
                QMessageBox.warning(self, "Selenium", "Screenshot invalid.")
        except Exception as e:
            QMessageBox.warning(self, "Selenium", f"Failed to launch Selenium stub: {e}")


def create_app_window() -> MainWindow:
    """Factory to create the fully constructed MainWindow."""
    return MainWindow()


