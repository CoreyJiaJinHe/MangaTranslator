"""Primary application window implementation.

Embedded browser (PyQt6-WebEngine) with address bar, header injection,
panel grid management, OCR stubs, and export placeholder.

Selenium support removed: embedded browser is now the sole navigation mechanism.
If PyQt6-WebEngine is missing, a placeholder widget informs the user.
"""
from __future__ import annotations

from typing import List, Optional
import os

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QThread, QObject, QUrl, QTimer
from PyQt6.QtGui import QAction, QPixmap, QIcon
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
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
    QDialog,
    QApplication,
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


class PanelsView(QWidget):
    """Vertical list of panels on the left and a larger preview on the right.

    Keeps a `_cards` list of panel ids for compatibility with existing code.
    Provides `addPanel(panel_id, pixmap)` and emits `panelSelected(str)`.
    """
    panelSelected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        # Left: list of thumbnails (scrollable by QListWidget)
        self.listWidget = QListWidget(self)
        self.listWidget.setIconSize(QSize(140, 140))
        self.listWidget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.listWidget.setViewMode(QListWidget.ViewMode.ListMode)
        self.listWidget.setMovement(QListWidget.Movement.Static)
        # Allow multi-selection for batch operations
        self.listWidget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.listWidget.setMinimumWidth(180)
        # Icon-only appearance
        self.listWidget.setSpacing(6)
        self.listWidget.setUniformItemSizes(True)
        self.listWidget.setWordWrap(False)
        self.listWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.listWidget.customContextMenuRequested.connect(self._onContextMenu)

        # Right: preview area
        previewContainer = QVBoxLayout()
        self.previewLabel = QLabel("Select a panel to preview")
        self.previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.previewLabel.setMinimumSize(480, 520)
        previewContainer.addWidget(self.previewLabel, 1)

        layout.addWidget(self.listWidget, 0)
        layout.addLayout(previewContainer, 1)

        self._cards: List[str] = []
        self._pixmaps: dict[str, QPixmap] = {}

        self.listWidget.itemClicked.connect(self._onItemClicked)

    def addPanel(self, panel_id: str, pixmap: QPixmap):
        # Create thumbnail icon
        thumb = pixmap.scaled(QSize(140, 140), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        icon = QIcon(thumb)
        # Show text label under thumbnail (panel id) for clarity
        item = QListWidgetItem(icon, panel_id, self.listWidget)
        item.setData(Qt.ItemDataRole.UserRole, panel_id)
        # Ensure items have a consistent size to show icon + label
        try:
            item.setSizeHint(QSize(160, 160))
        except Exception:
            pass
        self._cards.append(panel_id)
        self._pixmaps[panel_id] = pixmap
        # Auto-select newly added and show preview immediately (add to selection)
        item.setSelected(True)
        self._onItemClicked(item)

    def selectedPanelIds(self) -> list[str]:
        ids: list[str] = []
        for it in self.listWidget.selectedItems():
            pid = it.data(Qt.ItemDataRole.UserRole) or it.text()
            ids.append(pid)
        return ids

    def allVisiblePanelIds(self) -> list[str]:
        ids: list[str] = []
        for i in range(self.listWidget.count()):
            it = self.listWidget.item(i)
            pid = it.data(Qt.ItemDataRole.UserRole) or it.text()
            ids.append(pid)
        return ids

    def removeSelectedPanels(self):
        sel = list(self.listWidget.selectedItems())
        for it in sel:
            pid = it.data(Qt.ItemDataRole.UserRole) or it.text()
            try:
                self._cards.remove(pid)
            except Exception:
                pass
            try:
                del self._pixmaps[pid]
            except Exception:
                pass
            row = self.listWidget.row(it)
            self.listWidget.takeItem(row)

    def _onContextMenu(self, pos):
        item = self.listWidget.itemAt(pos)
        if not item:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        rem = menu.addAction("Remove")
        act = menu.exec(self.listWidget.mapToGlobal(pos))
        if act is rem:
            self.removeSelectedPanels()

    def _onItemClicked(self, item: QListWidgetItem):
        panel_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
        pm = self._pixmaps.get(panel_id)
        if pm:
            area_w, area_h = self.previewLabel.width(), self.previewLabel.height()
            scaled = pm.scaled(area_w, area_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.previewLabel.setPixmap(scaled)
        self.panelSelected.emit(panel_id)


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
        if panel_id:
            self.title.setText(f"Panel: {panel_id}")
        else:
            self.title.setText("No panel selected")
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
        self.actShowPanels = QAction("Show Panels", self)
        self.actShowBrowser = QAction("Show Browser", self)
        self.actRemovePanel = QAction("Remove Panel", self)
        # Removed Selenium-related actions; embedded browser now primary.
        self.actScrapeImages = QAction("Scrape Images", self)

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
        tb.addAction(self.actShowPanels)
        tb.addAction(self.actShowBrowser)
        tb.addAction(self.actRemovePanel)
        tb.addAction(self.actScrapeImages)
        self.addToolBar(tb)

    def _createLayout(self):
        # Left composite area: stacked panel (grid vs web browser)
        self._stack = QWidget(self)
        stack_layout = QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        # PanelsView presents a vertical list of thumbnails + larger preview
        self.panelGrid = PanelsView(self._stack)
        # Web view (conditional import)
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
            # Some PyQt6 distributions expose interceptor in QtWebEngineCore; fallback if unavailable.
            try:
                from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineProfile  # type: ignore
            except Exception as core_import_err:  # pragma: no cover
                QWebEngineUrlRequestInterceptor = None  # type: ignore
                QWebEngineProfile = None  # type: ignore
                self._webengine_core_error = str(core_import_err)
            
            self.webView = QWebEngineView(self._stack)
            self.webView.setObjectName("webView")

            # Address bar row
            addr_row = QHBoxLayout()
            from PyQt6.QtWidgets import QLineEdit, QPushButton
            self.addressBar = QLineEdit(self._stack)
            self.addressBar.setPlaceholderText("Enter URL and press Go")
            import os
            from dotenv import load_dotenv
            load_dotenv()
            default_url = os.getenv("DEFAULT_MANGA_URL")
            self.addressBar.setText(default_url)

            self.goBtn = QPushButton("Go", self._stack)
            addr_row.addWidget(self.addressBar, 1)
            addr_row.addWidget(self.goBtn)
            stack_layout.addLayout(addr_row)

            # Interceptor for headers
            basicHeaders = {
                b"User-Agent": b"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
                b"Accept": b"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                b"Accept-Language": b"en-CA,en-US;q=0.7,en;q=0.3",
                b"Accept-Encoding": b"gzip, deflate, br, zstd",
                b"Cookie": b"",
            }
            if QWebEngineUrlRequestInterceptor and QWebEngineProfile:
                class _HeaderInterceptor(QWebEngineUrlRequestInterceptor):  # type: ignore
                    def interceptRequest(self, info):  # noqa: D401
                        # Only inject headers now; do not block hosts so legitimate errors surface.
                        for k, v in basicHeaders.items():
                            info.setHttpHeader(k, v)
                interceptor = _HeaderInterceptor()
                profile = QWebEngineProfile.defaultProfile()
                if hasattr(profile, "setUrlRequestInterceptor"):
                    profile.setUrlRequestInterceptor(interceptor)  # type: ignore[attr-defined]
                elif hasattr(profile, "setRequestInterceptor"):
                    profile.setRequestInterceptor(interceptor)  # type: ignore[attr-defined]
            self.goBtn.clicked.connect(self._onEmbeddedGo)
            self.addressBar.returnPressed.connect(self._onEmbeddedGo)
            # JS console messages left intact for debugging Cloudflare / script issues.
        except Exception as webengine_err:
            self.webView = QWidget(self._stack)
            placeholder = QLabel(f"PyQt6-WebEngine load failed: {webengine_err}\nCheck that PyQt6-WebEngine matches PyQt6 version and that QtWebEngineProcess is present.")
            ph_layout = QVBoxLayout(self.webView)
            ph_layout.addWidget(placeholder)
        # Initially show embedded browser (preferred) above grid toggle.
        stack_layout.addWidget(self.webView, 6)
        stack_layout.addWidget(self.panelGrid, 5)
        # Show webView by default for navigation experience.
        self.panelGrid.hide()

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
        self.actShowPanels.triggered.connect(self._onShowPanels)
        self.actShowBrowser.triggered.connect(self._onShowBrowser)
        self.actRemovePanel.triggered.connect(self._onRemovePanel)
        self.actScrapeImages.triggered.connect(self._onScrapeImages)

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
        # Run OCR on selected panels if any, otherwise on all visible panels.
        ids: list[str]
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            sel = self.panelGrid.selectedPanelIds()
            ids = sel if sel else self.panelGrid.allVisiblePanelIds()
        else:
            # fallback for legacy PanelGrid
            ids = [getattr(card, 'panel_id', str(card)) for card in self.panelGrid._cards]

        total = len(ids)
        if total == 0:
            QMessageBox.information(self, "OCR", "No panels to OCR.")
            return
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("Running OCR...", "Cancel", 0, total, self)
        progress.setWindowTitle("OCR Panels")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.show()
        done = 0
        for i, pid in enumerate(ids):
            if progress.wasCanceled():
                break
            # Placeholder OCR result
            self.ocrCompleted.emit(pid, ["全体OCR", "ダミー"])
            done += 1
            progress.setValue(done)
            QApplication.processEvents()
        progress.close()
        QMessageBox.information(self, "OCR", f"Processed {done} / {total} panels.")

    def _onTranslateSelected(self):
        # If panels are selected in the panels view, translate those; otherwise translate the current panel.
        ids: list[str] = []
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            ids = self.panelGrid.selectedPanelIds()
        if ids:
            total = len(ids)
            from PyQt6.QtWidgets import QProgressDialog
            progress = QProgressDialog("Translating panels...", "Cancel", 0, total, self)
            progress.setWindowTitle("Translate Panels")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.show()
            done = 0
            for pid in ids:
                if progress.wasCanceled():
                    break
                self._onRequestTranslate(pid)
                done += 1
                progress.setValue(done)
                QApplication.processEvents()
            progress.close()
            QMessageBox.information(self, "Translate", f"Translated {done} / {total} panels.")
        else:
            if not self.sidePanel.current_panel:
                QMessageBox.information(self, "Translate", "No panel selected to translate.")
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

    def _onEmbeddedGo(self):
        if not hasattr(self.webView, "load"):
            return
        url = self.addressBar.text().strip()
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        try:
            from PyQt6.QtCore import QUrl
            self.webView.load(QUrl(url))
        except Exception as e:
            QMessageBox.warning(self, "Go", f"Failed to load: {e}")

    def _onCaptureWebView(self):
        if self.webView.isHidden():
            QMessageBox.information(self, "Capture", "Web view not visible.")
            return
        pm = self.webView.grab()  # Visible region screenshot
        if pm.isNull():
            QMessageBox.warning(self, "Capture", "Failed to grab web view.")
            return
        panel_id = f"web_{len(self.panelGrid._cards)+1}"
        # Add captured image to panels but KEEP the browser visible so user can continue navigating.
        self.panelGrid.addPanel(panel_id, pm)
        QMessageBox.information(self, "Capture", f"Captured web view as panel {panel_id}. Use 'Show Panels' to view panels.")

    def _onScrapeImages(self):
        """Extract image sources from the currently loaded page and import them as panels.

        Uses JavaScript execution to gather candidate URLs including src, data-src, and first srcset entry.
        Downloads each (or decodes data URI) and adds to the panel grid. Duplicate URLs are skipped.
        """
        if not hasattr(self.webView, 'page'):
            QMessageBox.warning(self, "Scrape", "Web engine unavailable.")
            return
        # JavaScript now returns objects with url,width,height to aid filtering.
        js = r"""
        (function(){
          const imgs = Array.from(document.images);
          const seen = new Set();
          const out = [];
          for (const img of imgs) {
            let cand = img.getAttribute('src') || img.getAttribute('data-src') || '';
            if (!cand) {
              const ss = img.getAttribute('srcset');
              if (ss) {
                cand = ss.split(',')[0].trim().split(' ')[0];
              }
            }
            if (cand.startsWith('//')) cand = 'https:' + cand; // protocol-relative
            if (!cand) continue;
            if (seen.has(cand)) continue;
            seen.add(cand);
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            out.push({url: cand, width: w, height: h});
          }
          return out;
        })();
        """
        def after_js(entries):
            if not entries:
                QMessageBox.information(self, "Scrape", "No images found.")
                return
            dlg = ImageSelectionDialog(entries, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return  # user cancelled selection
            selected = dlg.selectedUrls()
            if not selected:
                QMessageBox.information(self, "Scrape", "No images selected for download.")
                return
            self._downloadSelectedImages(selected)
        try:
            self.webView.page().runJavaScript(js, after_js)
        except Exception as e:
            QMessageBox.warning(self, "Scrape", f"JS execution failed: {e}")

    def _onShowPanels(self):
        """User-requested action to show the panels grid (hides web view)."""
        self._ensureGridVisible()

    def _onShowBrowser(self):
        """User-requested action to show the embedded browser (hides panel grid)."""
        self._ensureWebVisible()

    def _onRemovePanel(self):
        # Remove selected panels from the PanelsView (or fallback)
        removed: list[str] = []
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            removed = self.panelGrid.selectedPanelIds()
            if removed:
                self.panelGrid.removeSelectedPanels()
        else:
            QMessageBox.information(self, "Remove", "Panel removal not supported for this view.")
            return

        # If the side panel was showing one of the removed panels, clear it
        if self.sidePanel.current_panel and self.sidePanel.current_panel in removed:
            self.sidePanel.setPanel(None)

    # ----------------------- Background Image Download -----------------------
    def _downloadSelectedImages(self, urls: list[str]):
        """Download chosen image URLs using a QThread worker with signals for progress/cancel."""
        if not urls:
            return
        out_dir = os.path.abspath("_scraped_images")
        os.makedirs(out_dir, exist_ok=True)

        total = len(urls)
        from PyQt6.QtWidgets import QProgressDialog
        progressDlg = QProgressDialog("Downloading images...", "Cancel", 0, total, self)
        progressDlg.setWindowTitle("Image Download")
        progressDlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        progressDlg.show()

        # Async worker object (no QThread)
        worker = AsyncImageDownloadWorker(urls=urls, out_dir=out_dir, existing_count=lambda: len(self.panelGrid._cards))
        # keep a reference on self so it isn't GC'd while running
        self._activeDownloadWorker = worker

        # Wiring
        worker.progress.connect(lambda idx: progressDlg.setValue(idx))
        worker.itemReady.connect(lambda panel_id, pm: self.panelGrid.addPanel(panel_id, pm))
        def done(status: str, added: int, errors: int, cancelled: bool):
            progressDlg.close()
            QMessageBox.information(self, "Download", f"{status}. Added {added} image(s). Errors: {errors}")
            try:
                worker.deleteLater()
            except Exception:
                pass
            self._activeDownloadWorker = None
        worker.finished.connect(done)

        def request_cancel():
            worker.cancel()
        progressDlg.canceled.connect(request_cancel)

        # start the sequential async download
        worker.start()

        # If dialog closed via X while running, treat as cancel.
        def on_close():
            if getattr(self, '_activeDownloadWorker', None) is not None:
                self._activeDownloadWorker.cancel()
        progressDlg.finished.connect(on_close)


class ImageSelectionDialog(QDialog):  # type: ignore[name-defined]
    """Dialog allowing user to choose which images to download.

    Layout: left side shows a scrollable full-size preview (no forced scaling),
    right side shows the list of images with checkboxes and controls.
    Supports shift-click range operations: when Shift is held while clicking a
    checkbox item, all items between the previously clicked item and current
    are set to the clicked item's new state.
    Small images (icons/emojis) are pre-unchecked.
    """
    def __init__(self, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Images to Download")
        self.resize(880, 520)
        self._entries = entries
        self._lastClickedIndex: int | None = None
        # legacy per-preview thread lists removed; using AsyncImagePreviewer


        # Root horizontal layout splits preview (left) and list+controls (right)
        root = QHBoxLayout(self)

        # Preview area (scrollable for large images)
        preview_container = QVBoxLayout()
        self._dimensionLabel = QLabel("No preview")
        self._dimensionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_container.addWidget(self._dimensionLabel)
        self._previewLabel = QLabel("Select an item to preview", self)
        self._previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._previewLabel.setFixedSize(320, 320)  # Preview area size
        preview_container.addWidget(self._previewLabel, 1)
        root.addLayout(preview_container, 3)

        # Right side vertical layout (list + controls + buttons)
        rightLayout = QVBoxLayout()
        rightLayout.addWidget(QLabel("Images found:"))
        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        rightLayout.addWidget(self._list, 1)

        # Populate list with checkable items
        for e in entries:
            url = e.get('url', '')
            w = e.get('width', 0)
            h = e.get('height', 0)
            txt = f"[{w}x{h}] {url}"
            item = QListWidgetItem(txt, self._list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            small = (w and w < 64) or (h and h < 64) or 'icon' in url.lower() or 'favicon' in url.lower() or 'emoji' in url.lower()
            item.setCheckState(Qt.CheckState.Unchecked if small else Qt.CheckState.Checked)

        controls = QHBoxLayout()
        self._btnUncheckSmall = QPushButton("Uncheck Small")
        self._btnCheckAll = QPushButton("Check All")
        self._btnInvert = QPushButton("Invert Selection")
        controls.addWidget(self._btnUncheckSmall)
        controls.addWidget(self._btnCheckAll)
        controls.addWidget(self._btnInvert)
        rightLayout.addLayout(controls)

        from PyQt6.QtWidgets import QDialogButtonBox
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        rightLayout.addWidget(bb)

        root.addLayout(rightLayout, 4)

        # Button wiring
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self._btnUncheckSmall.clicked.connect(self._uncheckSmall)
        self._btnCheckAll.clicked.connect(self._checkAll)
        self._btnInvert.clicked.connect(self._invert)
        self._list.currentItemChanged.connect(self._previewSelected)
        # itemClicked provides post-toggle state; we can apply shift-range logic here.
        self._list.itemClicked.connect(self._onItemClicked)
        # Async previewer (uses Qt networking; cancellable, no extra threads)
        self._previewer = AsyncImagePreviewer(self)
        self._previewer.ready.connect(self._setPreviewPixmap)
        self._previewer.failed.connect(self._setPreviewError)
    def closeEvent(self, event):
        """
        Ensure all preview threads and workers are stopped and deleted when the dialog closes.
        Prevents memory leaks and orphaned threads.
        """
        # Abort any active async preview request
        try:
            self._previewer.abort()
        except Exception:
            pass
        super().closeEvent(event)
    def selectedUrls(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                # Extract URL portion (after size prefix)
                txt = item.text()
                # Find first space after ]
                pos = txt.find('] ')
                url = txt[pos+2:] if pos != -1 else txt
                out.append(url)
        return out

    def _uncheckSmall(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.text().startswith('['):
                size_part = item.text().split(']')[0][1:]
                try:
                    dims = size_part.split('x')
                    w = int(dims[0])
                    h = int(dims[1])
                    if w < 128 or h < 128:
                        item.setCheckState(Qt.CheckState.Unchecked)
                except Exception:
                    pass

    def _checkAll(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)

    def _invert(self):
        for i in range(self._list.count()):
            itm = self._list.item(i)
            itm.setCheckState(Qt.CheckState.Checked if itm.checkState() == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked)

    def _previewSelected(self, current: QListWidgetItem, previous: QListWidgetItem | None):  # type: ignore[name-defined]
        # Using AsyncImagePreviewer; no legacy QThread workers to clean up here.
        if not current:
            self._previewLabel.setText("Select an item to preview")
            self._dimensionLabel.setText("No preview")
            return
        txt = current.text()
        pos = txt.find('] ')
        url = txt[pos+2:] if pos != -1 else txt
        if url.startswith('data:image/'):
            import re, base64
            m = re.match(r'^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$', url, re.IGNORECASE)
            if not m:
                self._previewLabel.setText("Unsupported data URI")
                self._dimensionLabel.setText("Unsupported")
                return
            ext, b64 = m.group(1), m.group(2)
            try:
                raw = base64.b64decode(b64)
                from PyQt6.QtGui import QImage
                img = QImage.fromData(raw)
                if img.isNull():
                    self._previewLabel.setText("Decode failed")
                    self._dimensionLabel.setText("Decode failed")
                    return
                pm = QPixmap.fromImage(img)
                self._setPreviewPixmap(pm)
                return
            except Exception:
                self._previewLabel.setText("Decode error")
                self._dimensionLabel.setText("Decode error")
                return
        # Network fetch (natural size) via short-lived worker thread
        self._previewLabel.setText("Loading preview...")
        self._dimensionLabel.setText("Loading...")
        # Use AsyncImagePreviewer (no extra threads). It will abort any in-flight request.
        self._previewer.fetch(url)

    def _setPreviewPixmap(self, pm: QPixmap):
        if pm.isNull():
            self._previewLabel.setText("Invalid image")
            self._dimensionLabel.setText("Invalid")
            return
        area_w, area_h = self._previewLabel.width(), self._previewLabel.height()
        img_w, img_h = pm.width(), pm.height()
        # Resize to fit area, keeping aspect ratio
        scaled = pm.scaled(area_w, area_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._previewLabel.setPixmap(scaled)
        self._dimensionLabel.setText(f"{img_w} x {img_h} px (scaled)")

    def _setPreviewError(self, err: str):
        # Centralized preview error handling for async previewer
        try:
            self._previewLabel.setText(err)
            self._dimensionLabel.setText(err)
        except Exception:
            pass

    def _onItemClicked(self, item: QListWidgetItem):  # Shift-range checkbox logic
        modifiers = QApplication.keyboardModifiers()
        current_index = self._list.row(item)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._lastClickedIndex is not None:
            start = min(self._lastClickedIndex, current_index)
            end = max(self._lastClickedIndex, current_index)
            target_state = item.checkState()
            for i in range(start, end + 1):
                it = self._list.item(i)
                it.setCheckState(target_state)
        self._lastClickedIndex = current_index


class AsyncImageDownloadWorker(QObject):
    """Asynchronous sequential image downloader using QNetworkAccessManager.

    Downloads images one-by-one (keeps ordering) and emits progress, itemReady and finished.
    Supports `cancel()` which aborts the current in-flight request.
    """
    progress = pyqtSignal(int)            # current index
    itemReady = pyqtSignal(str, QPixmap)  # panel_id, pixmap
    finished = pyqtSignal(str, int, int, bool)  # status, added, errors, cancelled

    def __init__(self, urls: list[str], out_dir: str, existing_count):
        super().__init__()
        import re
        self._urls = urls
        self._out_dir = out_dir
        self._cancel = False
        self._existing_count_cb = existing_count
        self._manager = QNetworkAccessManager(self)
        self._currentReply: QNetworkReply | None = None
        self._index = 0
        self._added = 0
        self._errors = 0
        self._data_uri_re = re.compile(r'^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$', re.IGNORECASE)

    def start(self):
        self._cancel = False
        self._index = 0
        self._added = 0
        self._errors = 0
        QTimer.singleShot(0, self._start_next)

    def cancel(self):
        self._cancel = True
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            try:
                self._currentReply.deleteLater()
            except Exception:
                pass
            self._currentReply = None

    def _start_next(self):
        if self._cancel:
            status = "Cancelled"
            self.finished.emit(status, self._added, self._errors, True)
            return
        if self._index >= len(self._urls):
            status = "Completed"
            self.finished.emit(status, self._added, self._errors, False)
            return

        u = self._urls[self._index]
        idx = self._index + 1

        # Data URI case
        m = self._data_uri_re.match(u)
        if m:
            import base64, os
            try:
                ext, b64 = m.group(1), m.group(2)
                raw = base64.b64decode(b64)
                fname = f"data_{self._existing_count_cb()+1}.{ 'jpg' if ext=='jpeg' else ext }"
                path = os.path.join(self._out_dir, fname)
                with open(path, 'wb') as f:
                    f.write(raw)
                pm = QPixmap(path)
                if pm.isNull():
                    self._errors += 1
                else:
                    panel_id = f"scrape_{self._existing_count_cb()+1}"
                    self.itemReady.emit(panel_id, pm)
                    self._added += 1
            except Exception:
                self._errors += 1
            self.progress.emit(idx)
            self._index += 1
            QTimer.singleShot(0, self._start_next)
            return

        # Network download
        req = QNetworkRequest(QUrl(u))
        reply = self._manager.get(req)
        self._currentReply = reply
        reply.finished.connect(lambda: self._on_reply_finished(reply))
        reply.errorOccurred.connect(lambda err: self._on_reply_error(reply, err))

    def _on_reply_error(self, reply: QNetworkReply, err):
        self._errors += 1
        idx = self._index + 1
        self.progress.emit(idx)
        try:
            reply.deleteLater()
        except Exception:
            pass
        self._currentReply = None
        self._index += 1
        QTimer.singleShot(0, self._start_next)

    def _on_reply_finished(self, reply: QNetworkReply):
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return self._on_reply_error(reply, reply.error())
        try:
            data = bytes(reply.readAll())
            import os
            url_path = reply.url().path() or ''
            tail = url_path.split('/')[-1].split('?')[0] or f"img_{self._existing_count_cb()+1}.bin"
            if '.' not in tail:
                tail += '.png'
            path = os.path.join(self._out_dir, tail)
            with open(path, 'wb') as f:
                f.write(data)
            pm = QPixmap(path)
            if pm.isNull():
                self._errors += 1
            else:
                panel_id = f"scrape_{self._existing_count_cb()+1}"
                self.itemReady.emit(panel_id, pm)
                self._added += 1
        except Exception:
            self._errors += 1
        idx = self._index + 1
        self.progress.emit(idx)
        try:
            reply.deleteLater()
        except Exception:
            pass
        self._currentReply = None
        self._index += 1
        QTimer.singleShot(0, self._start_next)


# Legacy blocking preview worker removed; AsyncImagePreviewer is used instead.


class AsyncImagePreviewer(QObject):
    """Asynchronous image fetcher using QNetworkAccessManager.

    - `fetch(url)` starts a new request, aborting any active request.
    - Emits `ready(QPixmap)` on success, `failed(str)` on error.
    - No extra QThread required — runs on the Qt event loop.
    """
    ready = pyqtSignal(QPixmap)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._currentReply: QNetworkReply | None = None

    def fetch(self, url: str):
        # Abort any in-flight request
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            self._currentReply.deleteLater()
            self._currentReply = None

        req = QNetworkRequest(QUrl(url))
        reply = self._manager.get(req)
        self._currentReply = reply

        # Bind handlers
        reply.finished.connect(lambda: self._onFinished(reply))
        reply.errorOccurred.connect(lambda err: self._onError(reply, err))

    def abort(self):
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            self._currentReply.deleteLater()
            self._currentReply = None

    def _onError(self, reply: QNetworkReply, err):
        try:
            errstr = reply.errorString() if hasattr(reply, 'errorString') else str(err)
        except Exception:
            errstr = str(err)
        self.failed.emit(errstr)
        try:
            reply.deleteLater()
        except Exception:
            pass
        if self._currentReply is reply:
            self._currentReply = None
        self.finished.emit()

    def _onFinished(self, reply: QNetworkReply):
        # If the reply reports an error, route to error handler.
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._onError(reply, reply.error())
            return
        try:
            data = bytes(reply.readAll())
            pm = QPixmap()
            ok = pm.loadFromData(data)
            if not ok or pm.isNull():
                self.failed.emit("Invalid image data")
            else:
                self.ready.emit(pm)
        except Exception as e:
            self.failed.emit(f"Decode error: {e}")
        try:
            reply.deleteLater()
        except Exception:
            pass
        if self._currentReply is reply:
            self._currentReply = None
        self.finished.emit()


def create_app_window() -> MainWindow:
    """Factory to create the fully constructed MainWindow."""
    return MainWindow()


