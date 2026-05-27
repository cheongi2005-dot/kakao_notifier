import os, sys
from pathlib import Path

# PyInstaller frozen 여부에 따라 경로 결정
if getattr(sys, 'frozen', False):
    _APP_DIR    = Path(os.path.dirname(sys.executable))   # exe 옆 폴더
    _BUNDLE_DIR = Path(sys._MEIPASS)                       # 번들 내부 (_internal)
else:
    _APP_DIR    = Path(os.path.dirname(os.path.abspath(__file__)))
    _BUNDLE_DIR = _APP_DIR

# firebase-key.json: 번들 내부 → 없으면 student_manager 폴더 시도
_fb_candidates = [
    _BUNDLE_DIR / "firebase-key.json",
    Path(r"c:\Users\Cheon\OneDrive\바탕 화면\student_manager") / "firebase-key.json",
]
FIREBASE_KEY        = str(next((p for p in _fb_candidates if p.exists()), _fb_candidates[0]))
FIREBASE_PROJECT_ID = "student-manager-coaching"

TEACHER = "이다성"

KAKAO_CHAT_URL      = "https://business.kakao.com/_ADPZb/chats"
BROWSER_SESSION_DIR = str(_APP_DIR / ".browser_session")

TEMPLATES = {
    "homework": "{name}~ 저번주에 숙제가 잘 안됐는데 이번주는 잊지 말고 해보자!",
    "attend":   "{name}~ 이번 기간에 출석이 확인이 안됐어! 선생님한테 꼭 알려줘 😊",
}
