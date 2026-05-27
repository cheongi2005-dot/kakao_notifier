"""카카오 비즈니스 채팅 자동화.

로그인 방식 (student_manager 동일):
  Stage 1. Chrome 쿠키 DB 직접 읽기 (Chrome 실행 중이어도 동작)
  Stage 2. Playwright 브라우저로 직접 로그인
메시지 전송: Playwright headless → textarea.tf_g → btn_submit → 상담완료
"""
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

PROFILE_ID      = "_ADPZb"
CHAT_BASE       = f"https://business.kakao.com/{PROFILE_ID}/chats"
SEARCH_URL      = f"https://business.kakao.com/api/profiles/{PROFILE_ID}/chats/search"
SESSION_FILE    = (
    Path(os.path.dirname(sys.executable))          # frozen exe 옆
    if getattr(sys, 'frozen', False)
    else Path(os.path.dirname(os.path.abspath(__file__)))
) / ".kakao_session.json"
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


# ── Stage 1: Chrome 쿠키 직접 읽기 ───────────────────────────────────────────

def _read_chrome_cookies() -> dict | None:
    """Chrome 쿠키 DB에서 kakao.com 쿠키를 직접 읽어 반환 (Chrome 실행 중도 가능)."""
    try:
        import win32crypt
        from Cryptodome.Cipher import AES
    except ImportError:
        try:
            import win32crypt
            from Crypto.Cipher import AES
        except ImportError:
            return None

    local_data       = Path(os.environ.get("LOCALAPPDATA", ""))
    local_state_path = local_data / "Google/Chrome/User Data/Local State"
    cookie_path      = local_data / "Google/Chrome/User Data/Default/Network/Cookies"

    if not local_state_path.exists() or not cookie_path.exists():
        return None

    try:
        ls      = json.loads(local_state_path.read_text(encoding="utf-8"))
        enc_key = base64.b64decode(ls["os_crypt"]["encrypted_key"])[5:]
        key     = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
    except Exception:
        return None

    def _open_db():
        uri = "file:///" + str(cookie_path).replace("\\", "/") + "?mode=ro&nolock=1&immutable=1"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)

    tmp = None
    try:
        con  = _open_db()
        rows = con.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%.kakao.com'"
        ).fetchall()
        con.close()
    except Exception:
        tmp = Path(tempfile.mktemp(suffix=".db"))
        try:
            shutil.copy2(cookie_path, tmp)
            con  = sqlite3.connect(str(tmp))
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%.kakao.com'"
            ).fetchall()
            con.close()
        except Exception:
            if tmp:
                tmp.unlink(missing_ok=True)
            return None

    cookies = {}
    try:
        for name, enc_val in rows:
            if not enc_val:
                continue
            try:
                if enc_val[:3] == b"v10":
                    nonce, ct, tag = enc_val[3:15], enc_val[15:-16], enc_val[-16:]
                    val = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode()
                else:
                    val = win32crypt.CryptUnprotectData(enc_val, None, None, None, 0)[1].decode()
                cookies[name] = val
            except Exception:
                pass
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)

    return cookies if cookies else None


def _try_chrome_direct() -> dict | None:
    """Chrome 쿠키로 API 검증 → 성공 시 session dict 반환."""
    cookies = _read_chrome_cookies()
    if not cookies:
        return None

    try:
        r = requests.get(
            f"https://business.kakao.com/api/profiles/{PROFILE_ID}/managers",
            cookies=cookies,
            headers={
                "Accept":       "application/json, text/plain, */*",
                "Origin":       "https://business.kakao.com",
                "Referer":      CHAT_BASE,
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "User-Agent":   _HEADERS["User-Agent"],
            },
            timeout=15,
        )
        if r.status_code == 200:
            return {"token": "", "cookies": cookies}
    except Exception:
        pass
    return None


# ── Stage 2: Selenium 브라우저 로그인 (student_manager 동일 로직) ─────────────

SELENIUM_PROFILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "kakao_selenium_profile"


