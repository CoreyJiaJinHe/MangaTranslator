"""Primary application window implementation.

Embedded browser (PyQt6-WebEngine) with address bar, header injection,
panel grid management, OCR stubs, and export placeholder.

Selenium support removed: embedded browser is now the sole navigation mechanism.
If PyQt6-WebEngine is missing, a placeholder widget informs the user.
"""
from __future__ import annotations
import torch
from typing import List, Optional
import os
import logging  # Added to enable logging.warning usage
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QSize, QThread, QObject, QUrl, QTimer
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
    QComboBox,
    QSpinBox,
    QCheckBox,
    QWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu
)
import json
from MangaWebTranslator.ui.custom_widget.rect_preview import RectPreview
from MangaWebTranslator.services.ocr.ocr_preprocess import qimage_to_pil, crop_regions, detect_text_regions
from MangaWebTranslator.ui.components.panel_preview import PanelImageThumbnailCard, PanelsChapterImagesPreview
from MangaWebTranslator.ui.components.side_panel import PanelRightOutput
from MangaWebTranslator.ui.components.dialogs import ImageSelectionDialog
from MangaWebTranslator.ui.components.async_workers import AsyncImageDownloadWorker, AsyncImagePreviewer, OcrWorker



def show_selectable_message(parent, title, text, icon=QMessageBox.Icon.Information):
    dlg = QMessageBox(parent)
    dlg.setWindowTitle(title)
    dlg.setText(text)
    dlg.setIcon(icon)
    dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
    dlg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.activateWindow()
    dlg.exec()

def show_info_message(parent, title, text):
    # Single helper for informational dialogs; selectable text for easy copying
    show_selectable_message(parent, title, text, QMessageBox.Icon.Information)

# PanelsChapterImagesPreview and PanelImageThumbnailCard moved to ui.components.panel_preview


# PanelRightOutput moved to ui.components.side_panel


