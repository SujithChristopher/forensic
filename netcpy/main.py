"""Network Copy - Main Application Entry Point"""

import sys
from PySide6.QtWidgets import QApplication

from netcpy.ui.main_window import MainWindow


def main():
    """Main entry point for the application"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
