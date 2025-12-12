
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton

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
        layout.addWidget(self.title)
        self.results_area = QTextEdit(self)
        self.results_area.setReadOnly(True)
        layout.addWidget(self.results_area)
        # Add a close button
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


    def show_results(self, text: str):
        self.results_area.setPlainText(text)

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
        main = data[0]
        examples = data[1:]
        lines = [f"Main: {main.get('slug', '')} ({main.get('japanese', [{}])[0].get('reading', '')})"]
        for sense in main.get('senses', []):
            lines.append('  - ' + ', '.join(sense.get('english_definitions', [])))
        if examples:
            lines.append("\nExamples:")
            for ex in examples:
                lines.append(f"{ex.get('slug', '')} ({ex.get('japanese', [{}])[0].get('reading', '')})")
                for sense in ex.get('senses', []):
                    lines.append('  - ' + ', '.join(sense.get('english_definitions', [])))
        self.show_results('\n'.join(lines))
