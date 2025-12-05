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

class PanelImageThumbnailCard(QWidget):
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



class PanelsChapterImagesPreview(QWidget):
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
        # Allow multi-selection for batch operations; use ExtendedSelection so
        # Shift+click performs a range selection (expected desktop behavior).
        self.listWidget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.listWidget.setMinimumWidth(180)
        # Icon-only appearance
        self.listWidget.setSpacing(6)
        self.listWidget.setUniformItemSizes(True)
        self.listWidget.setWordWrap(False)
        self.listWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.listWidget.customContextMenuRequested.connect(self._onContextMenu)

        # Right: preview area
        previewContainer = QVBoxLayout()
        # Interactive preview widget that supports rectangle overlay, selection,
        # multi-select (marquee), add-by-drag, and removal.
        self.preview = RectPreview(self)
        self.preview.setMinimumSize(480, 520)
        previewContainer.addWidget(self.preview, 1)

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
        # Offer both removing the clicked item and removing all selected items.
        act_remove_clicked = menu.addAction("Remove This")
        act_remove_selected = menu.addAction("Remove Selected")
        act = menu.exec(self.listWidget.mapToGlobal(pos))
        if act is act_remove_clicked:
            # Remove only the item that was right-clicked
            try:
                pid = item.data(Qt.ItemDataRole.UserRole) or item.text()
                # remove from internal lists if present
                try:
                    self._cards.remove(pid)
                except Exception:
                    pass
                try:
                    del self._pixmaps[pid]
                except Exception:
                    pass
                row = self.listWidget.row(item)
                self.listWidget.takeItem(row)
            except Exception:
                pass
        elif act is act_remove_selected:
            # Remove all currently selected items
            self.removeSelectedPanels()

    def _onItemClicked(self, item: QListWidgetItem):
        panel_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
        pm = self._pixmaps.get(panel_id)
        if pm:
            # Show original pixmap in interactive preview; it handles scaling.
            self.preview.setPixmap(pm)
        self.panelSelected.emit(panel_id)

    def showOcrOverlay(self, panel_id: str, blocks: list[dict]):
        """Draw OCR bounding boxes over the panel preview.

        `blocks` should be list of dicts with keys: left, top, width, height
        """
        pm = self._pixmaps.get(panel_id)
        if pm is None or pm.isNull():
            return
        # Forward rectangles to interactive preview; it will render/scaling.
        try:
            # Pass panel_id so RectPreview assigns IDs as panel_id+idx
            self.preview.setRects(blocks, panel_id=panel_id)
        except Exception:
            pass


