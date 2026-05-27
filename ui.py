import sys, os, threading, time, json, requests, multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed

# PyInstaller --noconsole (console=False) 환경에서 print() 에러 방지
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# frozen exe: exe 옆 ms-playwright 폴더에서 Chromium 찾기
if getattr(sys, 'frozen', False):
    _browsers_path = os.path.join(os.path.dirname(sys.executable), "ms-playwright")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _browsers_path)

from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kakao_sender import (send_message, do_login,
                          SESSION_FILE, _LEGACY_SESSION,
                          SEARCH_URL, PROFILE_ID, _HEADERS,
                          _write_login_error)

BG     = "#FAFAFA"
WHITE  = "#FFFFFF"
YELLOW = "#FEE500"
Y_HOV  = "#E6CE00"
DARK   = "#1A1A1A"
GRAY   = "#888888"
LGRAY  = "#EFEFEF"
BORDER = "#DCDCDC"
CHIP   = "#FFF3B0"
CHIP_B = "#E6D800"
GREEN  = "#2ECC71"
RED    = "#E74C3C"
BLUE   = "#3498DB"
F      = ("맑은 고딕", 10)
FB     = ("맑은 고딕", 10, "bold")
FH     = ("맑은 고딕", 13, "bold")
FS     = ("맑은 고딕", 9)
FSB    = ("맑은 고딕", 9, "bold")


def _load_session():
    for path in (SESSION_FILE, _LEGACY_SESSION):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}

# ── 그룹 저장/불러오기 ────────────────────────────────────────────────────────
def _groups_path():
    return SESSION_FILE.parent / "kakao_groups.json"

def _load_groups() -> dict:
    p = _groups_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_groups(groups: dict) -> None:
    p = _groups_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

def _get_headers(session):
    hdrs = dict(_HEADERS)
    token = session.get("token", "")
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs

def _fetch_my_id(session) -> tuple[int | None, dict, bool]:
    """내 assignee_id, 전체 manager 이름 맵, 세션 유효 여부 반환."""
    cookies = session.get("cookies", {})
    token   = session.get("token", "")
    hdrs = {
        "Accept":         "application/json, text/plain, */*",
        "Origin":         "https://business.kakao.com",
        "Referer":        f"https://business.kakao.com/{PROFILE_ID}/chats",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "User-Agent":     _HEADERS["User-Agent"],
    }
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(
            f"https://business.kakao.com/api/profiles/{PROFILE_ID}/managers",
            headers=hdrs, cookies=cookies, timeout=10,
        )
        if r.status_code != 200:
            return None, {}, False
        managers = r.json()
        name_map = {m.get("id"): m.get("name", "") for m in managers}
        my_id = None
        for m in managers:
            if m.get("relation") == "me":
                my_id = m.get("id")
                break
        return my_id, name_map, True
    except Exception:
        return None, {}, False

