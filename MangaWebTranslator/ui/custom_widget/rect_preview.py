"""
Interactive preview widget for rectangle overlay and selection.

Features:
- Displays scaled original pixmap centered in the widget
- Click to select a rectangle; Ctrl+click toggles selection
- Shift+drag marquee to multi-select rectangles
- Left-drag on empty area to add a new rectangle
- Delete/Backspace to remove selected rectangles
- Right-click context menu for remove/clear actions

Coordinates:
- Rectangles are stored in image-space `{left, top, width, height}`
- Rendering maps to widget-space using current scale and offsets
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QPixmap,
    QPainter,
    QPen,
    QColor,
    QBrush,
    QMouseEvent,
    QContextMenuEvent,
    QKeyEvent,
)
from PyQt6.QtWidgets import QWidget


class RectPreview(QWidget):
    rectsChanged = pyqtSignal(list)  # emits list[dict] of current rectangles

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._rects: list[dict] = []
        self._selected: set[int] = set()
        # Interaction state
        self._marquee_active = False
        self._marquee_start = None
        self._marquee_end = None
        self._draw_active = False
        self._draw_start = None
        self._draw_end = None
        # Last draw geometry for coordinate mapping
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._show_boxes: bool = True
        self._interaction_enabled: bool = True

    # -------- Public API --------
    def setPixmap(self, pm: QPixmap) -> None:
        """Set the base pixmap to display (original image)."""
        self._pixmap = pm
        self.update()

    def setRects(self, rects: list[dict]) -> None:
        """Replace existing rectangles with the provided list (image-space)."""
        self._rects = []
        for r in (rects or []):
            try:
                self._rects.append({
                    'left': int(r.get('left', 0)),
                    'top': int(r.get('top', 0)),
                    'width': int(r.get('width', 0)),
                    'height': int(r.get('height', 0)),
                })
            except Exception:
                continue
        self._selected.clear()
        self.update()
        self.rectsChanged.emit(self._rects.copy())

    def getRects(self) -> list[dict]:
        """Return a copy of current rectangles (image-space)."""
        return self._rects.copy()

    def setShowBoxes(self, show: bool) -> None:
        """Control whether rectangles are drawn (does not clear stored rects)."""
        self._show_boxes = bool(show)
        # Link interaction to overlay visibility
        self._interaction_enabled = self._show_boxes
        self.update()

    def removeSelected(self) -> None:
        """Remove all currently selected rectangles."""
        if not self._selected:
            return
        keep: list[dict] = []
        for i, r in enumerate(self._rects):
            if i not in self._selected:
                keep.append(r)
        self._rects = keep
        self._selected.clear()
        self.update()
        self.rectsChanged.emit(self._rects.copy())

    def clearRects(self) -> None:
        """Clear all rectangles."""
        self._rects = []
        self._selected.clear()
        self.update()
        self.rectsChanged.emit(self._rects.copy())

    # -------- Coordinate helpers --------
    def _compute_draw_geom(self) -> None:
        """Compute scale and offsets for drawing scaled pixmap centered in widget."""
        if not self._pixmap or self._pixmap.isNull():
            self._scale = 1.0
            self._offset_x = 0
            self._offset_y = 0
            return
        ww, wh = self.width(), self.height()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw == 0 or ph == 0:
            self._scale = 1.0
            self._offset_x = 0
            self._offset_y = 0
            return
        scale = min(ww / pw, wh / ph)
        sw = int(pw * scale)
        sh = int(ph * scale)
        self._scale = scale
        self._offset_x = (ww - sw) // 2
        self._offset_y = (wh - sh) // 2

    def _widget_to_image(self, x: int, y: int) -> tuple[int, int]:
        """Map widget coords to image-space coords using last draw geometry."""
        ix = int((x - self._offset_x) / self._scale)
        iy = int((y - self._offset_y) / self._scale)
        return ix, iy

    def _image_rect_to_widget(self, r: dict) -> tuple[int, int, int, int]:
        """Convert image-space rectangle to widget-space for painting."""
        l = int(r.get('left', 0))
        t = int(r.get('top', 0))
        w = int(r.get('width', 0))
        h = int(r.get('height', 0))
        x = int(l * self._scale) + self._offset_x
        y = int(t * self._scale) + self._offset_y
        rw = int(w * self._scale)
        rh = int(h * self._scale)
        return x, y, rw, rh

    # -------- Painting --------
    def paintEvent(self, event):  # noqa: D401
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))  # dark background

        self._compute_draw_geom()
        if self._pixmap and not self._pixmap.isNull():
            # Draw scaled pixmap centered
            pw, ph = self._pixmap.width(), self._pixmap.height()
            sw = int(pw * self._scale)
            sh = int(ph * self._scale)
            scaled = self._pixmap.scaled(sw, sh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(self._offset_x, self._offset_y, scaled)

        # Draw rectangles (if enabled)
        if self._show_boxes:
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(2)
            painter.setPen(pen)
            brush = QBrush(QColor(255, 0, 0, 40))
            painter.setBrush(brush)

            for i, r in enumerate(self._rects):
                x, y, rw, rh = self._image_rect_to_widget(r)
                painter.drawRect(x, y, rw, rh)
                # Selected highlight
                if i in self._selected:
                    sel_pen = QPen(QColor(255, 255, 0))
                    sel_pen.setWidth(3)
                    painter.setPen(sel_pen)
                    painter.setBrush(QBrush(QColor(255, 255, 0, 30)))
                    painter.drawRect(x, y, rw, rh)
                    painter.setPen(pen)
                    painter.setBrush(brush)

        # Marquee selection box
        if self._marquee_active and self._marquee_start and self._marquee_end:
            mx1, my1 = self._marquee_start
            mx2, my2 = self._marquee_end
            x = min(mx1, mx2)
            y = min(my1, my2)
            w = abs(mx2 - mx1)
            h = abs(my2 - my1)
            m_pen = QPen(QColor(0, 180, 255))
            m_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(m_pen)
            painter.setBrush(QBrush(QColor(0, 180, 255, 40)))
            painter.drawRect(x, y, w, h)

        # Draw-in-progress new rectangle
        if self._draw_active and self._draw_start and self._draw_end:
            sx, sy = self._draw_start
            ex, ey = self._draw_end
            x = min(sx, ex)
            y = min(sy, ey)
            w = abs(ex - sx)
            h = abs(ey - sy)
            d_pen = QPen(QColor(0, 255, 0))
            d_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(d_pen)
            painter.setBrush(QBrush(QColor(0, 255, 0, 40)))
            painter.drawRect(x, y, w, h)

        painter.end()

    # -------- Interaction --------
    def _hit_test(self, ix: int, iy: int) -> Optional[int]:
        """Return index of rect containing (ix, iy) in image-space, else None."""
        for i in range(len(self._rects) - 1, -1, -1):
            r = self._rects[i]
            l = r['left']; t = r['top']; w = r['width']; h = r['height']
            if ix >= l and iy >= t and ix <= l + w and iy <= t + h:
                return i
        return None

    def mousePressEvent(self, event: QMouseEvent):  # noqa: D401
        if not self._interaction_enabled:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            ix, iy = self._widget_to_image(event.position().x(), event.position().y())
            hit = self._hit_test(ix, iy)
            # Shift-click on a rect -> additive toggle selection; Shift-drag -> marquee multi-select
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if hit is not None:
                    # Add/remove without clearing existing selection
                    if hit in self._selected:
                        self._selected.remove(hit)
                    else:
                        self._selected.add(hit)
                    self.update()
                    return
                # No rect hit: begin marquee selection (additive mode)
                self._marquee_active = True
                self._marquee_start = (int(event.position().x()), int(event.position().y()))
                self._marquee_end = self._marquee_start
                # Track additive marquee so it doesn't clear existing selection
                self._marquee_additive = True
                self.update()
                return
            # Click inside a rect -> select it
            if hit is not None:
                # Ctrl-click toggles without clearing; plain click selects exclusively
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if hit in self._selected:
                        self._selected.remove(hit)
                    else:
                        self._selected.add(hit)
                else:
                    self._selected.clear()
                    self._selected.add(hit)
                self.update()
                return
            # Otherwise start drawing a new rectangle
            self._draw_active = True
            self._draw_start = (int(event.position().x()), int(event.position().y()))
            self._draw_end = self._draw_start
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right-click opens context menu for removal/clear
            self._show_context_menu(event)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: D401
        if not self._interaction_enabled:
            return
        if self._marquee_active and self._marquee_start:
            self._marquee_end = (int(event.position().x()), int(event.position().y()))
            self.update()
        elif self._draw_active and self._draw_start:
            self._draw_end = (int(event.position().x()), int(event.position().y()))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: D401
        if not self._interaction_enabled:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # Finish marquee -> select all rects intersecting marquee area
            if self._marquee_active and self._marquee_start and self._marquee_end:
                mx1, my1 = self._marquee_start
                mx2, my2 = self._marquee_end
                x = min(mx1, mx2); y = min(my1, my2)
                w = abs(mx2 - mx1); h = abs(my2 - my1)
                # Convert marquee to image-space rect
                i_l, i_t = self._widget_to_image(x, y)
                i_r = i_l + int(w / self._scale)
                i_b = i_t + int(h / self._scale)
                # Select rects with any overlap
                if not getattr(self, '_marquee_additive', False):
                    self._selected.clear()
                for i, r in enumerate(self._rects):
                    rl = r['left']; rt = r['top']; rr = rl + r['width']; rb = rt + r['height']
                    if not (rr < i_l or rb < i_t or rl > i_r or rt > i_b):
                        self._selected.add(i)
                # Reset marquee
                self._marquee_active = False
                self._marquee_start = None
                self._marquee_end = None
                self._marquee_additive = False
                self.update()
                return

            # Finish drawing -> add rect in image-space
            if self._draw_active and self._draw_start and self._draw_end:
                sx, sy = self._draw_start
                ex, ey = self._draw_end
                x = min(sx, ex); y = min(sy, ey)
                w = abs(ex - sx); h = abs(ey - sy)
                i_l, i_t = self._widget_to_image(x, y)
                i_w = max(0, int(w / self._scale))
                i_h = max(0, int(h / self._scale))
                # Minimum size to avoid accidental clicks
                if i_w >= 10 and i_h >= 10 and self._pixmap and not self._pixmap.isNull():
                    # Clamp to image bounds
                    pw, ph = self._pixmap.width(), self._pixmap.height()
                    i_l = max(0, min(i_l, pw - 1))
                    i_t = max(0, min(i_t, ph - 1))
                    i_w = max(1, min(i_w, pw - i_l))
                    i_h = max(1, min(i_h, ph - i_t))
                    self._rects.append({'left': i_l, 'top': i_t, 'width': i_w, 'height': i_h})
                    self.rectsChanged.emit(self._rects.copy())
                # Reset draw state
                self._draw_active = False
                self._draw_start = None
                self._draw_end = None
                self.update()

    def keyPressEvent(self, event: QKeyEvent):  # noqa: D401
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.removeSelected()

    def _show_context_menu(self, event: QContextMenuEvent | QMouseEvent) -> None:
        try:
            from PyQt6.QtWidgets import QMenu
        except Exception:
            return
        menu = QMenu(self)
        act_remove = menu.addAction("Remove Selected")
        act_clear = menu.addAction("Clear All")
        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is None:
            return
        if chosen == act_remove:
            self.removeSelected()
        elif chosen == act_clear:
            self.clearRects()
