from __future__ import annotations
from typing import List, Optional, Dict
import os
import json
import re

from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QTextEdit, QHBoxLayout, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QListWidgetItem, QLineEdit, QMenu, QMainWindow,
    QMessageBox, QScrollArea, QSizePolicy
)


class PanelRightOutput(QWidget):
    # Store edited block texts per panel
    _panel_block_edits = {}
    # Cached kanji dictionary loaded once
    _kanji_dict_cache: Optional[Dict[str, str]] = None
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

        # Place Dictionary Lookup beneath the blocks zone, aligned to the right
        lookupRow = QHBoxLayout()
        lookupRow.addStretch(1)
        self.dictLookupBtn = QPushButton("Dictionary Lookup")
        lookupRow.addWidget(self.dictLookupBtn)
        outer.addLayout(lookupRow)

        # Dictionary results container (rows of kanji squares per OCR block)
        outer.addWidget(QLabel("Dictionary Lookup:"))
        self.dictContainer = QWidget(self)
        self.dictLayout = QVBoxLayout(self.dictContainer)
        self.dictLayout.setContentsMargins(0, 0, 0, 0)
        self.dictLayout.setSpacing(8)
        # Wrap dictContainer in a QScrollArea for vertical scrolling
        self.dictScrollArea = QScrollArea(self)
        self.dictScrollArea.setWidgetResizable(True)
        self.dictScrollArea.setWidget(self.dictContainer)
        self.dictScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.dictScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dictScrollArea.setMinimumHeight(300)
        self.dictScrollArea.setMaximumHeight(400)
        outer.addWidget(self.dictScrollArea, 1)

        # Under dictionary: right-aligned Translate button (stub)
        dictBtnRow = QHBoxLayout()
        dictBtnRow.addStretch(1)
        self.translateBtn = QPushButton("Translate")
        dictBtnRow.addWidget(self.translateBtn)
        outer.addLayout(dictBtnRow)

        # Translation output
        outer.addWidget(QLabel("Translation:"))
        # Translation output as cards
        self.translationList = QListWidget(self)
        self.translationList.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        outer.addWidget(self.translationList, 1)

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
        self.dictLookupBtn.clicked.connect(self._on_dictionary_lookup)
        self.translateBtn.clicked.connect(self._emit_translate)

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
        # Clear dictionary container
        if hasattr(self, 'dictLayout'):
            self._clear_dict_container()
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

    # ----------------------- Kanji dictionary helpers -----------------------
    def _load_kanji_dict_once(self) -> Dict[str, str]:
        """Load kanji dictionary JSON once and cache it."""
        if PanelRightOutput._kanji_dict_cache is not None:
            return PanelRightOutput._kanji_dict_cache
        # Resolve path to data/kanji_merged.json relative to this file
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        data_path = os.path.join(root, 'data', 'kanji_merged.json')
        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                dct = json.load(f)
                # Normalize dictionary structure once if needed
                if isinstance(dct, list):
                    try:
                        norm = {}
                        for entry in dct:
                            if isinstance(entry, dict):
                                k = entry.get('kanji') or entry.get('char') or entry.get('k')
                                if isinstance(k, str) and k:
                                    norm[k] = entry
                        dct = norm
                    except Exception:
                        dct = {}
                PanelRightOutput._kanji_dict_cache = dct
        except Exception:
            PanelRightOutput._kanji_dict_cache = {}
        
        print(f"Kanji dictionary loaded with {len(PanelRightOutput._kanji_dict_cache)} entries.")
        return PanelRightOutput._kanji_dict_cache

    @staticmethod
    def extract_unique_kanji(text: str) -> List[str]:
        """Extract unique Kanji characters from text, filtering punctuation and duplicates."""
        if not text:
            return []
        # Only keep CJK Unified Ideographs (basic range)
        chars = [ch for ch in text if re.match(r"[\u4E00-\u9FFF]", ch)]
        seen = set()
        unique: List[str] = []
        for ch in chars:
            if ch not in seen:
                seen.add(ch)
                unique.append(ch)
        return unique

    def lookup_kanji_meanings(self, kanji_list: List[str]) -> Dict[str, str]:
        """Lookup meanings in cached dictionary; return 'no meaning' when absent."""
        dct = self._load_kanji_dict_once()
        out: Dict[str, str] = {}
        for k in kanji_list:
            meaning = dct.get(k)
            text = None
            if isinstance(meaning, dict):
                # Try common keys, supporting list or string values
                for key in ('meaning', 'meanings', 'english', 'gloss', 'glosses', 'definition'):
                    val = meaning.get(key)
                    if val is None:
                        continue
                    if isinstance(val, list):
                        val = ', '.join([str(x).strip() for x in val if str(x).strip()])
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
            elif isinstance(meaning, list):
                text = ', '.join([str(x).strip() for x in meaning if str(x).strip()]) or None
            elif isinstance(meaning, str):
                text = meaning.strip() or None
            out[k] = text if text else 'no meaning'
        return out

    def extract_and_lookup_kanji(self, text: str) -> Dict[str, str]:
        """Combined extraction and lookup for convenience."""
        return self.lookup_kanji_meanings(self.extract_unique_kanji(text))

    def _clear_dict_container(self) -> None:
        layout = self.dictLayout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    while child.count():
                        sub = child.takeAt(0)
                        sw = sub.widget()
                        if sw is not None:
                            sw.deleteLater()

    def _on_dictionary_lookup(self):
        """Render kanji squares per OCR block with meanings and Jisho stub button."""
        if not self.current_panel:
            try:
                QMessageBox.information(self, 'Dictionary Lookup', 'No panel selected.')
            except Exception:
                pass
            return
        self._clear_dict_container()
        edited = self._panel_block_edits.get(self.current_panel, [])
        count = self.blocksList.count()
        for i in range(count):
            text = None
            if edited and i < len(edited) and isinstance(edited[i], str) and edited[i].strip():
                text = edited[i].strip()
            else:
                item = self.blocksList.item(i)
                self._clear_dict_container()
                edited = self._panel_block_edits.get(self.current_panel, [])
                count = self.blocksList.count()
                for i in range(count):
                    text = None
                    if edited and i < len(edited) and isinstance(edited[i], str) and edited[i].strip():
                        text = edited[i].strip()
                    else:
                        item = self.blocksList.item(i)
                        widget = self.blocksList.itemWidget(item)
                        if widget:
                            labels = widget.findChildren(QLabel)
                            if labels:
                                text = labels[-1].text().strip()
                    if not text:
                        continue  # skip empty blocks
                    kanji_list = self.extract_unique_kanji(text)
                    if not kanji_list:
                        continue  # no kanji found
                    meanings = self.lookup_kanji_meanings(kanji_list)

                    # Build a horizontally scrollable row for potentially many kanji
                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(4, 4, 4, 4)
                    row_layout.setSpacing(6)
                    row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)  # left-align kanji squares
                    for k in kanji_list:
                        cell = QWidget(row_widget)
                        cell_layout = QVBoxLayout(cell)
                        cell_layout.setContentsMargins(6, 6, 6, 2)
                        cell_layout.setSpacing(4)
                        lbl = QLabel(k, cell)
                        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        lbl.setFixedSize(48, 48)
                        lbl.setStyleSheet('border:1px solid #999; border-radius:4px; padding:4px; font-size:22px;')
                        lbl.setToolTip(meanings.get(k, 'no meaning'))
                        try:
                            lbl.setToolTipDuration(5000)
                        except Exception:
                            pass
                        cell_layout.addWidget(lbl)
                        btn = QPushButton('Jisho', cell)
                        btn.setFixedWidth(40)
                        btn.clicked.connect(lambda _=False, ch=k: self._on_jisho_lookup(ch))
                        cell_layout.addWidget(btn)
                        row_layout.addWidget(cell)
                    # Do not set a fixed height; let the row expand to fit its contents
                    # Place row_widget in a QScrollArea for horizontal scrolling if needed
                    scroll = QScrollArea(self.dictContainer)
                    scroll.setWidgetResizable(True)
                    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    # Set min/max height to fit kanji square and button (e.g., 100px)
                    scroll.setMinimumHeight(100)
                    scroll.setMaximumHeight(140)
                    scroll.setWidget(row_widget)
                    self.dictLayout.addWidget(scroll)


    def _on_jisho_lookup(self, kanji: str):
        """Stub for future API-based lookup via jisho.py."""
        try:
            QMessageBox.information(self, 'Jisho', f'Lookup stub for: {kanji}')
        except Exception:
            pass