class RightSidePanel(QWidget):
    # Store edited block texts per panel
    _panel_block_edits = {}
    """Right-side detail pane showing OCR text blocks and translations."""
    requestOcr = pyqtSignal(str)
    requestTranslate = pyqtSignal(str)
    requestDetectRegions = pyqtSignal(str)
    ocrSettingsChanged = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Store a direct reference to MainWindow for rectangle sync
        self.main_window = parent if isinstance(parent, QMainWindow) else None
        outer = QVBoxLayout(self)

        self.title = QLabel("No panel selected")
        self.title.setObjectName("panelTitle")
        outer.addWidget(self.title)

        # Row: Extracted Text Blocks label + top-right add (+) button
        blocksRow = QHBoxLayout()
        blocksRow.addWidget(QLabel("Extracted Text Blocks:"))
        self.addBlockBtn = QPushButton("+")
        self.addBlockBtn.setFixedSize(28, 28)
        self.addBlockBtn.setToolTip("Add a new OCR block card")
        blocksRow.addStretch(1)
        blocksRow.addWidget(self.addBlockBtn)
        outer.addLayout(blocksRow)

        # OCR text blocks list
        self.blocksList = QListWidget(self)
        # Enable drag-and-drop reordering
        try:
            self.blocksList.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.blocksList.setDefaultDropAction(Qt.DropAction.MoveAction)
        except Exception:
            pass
        # Enable multi-selection: shift-click for range, control-click for individuals
        self.blocksList.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        # Enable right-click context menu for delete
        self.blocksList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.blocksList.customContextMenuRequested.connect(self._showBlockContextMenu)
        # Wire add button
        self.addBlockBtn.clicked.connect(self._addBlock)
        outer.addWidget(self.blocksList, 2)

        # Place Translate beneath the blocks zone, aligned to the right
        translateRow = QHBoxLayout()
        translateRow.addStretch(1)
        self.txBtn = QPushButton("Translate")
        translateRow.addWidget(self.txBtn)
        outer.addLayout(translateRow)

        # Translation output
        outer.addWidget(QLabel("Translation:"))
        # Translation output as cards
        self.translationList = QListWidget(self)
        self.translationList.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        outer.addWidget(self.translationList, 1)

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
        self.detectBtn = QPushButton("Detect Regions")
        self.ocrBtn = QPushButton("OCR")
        actionRow.addWidget(self.detectBtn)
        actionRow.addWidget(self.ocrBtn)
        outer.addLayout(actionRow)

        self.current_panel: Optional[str] = None
        self.ocrBtn.clicked.connect(self._emit_ocr)
        self.detectBtn.clicked.connect(self._emit_detect_regions)
        self.txBtn.clicked.connect(self._emit_translate)

        # OCR settings controls (language, confidence threshold, preprocess)
        settingsRow = QHBoxLayout()
        self.langCombo = QComboBox(self)
        # Map display name -> tesseract lang code
        self.langCombo.addItem('Japanese', 'jpn')
        self.langCombo.addItem('Chinese (Simplified)', 'chi_sim')
        self.langCombo.addItem('Korean', 'kor')
        settingsRow.addWidget(QLabel("Lang:"))
        settingsRow.addWidget(self.langCombo)

        # Threshold control (frontend value passed to backend when applicable)
        self.threshSpin = QSpinBox(self)
        self.threshSpin.setRange(0, 300)
        self.threshSpin.setValue(240)
        settingsRow.addWidget(QLabel("Threshold:"))
        settingsRow.addWidget(self.threshSpin)

        # Clarify that this toggles Gaussian blur in detection
        self.preprocChk = QCheckBox("Preprocess: Gaussian Blur")
        self.preprocChk.setChecked(True)
        settingsRow.addWidget(self.preprocChk)

        self.showBoxesChk = QCheckBox("Show OCR Boxes")
        # Default ON so users can curate boxes immediately
        self.showBoxesChk.setChecked(True)
        settingsRow.addWidget(self.showBoxesChk)

        outer.addLayout(settingsRow)

        # Wire control changes to emit the class-level signal
        self.langCombo.currentIndexChanged.connect(lambda _: self.ocrSettingsChanged.emit())
        self.threshSpin.valueChanged.connect(lambda _: self.ocrSettingsChanged.emit())
        self.preprocChk.stateChanged.connect(lambda _: self.ocrSettingsChanged.emit())
        self.showBoxesChk.stateChanged.connect(lambda _: self.ocrSettingsChanged.emit())

    def _showBlockContextMenu(self, pos):
        item = self.blocksList.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete Block")
        delete_selected_action = menu.addAction("Delete Selected")
        chosen = menu.exec(self.blocksList.mapToGlobal(pos))
        panel_id = getattr(self, 'current_panel', None)
        if chosen is delete_action:
            row = self.blocksList.row(item)
            widget = self.blocksList.itemWidget(item)
            block_id = getattr(widget, 'block_id', None) if widget else None
            self.blocksList.takeItem(row)
            # Keep edits cache in sync if present
            if panel_id in self._panel_block_edits:
                edits = self._panel_block_edits.get(panel_id, [])
                if 0 <= row < len(edits):
                    edits.pop(row)
                    self._panel_block_edits[panel_id] = edits
            # Remove the corresponding rectangle using direct main_window reference
            mw = self.main_window
            if mw and hasattr(mw, '_panel_rects') and block_id:
                rects = mw._panel_rects.get(panel_id, [])
                new_rects = [r for r in rects if r.get('id') != block_id]
                mw._panel_rects[panel_id] = new_rects
                # Update the preview
                if hasattr(mw.panelGrid, 'showOcrOverlay'):
                    mw.panelGrid.showOcrOverlay(panel_id, new_rects)
            # Renumber block card labels only (preserve text)
            self.renumberBlockCardLabels()
        elif chosen is delete_selected_action:
            selected_items = self.blocksList.selectedItems()
            rows_and_block_ids = []
            for it in selected_items:
                row = self.blocksList.row(it)
                widget = self.blocksList.itemWidget(it)
                block_id = getattr(widget, 'block_id', None) if widget else None
                rows_and_block_ids.append((row, block_id))
            # Remove selected items from blocksList and edits cache
            for row, _ in sorted(rows_and_block_ids, reverse=True):
                self.blocksList.takeItem(row)
                if panel_id in self._panel_block_edits:
                    edits = self._panel_block_edits.get(panel_id, [])
                    if 0 <= row < len(edits):
                        edits.pop(row)
                        self._panel_block_edits[panel_id] = edits
            # Remove all corresponding rectangles from MainWindow._panel_rects
            mw = self.main_window
            block_ids_to_remove = set(bid for _, bid in rows_and_block_ids if bid)
            if mw and hasattr(mw, '_panel_rects') and block_ids_to_remove:
                rects = mw._panel_rects.get(panel_id, [])
                new_rects = [r for r in rects if r.get('id') not in block_ids_to_remove]
                mw._panel_rects[panel_id] = new_rects
                # Update the preview
                if hasattr(mw.panelGrid, 'showOcrOverlay'):
                    mw.panelGrid.showOcrOverlay(panel_id, new_rects)
            # Renumber block card labels only (preserve text)
            self.renumberBlockCardLabels()

    def _addBlock(self):
        # Add a new empty editable OCR block card at the end
        panel_id = getattr(self, 'current_panel', None)
        w = QWidget(self.blocksList)
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        edit = QLineEdit("", w)
        edit.setMinimumWidth(220)
        edit.setStyleSheet("font-size: 15px; padding: 6px;")
        h.addWidget(edit, 1)
        item = QListWidgetItem(self.blocksList)
        item.setSizeHint(w.sizeHint())
        self.blocksList.addItem(item)
        self.blocksList.setItemWidget(item, w)
        # Persist when user finishes editing
        idx = self.blocksList.count() - 1
        edit.editingFinished.connect(lambda i=idx, e=edit: self._onBlockEditFinished(panel_id, i, e.text()))
    def setPanel(self, panel_id: str):
        self.current_panel = panel_id
        if panel_id:
            self.title.setText(f"Panel: {panel_id}")
        else:
            self.title.setText("No panel selected")
        self.blocksList.clear()
        self.translationList.clear()
        self.dictEdit.clear()
        self.similarityList.clear()

    def setOcrBlocks(self, panel_id: str, blocks: List):
        if panel_id != self.current_panel:
            return
        self.blocksList.clear()
        edited_blocks = self._panel_block_edits.get(panel_id, None)
        if not blocks:
            return
        # Track the currently active editor (QLineEdit) and its label
        self._active_block_editor = getattr(self, '_active_block_editor', None)
        self._active_block_label = getattr(self, '_active_block_label', None)
        for idx, block in enumerate(blocks):
            try:
                #Prefer user-edited text; else extract textual payload only
                if edited_blocks and idx < len(edited_blocks) and isinstance(edited_blocks[idx], str):
                    text = edited_blocks[idx]
                elif isinstance(block, dict):
                    text = block.get('text', '')
                elif isinstance(block, str):
                    text = block
                else:
                    text = ''
                text = block.get('text', '')
                w = QWidget(self.blocksList)
                h = QHBoxLayout(w)
                h.setContentsMargins(8, 6, 8, 6)
                # Add block number label
                num_label = QLabel(f"{idx+1}", w)
                num_label.setStyleSheet("color: #888; font-size: 13px; font-weight: bold; padding-right: 8px;")
                num_label.setFixedWidth(24)
                h.addWidget(num_label, 0)
                # Wrap text_label in a container for easy swap
                text_container = QWidget(w)
                text_layout = QVBoxLayout(text_container)
                text_layout.setContentsMargins(0, 0, 0, 0)
                text_label = QLabel(str(text), text_container)
                text_label.setStyleSheet("font-size: 15px; padding: 6px;")
                text_label.setMinimumWidth(220)
                text_layout.addWidget(text_label)
                h.addWidget(text_container, 1)
                item = QListWidgetItem(self.blocksList)
                item.setSizeHint(w.sizeHint())
                self.blocksList.addItem(item)
                self.blocksList.setItemWidget(item, w)

                # Assign block_id to the widget for removal logic
                block_id = None
                if isinstance(block, dict) and 'id' in block:
                    block_id = block['id']
                else:
                    block_id = f"{panel_id}_{idx}"
                setattr(w, 'block_id', block_id)

                # Dedicated event filter for each label
                class LabelEditFilter(QObject):
                    def __init__(self, label, container, idx, panel_id, sidepanel):
                        super().__init__(label)
                        self.label = label
                        self.container = container
                        self.idx = idx
                        self.panel_id = panel_id
                        self.sidepanel = sidepanel
                    def eventFilter(self, obj, event):
                        if obj is self.label and event.type() == event.Type.MouseButtonDblClick:
                            # If another editor is open, close it first
                            if self.sidepanel._active_block_editor is not None:
                                prev_edit = self.sidepanel._active_block_editor
                                prev_label = self.sidepanel._active_block_label
                                prev_container = prev_label.parent()
                                prev_label.setText(prev_edit.text())
                                prev_container.layout().removeWidget(prev_edit)
                                prev_edit.deleteLater()
                                prev_label.show()
                                self.sidepanel._active_block_editor = None
                                self.sidepanel._active_block_label = None
                            self.label.hide()
                            edit = QLineEdit(self.label.text(), self.container)
                            edit.setMinimumWidth(220)
                            edit.setStyleSheet("font-size: 15px; padding: 6px;")
                            self.container.layout().addWidget(edit)
                            edit.setFocus()
                            self.sidepanel._active_block_editor = edit
                            self.sidepanel._active_block_label = self.label
                            def finish_edit():
                                self.sidepanel._onBlockEditFinished(self.panel_id, self.idx, edit.text())
                                self.label.setText(edit.text())
                                self.container.layout().removeWidget(edit)
                                edit.deleteLater()
                                self.label.show()
                                self.sidepanel._active_block_editor = None
                                self.sidepanel._active_block_label = None
                            edit.editingFinished.connect(finish_edit)
                            return True
                        return False

                filter_obj = LabelEditFilter(text_label, text_container, idx, panel_id, self)
                text_label.installEventFilter(filter_obj)
            except Exception:
                QListWidgetItem("I broke.", self.blocksList)

    class EditOnDoubleClickFilter(QObject):
        """Event filter to enable editing on double-click for QLineEdit."""
        def __init__(self, line_edit):
            super().__init__(line_edit)
            self.line_edit = line_edit
        def eventFilter(self, obj, event):
            if obj is self.line_edit and event.type() == event.Type.MouseButtonDblClick:
                self.line_edit.setReadOnly(False)
                self.line_edit.setFocus()
                return True
            return False

    def _onBlockEditFinished(self, panel_id: str, idx: int, new_text: str):
        # Update the edited block text for this panel and index
        edits = self._panel_block_edits.get(panel_id, [])
        # Ensure the list is long enough
        while len(edits) <= idx:
            edits.append("")
        edits[idx] = new_text
        self._panel_block_edits[panel_id] = edits

    def _onBlockEdited(self, panel_id: str):
        # Save all current block texts for this panel
        texts = [self.blocksList.item(i).text() for i in range(self.blocksList.count())]
        self._panel_block_edits[panel_id] = texts

    def getOcrSettings(self) -> dict:
        """Return current OCR settings as a dict."""
        lang = self.langCombo.currentData() or 'jpn'
        threshold = int(self.threshSpin.value() or 0)
        pre = bool(self.preprocChk.isChecked())
        show_boxes = bool(self.showBoxesChk.isChecked())
        return {'lang': lang, 'threshold': threshold, 'preprocess': pre, 'show_boxes': show_boxes}

    def setOcrSettings(self, settings: dict):
        """Apply OCR settings from a dict (best-effort)."""
        lang = settings.get('lang', 'jpn')
        idx = 0
        for i in range(self.langCombo.count()):
            if self.langCombo.itemData(i) == lang:
                idx = i
                break
        self.langCombo.setCurrentIndex(idx)
        try:
            self.threshSpin.setValue(int(settings.get('threshold', 240)))
        except Exception:
            self.threshSpin.setValue(240)
        try:
            self.preprocChk.setChecked(bool(settings.get('preprocess', True)))
        except Exception:
            self.preprocChk.setChecked(True)
        try:
            self.showBoxesChk.setChecked(bool(settings.get('show_boxes', True)))
        except Exception:
            self.showBoxesChk.setChecked(False)

    def setTranslation(self, panel_id: str, translated: str):
        if panel_id != self.current_panel:
            return
        self.translationList.clear()
        # If translated is a string, split by lines; if list, use directly
        if isinstance(translated, str):
            blocks = [s.strip() for s in translated.split('\n') if s.strip()]
        elif isinstance(translated, list):
            blocks = [str(s) for s in translated]
        else:
            blocks = []
        for idx, text in enumerate(blocks):
            w = QWidget(self.translationList)
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 6, 8, 6)
            num_label = QLabel(f"{idx+1}", w)
            num_label.setStyleSheet("color: #888; font-size: 13px; font-weight: bold; padding-right: 8px;")
            num_label.setFixedWidth(24)
            h.addWidget(num_label, 0)
            label = QLabel(str(text), w)
            label.setStyleSheet("font-size: 15px; padding: 6px;")
            label.setMinimumWidth(220)
            h.addWidget(label, 1)
            item = QListWidgetItem(self.translationList)
            item.setSizeHint(w.sizeHint())
            self.translationList.addItem(item)
            self.translationList.setItemWidget(item, w)

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
        pid = self.current_panel
        if not pid:
            # Try to fallback to the application's current selection if available
            try:
                mw = self.parent()
                if mw and hasattr(mw, 'panelGrid'):
                    sel = mw.panelGrid.selectedPanelIds()
                    pid = sel[0] if sel else None
            except Exception:
                pid = None
        if pid:
            self.requestOcr.emit(pid)
        else:
            try:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "OCR", "No panel selected for OCR.")
            except Exception:
                pass

    def _emit_translate(self):
        if self.current_panel:
            self.requestTranslate.emit(self.current_panel)

    def _emit_detect_regions(self):
        pid = self.current_panel
        if not pid:
            try:
                mw = self.parent()
                if mw and hasattr(mw, 'panelGrid'):
                    sel = mw.panelGrid.selectedPanelIds()
                    pid = sel[0] if sel else None
            except Exception:
                pid = None
        if pid:
            self.requestDetectRegions.emit(pid)
        else:
            try:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Detect Regions", "No panel selected.")
            except Exception:
                pass


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

        # Debug: print remaining block IDs in blocksList after removal
        # remaining_block_ids = []
        # for i in range(self.sidePanel.blocksList.count()):
        #     item = self.sidePanel.blocksList.item(i)
        #     widget = self.sidePanel.blocksList.itemWidget(item)
        #     if widget:
        #         block_id = getattr(widget, 'block_id', None)
        #         remaining_block_ids.append(block_id)
        #print("[DEBUG] Remaining OCR block IDs after removal:", remaining_block_ids)
        
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

        self.sidePanel = RightSidePanel(self)
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
                    text=result.get('text', '')
                blocks_with_ids.append({'id': rect_id or f"{panel_id}_{idx}", 'text': text})
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

    def _onRequestDetectRegions(self, _panel_id: str):
        """Detect regions for selected panels, or current if none selected."""
        if hasattr(self.panelGrid, 'selectedPanelIds'):
            sel = self.panelGrid.selectedPanelIds()
        else:
            sel = []
        panel_ids = sel if sel else [self.sidePanel.current_panel]
        if not panel_ids or not panel_ids[0]:
            show_info_message(self, "Detect Regions", "No panel selected.")
            return
        # Only process the first panel for now (single-panel detect)
        panel_id = panel_ids[0]
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
        except Exception:
            blur_enabled = False
        # Run detection
        try:
            rects = detect_text_regions(
                pil_img,
                blur=blur_enabled,
                fixed_threshold=240,
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
        """Preview detected regions as overlay boxes on the panel preview, and store per-panel rectangles."""
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
        # Prepare (panel_id, QImage) items for batch processing
        items: list[tuple[str, object]] = []
        for pid in ids:
            pm = getattr(self.panelGrid, '_pixmaps', {}).get(pid)
            if pm:
                items.append((pid, pm.toImage()))

        if not items:
            show_info_message(self, "OCR", "No panel images available for OCR.")
            return

        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("Running OCR...", "Cancel", 0, len(items), self)
        progress.setWindowTitle("OCR Panels")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.show()

        # Get OCR settings from side panel
        try:
            st = self.sidePanel.getOcrSettings()
            lang = st.get('lang', 'jpn')
            conf = int(st.get('conf_thresh', 0) or 0)
            pre = bool(st.get('preprocess', True))
        except Exception:
            lang, conf, pre = 'jpn', 0, True

        # Use preloaded adapter
        adapter = self._ocr_adapter
        # Batch worker + thread
        worker = OcrWorker(items, lang=lang, adapter=adapter, conf_thresh=conf, preprocess=pre)
        thread = QThread(self)
        worker.moveToThread(thread)

        # Keep reference to allow cancel and avoid GC
        self._activeOcrBatch = (thread, worker)

        worker.itemFinished.connect(lambda pid, blocks: self.ocrCompleted.emit(pid, blocks))
        # Collect per-item batch errors and show a single aggregated dialog after completion
        batch_errors: list[tuple[str, str]] = []
        def _collect_item_error(pid: str, err: str):
            try:
                batch_errors.append((pid, err))
            except Exception:
                pass
        try:
            worker.error.connect(_collect_item_error)
        except Exception:
            pass
        worker.progress.connect(lambda done, total: progress.setValue(done))

        def on_finished(done_count: int):
            progress.close()
            show_info_message(self, "OCR", f"Processed {done_count} / {len(items)} panels.")
            # If any per-item errors were collected, present a single aggregated warning.
            try:
                if batch_errors:
                    # Show up to a handful of errors to avoid overwhelming the user
                    max_show = 8
                    lines = [f"{pid}: {err}" for pid, err in batch_errors[:max_show]]
                    more = len(batch_errors) - len(lines)
                    if more > 0:
                        lines.append(f"... and {more} more errors")
                    QMessageBox.warning(self, "OCR Errors", "Errors occurred during OCR:\n" + "\n".join(lines))
            except Exception:
                pass
            try:
                worker.deleteLater()
            except Exception:
                pass
            try:
                thread.deleteLater()
            except Exception:
                pass
            self._activeOcrBatch = None

        worker.finished.connect(on_finished)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.start()

        # Wire cancel
        def on_cancel():
            try:
                worker.cancel()
            except Exception:
                pass
        progress.canceled.connect(on_cancel)

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
    itemError = pyqtSignal(str, str)      # url_or_panel_id, error message
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
                    try:
                        self.itemError.emit(u, 'Decoded image is invalid')
                    except Exception:
                        pass
                else:
                    panel_id = f"scrape_{self._existing_count_cb()+1}"
                    self.itemReady.emit(panel_id, pm)
                    self._added += 1
            except Exception:
                self._errors += 1
                try:
                    import traceback
                    traceback.print_exc()
                except Exception:
                    pass
                try:
                    self.itemError.emit(u, 'Data URI decode or save failed')
                except Exception:
                    pass
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
        # On certain SSL/handshake-related failures Qt's network stack can fail
        # while a Python-based fetch (requests/urllib) would succeed. Try a
        # threaded fallback before declaring the item failed.
        try:
            url = reply.url().toString() if hasattr(reply, 'url') else ''
        except Exception:
            url = ''
        try:
            errstr = reply.errorString() if hasattr(reply, 'errorString') else str(err)
        except Exception:
            errstr = str(err)

        ssl_indicators = ['ssl', 'handshake', 'unsupported function', 'certificate', 'secure']
        if url and any(k in errstr.lower() for k in ssl_indicators):
            # attempt fallback download using Python libraries in a QThread
            try:
                # delete the Qt reply early; we'll continue via fallback
                try:
                    reply.deleteLater()
                except Exception:
                    pass
                self._currentReply = None
                self._start_fallback_download(url)
                return
            except Exception:
                # if fallback setup fails, fall through to emit error below
                pass

        # Non-SSL or fallback not attempted/failed — emit per-item error and continue
        self._errors += 1
        try:
            self.itemError.emit(url or str(self._index), errstr)
        except Exception:
            pass
        idx = self._index + 1
        self.progress.emit(idx)
        try:
            reply.deleteLater()
        except Exception:
            pass
        self._currentReply = None
        self._index += 1
        QTimer.singleShot(0, self._start_next)

    def _start_fallback_download(self, url: str):
        """Start a fallback downloader in a QThread that tries requests then urllib."""
        class _FallbackWorker(QObject):
            ready = pyqtSignal(bytes)
            failed = pyqtSignal(str)
            finished = pyqtSignal()

            def __init__(self, url: str):
                super().__init__()
                self.url = url

            @pyqtSlot()
            def run(self):
                try:
                    try:
                        import requests
                        hdrs = {'User-Agent': 'Mozilla/5.0'}
                        r = requests.get(self.url, headers=hdrs, timeout=16, verify=False)
                        data = r.content
                    except Exception:
                        try:
                            import urllib.request, ssl
                            ctx = ssl.create_default_context()
                            ctx.check_hostname = False
                            ctx.verify_mode = ssl.CERT_NONE
                            with urllib.request.urlopen(self.url, context=ctx, timeout=16) as resp:
                                data = resp.read()
                        except Exception:
                            data = b''
                    if not data:
                        self.failed.emit('Fallback: empty response')
                    else:
                        self.ready.emit(data)
                except Exception as e:
                    try:
                        import traceback
                        traceback.print_exc()
                    except Exception:
                        pass
                    self.failed.emit(str(e))
                finally:
                    self.finished.emit()

        # Create worker/thread
        try:
            worker = _FallbackWorker(url)
            thread = QThread(self)
            worker.moveToThread(thread)
            # When data ready, handle it and continue to next item
            worker.ready.connect(lambda data: self._on_fallback_ready(url, data))
            worker.failed.connect(lambda err: self._on_fallback_failed(url, err))
            worker.finished.connect(thread.quit)
            thread.started.connect(worker.run)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            # keep temporary references to avoid GC until finished
            if not hasattr(self, '_fallback_threads'):
                self._fallback_threads = []
            self._fallback_threads.append((thread, worker))
            thread.start()
        except Exception:
            # if fallback couldn't be started, mark as failed immediately
            self._errors += 1
            try:
                self.itemError.emit(url or str(self._index), 'Fallback start failed')
            except Exception:
                pass
            idx = self._index + 1
            self.progress.emit(idx)
            self._index += 1
            QTimer.singleShot(0, self._start_next)

    def _on_fallback_ready(self, url: str, data: bytes):
        # Write file and emit itemReady if valid image
        try:
            import os
            url_path = url.split('?')[0]
            tail = url_path.split('/')[-1] or f"img_{self._existing_count_cb()+1}.bin"
            if '.' not in tail:
                tail += '.png'
            path = os.path.join(self._out_dir, tail)
            with open(path, 'wb') as f:
                f.write(data)
            pm = QPixmap()
            ok = pm.loadFromData(data)
            if not ok or pm.isNull():
                # try loading from saved file as fallback
                pm = QPixmap(path)
            if pm.isNull():
                self._errors += 1
                try:
                    self.itemError.emit(url, 'Fallback download produced invalid image')
                except Exception:
                    pass
            else:
                panel_id = f"scrape_{self._existing_count_cb()+1}"
                self.itemReady.emit(panel_id, pm)
                self._added += 1
        except Exception:
            self._errors += 1
            try:
                self.itemError.emit(url, 'Fallback save or decode failed')
            except Exception:
                pass
        # finalize this item and move to next
        idx = self._index + 1
        self.progress.emit(idx)
        self._index += 1
        QTimer.singleShot(0, self._start_next)

   
    def _on_fallback_failed(self, url: str, errmsg: str):

        try:
            self._errors += 1
            self.itemError.emit(url, f'Fallback failed: {errmsg}')
        except Exception:
            pass
        idx = self._index + 1
        self.progress.emit(idx)
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
                try:
                    self.itemError.emit(reply.url().toString(), 'Downloaded data is not a valid image')
                except Exception:
                    pass
            else:
                panel_id = f"scrape_{self._existing_count_cb()+1}"
                self.itemReady.emit(panel_id, pm)
                self._added += 1
        except Exception:
            self._errors += 1
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
            try:
                self.itemError.emit(reply.url().toString() if hasattr(reply, 'url') else str(self._index), 'Download or save failed')
            except Exception:
                pass
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
        self._currentUrl: str | None = None
        self._fallbackThread: QThread | None = None
        self._fallbackWorker: QObject | None = None

    def fetch(self, url: str):
        # Abort any in-flight request
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            self._currentReply.deleteLater()
            self._currentReply = None
        self._currentUrl = url
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
        # If SSL handshake related, attempt a Python-based fallback download in a thread
        url_str = ''
        try:
            url_str = reply.url().toString()
        except Exception:
            url_str = self._currentUrl or ''

        # common indicator text for SSL handshake issues
        ssl_indicators = ['ssl', 'handshake', 'unsupported function', 'certificate', 'secure']
        if any(k in errstr.lower() for k in ssl_indicators) and url_str:
            try:
                # Start fallback downloader in a QThread to avoid blocking UI
                class _FallbackWorker(QObject):
                    finished = pyqtSignal()
                    ready = pyqtSignal(QPixmap)
                    failed = pyqtSignal(str)

                    def __init__(self, url: str):
                        super().__init__()
                        self.url = url

                    @pyqtSlot()
                    def run(self):
                        try:
                            # Prefer requests if available (disable verify to bypass cert issues)
                            try:
                                import requests
                                hdrs = {'User-Agent': 'Mozilla/5.0'}
                                r = requests.get(self.url, headers=hdrs, timeout=12, verify=False)
                                data = r.content
                            except Exception:
                                # Fallback to urllib with unverified SSL context
                                try:
                                    import urllib.request, ssl
                                    ctx = ssl.create_default_context()
                                    ctx.check_hostname = False
                                    ctx.verify_mode = ssl.CERT_NONE
                                    with urllib.request.urlopen(self.url, context=ctx, timeout=12) as resp:
                                        data = resp.read()
                                except Exception as e:
                                    raise
                            pm = QPixmap()
                            ok = pm.loadFromData(data)
                            if not ok or pm.isNull():
                                self.failed.emit('Fallback decode failed')
                            else:
                                self.ready.emit(pm)
                        except Exception as e:
                            self.failed.emit(str(e))
                        finally:
                            self.finished.emit()

                # Clean up any existing fallback
                try:
                    if self._fallbackThread is not None:
                        self._fallbackThread.quit()
                        self._fallbackThread.wait(100)
                except Exception:
                    pass

                worker = _FallbackWorker(url_str)
                thread = QThread(self)
                worker.moveToThread(thread)
                worker.ready.connect(lambda pm: (self.ready.emit(pm)))
                worker.failed.connect(lambda e: self.failed.emit(f"Fallback failed: {e}"))
                worker.finished.connect(thread.quit)
                thread.started.connect(worker.run)
                thread.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                self._fallbackThread = thread
                self._fallbackWorker = worker
                thread.start()
                # return early; don't emit original failure yet
                try:
                    reply.deleteLater()
                except Exception:
                    pass
                self._currentReply = None
                return
            except Exception:
                pass

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



# Unified OcrWorker: handles both single-panel (multi-crop) and batch (multi-panel) OCR
class OcrWorker(QObject):
    """Worker that performs OCR on one or more panels in a background QThread.

    Emits:
        - finished(panel_id, blocks): for each panel processed
        - error(panel_id, errmsg): for per-panel errors
        - progress(done, total): after each panel
        - finished(done): when all panels are done
    """
    itemFinished = pyqtSignal(str, list)
    itemError = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)

    def __init__(self, items, lang: str = 'jpn', ocr_engine=None, conf_thresh: int = 0, preprocess: bool = True):
        """
        items: list of (panel_id, crops) or (panel_id, QImage), or a single tuple
        ocr_engine: preloaded OCR engine (optional, for single-panel use)
        """
        super().__init__()
        # Normalize input to always be a list of (panel_id, crops) tuples
        if isinstance(items, tuple) and len(items) == 2:
            self._items = [items]
        elif isinstance(items, list):
            # If it's a list of crops/images, treat as single panel
            if items and not (isinstance(items[0], tuple) and len(items[0]) == 2):
                self._items = [('panel', items)]  # Use a dummy panel_id if not provided
            else:
                self._items = items
        else:
            raise ValueError("OcrWorker items must be a tuple or list")
        self.ocr_engine = ocr_engine
        self.lang = lang
        self.conf_thresh = conf_thresh
        self.preprocess = preprocess
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @pyqtSlot()
    def run(self):
        import traceback
        done = 0
        total = len(self._items)
        # Use provided ocr_engine or create one (for batch)
        ocr = self.ocr_engine
        if ocr is None:
            from MangaWebTranslator.services.ocr.ocr_adapter import create_ocr
            ocr = create_ocr()
        for item in self._items:
            # Defensive unpacking
            if isinstance(item, tuple) and len(item) == 2:
                panel_id, crops = item
            else:
                panel_id, crops = 'panel', item
            if self._cancel:
                break
            try:
                # Accept either a single image or a list of crops
                crop_list = crops if isinstance(crops, list) else [crops]
                print(f"[OCR] OCRing {panel_id} with {len(crop_list)} crops (lang={self.lang} preprocess={self.preprocess} conf={self.conf_thresh})")
                results = []
                for idx, crop in enumerate(crop_list):
                    print(f"[OCR] Crop {idx+1} type: {type(crop).__name__}")
                    if not hasattr(ocr, 'extract_blocks'):
                        print("[OCR] ERROR: Provided ocr_engine does not have extract_blocks method.")
                        results.append([])
                        continue
                    if not (hasattr(crop, 'size') or hasattr(crop, 'width')):
                        print(f"[OCR] WARNING: Crop {idx+1} is not an image. Value: {crop}")
                    try:
                        blocks = ocr.extract_blocks(crop, lang=self.lang, preprocess=self.preprocess, conf_thresh=self.conf_thresh)
                        results.append(blocks)
                    except Exception as e:
                        print(f"[OCR] Error in crop {idx+1}: {e}")
                        try:
                            traceback.print_exc()
                        except Exception:
                            pass
                        results.append([])
                # Flatten results for display logic
                flat_results = [block for blocks in results for block in blocks]
                self.itemFinished.emit(panel_id, flat_results)
            except Exception as e:
                try:
                    traceback.print_exc()
                except Exception:
                    pass
                self.itemError.emit(panel_id, str(e))
            done += 1
            self.progress.emit(done, total)
        self.finished.emit(done)

def create_app_window() -> MainWindow:
    """Factory to create the fully constructed MainWindow."""
    return MainWindow()
