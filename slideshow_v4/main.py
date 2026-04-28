"""AI Slideshow Generator v2 - Entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Slideshow Generator v2")
    app.setOrganizationName("SlideshowApp")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