class MainWindow(QMainWindow):
    def _onRectsChanged(self, rects):
        # Update rectangles for the current panel when changed in the preview
        panel_id = getattr(self.sidePanel, 'current_panel', None)
        if not panel_id:
            return
        self._panel_rects[panel_id] = rects.copy()

        # Build the set of block IDs present in rects
        rect_block_ids = set(rect.get('id') for rect in rects if 'id' in rect)
        #print(f"[DEBUG] Updated rects for panel {panel_id} with block IDs: {list(rect_block_ids)}")

        # Remove block cards whose block_id is not in rect_block_ids
        blocks_to_remove = []
        for i in range(self.sidePanel.blocksList.count()):
            item = self.sidePanel.blocksList.item(i)
            widget = self.sidePanel.blocksList.itemWidget(item)
            if widget:
                block_id = getattr(widget, 'block_id', None)
                if block_id not in rect_block_ids:
                    blocks_to_remove.append(i)
        #print("[DEBUG] Removing block rows at indices:", blocks_to_remove)
        for row in reversed(blocks_to_remove):
            self.sidePanel.blocksList.takeItem(row)

        # Remove OCR results for blocks that no longer exist, but do NOT renumber block IDs
        if panel_id in self._panel_ocr_results:
            # Only keep OCR blocks whose id is still present in rect_block_ids
            filtered_blocks = [b for b in self._panel_ocr_results[panel_id] if b.get('id') in rect_block_ids]
            if filtered_blocks:
                self._panel_ocr_results[panel_id] = filtered_blocks
                self.sidePanel.setOcrBlocks(panel_id, filtered_blocks)
            else:
                del self._panel_ocr_results[panel_id]
        
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
        # Connect rectsChanged from preview to keep per-panel rectangles in sync
        try:
            self.panelGrid.preview.rectsChanged.connect(self._onRectsChanged)
        except Exception:
            pass
        # Preload MangaOcrAdapter once for all OCR calls
        from MangaWebTranslator.services.ocr.ocr_adapter import create_ocr
        self._ocr_adapter = create_ocr()
        # Store rectangles per panel_id
        self._panel_rects = {}  # panel_id -> list of rects
        # Store OCR results per panel_id (in-memory only)
        self._panel_ocr_results = {}  # panel_id -> list of OCR blocks
        # Load persisted config and apply OCR settings (creates config file if missing)
        try:
            cfg = self._load_config()
            ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg, dict) else {}
            self.sidePanel.setOcrSettings(ocr_cfg)
        except Exception:
            pass
        # Debug: load images on startup
        self.debug_on_startup()

    # ----------------------- UI Construction -----------------------
    def _createActions(self):
        self.actLoad = QAction("Load Images", self)
        self.actDetectAll = QAction("Detect All Regions", self)
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
        tb.addAction(self.actDetectAll)
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
        # PanelsChapterImagesPreview presents a vertical list of thumbnails + larger preview
        self.panelGrid = PanelsChapterImagesPreview(self._stack)
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

        self.sidePanel = PanelRightOutput(self)
        # Widen right panel for better control visibility
        self.sidePanel.setFixedWidth(400)
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
        # Detect regions (backend) and overlay them for user curation
        try:
            self.sidePanel.requestDetectRegions.connect(self._onRequestDetectRegions)
        except Exception:
            pass
        # Persist OCR settings when changed in the side panel
        try:
            self.sidePanel.ocrSettingsChanged.connect(self._onOcrSettingsChanged)
        except Exception:
            pass
        self.actLoad.triggered.connect(self._onLoadImages)
        self.actDetectAll.triggered.connect(self._onDetectAll)
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
        # Also show OCR overlay boxes on the preview when enabled in settings
        try:
            self.ocrCompleted.connect(self._onOcrOverlay)
        except Exception:
            pass

    # ----------------------- Config helpers -----------------------
    def _config_file_path(self) -> str:
        # config located at ../config/config.json relative to this file
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'config'))
        os.makedirs(base, exist_ok=True)
        return os.path.abspath(os.path.join(base, 'config.json'))

    def _load_config(self) -> dict:
        path = self._config_file_path()
        if not os.path.exists(path):
            default = {'ocr': {'lang': 'jpn', 'conf_thresh': 0, 'preprocess': True}}
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(default, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return default
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'ocr': {'lang': 'jpn', 'conf_thresh': 0, 'preprocess': True}}

    def _save_config(self, cfg: dict) -> None:
        path = self._config_file_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            show_selectable_message(self, "Config", f"Failed to save config: {e}", QMessageBox.Icon.Warning)

    def _onOcrSettingsChanged(self):
        # Persist current OCR settings to config file
        try:
            cfg = self._load_config() or {}
            cfg['ocr'] = self.sidePanel.getOcrSettings()
            self._save_config(cfg)
        except Exception:
            pass
        # Also toggle overlay visibility according to "Show OCR Boxes"
        try:
            st = self.sidePanel.getOcrSettings()
            self.panelGrid.preview.setShowBoxes(bool(st.get('show_boxes', False)))
            self.panelGrid.preview.update()
        except Exception:
            pass
    
    
    def debug_on_startup(self):
        """Debug: Load three images from _scraped_images/ (1.jpg, 2.jpg, 3.jpg) at startup."""
        import os
        img_dir = os.path.abspath("_scraped_images")
        img_names = ["1.jpg", "2.jpg", "3.jpg"]
        loaded = 0
        for name in img_names:
            path = os.path.join(img_dir, name)
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    panel_id = os.path.basename(path)
                    self.panelGrid.addPanel(panel_id, pm)
                    loaded += 1
        if loaded:
            show_info_message(self, "Debug Load", f"Loaded {loaded} debug image(s) from _scraped_images.")
            self._ensureGridVisible()

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
        show_info_message(self, "Load", f"Loaded {len(files)} image(s).")
        # Switch to panels view after loading images
        self._ensureGridVisible()

    def _onPanelSelected(self, panel_id: str):
        self.sidePanel.setPanel(panel_id)
        # Only show rectangles overlay, do NOT show block cards until OCR is run
        rects = self._panel_rects.get(panel_id, [])
        self.panelGrid.showOcrOverlay(panel_id, rects)
        # Restore OCR results if present for this panel
        ocr_blocks = self._panel_ocr_results.get(panel_id)
        if ocr_blocks:
            self.sidePanel.setOcrBlocks(panel_id, ocr_blocks)
        self.panelSelected.emit(panel_id)

    def _onRequestOcr(self, _panel_id: str):
        """OCR only selected panels' regions; if none selected, OCR the currently previewing panel."""
        # Get selected panels, or fallback to current panel
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            sel = self.panelGrid.selectedPanelIds()
        else:
            sel = []
        panel_ids = sel if sel else [self.sidePanel.current_panel]
        if not panel_ids or not panel_ids[0]:
            show_info_message(self, "OCR", "No panel selected.")
            return
        # Only OCR the first panel in the list (button is for single-panel OCR)
        panel_id = panel_ids[0]
        pm = getattr(self.panelGrid, '_pixmaps', {}).get(panel_id)
        if not pm:
            show_info_message(self, "OCR", f"Panel not found: {panel_id}")
            return
        # Use stored rectangles for this panel
        rects = self._panel_rects.get(panel_id, [])
        if not rects:
            show_info_message(self, "OCR", "No regions selected. Run Detect Regions or draw rectangles.")
            return
        # Convert to PIL.Image
        try:
            qimg = pm.toImage()
            pil_img = qimage_to_pil(qimg)
        except Exception as e:
            show_selectable_message(self, "OCR", f"Failed to prepare image: {e}", QMessageBox.Icon.Warning)
            return
        # Crop regions
        try:
            crops = crop_regions(pil_img, rects, pad=2)
        except Exception as e:
            show_selectable_message(self, "OCR", f"Cropping failed: {e}", QMessageBox.Icon.Warning)
            return
        # Assign IDs to each rectangle using panel_id + crop_idx
        for idx, rect in enumerate(rects):
            rect['id'] = f"{panel_id}_{idx}"
        # Use preloaded adapter
        adapter = self._ocr_adapter
        try:
            st = self.sidePanel.getOcrSettings()
            lang = st.get('lang', 'jpn')
            conf_thresh = int(st.get('conf_thresh', 0) or 0)
            preprocess = bool(st.get('preprocess', True))
        except Exception:
            lang = 'jpn'
            conf_thresh = 240
            preprocess = True
        # Start OCR in a background thread
        self._ocr_thread = QThread()
        items = [(panel_id, crops)]
        self._ocr_worker = OcrWorker(items, lang, adapter, conf_thresh, preprocess=preprocess)
        self._ocr_worker.moveToThread(self._ocr_thread)
        self._ocr_thread.started.connect(self._ocr_worker.run)
        def on_item_finished(panel_id, results):
            # Map returned texts to rect IDs in the same order
            rects_for_panel = self._panel_rects.get(panel_id, [])
            blocks_with_ids = []
            for idx, result in enumerate(results or []):
                rect_id = None
                if idx < len(rects_for_panel):
                    rect_id = rects_for_panel[idx].get('id')
                    text = result.get('text', '')
                blocks_with_ids.append({'id': rect_id or f"{panel_id}_{idx}", 'text': text})
            # Save OCR results for this panel in memory
            self._panel_ocr_results[panel_id] = blocks_with_ids.copy()
            self.sidePanel.setOcrBlocks(panel_id, blocks_with_ids)
            self._ocr_thread.quit()
            self._ocr_worker.deleteLater()
            self._ocr_thread.deleteLater()
        def on_error(panel_id, msg):
            show_selectable_message(self, "OCR", f"OCR failed: {msg}", QMessageBox.Icon.Warning)
            self._ocr_thread.quit()
            self._ocr_worker.deleteLater()
            self._ocr_thread.deleteLater()
        self._ocr_worker.itemFinished.connect(on_item_finished)
        self._ocr_worker.itemError.connect(on_error)
        self._ocr_thread.start()

    def _ocr_all_panels_regions(self):
        """
        Not exposed: OCR all loaded panels' regions. For future batch OCR feature.
        """
        for panel_id, pm in getattr(self.panelGrid, '_pixmaps', {}).items():
            rects = self._panel_rects.get(panel_id, [])
            if not rects:
                continue
            try:
                qimg = pm.toImage()
                pil_img = qimage_to_pil(qimg)
                crops = crop_regions(pil_img, rects, pad=2)
            except Exception:
                continue
            adapter = self._ocr_adapter
            try:
                st = self.sidePanel.getOcrSettings()
                lang = st.get('lang', 'jpn')
            except Exception:
                lang = 'jpn'
            # This is a placeholder for future batch threading/aggregation logic
            # For now, just a stub for future work
            # Example: texts = [adapter.recognize(crop, lang=lang) for crop in crops]
            pass

    def _onRequestTranslate(self, panel_id: str):
        # Placeholder translation echo.
        translated = "(EN) " + "; ".join(["example", "sample", "test"])
        self.translationCompleted.emit(panel_id, translated)

    def _onRequestDetectRegions(self):
        """Detect regions for the currently previewed panel only."""
        panel_id = self.sidePanel.current_panel
        if not panel_id:
            show_info_message(self, "Detect Regions", "No panel selected.")
            return
        pm = getattr(self.panelGrid, '_pixmaps', {}).get(panel_id)
        if pm is None or pm.isNull():
            show_info_message(self, "Detect Regions", "No image for the selected panel.")
            return
        # Convert QPixmap -> QImage -> PIL.Image
        try:
            qimg = pm.toImage()
            pil_img = qimage_to_pil(qimg)
        except Exception as e:
            show_selectable_message(self, "Detect Regions", f"Failed to prepare image: {e}", QMessageBox.Icon.Warning)
            return
        # Read settings to decide blur; keep threshold as a constant for now
        try:
            st = self.sidePanel.getOcrSettings()
            blur_enabled = bool(st.get('preprocess', True))
            threshold = int(st.get('conf_thresh', 240) or 240)
        except Exception:
            blur_enabled = False
            threshold = 240
        # Run detection
        try:
            rects = detect_text_regions(
                pil_img,
                blur=blur_enabled,
                fixed_threshold=threshold,
                subsume_ratio_primary=0.8,
                kernel_trials=[(3, 5, 1), (5, 10, 2), (5, 15, 4), (7, 7, 2)],
            )
        except Exception as e:
            show_selectable_message(self, "Detect Regions", f"Detection failed: {e}", QMessageBox.Icon.Warning)
            return
        # Overlay rectangles in the interactive preview and store them
        try:
            self.previewDetectedRegions(panel_id, rects)
        except Exception:
            pass

    def _onOcrWorkerFinished(self, panel_id: str, blocks: list):
        try:
            self.ocrCompleted.emit(panel_id, blocks)
        finally:
            # cleanup any finished threads from the active list
            if hasattr(self, '_activeOcrThreads'):
                self._activeOcrThreads = [(t, w) for (t, w) in self._activeOcrThreads if w is not None and w.panel_id != panel_id]

    def _onOcrWorkerError(self, panel_id: str, errmsg: str):
        show_selectable_message(self, "OCR Error", f"OCR failed for {panel_id}: {errmsg}", QMessageBox.Icon.Warning)
        # ensure removal from active list
        if hasattr(self, '_activeOcrThreads'):
            self._activeOcrThreads = [(t, w) for (t, w) in self._activeOcrThreads if w is not None and w.panel_id != panel_id]

    def _onOcrOverlay(self, panel_id: str, blocks: list):
        """If the user has enabled overlay boxes, render them on the preview for the panel."""
        try:
            settings = self.sidePanel.getOcrSettings()
            if not settings.get('show_boxes', False):
                return
        except Exception:
            return
        # blocks expected as list[dict] with left,top,width,height
        if not blocks or not isinstance(blocks, list) or not isinstance(blocks[0], dict):
            return
        try:
            self.panelGrid.showOcrOverlay(panel_id, blocks)
        except Exception:
            pass

    # ----------------------- Region Detection (GUI stubs) -----------------------
    def previewDetectedRegions(self, panel_id: str, rects: list[dict]) -> None:
        """Preview detected regions as overlay boxes on the panel preview, 
        and store per-panel rectangles."""
        if not rects or not isinstance(rects, list):
            return
        # Store rectangles for this panel
        self._panel_rects[panel_id] = rects.copy()
        try:
            self.panelGrid.showOcrOverlay(panel_id, rects)
        except Exception:
            pass

    def beginRegionSelection(self, panel_id: str) -> None:
        """Stub entry point for interactive region selection workflow.

        Planned flow:
        - Display current rectangles on preview
        - Allow user to add (drag-to-draw), remove (click "X"), and multi-select
        - Confirm to proceed with cropping + OCR of curated rectangles

        Implementation will be added in a follow-up, keeping this hook to
        avoid touching broader UI logic now.
        """
        try:
            self.sidePanel.setPanel(panel_id)
            # When switching panels, update the preview with the correct rectangles
            rects = self._panel_rects.get(panel_id, [])
            self.panelGrid.showOcrOverlay(panel_id, rects)
        except Exception:
            pass

    def _onDetectAll(self):
        """Detect regions for all loaded panels."""
        from PyQt6.QtWidgets import QProgressDialog
        pixmaps = getattr(self.panelGrid, '_pixmaps', {})
        panel_ids = list(pixmaps.keys())
        total = len(panel_ids)
        if total == 0:
            show_info_message(self, "Detect Regions", "No panels loaded.")
            return
        progress = QProgressDialog("Detecting regions...", "Cancel", 0, total, self)
        progress.setWindowTitle("Detect All Regions")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.show()
        cancelled = [False]
        for idx, panel_id in enumerate(panel_ids):
            if progress.wasCanceled():
                cancelled[0] = True
                break
            pm = pixmaps.get(panel_id)
            if pm is None or pm.isNull():
                continue
            try:
                qimg = pm.toImage()
                pil_img = qimage_to_pil(qimg)
            except Exception as e:
                show_selectable_message(self, "Detect Regions", f"Failed to prepare image for {panel_id}: {e}", QMessageBox.Icon.Warning)
                continue
            try:
                st = self.sidePanel.getOcrSettings()
                blur_enabled = bool(st.get('preprocess', True))
                threshold = int(st.get('conf_thresh', 240) or 240)
            except Exception:
                blur_enabled = False
                threshold = 240
            try:
                rects = detect_text_regions(
                    pil_img,
                    blur=blur_enabled,
                    fixed_threshold=threshold,
                    subsume_ratio_primary=0.8,
                    kernel_trials=[(3, 5, 1), (5, 10, 2), (5, 15, 4), (7, 7, 2)],
                )
            except Exception as e:
                show_selectable_message(self, "Detect Regions", f"Detection failed for {panel_id}: {e}", QMessageBox.Icon.Warning)
                continue
            self.previewDetectedRegions(panel_id, rects)
            progress.setValue(idx + 1)
            QApplication.processEvents()
        progress.close()
        if cancelled[0]:
            show_info_message(self, "Detect Regions", "Detection cancelled.")
        else:
            show_info_message(self, "Detect Regions", f"Detected regions for {total} panels.")

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
            show_info_message(self, "Translate", f"Translated {done} / {total} panels.")
        else:
            if not self.sidePanel.current_panel:
                show_info_message(self, "Translate", "No panel selected to translate.")
                return
            self._onRequestTranslate(self.sidePanel.current_panel)

    def _onExport(self):
        # Placeholder: aggregate text blocks + translation.
        if not self.sidePanel.current_panel:
            show_info_message(self, "Export", "No panel selected.")
            return
        blocks = [self.sidePanel.blocksList.item(i).text() for i in range(self.sidePanel.blocksList.count())]
        translation = self.sidePanel.translationEdit.toPlainText()
        summary = f"Panel: {self.sidePanel.current_panel}\nBlocks: {blocks}\nTranslation:\n{translation}"
        show_info_message(self, "Export (stub)", summary)


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
            show_info_message(self, "WebEngine Missing", "PyQt6-WebEngine not installed.")

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
            show_info_message(self, "Capture", "Web view not visible.")
            return
        pm = self.webView.grab()  # Visible region screenshot
        if pm.isNull():
            show_selectable_message(self, "Capture", "Failed to grab web view.", QMessageBox.Icon.Warning)
            return
        panel_id = f"web_{len(self.panelGrid._cards)+1}"
        # Add captured image to panels but KEEP the browser visible so user can continue navigating.
        self.panelGrid.addPanel(panel_id, pm)
        show_info_message(self, "Capture", f"Captured web view as panel {panel_id}. Use 'Show Panels' to view panels.")

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
                show_info_message(self, "Scrape", "No images found.")
                return
            dlg = ImageSelectionDialog(entries, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return  # user cancelled selection
            selected = dlg.selectedUrls()
            if not selected:
                show_info_message(self, "Scrape", "No images selected for download.")
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
        # Remove selected panels from the PanelsChapterImagesPreview (or fallback)
        removed: list[str] = []
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            removed = self.panelGrid.selectedPanelIds()
            if removed:
                self.panelGrid.removeSelectedPanels()
                # Remove only the rects and ocr_results for panels that are actually removed
                for panel_id in removed:
                    self._panel_rects.pop(panel_id, None)
                    self._panel_ocr_results.pop(panel_id, None)
        else:
            show_info_message(self, "Remove", "Panel removal not supported for this view.")
            return

        # If the side panel was showing one of the removed panels, clear it
        if self.sidePanel.current_panel and self.sidePanel.current_panel in removed:
            self.sidePanel.setPanel(None)

    # ----------------------- Background Image Download -----------------------
    def _downloadSelectedImages(self, urls: list[str]):
        """Download chosen image URLs using a QThread worker with signals for progress/cancel."""
        if not urls:
            return
        # Deduplicate exact URL matches (preserve first occurrence order).
        # This avoids adding the same scraped image multiple times when the
        # page contains duplicate <img> tags or identical sources.
        seen_urls = set()
        unique_urls: list[str] = []
        dup_count = 0
        for u in urls:
            if u in seen_urls:
                dup_count += 1
                continue
            seen_urls.add(u)
            unique_urls.append(u)
        if dup_count:
            try:
                QMessageBox.information(self, "Scrape", f"Skipped {dup_count} duplicate image(s).")
            except Exception:
                pass
        urls = unique_urls
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

        # Collect per-item errors to present a single aggregated dialog at the end
        batch_errors: list[tuple[str, str]] = []
        def _collect_download_error(url_or_id: str, errmsg: str):
            try:
                batch_errors.append((url_or_id, errmsg))
            except Exception:
                pass

        # Wiring
        worker.progress.connect(lambda idx: progressDlg.setValue(idx))
        worker.itemReady.connect(lambda panel_id, pm: self.panelGrid.addPanel(panel_id, pm))
        try:
            worker.itemError.connect(_collect_download_error)
        except Exception:
            pass

        # Temporarily suppress modal messageboxes while downloads are in-flight.
        # Some network errors or other signal handlers may show per-item dialogs; capture them
        # and present a single aggregated dialog after the batch completes.
        suppressed_msgs: list[tuple[str, str]] = []
        from PyQt6.QtWidgets import QMessageBox as _QMB
        _orig_warning = _QMB.warning
        _orig_info = _QMB.information

        def _capture_warning(parent, title, text, *args, **kwargs):
            try:
                suppressed_msgs.append((title or 'Warning', text or ''))
            except Exception:
                pass
            # emulate standard return value (button role) as None
            return None

        def _capture_info(parent, title, text, *args, **kwargs):
            try:
                suppressed_msgs.append((title or 'Info', text or ''))
            except Exception:
                pass
            return None

        # Patch QMessageBox functions
        try:
            _QMB.warning = staticmethod(_capture_warning)  # type: ignore[attr-defined]
            _QMB.information = staticmethod(_capture_info)  # type: ignore[attr-defined]
        except Exception:
            # If patching fails, continue without suppression
            pass

        def _restore_messageboxes():
            try:
                _QMB.warning = _orig_warning
                _QMB.information = _orig_info
            except Exception:
                pass

        # Guard to ensure we only present the summary once even if `finished` fires
        # multiple times due to races with dialog close / cancel handlers.
        _done_called = {'v': False}
        def done(status: str, added: int, errors: int, cancelled: bool):
            if _done_called['v']:
                return
            _done_called['v'] = True
            # restore message boxes first so subsequent dialogs (summary) show normally
            _restore_messageboxes()
            # Prevent on_close from racing in while we close the dialog: clear active worker
            try:
                self._activeDownloadWorker = None
            except Exception:
                pass
            # Disconnect the on_close handler so calling close() does not trigger a cancel
            try:
                progressDlg.finished.disconnect(on_close)
            except Exception:
                pass
            try:
                progressDlg.close()
            except Exception:
                pass
            # Show the regular end-of-download info
            try:
                _orig_info(self, "Download", f"{status}. Added {added} image(s). Errors: {errors}")
            except Exception:
                pass
            # If any per-item errors were collected via signals, show aggregated warning
            try:
                if batch_errors:
                    max_show = 8
                    lines = [f"{pid}: {err}" for pid, err in batch_errors[:max_show]]
                    more = len(batch_errors) - len(lines)
                    if more > 0:
                        lines.append(f"... and {more} more errors")
                    _orig_warning(self, "Download Errors", "Errors occurred during download:\n" + "\n".join(lines))
            except Exception:
                pass
            # Also show any suppressed modal messages that were captured during the run (limit output)
            try:
                if suppressed_msgs:
                    # Deduplicate suppressed messages that mirror per-item errors (avoid double-reporting)
                    seen_texts = set(u for u, _ in batch_errors)
                    filtered = []
                    for title, msg in suppressed_msgs:
                        # skip if message contains a URL or id we've already reported
                        if any(key in msg for key in seen_texts):
                            continue
                        filtered.append((title, msg))
                    if filtered:
                        max_show = 6
                        lines = [f"{t}: {m}" for t, m in filtered[:max_show]]
                        more = len(filtered) - len(lines)
                        if more > 0:
                            lines.append(f"... and {more} more messages")
                        _orig_warning(self, "Additional Messages During Download", "Some dialogs were suppressed during batch download:\n" + "\n".join(lines))
            except Exception:
                pass
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


# ImageSelectionDialog moved to ui.components.dialogs


"""AsyncImageDownloadWorker moved to ui.components.async_workers"""


# Legacy blocking preview worker removed; AsyncImagePreviewer is used instead.


"""AsyncImagePreviewer moved to ui.components.async_workers"""



# Unified OcrWorker: handles both single-panel (multi-crop) and batch (multi-panel) OCR
"""OcrWorker moved to ui.components.async_workers"""

def create_app_window() -> MainWindow:
    """Factory to create the fully constructed MainWindow."""
    return MainWindow()
