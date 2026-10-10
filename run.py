"""PyInstaller entry script."""
import sys

from moodle_downloader.app import main

if __name__ == "__main__":
    sys.exit(main())
