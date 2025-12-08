from __future__ import annotations
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QTextEdit, QHBoxLayout, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QListWidgetItem, QLineEdit, QMenu, QMainWindow
)


class PanelRightOutput(QWidget):
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

    def renumberBlockCardLabels(self):
        # After deletions, update the numeric labels on block cards
        for i in range(self.blocksList.count()):
            item = self.blocksList.item(i)
            widget = self.blocksList.itemWidget(item)
            if not widget:
                continue
            # first child in layout is the number label
            lbl = widget.findChild(QLabel)
            if lbl:
                lbl.setText(str(i + 1))

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
