from __future__ import annotations
from typing import List, Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QHBoxLayout, QMenu

from MangaWebTranslator.ui.custom_widget.rect_preview import RectPreview


class PanelImageThumbnailCard(QWidget):
    """Visual card representing a manga panel image.

    Displays the image (scaled) and stores an identifier used for
    downstream operations (OCR, translation, etc.).
    """
    from PyQt6.QtCore import pyqtSignal
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
    from PyQt6.QtCore import pyqtSignal
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