def _kakao_search(keyword: str, session: dict, my_id) -> list[dict]:
    """키워드로 검색 후 내 담당 채팅만 필터링."""
    cookies = session.get("cookies", {})
    hdrs = _get_headers(session)
    try:
        r = requests.post(
            SEARCH_URL, params={"size": 50},
            json={"is_blocked": False, "keyword": keyword, "labels": []},
            headers=hdrs, cookies=cookies, timeout=10,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        # 내 담당만 필터
        if my_id is not None:
            items = [i for i in items if i.get("assignee_id") == my_id]
        return [
            {
                "name":        it.get("name", "").strip(),
                "chat_id":     str(it.get("id") or it.get("chatId") or ""),
                "assignee_id": it.get("assignee_id"),
            }
            for it in items if it.get("name", "").strip()
        ]
    except Exception:
        return []


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("카카오톡 알림 전송")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(520, 480)

        self._session: dict = {}
        self._my_id = None
        self._name_map: dict = {}
        self._results: list[dict] = []
        self._result_vars: list[tk.BooleanVar] = []
        self._selected: list[dict] = []   # 전송 대상
        self._sched_jobs: dict = {}       # job_id → {label, cancelled}
        self._search_after = None

        self._build()
        self._center()
        self.lift()
        self.focus_force()

        # 전역 마우스휠 바인딩
        self.bind_all("<MouseWheel>", self._on_wheel)

        self.after(100, self._init_session)

    # ── 초기화 ────────────────────────────────────────────────────
    def _init_session(self):
        self._hint.config(text="세션 로딩 중...", fg=GRAY)
        threading.Thread(target=self._init_thread, daemon=True).start()

    def _init_thread(self):
        self._session = _load_session()
        if not self._session:
            self.after(0, lambda: self._hint.config(text="로그인이 필요합니다", fg=RED))
            self.after(0, self._show_login_btn)
            return
        my_id, name_map, valid = _fetch_my_id(self._session)
        if not valid:
            self.after(0, lambda: self._hint.config(text="세션 만료 — 재로그인 필요", fg=RED))
            self.after(0, self._show_login_btn)
            return
        self._my_id = my_id
        self._name_map = name_map
        my_name = name_map.get(my_id, "") if my_id else ""
        msg = f"담당: {my_name}  |  이름 검색으로 내 학생 찾기"
        self.after(0, lambda: self._hint.config(text=msg, fg=GRAY))
        self.after(0, self._hide_login_btn)

    # ── UI 구성 ───────────────────────────────────────────────────
    def _build(self):
        root = tk.Frame(self, bg=BG, padx=22, pady=18)
        root.pack(fill="both", expand=True)

        tk.Label(root, text="카카오톡 알림 전송", font=FH,
                 bg=BG, fg=DARK).pack(anchor="w", pady=(0, 14))

        # 좌우 분할
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)

        left  = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 16))

        right = tk.Frame(body, bg=BG, width=200)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        # ══ [왼쪽] 전송 대상 ══════════════════════════════════════
        send_hdr = tk.Frame(left, bg=BG)
        send_hdr.pack(fill="x")
        tk.Label(send_hdr, text="전송 대상", font=FB, bg=BG, fg=DARK).pack(side="left")
        tk.Button(send_hdr, text="전체 제거", font=FS,
                  bg=LGRAY, fg=GRAY, relief="flat", bd=0,
                  cursor="hand2", padx=8, pady=2,
                  command=self._clear_selected).pack(side="right")
        tk.Button(send_hdr, text="그룹 생성", font=FS,
                  bg=YELLOW, fg=DARK, relief="flat", bd=0,
                  cursor="hand2", padx=8, pady=2,
                  command=self._on_create_group).pack(side="right", padx=(0, 6))

        self._chip_frame = tk.Frame(left, bg=LGRAY, highlightthickness=1,
                                    highlightbackground=BORDER)
        self._chip_frame.pack(fill="x", pady=(4, 2))

        _csr = tk.Frame(self._chip_frame, bg=LGRAY)
        _csr.pack(fill="x", padx=6, pady=6)

        self._chip_canvas = tk.Canvas(_csr, bg=LGRAY, highlightthickness=0, height=30)
        self._chip_vsb = ttk.Scrollbar(_csr, orient="vertical",
                                        command=self._chip_canvas.yview)
        self._chip_canvas.configure(yscrollcommand=self._chip_vsb.set)
        self._chip_vsb.pack(side="right", fill="y")
        self._chip_canvas.pack(side="left", fill="x", expand=True)

        self._chip_inner = tk.Frame(self._chip_canvas, bg=LGRAY)
        self._chip_cwin_id = self._chip_canvas.create_window(
            (0, 0), window=self._chip_inner, anchor="nw")
        self._chip_inner.bind("<Configure>", self._on_chip_inner_cfg)
        self._chip_canvas.bind("<Configure>", self._on_chip_canvas_cfg)

        self._sel_count = tk.Label(left, text="", font=FS, bg=BG, fg=GRAY)
        self._sel_count.pack(anchor="w", pady=(2, 12))

        # ══ [왼쪽] 검색 ═══════════════════════════════════════════
        tk.Label(left, text="이름 검색  (내 담당 학생만 표시)", font=FB,
                 bg=BG, fg=DARK).pack(anchor="w")

        search_row = tk.Frame(left, bg=BG)
        search_row.pack(fill="x", pady=(4, 0))
        self._kw_var = tk.StringVar()
        self._kw_var.trace_add("write", self._on_kw_change)
        tk.Entry(search_row, textvariable=self._kw_var,
                 font=F, width=28, relief="flat", bd=0,
                 bg=WHITE, fg=DARK,
                 highlightthickness=1,
                 highlightbackground=BORDER,
                 highlightcolor=YELLOW).pack(side="left", ipady=7, padx=(0, 8))
        tk.Button(search_row, text="전체 선택", font=FS,
                  bg=LGRAY, fg=DARK, relief="flat", bd=0,
                  cursor="hand2", padx=8, pady=5,
                  command=self._select_all_results).pack(side="left")
        tk.Button(search_row, text="그룹 확인", font=FS,
                  bg=LGRAY, fg=DARK, relief="flat", bd=0,
                  cursor="hand2", padx=8, pady=5,
                  command=self._on_view_groups).pack(side="left", padx=(6, 0))

        list_box = tk.Frame(left, bg=WHITE, highlightthickness=1,
                            highlightbackground=BORDER)
        list_box.pack(fill="both", expand=True, pady=(6, 4))

        self._canvas = tk.Canvas(list_box, bg=WHITE, highlightthickness=0)
        sb = ttk.Scrollbar(list_box, orient="vertical",
                           command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._list_frame = tk.Frame(self._canvas, bg=WHITE)
        self._cwin = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw")
        self._list_frame.bind("<Configure>", self._on_list_cfg)

        self._hint = tk.Label(left, text="", font=FS, bg=BG, fg=GRAY)
        self._hint.pack(anchor="w", pady=(2, 4))

        self._login_btn = tk.Button(
            left, text="카카오 로그인", font=FB,
            bg=YELLOW, fg=DARK, relief="flat", bd=0,
            width=22, height=1, cursor="hand2",
            command=self._on_login_click,
        )
        self._login_btn.bind("<Enter>", lambda e: self._login_btn.config(bg=Y_HOV))
        self._login_btn.bind("<Leave>", lambda e: self._login_btn.config(bg=YELLOW))
        # 처음엔 숨김 — 세션 없을 때만 표시
        self._login_btn_visible = False

        # ══ [왼쪽] 메시지 ═════════════════════════════════════════
        tk.Label(left, text="메시지 내용", font=FB, bg=BG, fg=DARK).pack(anchor="w")
        self._msg = tk.Text(left, font=F, width=38, height=4,
                            relief="flat", bd=0, bg=WHITE, fg=DARK,
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=YELLOW, wrap="word")
        self._msg.pack(anchor="w", pady=(4, 10))

        # ══ [왼쪽] 예약 전송 체크박스 + 날짜/시간 ═════════════════
        sched_row = tk.Frame(left, bg=BG)
        sched_row.pack(fill="x", pady=(0, 6))

        self._sched_var = tk.BooleanVar()
        tk.Checkbutton(sched_row, text="예약 전송", variable=self._sched_var,
                       font=F, bg=BG, activebackground=BG,
                       command=self._toggle_sched).pack(side="left")

        self._date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self._time_var = tk.StringVar(
            value=(datetime.now() + timedelta(minutes=5)).strftime("%H:%M"))

        self._lbl_date = tk.Label(sched_row, text="날짜", font=FS, bg=BG, fg=GRAY)
        self._ent_date = tk.Entry(sched_row, textvariable=self._date_var,
                                  font=F, width=11, relief="flat", bd=0,
                                  bg=WHITE, fg=DARK,
                                  highlightthickness=1, highlightbackground=BORDER)
        self._lbl_time = tk.Label(sched_row, text="시간", font=FS, bg=BG, fg=GRAY)
        self._ent_time = tk.Entry(sched_row, textvariable=self._time_var,
                                  font=F, width=6, relief="flat", bd=0,
                                  bg=WHITE, fg=DARK,
                                  highlightthickness=1, highlightbackground=BORDER)
        # ══ [왼쪽] 전송 버튼 ══════════════════════════════════════
        self._send_btn = tk.Button(left, text="전송", font=FB,
                                   bg=YELLOW, fg=DARK, relief="flat", bd=0,
                                   width=36, height=2, cursor="hand2",
                                   command=self._on_send)
        self._send_btn.pack(anchor="w", pady=(2, 8))
        self._send_btn.bind("<Enter>", lambda e: self._send_btn.config(bg=Y_HOV))
        self._send_btn.bind("<Leave>", lambda e: self._send_btn.config(bg=YELLOW))

        self._status = tk.Label(left, text="", font=FS, bg=BG, fg=GRAY)
        self._status.pack(anchor="w")

        # ══ [오른쪽] 예약 확인 ════════════════════════════════════
        tk.Label(right, text="예약 확인", font=FB, bg=BG, fg=DARK
                 ).pack(anchor="w", pady=(0, 8))

        self._sched_list_frame = tk.Frame(right, bg=BG)
        self._sched_list_frame.pack(fill="both", expand=True)

        self._sched_empty = tk.Label(self._sched_list_frame,
                                     text="예약된 전송 없음",
                                     font=FS, bg=BG, fg=GRAY)
        self._sched_empty.pack(anchor="w")

    # ── 마우스휠 ─────────────────────────────────────────────────
    def _on_wheel(self, event):
        w = event.widget
        while w is not None:
            if w is self._chip_canvas or w is self._chip_inner:
                self._chip_canvas.yview_scroll(-1 * (event.delta // 120), "units")
                return
            w = getattr(w, "master", None)
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_list_cfg(self, _=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.itemconfig(self._cwin, width=self._canvas.winfo_width())

    # ── 검색 ─────────────────────────────────────────────────────
    def _on_kw_change(self, *_):
        if self._search_after:
            self.after_cancel(self._search_after)
        kw = self._kw_var.get().strip()
        if not kw:
            self._render_results([])
            my_name = self._name_map.get(self._my_id, "")
            self._hint.config(
                text=f"담당: {my_name}  |  이름 검색으로 내 학생 찾기" if my_name else "",
                fg=GRAY)
            return
        self._hint.config(text="검색 중...", fg=GRAY)
        self._search_after = self.after(
            350, lambda: threading.Thread(
                target=self._search_thread, args=(kw,), daemon=True).start())

    def _search_thread(self, kw):
        results = _kakao_search(kw, self._session, self._my_id)
        self.after(0, lambda: self._render_results(results))
        n = len(results)
        my_name = self._name_map.get(self._my_id, "")
        suffix = f"  (담당: {my_name})" if my_name else ""
        msg = f"{n}명{suffix}" if n else f"검색 결과 없음{suffix}"
        self.after(0, lambda: self._hint.config(text=msg, fg=GRAY))

    def _render_results(self, results):
        self._results = results
        self._result_vars.clear()
        for w in self._list_frame.winfo_children():
            w.destroy()

        selected_names = {s["name"] for s in self._selected}
        for r in results:
            var = tk.BooleanVar(value=r["name"] in selected_names)
            self._result_vars.append(var)

            row = tk.Frame(self._list_frame, bg=WHITE)
            row.pack(fill="x", padx=6, pady=1)

            assignee_name = self._name_map.get(r.get("assignee_id"), "")
            cb = tk.Checkbutton(row, text=r["name"], variable=var,
                                font=F, bg=WHITE, activebackground=WHITE,
                                anchor="w",
                                command=lambda v=var, item=r: self._on_check(v, item))
            cb.pack(side="left")

            if assignee_name:
                tk.Label(row, text=assignee_name, font=FS,
                         bg=WHITE, fg=BLUE).pack(side="right", padx=4)

    def _select_all_results(self):
        for var, r in zip(self._result_vars, self._results):
            var.set(True)
            self._add_selected(r)

    def _on_check(self, var: tk.BooleanVar, item: dict):
        if var.get():
            self._add_selected(item)
        else:
            self._remove_selected(item["name"])

    # ── 전송 대상 관리 ────────────────────────────────────────────
    def _add_selected(self, item: dict):
        if any(s["name"] == item["name"] for s in self._selected):
            return
        self._selected.append(item)
        self._refresh_chips()

    def _remove_selected(self, name: str):
        self._selected = [s for s in self._selected if s["name"] != name]
        # 검색 결과에서 체크 해제
        for var, r in zip(self._result_vars, self._results):
            if r["name"] == name:
                var.set(False)
        self._refresh_chips()

    def _clear_selected(self):
        self._selected.clear()
        for var in self._result_vars:
            var.set(False)
        self._refresh_chips()

    def _on_chip_canvas_cfg(self, event):
        self._chip_canvas.itemconfig(self._chip_cwin_id, width=event.width)
        if getattr(self, "_chip_canvas_last_w", 0) != event.width:
            self._chip_canvas_last_w = event.width
            self.after(1, self._refresh_chips)

    def _on_chip_inner_cfg(self, event):
        self._chip_canvas.configure(scrollregion=self._chip_canvas.bbox("all"))
        inner_h = self._chip_inner.winfo_reqheight()
        self._chip_canvas.config(height=max(30, min(inner_h + 4, 108)))

    def _refresh_chips(self):
        for w in self._chip_inner.winfo_children():
            w.destroy()

        if not self._selected:
            tk.Label(self._chip_inner, text="선택된 학생 없음",
                     font=FS, bg=LGRAY, fg=GRAY).place(x=0, y=4)
            self._chip_inner.config(height=30)
            self._sel_count.config(text="")
            return

        avail = self._chip_canvas.winfo_width()
        if avail <= 10:
            avail = 310

        # 칩 생성 후 place로 배치 (동적 줄바꿈)
        chip_list = []
        for s in self._selected:
            chip = tk.Frame(self._chip_inner, bg=CHIP,
                            highlightthickness=1, highlightbackground=CHIP_B)
            tk.Label(chip, text=s["name"], font=FSB,
                     bg=CHIP, fg=DARK, padx=6, pady=2).pack(side="left")
            tk.Button(chip, text="×", font=FS, bg=CHIP, fg=GRAY,
                      relief="flat", bd=0, cursor="hand2", padx=2,
                      command=lambda n=s["name"]: self._remove_selected(n)
                      ).pack(side="left")
            chip_list.append(chip)

        self._chip_inner.update_idletasks()
        x, y, row_h = 0, 0, 0
        for chip in chip_list:
            cw = chip.winfo_reqwidth()
            ch = chip.winfo_reqheight()
            if x > 0 and x + cw + 3 > avail:
                x = 0
                y += row_h + 3
                row_h = 0
            chip.place(x=x, y=y)
            x += cw + 3
            row_h = max(row_h, ch)

        self._chip_inner.config(height=y + row_h + 6)
        self._sel_count.config(text=f"총 {len(self._selected)}명 선택됨", fg=DARK)

    # ── 예약 토글 ─────────────────────────────────────────────────
    def _toggle_sched(self):
        if self._sched_var.get():
            self._lbl_date.pack(side="left", padx=(12, 4))
            self._ent_date.pack(side="left", ipady=5, padx=(0, 10))
            self._lbl_time.pack(side="left", padx=(0, 4))
            self._ent_time.pack(side="left", ipady=5)
            self._send_btn.config(text="예약 등록")
        else:
            self._lbl_date.pack_forget()
            self._ent_date.pack_forget()
            self._lbl_time.pack_forget()
            self._ent_time.pack_forget()
            self._send_btn.config(text="전송")

    # ── 전송 ─────────────────────────────────────────────────────
    def _on_send(self):
        if not self._selected:
            messagebox.showwarning("선택 필요", "전송 대상을 선택하세요.")
            return
        msg = self._msg.get("1.0", "end").strip()
        if not msg:
            messagebox.showwarning("입력 필요", "메시지를 입력하세요.")
            return
        if self._sched_var.get():
            self._register_sched(list(self._selected), msg)
        else:
            self._start_send(list(self._selected), msg)

    def _register_sched(self, targets, msg):
        try:
            dt = datetime.strptime(
                f"{self._date_var.get()} {self._time_var.get()}", "%Y-%m-%d %H:%M")
        except ValueError:
            messagebox.showerror("형식 오류", "날짜: YYYY-MM-DD  시간: HH:MM")
            return
        delay = (dt - datetime.now()).total_seconds()
        if delay <= 0:
            messagebox.showerror("시간 오류", "현재 시각 이후로 설정하세요.")
            return

        names = ", ".join(t["name"] for t in targets)
        label = f"⏰ {dt.strftime('%m/%d %H:%M')} — {names}"

        # 예약 큐에 추가 (버튼은 계속 활성)
        job_id = id(targets)
        self._sched_jobs[job_id] = {"label": label, "msg": msg, "cancelled": False}
        self._refresh_sched_list()

        def _wait():
            time.sleep(delay)
            if self._sched_jobs.get(job_id, {}).get("cancelled"):
                self._sched_jobs.pop(job_id, None)
                return
            self._sched_jobs.pop(job_id, None)
            self.after(0, self._refresh_sched_list)
            self._start_send(targets, msg)

        threading.Thread(target=_wait, daemon=True).start()

        # 예약 후 체크박스 해제
        self._sched_var.set(False)
        self._toggle_sched()

    def _cancel_sched(self, job_id):
        if job_id in self._sched_jobs:
            self._sched_jobs[job_id]["cancelled"] = True
            # pop 하지 않음 — 대기 스레드가 플래그 확인 후 직접 제거
            self._refresh_sched_list()

    def _refresh_sched_list(self):
        for w in self._sched_list_frame.winfo_children():
            w.destroy()
        active = {jid: job for jid, job in self._sched_jobs.items()
                  if not job.get("cancelled")}
        if not active:
            tk.Label(self._sched_list_frame, text="예약된 전송 없음",
                     font=FS, bg=BG, fg=GRAY).pack(anchor="w")
            return
        for job_id, job in list(active.items()):
            card = tk.Frame(self._sched_list_frame, bg=CHIP,
                            highlightthickness=1, highlightbackground=CHIP_B)
            card.pack(fill="x", pady=(0, 6))
            tk.Label(card, text=job["label"], font=FS, bg=CHIP, fg=DARK,
                     wraplength=170, justify="left",
                     padx=8, pady=(6, 2)).pack(anchor="w")
            msg_txt = job.get("msg", "")
            if msg_txt:
                preview = msg_txt[:40] + ("…" if len(msg_txt) > 40 else "")
                tk.Label(card, text=f"💬 {preview}", font=FS, bg=CHIP, fg=GRAY,
                         wraplength=170, justify="left",
                         padx=8, pady=(0, 4)).pack(anchor="w")
            tk.Button(card, text="취소", font=FS, bg=CHIP, fg=RED,
                      relief="flat", bd=0, cursor="hand2", padx=8, pady=3,
                      command=lambda jid=job_id: self._cancel_sched(jid)
                      ).pack(anchor="e", padx=6, pady=(0, 4))

    def _start_send(self, targets, msg):
        # 버튼은 건드리지 않고 상태만 표시
        self._status.config(
            text=f"전송 중: {len(targets)}명 (백그라운드)...", fg=GRAY)
        threading.Thread(target=self._send_thread,
                         args=(targets, msg), daemon=True).start()

    def _send_thread(self, targets, msg):
        ok_list  = []
        fail_map = {}   # name → reason
        total    = len(targets)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(send_message, t["name"], msg): t["name"]
                       for t in targets}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    ok, reason = future.result()
                except Exception as e:
                    ok, reason = False, str(e)
                if ok:
                    ok_list.append(name)
                else:
                    fail_map[name] = reason
                done = len(ok_list) + len(fail_map)
                self.after(0, lambda d=done, n=total:
                           self._status.config(
                               text=f"전송 중... {d}/{n}명", fg=GRAY))

        def _done():
            parts = []
            if ok_list:
                parts.append(f"✓ {len(ok_list)}명 완료")
            if fail_map:
                detail = "\n".join(f"  {n}: {r}" for n, r in fail_map.items())
                parts.append(f"✗ {len(fail_map)}명 실패")
                self._status.config(text="  ".join(parts), fg=RED)

                # 추가인증 만료 여부 확인
                needs_auth = any(r == "추가인증 만료" for r in fail_map.values())
                if needs_auth:
                    messagebox.showwarning(
                        "관리자 추가인증 필요",
                        "카카오비즈니스 관리자 추가인증이 만료되었습니다.\n\n"
                        "해결 방법:\n"
                        "1. Chrome에서 business.kakao.com 접속\n"
                        "2. 채팅 목록 페이지에서\n"
                        "   '관리자 추가인증' 버튼 클릭\n"
                        "3. 휴대전화 인증 완료\n"
                        "4. 이 앱에서 '카카오 로그인' 버튼 클릭\n\n"
                        "인증 완료 후 다시 전송해 주세요.",
                    )
                    self.after(0, self._show_login_btn)
                else:
                    log_path = SESSION_FILE.parent / "send_error.log"
                    messagebox.showerror(
                        "전송 실패",
                        f"다음 학생 전송 실패:\n{detail}\n\n"
                        f"로그 파일: {log_path}",
                    )
            else:
                self._status.config(text="  ".join(parts), fg=GREEN)
        self.after(0, _done)

    # ── 그룹 ─────────────────────────────────────────────────────
    def _on_create_group(self):
        if not self._selected:
            messagebox.showwarning("선택 필요", "그룹으로 저장할 학생을 먼저 선택하세요.")
            return
        from tkinter.simpledialog import askstring
        name = askstring("그룹 생성", "그룹 이름을 입력하세요:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        groups = _load_groups()
        groups[name] = list(self._selected)
        _save_groups(groups)
        messagebox.showinfo("저장 완료", f"'{name}' 그룹 저장됨  ({len(self._selected)}명)")

    def _on_view_groups(self):
        win = tk.Toplevel(self)
        win.title("그룹 관리")
        win.configure(bg=BG)
        win.resizable(True, True)
        win.minsize(400, 300)
        # non-modal: no grab_set()

        outer = tk.Frame(win, bg=BG, padx=16, pady=12)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="그룹 관리", font=FH, bg=BG, fg=DARK
                 ).pack(anchor="w", pady=(0, 10))

        scroll_area = tk.Frame(outer, bg=BG)
        scroll_area.pack(fill="both", expand=True)

        canv = tk.Canvas(scroll_area, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_area, orient="vertical", command=canv.yview)
        canv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canv.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canv, bg=BG)
        cwin_id = canv.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>",
                     lambda e: canv.configure(scrollregion=canv.bbox("all")))
        canv.bind("<Configure>",
                  lambda e: canv.itemconfig(cwin_id, width=e.width))

        def _on_wheel(ev):
            canv.yview_scroll(-1 * (ev.delta // 120), "units")
        win.bind("<MouseWheel>", _on_wheel)

        def _refresh():
            for w in content.winfo_children():
                w.destroy()
            grps = _load_groups()
            if not grps:
                tk.Label(content, text="저장된 그룹이 없습니다.\n학생 선택 후 '그룹 생성'으로 만들어 보세요.",
                         font=FS, bg=BG, fg=GRAY,
                         justify="left").pack(anchor="w", padx=4, pady=8)
                return

            for gname, members in grps.items():
                card = tk.Frame(content, bg=CHIP,
                                highlightthickness=1, highlightbackground=CHIP_B)
                card.pack(fill="x", pady=(0, 10), padx=2)

                # ── 헤더: 그룹명 + 인원수 + 그룹 삭제 ──
                hdr = tk.Frame(card, bg=CHIP)
                hdr.pack(fill="x", padx=10, pady=(8, 4))
                tk.Label(hdr, text=gname, font=FB, bg=CHIP, fg=DARK).pack(side="left")
                tk.Label(hdr, text=f"({len(members)}명)", font=FS,
                         bg=CHIP, fg=GRAY).pack(side="left", padx=4)

                def _make_del(g=gname):
                    def _del():
                        if messagebox.askyesno("삭제 확인",
                                               f"'{g}' 그룹을 삭제할까요?", parent=win):
                            grps2 = _load_groups()
                            grps2.pop(g, None)
                            _save_groups(grps2)
                            _refresh()
                    return _del

                tk.Button(hdr, text="그룹 삭제", font=FS,
                          bg=LGRAY, fg=RED, relief="flat", bd=0,
                          cursor="hand2", padx=8, pady=2,
                          command=_make_del()).pack(side="right")

                # ── 멤버 목록 (이름 + 개별 삭제) ──
                if members:
                    sep = tk.Frame(card, bg=BORDER, height=1)
                    sep.pack(fill="x", padx=10, pady=(0, 4))

                    for m in members:
                        mrow = tk.Frame(card, bg=CHIP)
                        mrow.pack(fill="x", padx=10, pady=1)
                        tk.Label(mrow, text="•  " + m["name"], font=F,
                                 bg=CHIP, fg=DARK).pack(side="left")

                        def _make_rm(g=gname, mn=m["name"]):
                            def _rm():
                                grps2 = _load_groups()
                                if g in grps2:
                                    grps2[g] = [x for x in grps2[g]
                                                if x["name"] != mn]
                                    _save_groups(grps2)
                                _refresh()
                            return _rm

                        tk.Button(mrow, text="삭제", font=FS,
                                  bg=CHIP, fg=RED, relief="flat", bd=0,
                                  cursor="hand2", padx=6, pady=0,
                                  command=_make_rm()).pack(side="left", padx=(6, 0))
                else:
                    tk.Label(card, text="(멤버 없음)", font=FS,
                             bg=CHIP, fg=GRAY, padx=10).pack(anchor="w", pady=(0, 4))

                # ── 액션 버튼 ──
                btn_row = tk.Frame(card, bg=CHIP)
                btn_row.pack(fill="x", padx=10, pady=(6, 8))

                def _make_load_all(g=gname):
                    def _load_all():
                        for m in _load_groups().get(g, []):
                            self._add_selected(m)
                    return _load_all

                def _make_add_sel(g=gname):
                    def _add_sel():
                        if not self._selected:
                            messagebox.showwarning("선택 필요",
                                "메인 창에서 학생을 먼저 선택하세요.", parent=win)
                            return
                        grps2 = _load_groups()
                        existing = {x["name"] for x in grps2.get(g, [])}
                        added = 0
                        for s in self._selected:
                            if s["name"] not in existing:
                                grps2.setdefault(g, []).append(s)
                                existing.add(s["name"])
                                added += 1
                        _save_groups(grps2)
                        _refresh()
                        if added:
                            messagebox.showinfo("추가 완료",
                                f"'{g}' 그룹에 {added}명 추가됐습니다.", parent=win)
                        else:
                            messagebox.showinfo("이미 포함",
                                "선택된 학생이 이미 모두 그룹에 있습니다.", parent=win)
                    return _add_sel

                tk.Button(btn_row, text="전체 선택에 추가", font=FS,
                          bg=YELLOW, fg=DARK, relief="flat", bd=0,
                          cursor="hand2", padx=10, pady=3,
                          command=_make_load_all()).pack(side="left")
                tk.Button(btn_row, text="현재 선택에서 추가", font=FS,
                          bg=LGRAY, fg=DARK, relief="flat", bd=0,
                          cursor="hand2", padx=8, pady=3,
                          command=_make_add_sel()).pack(side="left", padx=(6, 0))

        _refresh()

        tk.Button(outer, text="닫기", font=F, bg=LGRAY, fg=DARK,
                  relief="flat", bd=0, cursor="hand2", padx=16, pady=5,
                  command=win.destroy).pack(anchor="e", pady=(10, 0))

        win.update_idletasks()
        w = max(win.winfo_reqwidth(), 430)
        h = min(max(win.winfo_reqheight(), 300), 580)
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    # ── 로그인 ────────────────────────────────────────────────────
    def _show_login_btn(self):
        if not self._login_btn_visible:
            self._login_btn.pack(anchor="w", pady=(0, 10))
            self._login_btn_visible = True
            self._refit()

    def _hide_login_btn(self):
        if self._login_btn_visible:
            self._login_btn.pack_forget()
            self._login_btn_visible = False
            self._refit()

    def _on_login_click(self):
        self._login_btn.config(text="브라우저 열기...", state="disabled", bg=LGRAY)
        self._hint.config(
            text="로그인 후 '관리자 추가인증' 버튼도 클릭하여 인증을 완료해 주세요", fg=GRAY
        )
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _login_thread(self):
        try:
            ok = do_login()
        except Exception as e:
            _write_login_error(e)
            ok = False
            err_msg = f"로그인 오류: {type(e).__name__}: {str(e)[:120]}"
            self.after(0, lambda m=err_msg: self._hint.config(text=m, fg=RED))
        self.after(0, lambda: self._login_btn.config(
            text="카카오 로그인", state="normal", bg=YELLOW))
        if ok:
            self.after(0, lambda: self._hint.config(text="로그인 완료 — 세션 확인 중...", fg=GRAY))
            self.after(0, self._init_session)
        else:
            self.after(0, lambda: self._hint.config(
                text="로그인 실패 — 다시 시도해주세요", fg=RED))

    # ── 창 중앙 배치 ──────────────────────────────────────────────
    def _refit(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _center(self):
        self._refit()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    App().mainloop()
