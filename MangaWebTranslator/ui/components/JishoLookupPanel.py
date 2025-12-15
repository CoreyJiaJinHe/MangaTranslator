from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
    QHBoxLayout,
    QFrame,
)
from PyQt6.QtCore import Qt

class JishoLookupPanel(QDialog):
    """
    Pop-up dialog to display Jisho.org search results in a non-blocking way.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jisho Lookup Results")
        self.setMinimumSize(500, 400)
        layout = QVBoxLayout(self)
        self.setLayout(layout)
        self.title = QLabel("Jisho Lookup Results")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self.title)
        # Scroll area that will contain result cards
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        # prefer wrapping over horizontal scroll
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(6, 6, 6, 6)
        self.container_layout.setSpacing(8)
        self.container.setLayout(self.container_layout)

        self.scroll.setWidget(self.container)
        # Add a close button
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


    def show_results(self, text: str):
        # Fallback: clear cards and show a single label
        for i in reversed(range(self.container_layout.count())):
            w = self.container_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        lbl = QLabel(text, self.container)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.container_layout.addWidget(lbl)

    def display_result(self, result):
        """
        Format and display the Jisho API result in the panel.
        """
        if not isinstance(result, dict):
            self.show_results("Error: Unexpected result format.")
            return
        if result.get('error'):
            self.show_results(f"Error: {result['error']}")
            return
        if result.get('meta', {}).get('status') != 200:
            self.show_results(f"API Error: Status {result.get('meta', {}).get('status')}")
            return
        data = result.get('data', [])
        if not data:
            self.show_results("No results found.")
            return

        # clear previous cards
        for i in reversed(range(self.container_layout.count())):
            w = self.container_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        main = data[0]
        examples = data[1:]

        # Helper functions to reduce duplication and improve performance
        def _rich_label(html: str, stylesheet: str = None) -> QLabel:
            lbl = QLabel()
            lbl.setText(html)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            if stylesheet:
                lbl.setStyleSheet(stylesheet)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            return lbl

        def _plain_label(text: str, stylesheet: str = None) -> QLabel:
            lbl = QLabel(text)
            if stylesheet:
                lbl.setStyleSheet(stylesheet)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            return lbl

        def _build_list_html(items, padding_left: int = 6):
            html = f'<ul style="margin:6px 0 0 0; padding-left:{padding_left}px; list-style-position:outside;">'
            for it in items:
                html += f'<li>{it}</li>'
            html += '</ul>'
            return html

        def _attach_toggle(button: QPushButton, label: QLabel, collapsed_html: str, full_html: str):
            def _handler(*_args):
                if button.text() == 'Show more':
                    label.setText(full_html)
                    button.setText('Show less')
                else:
                    label.setText(collapsed_html)
                    button.setText('Show more')

            button.clicked.connect(_handler)

        # Create main card
        main_card = QFrame(self.container)
        main_card.setFrameShape(QFrame.Shape.StyledPanel)
        main_card.setStyleSheet("QFrame{background:#ffffff;border:1px solid #ccc;border-radius:6px;padding:8px}")
        mc_layout = QVBoxLayout(main_card)

        # Title row: slug (large) and reading separated by a dash
        slug = main.get('slug', '')
        try:
            reading = main.get('japanese', [{}])[0].get('reading', '')
        except Exception:
            reading = ''
        
        # Label for Main
        if reading:
            sep = QLabel('Basic Meaning:')
            sep.setStyleSheet('font-size:12pt;font-weight:600;margin-top:8px;')
            sep.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.container_layout.addWidget(sep)


        # Single title label combining slug and reading to avoid extra widgets
        if reading:
            title_html = (
                f"<span style='font-size:16pt;font-weight:700'>{slug}</span>\u00A0"
                f"<span style='font-size:16pt;font-weight:400;color:#333'>&#8212;&nbsp;{reading}</span>"
            )
        else:
            title_html = f"<span style='font-size:16pt;font-weight:700'>{slug}</span>"
        main_title = QLabel()
        main_title.setText(title_html)
        main_title.setTextFormat(Qt.TextFormat.RichText)
        main_title.setWordWrap(True)
        # main title uses rich text and word-wrap; no unsupported CSS properties
        main_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        mc_layout.addWidget(main_title)

        # Meanings: render as a single bulleted block inside the main card.
        senses = main.get('senses', []) or []
        sense_texts = [', '.join(s.get('english_definitions', [])) for s in senses if s.get('english_definitions')]

        if not sense_texts:
            mc_layout.addWidget(_plain_label('No meanings available', "font-size:10pt;color:#222;"))
        else:
            if len(sense_texts) <= 5:
                mc_layout.addWidget(_rich_label(_build_list_html(sense_texts), "font-size:10pt;color:#222;"))
            else:
                collapsed_html = _build_list_html(sense_texts[:5])
                full_html = _build_list_html(sense_texts)
                lbl_mean = _rich_label(collapsed_html, "font-size:10pt;color:#222;")
                mc_layout.addWidget(lbl_mean)

                show_more_btn = QPushButton('Show more')
                show_more_btn.setFlat(True)
                show_more_btn.setStyleSheet('color:#0078d4;text-decoration:underline;background:transparent;border:0;padding:4px')
                _attach_toggle(show_more_btn, lbl_mean, collapsed_html, full_html)
                mc_layout.addWidget(show_more_btn)

        self.container_layout.addWidget(main_card)

        # Separator label for examples
        if examples:
            sep = QLabel('Examples:')
            sep.setStyleSheet('font-size:11pt;font-weight:600;margin-top:8px;')
            sep.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.container_layout.addWidget(sep)

        # Example cards
        for ex in examples:
            ex_card = QFrame(self.container)
            ex_card.setFrameShape(QFrame.Shape.StyledPanel)
            ex_card.setStyleSheet("QFrame{background:#fbfbfb;border:1px solid #eee;border-radius:6px;padding:8px}")
            ex_layout = QVBoxLayout(ex_card)

            # Title for example (slug + reading in one label)
            ex_slug = ex.get('slug', '')
            try:
                ex_reading = ex.get('japanese', [{}])[0].get('reading', '')
            except Exception:
                ex_reading = ''
            if ex_reading:
                ex_title_html = (
                    f"<span style='font-size:12pt;font-weight:700'>{ex_slug}</span>\u00A0"
                    f"<span style='font-size:12pt;font-weight:400;color:#444'>&#8212;&nbsp;{ex_reading}</span>"
                )
            else:
                ex_title_html = f"<span style='font-size:12pt;font-weight:700'>{ex_slug}</span>"
            ex_title_lbl = QLabel()
            ex_title_lbl.setText(ex_title_html)
            ex_title_lbl.setTextFormat(Qt.TextFormat.RichText)
            ex_title_lbl.setWordWrap(True)
            ex_title_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            ex_layout.addWidget(ex_title_lbl)

            # meanings as bullets, with collapse/expand when >5
            ex_senses = ex.get('senses', []) or []
            ex_texts = []
            for s in ex_senses:
                defs = ', '.join(s.get('english_definitions', []))
                if defs:
                    ex_texts.append(defs)

            def build_html(items):
                html = '<ul style="margin:4px 0 0 18px; padding:0;">'
                for it in items:
                    html += f'<li>{it}</li>'
                html += '</ul>'
                return html

            if not ex_texts:
                lbl_defs = QLabel('No meanings')
                lbl_defs.setStyleSheet('font-size:10pt;color:#222;')
                lbl_defs.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
                ex_layout.addWidget(lbl_defs)
            elif len(ex_texts) <= 5:
                lbl_defs = QLabel()
                lbl_defs.setText(build_html(ex_texts))
                lbl_defs.setTextFormat(Qt.TextFormat.RichText)
                lbl_defs.setWordWrap(True)
                lbl_defs.setStyleSheet('font-size:10pt;color:#222;')
                lbl_defs.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
                ex_layout.addWidget(lbl_defs)
            else:
                collapsed = build_html(ex_texts[:5])
                full = build_html(ex_texts)
                lbl_defs = QLabel()
                lbl_defs.setText(collapsed)
                lbl_defs.setTextFormat(Qt.TextFormat.RichText)
                lbl_defs.setWordWrap(True)
                lbl_defs.setStyleSheet('font-size:10pt;color:#222;')
                lbl_defs.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
                ex_layout.addWidget(lbl_defs)

                ex_show_btn = QPushButton('Show more')
                ex_show_btn.setFlat(True)
                ex_show_btn.setStyleSheet('color:#0078d4;text-decoration:underline;background:transparent;border:0;padding:4px')

                def ex_toggle_event(*_args, lbl=lbl_defs, btn=ex_show_btn, full_html=full, collapsed_html=collapsed):
                    if btn.text() == 'Show more':
                        lbl.setText(full_html)
                        btn.setText('Show less')
                    else:
                        lbl.setText(collapsed_html)
                        btn.setText('Show more')

                ex_show_btn.clicked.connect(ex_toggle_event)
                ex_layout.addWidget(ex_show_btn)

            self.container_layout.addWidget(ex_card)

        # add stretch so cards stay at top
        self.container_layout.addStretch(1)







    # def display_result(self, result):
    #     """
    #     Format and display the Jisho API result in the panel.
    #     """
    #     if not isinstance(result, dict):
    #         self.show_results("Error: Unexpected result format.")
    #         return
    #     if result.get('error'):
    #         self.show_results(f"Error: {result['error']}")
    #         return
    #     if result.get('meta', {}).get('status') != 200:
    #         self.show_results(f"API Error: Status {result.get('meta', {}).get('status')}")
    #         return
    #     data = result.get('data', [])
    #     if not data:
    #         self.show_results("No results found.")
    #         return
    #     main = data[0]
    #     examples = data[1:]
    #     lines = [f"Main: {main.get('slug', '')} ({main.get('japanese', [{}])[0].get('reading', '')})"]
    #     for sense in main.get('senses', []):
    #         lines.append('  - ' + ', '.join(sense.get('english_definitions', [])))
    #     if examples:
    #         lines.append("\nExamples:")
    #         for ex in examples:
    #             lines.append(f"{ex.get('slug', '')} ({ex.get('japanese', [{}])[0].get('reading', '')})")
    #             for sense in ex.get('senses', []):
    #                 lines.append('  - ' + ', '.join(sense.get('english_definitions', [])))
    #     self.show_results('\n'.join(lines))