def _try_selenium() -> dict | None:
    """student_manager와 동일한 Selenium 로그인.
    전용 Chrome 프로필 사용 → 로그인 유지, 완료 후 자동 종료.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        print(f"  selenium 패키지 없음: {e}")
        return None

    SELENIUM_PROFILE.mkdir(parents=True, exist_ok=True)

    opts = Options()
    for arg in [
        "--disable-blink-features=AutomationControlled",
        "--disable-popup-blocking",
        "--window-size=1280,800",
        f"--user-data-dir={SELENIUM_PROFILE}",
    ]:
        opts.add_argument(arg)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    if sys.platform == "win32":
        import subprocess
        service.creation_flags = subprocess.CREATE_NO_WINDOW

    driver = webdriver.Chrome(
        service=service, options=opts
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(30)
    driver.get(f"https://business.kakao.com/{PROFILE_ID}/chats")

    def _drain_perf_logs() -> str:
        tok = ""
        try:
            for entry in driver.get_log("performance"):
                msg = json.loads(entry.get("message", "{}")).get("message", {})
                if msg.get("method") != "Network.requestWillBeSent":
                    continue
                req = msg.get("params", {}).get("request", {})
                if "crux-bizgateway.kakao.com" not in req.get("url", ""):
                    continue
                auth = req.get("headers", {}).get("Authorization", "")
                if auth.startswith("Bearer "):
                    t = auth.removeprefix("Bearer ").strip()
                    if t:
                        tok = t
        except Exception:
            pass
        return tok

    token  = ""
    stable = 0
    for waited in range(0, 300, 2):  # 최대 5분
        cur = driver.current_url
        is_chat = (
            "business.kakao.com" in cur
            and "login" not in cur
            and "accounts.kakao.com" not in cur
            and "biz-auth.kakao.com" not in cur
        )
        t = _drain_perf_logs()
        if t:
            token = t

        if is_chat:
            stable += 1
            if stable >= 5:  # 10초 안정 확인
                break
        else:
            if stable > 0:
                print("  2FA 진행 중 — 대기...")
            stable = 0

        time.sleep(2)
    else:
        driver.quit()
        return None

    # ── 관리자 추가인증 자동 처리 ──────────────────────────────────────
    # 채팅 목록에 '관리자 추가인증' 버튼이 있으면 자동 클릭 후 사용자 완료 대기
    try:
        from selenium.webdriver.common.by import By
        auth_btns = driver.find_elements(
            By.XPATH, "//button[contains(text(),'관리자 추가인증')]"
        )
        if auth_btns:
            print("  관리자 추가인증 버튼 감지 — 자동 클릭, 인증을 완료해 주세요")
            auth_btns[0].click()
            # 사용자가 인증을 완료해 채팅 목록으로 돌아올 때까지 최대 5분 대기
            for _ in range(0, 300, 2):
                time.sleep(2)
                cur2 = driver.current_url
                # 추가인증 완료 → 채팅 목록 또는 채팅 페이지로 복귀
                if (f"/{PROFILE_ID}/chats" in cur2
                        and "additional-auth" not in cur2
                        and "extra-auth" not in cur2):
                    print("  추가인증 완료 감지")
                    break
    except Exception:
        pass

    cookies = {
        c["name"]: c["value"]
        for c in driver.get_cookies()
        if "kakao.com" in c.get("domain", "")
    }

    # localStorage도 함께 캡처 (추가인증 등 쿠키 외 인증 상태 보존)
    local_storage: dict = {}
    try:
        ls_json = driver.execute_script(
            "return JSON.stringify(Object.fromEntries("
            "Object.entries(localStorage).filter(([k]) => "
            "k.includes('auth') || k.includes('kakao') || k.includes('biz'))))"
        )
        if ls_json:
            local_storage = json.loads(ls_json)
    except Exception:
        pass

    driver.quit()  # 로그인 완료 후 자동 종료

    if not cookies:
        return None

    return {"token": token, "cookies": cookies, "local_storage": local_storage}


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


def do_login() -> bool:
    """Stage 1(Chrome 쿠키 직접 읽기) → Stage 2(Selenium 브라우저 로그인) 순서로 시도."""
    # Stage 1: Chrome 쿠키 직접 읽기 (API 검증 포함)
    session = _try_chrome_direct()
    if session:
        _save_session(session)
        return True

    # Stage 2: Selenium 로그인
    session = _try_selenium()
    if session:
        cookies = session.get("cookies", {})
        # _kaslt 있으면 로그인 성공으로 간주 — API 검증 없이 저장
        if "_kaslt" in cookies:
            _save_session(session)
            return True
        # _kaslt 없으면 API 검증 후 저장
        if cookies and _validate_session(session):
            _save_session(session)
            return True
        # 신규 세션 실패 → 레거시 시도
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
            return str(item.get("id") or item.get("chatId") or item.get("chat_id") or "")

    first      = items[0]
    found_name = first.get("name", "")
    print(f"  [참고] '{name}' 정확 일치 없음 → '{found_name}' 사용")
    return str(first.get("id") or first.get("chatId") or first.get("chat_id") or "")


def _write_log(msg: str) -> None:
    """에러 로그를 세션 파일 옆에 기록."""
    try:
        log_path = SESSION_FILE.parent / "send_error.log"
        import traceback as _tb
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n{_tb.format_exc()}\n---\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


def send_message(name: str, message: str) -> tuple[bool, str]:
    """백그라운드(headless) 브라우저로 메시지 전송.
    반환값: (성공여부, 실패이유 또는 "")
    """
    try:
        session = _load_session()
    except FileNotFoundError:
        return False, "세션 파일 없음"

    chat_id = _find_chat_id(name, session)
    if not chat_id:
        return False, "채팅방 검색 실패"

    chat_url    = f"{CHAT_BASE}/{chat_id}"
    cookie_list = [
        {"name": k, "value": v, "domain": ".kakao.com", "path": "/"}
        for k, v in session.get("cookies", {}).items()
    ]

    local_storage = session.get("local_storage", {})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                slow_mo=150,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx  = browser.new_context()
            ctx.add_cookies(cookie_list)
            page = ctx.new_page()

            # localStorage 주입 (추가인증 상태 복원)
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
                page.goto(chat_url, wait_until="domcontentloaded", timeout=25_000)
                page.wait_for_timeout(2000)

                # 로그인 페이지로 리다이렉트 되면 세션 만료
                cur = page.url
                if ("accounts.kakao.com" in cur or "biz-auth.kakao.com" in cur
                        or "login" in cur.lower()):
                    return False, f"세션 만료 (→ {cur[:80]})"

                # 관리자 추가인증 만료 모달 감지
                modal = page.locator("div[role=dialog]")
                if modal.count() > 0:
                    txt = modal.first.inner_text()
                    if "추가인증" in txt:
                        return False, "추가인증 만료"

                msg_box = page.locator("textarea.tf_g").first
                msg_box.wait_for(timeout=10_000)
                msg_box.click()
                msg_box.fill(message)
                page.wait_for_timeout(300)

                page.locator("button.btn_submit").click(timeout=5_000)
                page.wait_for_timeout(600)

                try:
                    page.locator("button.btn_state").click(timeout=10_000)
                    page.wait_for_timeout(600)
                    page.locator("button.btn_g_m").first.click(timeout=5_000)
                    page.wait_for_timeout(600)
                    page.locator("button.btn_g.btn_g2").click(timeout=5_000)
                    page.wait_for_timeout(400)
                except PWTimeout:
                    pass  # 상담완료 버튼은 선택사항 — 전송 자체는 성공

                return True, ""

            except PWTimeout:
                return False, "페이지 로딩 또는 메시지 전송 시간 초과"
            except Exception as e:
                _write_log(f"page error ({name}): {type(e).__name__}: {e}")
                return False, f"{type(e).__name__}: {str(e)[:200]}"
            finally:
                browser.close()
    except Exception as e:
        _write_log(f"launch error ({name}): {type(e).__name__}: {e}")
        return False, f"브라우저 시작 실패: {str(e)[:200]}"
