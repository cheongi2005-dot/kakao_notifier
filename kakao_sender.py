"""카카오 비즈니스 채팅 자동화.

로그인 방식:
  Playwright Chromium headed 로그인 (Chrome 설치 불필요, persistent context로 재사용)
메시지 전송: requests 직접 API 호출 (브라우저 불필요)
"""
import json
import mimetypes
import os
import struct
import sys
import time
import requests
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# Playwright 브라우저 경로: run.bat이 설정하지만 직접 실행 시에도 동작하도록 폴백 설정
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "C:/Users/Public/kakao_pw_browsers"

PROFILE_ID      = "_ADPZb"
CHAT_BASE       = f"https://business.kakao.com/{PROFILE_ID}/chats"
SEARCH_URL      = f"https://business.kakao.com/api/profiles/{PROFILE_ID}/chats/search"

# 데이터 파일 (세션, 그룹, 로그)은 OneDrive 밖의 고정 경로에 저장
_DATA_DIR       = Path("C:/Users/Public/kakao_notifier_data")
SESSION_FILE    = _DATA_DIR / ".kakao_session.json"
_LEGACY_SESSION = Path(os.environ.get("APPDATA", "")) / "학생관리시스템" / ".kakao_session.json"

_HEADERS = {
    "Accept":       "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin":       "https://business.kakao.com",
    "Referer":      CHAT_BASE,
    "User-Agent":   (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


# ── Playwright Chromium headed 로그인 ────────────────────────────────────────

_PW_PROFILE = Path("C:/Users/Public/kakao_notifier_browser")


def _try_playwright_login() -> dict | None:
    """이미 설치된 Playwright Chromium으로 headed 로그인.
    Chrome 설치 불필요 — persistent context로 프로필 유지.
    """
    _PW_PROFILE.mkdir(parents=True, exist_ok=True)

    # Playwright의 Node.js 드라이버가 CREATE_NO_WINDOW(0x08000000)로 spawn되면
    # libuv가 GetConsoleTitle()=0을 받아 process_title NULL assert로 crash함.
    # subprocess.Popen을 임시 패치해 해당 플래그를 제거.
    import subprocess as _sp
    _orig_Popen = _sp.Popen
    class _PatchedPopen(_orig_Popen):
        def __init__(self, *a, **kw):
            if sys.platform == "win32":
                kw["creationflags"] = kw.get("creationflags", 0) & ~0x08000000
            super().__init__(*a, **kw)

    _sp.Popen = _PatchedPopen
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(_PW_PROFILE),
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-popup-blocking",
                    "--window-size=1280,800",
                ],
                ignore_default_args=["--enable-automation"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(
                    f"https://business.kakao.com/{PROFILE_ID}/chats",
                    wait_until="domcontentloaded", timeout=30_000,
                )
            except Exception:
                pass

            stable = 0
            login_ok = False
            for _ in range(300):  # 최대 10분
                try:
                    if ctx.pages:
                        page = ctx.pages[-1]

                    # 1순위: _kaslt 쿠키 등장 = 2FA 포함 로그인 완전 완료
                    kakao_ck = {
                        c["name"]: c["value"]
                        for c in ctx.cookies()
                        if "kakao.com" in c.get("domain", "")
                    }
                    if "_kaslt" in kakao_ck:
                        login_ok = True
                        break

                    # 2순위(폴백): 채팅 URL 안정 감지
                    cur = page.url
                except Exception as e:
                    _write_login_error(e)
                    break

                is_chat = (
                    "business.kakao.com" in cur
                    and "login" not in cur.lower()
                    and "accounts.kakao.com" not in cur
                    and "biz-auth.kakao.com" not in cur
                )
                if is_chat:
                    stable += 1
                    if stable >= 3:
                        login_ok = True
                        break
                else:
                    stable = 0
                time.sleep(2)
            else:
                ctx.close()
                return None

            if not login_ok:
                ctx.close()
                return None

            # 관리자 추가인증 버튼 처리
            try:
                btn = page.locator("button:has-text('관리자 추가인증')").first
                if btn.is_visible(timeout=2_000):
                    btn.click()
                    for _ in range(300):  # 최대 10분
                        time.sleep(2)
                        if ctx.pages:
                            page = ctx.pages[-1]
                        cur2 = page.url
                        if (f"/{PROFILE_ID}/chats" in cur2
                                and "additional-auth" not in cur2
                                and "extra-auth" not in cur2):
                            break
            except Exception:
                pass

            cookies = {
                c["name"]: c["value"]
                for c in ctx.cookies()
                if "kakao.com" in c.get("domain", "")
            }
            local_storage: dict = {}
            try:
                ls_json = page.evaluate(
                    "() => JSON.stringify(Object.fromEntries("
                    "Object.entries(localStorage).filter(([k]) => "
                    "k.includes('auth') || k.includes('kakao') || k.includes('biz'))))"
                )
                if ls_json:
                    local_storage = json.loads(ls_json)
            except Exception:
                pass

            ctx.close()
            if not cookies:
                return None
            return {"token": "", "cookies": cookies, "local_storage": local_storage}
    except Exception as e:
        _write_login_error(e)
        return None
    finally:
        _sp.Popen = _orig_Popen


# ── 공통 ──────────────────────────────────────────────────────────────────────

def _save_session(session: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _validate_session(session: dict) -> bool:
    """managers API 호출로 세션 유효성 확인."""
    cookies = session.get("cookies", {})
    token   = session.get("token", "")
    hdrs = {
        "Accept":           "application/json, text/plain, */*",
        "Origin":           "https://business.kakao.com",
        "Referer":          CHAT_BASE,
        "sec-fetch-site":   "same-origin",
        "sec-fetch-mode":   "cors",
        "sec-fetch-dest":   "empty",
        "User-Agent":       _HEADERS["User-Agent"],
    }
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(
            f"https://business.kakao.com/api/profiles/{PROFILE_ID}/managers",
            headers=hdrs, cookies=cookies, timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def do_login(force_browser: bool = False) -> bool:
    """Playwright 브라우저로 로그인. force_browser 인수는 하위 호환성 유지용."""
    session = _try_playwright_login()
    if session:
        cookies = session.get("cookies", {})
        if "_kaslt" in cookies:
            _save_session(session)
            return True
        if cookies and _validate_session(session):
            _save_session(session)
            return True
        # 새 세션이 있지만 검증 실패 — 레거시 폴백하지 않음
        return False

    # Playwright도 실패한 경우에만 레거시 세션 시도
    if _LEGACY_SESSION.exists():
        try:
            legacy = json.loads(_LEGACY_SESSION.read_text(encoding="utf-8"))
            if _validate_session(legacy):
                _save_session(legacy)
                return True
        except Exception:
            pass

    return False


def _load_session() -> dict:
    for path in (SESSION_FILE, _LEGACY_SESSION):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    raise FileNotFoundError("세션 파일 없음 — 로그인 버튼을 클릭해 카카오 로그인을 진행하세요.")


def _find_chat_id(name: str, session: dict) -> str | None:
    """이름으로 진행중 채팅 검색 → chat_id 반환."""
    cookies = session.get("cookies", {})
    token   = session.get("token", "")
    hdrs    = dict(_HEADERS)
    if token:
        hdrs["Authorization"] = f"Bearer {token}"

    r = requests.post(
        SEARCH_URL,
        params={"size": 100},
        json={"is_blocked": False, "keyword": name, "labels": []},
        headers=hdrs,
        cookies=cookies,
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  [검색 실패] HTTP {r.status_code}")
        return None

    items = r.json().get("items", [])
    if not items:
        print(f"  [검색 결과 없음] '{name}'")
        return None

    for item in items:
        if item.get("name", "").strip() == name:
            cid = next((item[k] for k in ("id", "chatId", "chat_id") if item.get(k) is not None), "")
            return str(cid)

    first      = items[0]
    found_name = first.get("name", "")
    print(f"  [참고] '{name}' 정확 일치 없음 → '{found_name}' 사용")
    cid = next((first[k] for k in ("id", "chatId", "chat_id") if first.get(k) is not None), "")
    return str(cid)


def _write_login_error(exc: Exception) -> None:
    try:
        import traceback as _tb
        log_path = SESSION_FILE.parent / "login_error.log"
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {type(exc).__name__}: {exc}\n{_tb.format_exc()}\n---\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


def _write_log(msg: str) -> None:
    """에러 로그를 세션 파일 옆에 기록."""
    try:
        import sys as _sys, traceback as _tb
        log_path = SESSION_FILE.parent / "send_error.log"
        tb = _tb.format_exc() if _sys.exc_info()[0] is not None else ""
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n{tb}---\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


_API_BASE    = f"https://business.kakao.com/api/profiles/{PROFILE_ID}/chats"
_IMAGE_EXTS  = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_VIDEO_EXTS  = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm"}


def _api_hdrs(session: dict, referer: str = CHAT_BASE) -> dict:
    hdrs = {
        "Accept":     "*/*",
        "Origin":     "https://business.kakao.com",
        "Referer":    referer,
        "User-Agent": _HEADERS["User-Agent"],
    }
    token = session.get("token", "")
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


def _img_size(path: str) -> tuple[int, int]:
    """PNG / JPEG 이미지 크기 반환."""
    with open(path, "rb") as f:
        hdr = f.read(24)
    if hdr[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", hdr[16:24])
    if hdr[:2] == b"\xff\xd8":
        with open(path, "rb") as f:
            f.seek(2)
            while True:
                m = f.read(2)
                if len(m) < 2 or m[0] != 0xFF:
                    break
                n = struct.unpack(">H", f.read(2))[0]
                if m[1] in (0xC0, 0xC1, 0xC2, 0xC3):
                    f.read(1)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                f.seek(n - 2, 1)
    return 0, 0


def _file_category(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    return "document"


def _api_send_text(chat_url: str, web_url: str, message: str, session: dict) -> None:
    r = requests.post(
        f"{chat_url}/chatlogs",
        headers=_api_hdrs(session, web_url),
        cookies=session.get("cookies", {}),
        files=[("text", (None, message))],
        timeout=15,
    )
    r.raise_for_status()


def _api_send_image(chat_url: str, web_url: str, file_path: str, session: dict) -> None:
    mime, _ = mimetypes.guess_type(file_path)
    mime = mime or "image/jpeg"
    w, h   = _img_size(file_path)
    fname  = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        data = f.read()
    r = requests.post(
        f"{chat_url}/chatlogs",
        headers=_api_hdrs(session, web_url),
        cookies=session.get("cookies", {}),
        files=[
            ("image",    (fname, data, mime)),
            ("width",    (None,  str(w))),
            ("height",   (None,  str(h))),
            ("mimetype", (None,  mime)),
        ],
        timeout=60,
    )
    r.raise_for_status()


def _api_send_document(chat_url: str, web_url: str, file_path: str, session: dict) -> None:
    file_size = os.path.getsize(file_path)
    fname     = os.path.basename(file_path)
    mime, _   = mimetypes.guess_type(file_path)
    mime      = mime or ""
    hdrs      = _api_hdrs(session, web_url)
    hdrs["Content-Type"] = "application/octet-stream"
    url = (f"{chat_url}/chatlogs"
           f"?mimetype={quote(mime)}&fileSize={file_size}&fileName={quote(fname)}")
    with open(file_path, "rb") as f:
        data = f.read()
    r = requests.post(
        url,
        headers=hdrs,
        cookies=session.get("cookies", {}),
        data=data,
        timeout=120,
    )
    r.raise_for_status()


def _api_send_video(chat_url: str, web_url: str, file_path: str, session: dict) -> None:
    file_size = os.path.getsize(file_path)
    fname     = os.path.basename(file_path)
    hdrs      = _api_hdrs(session, web_url)
    cookies   = session.get("cookies", {})

    # 1단계: 업로드 세션 생성 → upload_token 획득
    r = requests.post(
        f"{chat_url}/videos/parts/session",
        headers=hdrs,
        cookies=cookies,
        json={"file_name": fname, "file_size": file_size},
        timeout=15,
    )
    r.raise_for_status()
    upload_token = r.json().get("upload_token")
    if not upload_token:
        raise RuntimeError("업로드 세션 생성 실패: upload_token 없음")

    # 2단계: 파일 업로드
    with open(file_path, "rb") as f:
        video_data = f.read()
    r = requests.post(
        f"{chat_url}/videos/parts",
        headers=hdrs,
        cookies=cookies,
        files=[
            ("fileName",    (None, fname)),
            ("fileSize",    (None, str(file_size))),
            ("partOffset",  (None, "0")),
            ("partSize",    (None, str(file_size))),
            ("video",       ("blob", video_data, "application/octet-stream")),
            ("uploadToken", (None, upload_token)),
        ],
        timeout=300,
    )
    r.raise_for_status()

    # 3단계: 트랜스코딩 완료까지 폴링 (최대 120초)
    for _ in range(60):
        r = requests.post(
            f"{chat_url}/videos/parts/status",
            headers=hdrs,
            cookies=cookies,
            json={"file_name": fname, "upload_token": upload_token},
            timeout=15,
        )
        r.raise_for_status()
        st = r.json().get("status", "")
        if st == "failed":
            raise RuntimeError("동영상 트랜스코딩 실패")
        if st != "transcoding":
            break
        time.sleep(2)
    else:
        raise TimeoutError("동영상 트랜스코딩 타임아웃 (120초)")

    # 4단계: 채팅에 동영상 메시지 전송
    r = requests.post(
        f"{chat_url}/chatlogs",
        headers=hdrs,
        cookies=cookies,
        files=[("video", (None, upload_token))],
        timeout=15,
    )
    r.raise_for_status()


def _pw_complete(web_url: str, session: dict) -> bool:
    """headless 브라우저로 상담완료 버튼 클릭 (WebSocket 기반이라 API 불가).
    반환값: True=완료 클릭 성공, False=실패(버튼 없음·세션 만료·에러 등)
    """
    cookie_list = [
        {"name": k, "value": v, "domain": ".kakao.com", "path": "/"}
        for k, v in session.get("cookies", {}).items()
    ]
    local_storage = session.get("local_storage", {})

    # pythonw.exe 환경에서 Playwright Node.js 드라이버 subprocess 창이 뜨는 문제 방지:
    # CREATE_NO_WINDOW 제거(libuv 크래시 방지) + SW_HIDE(창 숨김) 동시 적용
    import subprocess as _sp
    _orig_Popen = _sp.Popen
    class _PatchedPopen(_orig_Popen):
        def __init__(self, *a, **kw):
            if sys.platform == "win32":
                kw["creationflags"] = kw.get("creationflags", 0) & ~0x08000000
                if "startupinfo" not in kw:
                    si = _sp.STARTUPINFO()
                    si.dwFlags = _sp.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0  # SW_HIDE
                    kw["startupinfo"] = si
            super().__init__(*a, **kw)
    _sp.Popen = _PatchedPopen
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx  = browser.new_context()
            ctx.add_cookies(cookie_list)
            page = ctx.new_page()
            if local_storage:
                try:
                    page.goto("https://business.kakao.com",
                              wait_until="domcontentloaded", timeout=15_000)
                    page.evaluate(
                        "ls => { for (const [k,v] of Object.entries(ls)) "
                        "localStorage.setItem(k, v); }",
                        local_storage,
                    )
                except Exception:
                    pass
            try:
                page.goto(web_url, wait_until="domcontentloaded", timeout=25_000)

                # 로그인/추가인증 페이지로 리다이렉션 감지
                cur = page.url
                if ("login" in cur.lower()
                        or "accounts.kakao.com" in cur
                        or "biz-auth.kakao.com" in cur):
                    _write_log(f"_pw_complete: 인증 페이지로 리다이렉션 → {cur}")
                    return False

                page.wait_for_timeout(1500)

                # btn_state 클릭 (timeout=8s: 버튼 미출현 시 PWTimeout)
                try:
                    page.locator("button.btn_state").first.click(timeout=8_000)
                except PWTimeout:
                    _write_log(f"_pw_complete: btn_state 버튼 없음 (이미 완료 상태?) → {web_url}")
                    return False

                # 확인 다이얼로그 버튼 클릭 (클래스 선택자 → role/텍스트 폴백 순서)
                confirmed = False

                # 1순위: 기존 클래스 선택자
                for sel in ("button.btn_g_m", "button.btn_g.btn_g2"):
                    try:
                        page.locator(sel).first.click(timeout=4_000)
                        confirmed = True
                        break
                    except PWTimeout:
                        pass

                # 2순위: ARIA role + 텍스트 폴백 (카카오 UI 클래스 변경에 대응)
                if not confirmed:
                    for label in ("확인", "완료", "상담완료"):
                        try:
                            page.get_by_role("button", name=label).last.click(timeout=3_000)
                            confirmed = True
                            break
                        except PWTimeout:
                            pass

                if not confirmed:
                    _write_log(f"_pw_complete: 확인 다이얼로그 버튼 없음 → {web_url}")
                return confirmed

            except Exception as e:
                _write_log(f"_pw_complete: 예외 → {type(e).__name__}: {e}")
                return False
            finally:
                browser.close()
    except Exception as e:
        _write_log(f"_pw_complete: 브라우저 실행 실패 → {type(e).__name__}: {e}")
        return False
    finally:
        _sp.Popen = _orig_Popen


def send_message(name: str, message: str, file_paths: list[str] | None = None) -> tuple[bool, str]:
    """requests 직접 API로 메시지/파일 전송 (브라우저 불필요).
    반환값: (성공여부, 실패이유 또는 "")
    """
    if not message:
        return False, "메시지 없음 (파일 전송 시에도 메시지 필수)"

    try:
        session = _load_session()
    except FileNotFoundError:
        return False, "세션 파일 없음"

    chat_id = _find_chat_id(name, session)
    if not chat_id:
        return False, "채팅방 검색 실패"

    chat_url = f"{_API_BASE}/{chat_id}"
    web_url  = f"{CHAT_BASE}/{chat_id}"

    try:
        if file_paths:
            for fp in file_paths:
                if not os.path.exists(fp):
                    return False, f"파일 없음: {fp}"
                cat = _file_category(fp)
                if cat == "image":
                    _api_send_image(chat_url, web_url, fp, session)
                elif cat == "video":
                    _api_send_video(chat_url, web_url, fp, session)
                else:
                    _api_send_document(chat_url, web_url, fp, session)

        _api_send_text(chat_url, web_url, message, session)
        completed = _pw_complete(web_url, session)
        return True, "" if completed else "완료버튼 미처리"

    except requests.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            return False, "세션 만료"
        _write_log(f"API error ({name}): {status} {e.response.text[:200]}")
        return False, f"API 오류 {status}"
    except Exception as e:
        _write_log(f"send error ({name}): {type(e).__name__}: {e}")
        return False, f"{type(e).__name__}: {str(e)[:200]}"
