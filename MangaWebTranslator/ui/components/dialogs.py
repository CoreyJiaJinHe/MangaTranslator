from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QDialogButtonBox, QApplication
)

from MangaWebTranslator.ui.components.async_workers import AsyncImagePreviewer


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
        # Root horizontal layout splits preview (left) and list+controls (right)
        root = QHBoxLayout(self)

        # Preview area (scrollable for large images)
        preview_container = QVBoxLayout()
        self._dimensionLabel = QLabel("No preview")
        self._dimensionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_container.addWidget(self._dimensionLabel)
        self._previewLabel = QLabel("Select an item to preview", self)
        self._previewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._previewLabel.setFixedSize(320, 320)
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
        self._list.itemClicked.connect(self._onItemClicked)
        # Async previewer
        self._previewer = AsyncImagePreviewer(self)
        self._previewer.ready.connect(self._setPreviewPixmap)
        self._previewer.failed.connect(self._setPreviewError)

    def closeEvent(self, event):
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
                txt = item.text()
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

    def _previewSelected(self, current: QListWidgetItem, previous: QListWidgetItem | None):
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
        self._previewLabel.setText("Loading preview...")
        self._dimensionLabel.setText("Loading...")
        self._previewer.fetch(url)

    def _setPreviewPixmap(self, pm: QPixmap):
        if pm.isNull():
            self._previewLabel.setText("Invalid image")
            self._dimensionLabel.setText("Invalid")
            return
        area_w, area_h = self._previewLabel.width(), self._previewLabel.height()
        img_w, img_h = pm.width(), pm.height()
        scaled = pm.scaled(area_w, area_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._previewLabel.setPixmap(scaled)
        self._dimensionLabel.setText(f"{img_w} x {img_h} px (scaled)")

    def _setPreviewError(self, err: str):
        try:
            self._previewLabel.setText(err)
            self._dimensionLabel.setText(err)
        except Exception:
            pass

    def _onItemClicked(self, item: QListWidgetItem):
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
