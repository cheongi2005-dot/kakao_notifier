import os, sys
from pathlib import Path

# PyInstaller frozen 여부에 따라 경로 결정
if getattr(sys, 'frozen', False):
    _APP_DIR    = Path(os.path.dirname(sys.executable))   # exe 옆 폴더
    _BUNDLE_DIR = Path(sys._MEIPASS)                       # 번들 내부 (_internal)
else:
    _APP_DIR    = Path(os.path.dirname(os.path.abspath(__file__)))
    _BUNDLE_DIR = _APP_DIR

FIREBASE_KEY        = str(_BUNDLE_DIR / "firebase-key.json")
FIREBASE_PROJECT_ID = "student-manager-coaching"
