# gui/main_window.py
"""主控窗口模块 — tkinter GUI

职责：
- 实时显示每条消息的处理结果
- 状态栏显示统计信息
- 「待人工」页列出置信度不足的消息 + AI 推荐回复，可选择直接发送或编辑后发送
- 支持导出记录为 CSV

分流为二档（见 rag/responder.py）：分数够就直发，否则转人工、自动回一句
占位语，并把 AI 草稿放进「待人工」等你处理。
"""

import csv
import ctypes
import logging
import os
import tkinter as tk
from datetime import datetime
from time import monotonic
from tkinter import ttk, messagebox
from typing import Callable, Dict, List, Optional

from app_version import APP_VERSION, version_label
from gui.theme import SPACE, apply_theme, px, ui_icon
from gui.workbench_theme import COLORS, apply_workbench_theme, font

logger = logging.getLogger(__name__)


# ── 窗口置顶（可在界面底部一键切，写回 config.json）──────────────────────
#
# 2026-10-06 店主反馈："软件好像强制置顶在所有页面前面了，可以改吗"。
# 原来是硬编码 `self.root.attributes('-topmost', True)` —— 没开关、没注释、
# 想不置顶只能改代码。置顶对"盯着待人工"有用，但一直压着别的窗口很烦，
# 所以：**默认不置顶**，底部一个勾选框随时切。
#
# 抽成模块级函数是为了能单测（写配置这件事很容易写错，
# 而写错的后果是"界面显示置顶、其实没生效"或者反过来）。

def always_on_top_enabled() -> bool:
    """读窗口置顶开关。**默认 False** —— 不主动压别人的窗口。"""
    try:
        from config.settings_store import load_config
        return bool((load_config() or {}).get("ui", {}).get("always_on_top", False))
    except Exception:
        return False


def set_always_on_top(want: bool) -> None:
    """把置顶开关写回 config.json（重启也记得）。"""
    from config.settings_store import load_config, save_config
    cfg = load_config() or {}
    cfg.setdefault("ui", {})["always_on_top"] = bool(want)
    save_config(cfg)


# ── 「已回复」= 软件**发出去**的消息 ────────────────────────────────────
# 语义要写死在这里，别散落在过滤条件里：占位语、欢迎语都是真发出去的，
# 客户收到了它们 —— 只把 auto_send 算"已回复"是错的（2026-10-06 修）。
OUTBOUND_ACTIONS = frozenset({"replied", "auto_send", "hold", "greeting"})


def load_reply_history(path=None, limit: int = 500) -> List["MessageRecord"]:
    """从 `logs/auto_replies.jsonl` 读回"软件发过什么"。

    为什么需要：`self._records` 只在内存里，**一重启就全没了** —— 店主重启几次
    之后打开「已回复」是空的，会以为功能坏了（他确实这么反馈的："为什么全部和
    已回复不会有消息"）。而这个 jsonl 是落盘的，每次发送都写，所以直接从它读。

    返回**按时间先后**排的记录（跟 `add_record` 追加的顺序一致）；
    显示时由 `_refresh_list` 倒过来（最新在上）。
    文件没有/读不动就返回空列表（不抛）。
    """
    import json
    from pathlib import Path as _P
    p = _P(path) if path else _P("logs") / "auto_replies.jsonl"
    if not p.exists():
        return []
    out: List[MessageRecord] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if "sent" in row and row["sent"] is not True:
            continue
        sent = (row.get("learning_answer") or row.get("ai_reply") or "").strip()
        if not sent:
            continue                      # 没发出去的不算"已回复"
        ts = str(row.get("timestamp") or "")
        # 2026-09-22T14:57:03 → 09-22 14:57（**带日期**：历史跨很多天，
        # 光看 HH:MM 根本不知道是哪天发的）
        hhmm = (ts[5:10] + " " + ts[11:16]) if len(ts) >= 16 else ts[:5]
        level = row.get("dispatch_level") or ""
        action = "hold" if "占位" in str(row.get("guard_reason") or "") else "replied"
        if level == "no_reply":
            continue
        out.append(MessageRecord(
            hhmm, row.get("customer_name") or "客户", sent, action, sent,
            question=row.get("learning_question") or row.get("customer_message", ""),
            record_id=row.get("record_id", ""),
            archive=row.get("archive", ""), source=row.get("source", ""),
            draft=row.get("draft", ""),
        ))
    return out


class MessageRecord:
    """消息记录"""

    def __init__(self, timestamp: str, customer: str, message: str,
                 action: str, reply: str = "", *, question: str = "",
                 record_id: str = "", archive: str = "", source: str = "", draft: str = ""):
        self.timestamp = timestamp
        self.customer = customer
        self.message = message
        self.action = action
        self.reply = reply
        self.question = question
        self.record_id = record_id
        self.archive = archive
        self.source = source
        self.draft = draft

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "customer": self.customer,
            "message": self.message,
            "action": self.action,
            "reply": self.reply,
            "question": self.question,
            "record_id": self.record_id,
            "archive": self.archive,
            "source": self.source,
            "draft": self.draft,
        }


def _animations_enabled() -> bool:
    """Read the Windows animation preference (SPI_GETCLIENTAREAANIMATION)."""
    if os.name != "nt":
        return True
    enabled = ctypes.c_int()
    success = ctypes.windll.user32.SystemParametersInfoW(
        0x1042, 0, ctypes.byref(enabled), 0)
    return bool(success and enabled.value)


class MainWindow:
    """主控窗口"""
    def __init__(self, on_pause: Callable = None, on_resume: Callable = None,
                 on_settings: Callable = None, on_kb: Callable = None,
                 on_dashboard: Callable = None, can_start: Callable = None,
                 web_mode: bool = False):
        self._web_mode = web_mode
        self.on_pause = on_pause
        self.on_resume = on_resume
        # 「设置」常驻侧栏底部，任何状态都能点开重配。
        self.on_settings = on_settings
        # 「知识库」：编辑提示词 / 管理资料库（常驻，任何时候可点）
        self.on_kb = on_kb
        # 「数据」：运营看板（今日/近7天/自定义；我该补什么资料）
        self.on_dashboard = on_dashboard
        # ★ 「能不能开始」的守卫（由 main.py 注入）：返回 (是否允许, 原因)。
        #   没配模型接口时不许开始 —— 否则机器人答不了业务问题，却照样回客户
        #   "稍等，我帮您确认一下"；没人处理「待人工」就等于替店主许了个空头承诺。
        self.can_start = can_start
        # ★ 「已回复」列表的初始内容从落盘日志读回来（最新在前）。
        #   原来这里只是个空列表，**重启就清空** —— 店主重启几次后打开
        #   「已回复」什么都没有，以为功能坏了（"为什么全部和已回复不会有消息"）。
        #   读不动就当空表，不影响启动。
        try:
            self._records: List[MessageRecord] = load_reply_history()
        except Exception:
            self._records = []
        # 默认**未启动**：打开程序不会自动开始扫描/回复，先让用户确认配置再点「开始」。
        # 已有的暂停机制本来就同时挡住两条通道（截图扫描与 API 轮询），所以直接复用。
        # 想开机就跑（或脚本化启动）：设环境变量 WECOM_AUTOSTART=1。
        import os as _os
        self._autostart = _os.getenv("WECOM_AUTOSTART", "0").strip() == "1"
        if self._autostart and not self._start_allowed()[0]:
            # 没配好就不许偷偷跑起来（脚本化启动也一样）
            self._autostart = False
        self._paused = not self._autostart
        self._should_exit = False

        # 待人工页的动作回调（由 main.py 注册）
        self._on_pending_send: Optional[Callable] = None
        self._on_pending_edit: Optional[Callable] = None
        self._on_pending_ignore: Optional[Callable] = None
        self._on_get_reply: Optional[Callable] = None

        # Stats：只统计真实会发生的两种结果
        #   replied   = 已发给客户（含直发和转人工时的占位语）
        #   escalated = 转人工（同时在待人工页可见）
        self._stats = {
            "replied": 0,
            "escalated": 0,
        }

        # Create window
        self._create_window()

    def _create_window(self):
        """创建窗口"""
        self.root = tk.Tk()
        build = version_label()
        self.root.title(f"企业微信智能客服 {build}")
        logger.info("运行版本 %s", build)
        self.root.withdraw()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 置顶由配置决定（默认不置顶）—— 以前这里硬编码 True，想关只能改代码。
        # 底部「窗口置顶」勾选框可以随时切，见 _create_footer / _toggle_topmost。
        self.root.attributes('-topmost', always_on_top_enabled())
        # ★ 最小尺寸：以前没设，用户可以把窗口拖到 600px 以下，
        #   那时横幅、标签页、表格会互相盖住（用户反馈改窗口大小就盖住按钮）
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ★ 先把设计系统装上（ttk 样式必须在创建控件之前生效）
        apply_theme(self.root)
        apply_workbench_theme(self.root)
        self.root.minsize(min(px(920), sw - px(32)), min(px(540), sh - px(96)))
        # 窗口被拖动改大小 → 重排头部 + 表格列按比例（防抖，见 _on_root_configure）
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.configure(background=COLORS["canvas_soft"])

        self._shell = tk.Frame(self.root, background=COLORS["hairline"])
        self._shell.pack(fill=tk.BOTH, expand=True)
        self._content = tk.Frame(self._shell, background=COLORS["canvas_soft"])
        self._create_navigation()
        self._create_header()
        self._create_banner()
        self._create_footer()

        self._page_host = tk.Frame(self._content, background=COLORS["canvas_soft"])
        self._page_host.pack(fill=tk.BOTH, expand=True)
        workbench = tk.Frame(self._page_host, background=COLORS["canvas_soft"])
        self._create_tabs(workbench)
        workbench.pack(fill=tk.BOTH, expand=True)
        self._page_frames = {"工作台": workbench}
        self._page_views = {}
        self._current_page = "工作台"

        self._fit_window(sw)
        if not self._web_mode:
            self.root.deiconify()

    def _fit_window(self, screen_w):
        w = min(px(1180), screen_w - px(32))
        sh = self.root.winfo_screenheight()
        h = min(px(760), sh - px(96))
        x, y = (screen_w - w) // 2, (sh - h) // 4
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._layout_shell(w)

    def _layout_shell(self, width):
        """Keep navigation and service controls at the left at every window size."""
        compact = width < px(970)
        if compact == getattr(self, "_compact_navigation", None):
            return
        self._compact_navigation = compact
        self._shell.grid_columnconfigure(0, weight=0)
        self._shell.grid_columnconfigure(1, weight=1)
        self._shell.grid_rowconfigure(0, weight=1)
        self._sidebar.configure(width=px(176 if compact else 208))
        self._sidebar.pack_propagate(False)
        self._sidebar.grid(row=0, column=0, sticky="ns")
        self._content.grid(row=0, column=1, sticky="nsew")

    def _on_root_configure(self, event=None):
        """窗口被拖动改大小 → 防抖后重排头部 + 按比例分表格列。"""
        if event is not None and event.widget is not self.root:
            return
        if getattr(self, "_resize_job", None):
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(150, self._after_resize)

    def _after_resize(self):
        self._resize_job = None
        self._layout_shell(self.root.winfo_width())
        self._fit_tree_columns()
        self._fit_banner()

    def _fit_banner(self):
        """横幅文字按窗口宽度换行 —— 单行不换行时右边会被硬切（"…或点「设置」改配"）。"""
        try:
            w = self._content.winfo_width()
            if w > 1:
                self._banner.configure(wraplength=max(px(240), w - px(36)))
        except Exception:
            pass

    def _fit_tree_columns(self):
        """表格列宽按窗口宽度**按比例**分配（写死宽度在窄窗口下会把最后一列挤掉）。"""
        try:
            w = self._list_frame.winfo_width()
        except Exception:
            return
        if w > 1:
            for cid, ratio, minw in (("time", 0.13, px(64)), ("customer", 0.20, px(90)),
                                     ("message", 0.43, px(140)), ("action", 0.24, px(90))):
                self._tree.column(cid, width=max(minw, int(w * ratio)))
        if hasattr(self, "_queue_panel"):
            available = self._pending_frame.winfo_width()
            self._queue_panel.configure(width=max(px(250), min(px(340), int(available * .36))))
            self._pending_tree.column("#0", width=max(px(220), self._queue_panel.winfo_width() - px(24)))

    def _create_header(self):
        toolbar = tk.Frame(self._content, background=COLORS["canvas"])
        toolbar.pack(fill=tk.X)
        tk.Frame(toolbar, height=1, background=COLORS["hairline"]).pack(side=tk.BOTTOM, fill=tk.X)
        self._title_label = tk.Label(toolbar, text="工作台", font=font("h1"),
                                     background=COLORS["canvas"], foreground=COLORS["ink"])
        self._title_label.pack(side=tk.LEFT, padx=px(24), pady=px(24))
        ttk.Button(toolbar, text="打开新版工作台", style="Workbench.Primary.TButton",
                   command=self._open_web_workbench).pack(side=tk.RIGHT, padx=px(20))
        self._status_label = tk.Label(
            toolbar, text="状态：运行中" if self._autostart else "状态：未启动",
            font=font("small", True), padx=px(12), pady=px(6))
        self._status_label.bind("<Destroy>", lambda event: self._cancel_animation(event.widget))
        self._status_label.pack(side=tk.RIGHT, padx=px(28))
        self._paint_service_status(animate=False)

    def _paint_service_status(self, animate=True):
        running = not self._paused
        background = COLORS["success_bg" if running else "canvas_sunken"]
        foreground = COLORS["success" if running else "ink_mute"]
        self._status_label.configure(background=background, foreground=foreground)
        if animate and running and _animations_enabled():
            self._animate_color(self._status_label, COLORS["primary_subtle"], background)
        else:
            self._cancel_animation(self._status_label)

    @staticmethod
    def _cancel_animation(widget):
        job = getattr(widget, "_animation_job", None)
        if job is not None:
            widget.after_cancel(job)
            widget._animation_job = None

    def _animate_color(self, widget, start, end):
        def channels(color):
            return tuple(value // 257 for value in widget.winfo_rgb(color))

        initial, final = channels(start), channels(end)

        def frame(progress):
            rgb = tuple(round(a + (b - a) * progress) for a, b in zip(initial, final))
            widget.configure(background="#%02x%02x%02x" % rgb)

        self._animate(widget, frame)

    def _animate(self, widget, draw):
        self._cancel_animation(widget)

        started = monotonic()

        def step():
            widget._animation_job = None
            progress = min(1.0, (monotonic() - started) / 0.16)
            draw(1 - (1 - progress) ** 3)
            if progress < 1:
                widget._animation_job = widget.after(16, step)

        step()

    def _move_navigation_marker(self, page, animate=True):
        marker = self._navigation_marker
        button = self._navigation[page]
        end = button.winfo_y() + (button.winfo_height() - px(18)) // 2
        start = marker.winfo_y() if marker.winfo_ismapped() else end

        def draw(progress):
            marker.place(x=px(15), y=round(start + (end - start) * progress),
                         width=px(2), height=px(18))

        if animate and start != end and _animations_enabled():
            self._animate(marker, draw)
        else:
            self._cancel_animation(marker)
            draw(1)

    def _create_navigation(self):
        self._sidebar = tk.Frame(self._shell, background=COLORS["sidebar"])
        self._brand = tk.Frame(self._sidebar, background=COLORS["sidebar"])
        self._brand.pack(fill=tk.X, padx=px(18), pady=(px(23), px(28)))
        self._brand_icon = ui_icon(self.root, "conversation", 24, color=COLORS["ink"])
        tk.Label(self._brand, image=self._brand_icon, background=COLORS["sidebar"]).pack(
            side=tk.LEFT, padx=(0, px(8)))
        tk.Label(self._brand, text="智能客服", font=font("h2", True),
                 background=COLORS["sidebar"], foreground=COLORS["ink"]).pack(side=tk.LEFT)
        # Pack bottom controls first so navigation never pushes them off screen.
        self._sidebar_bottom = tk.Frame(self._sidebar, background=COLORS["sidebar"])
        self._sidebar_bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=px(12), pady=px(16))
        self._run_icons = {name: ui_icon(self.root, name, color=COLORS["ink"])
                           for name in ("play", "stop")}
        self._pause_btn = ttk.Button(
            self._sidebar_bottom, text="停止" if self._autostart else "开始",
            image=self._run_icons["stop" if self._autostart else "play"], compound="left",
            style="Workbench.Service.TButton", command=self._toggle_pause)
        self._pause_btn.pack(fill=tk.X, pady=(0, px(12)))
        self._settings_icon = ui_icon(self.root, "settings", color=COLORS["ink_mute"])
        self._settings_btn = ttk.Button(
            self._sidebar_bottom, text="设置", image=self._settings_icon, compound="left",
            style="Workbench.Page.TButton", command=self._on_settings_clicked)
        self._settings_btn.pack(fill=tk.X)
        tk.Label(self._sidebar_bottom, text=f"v{APP_VERSION}", font=font("micro"),
                 background=COLORS["sidebar"], foreground=COLORS["ink_faint"]).pack(
                     anchor="w", padx=px(12), pady=(px(10), 0))
        self._navigation = {}
        self._navigation_icons = {}
        for name, glyph in (("工作台", "inbox"), ("数据", "chart"), ("知识库", "book")):
            icon = self._navigation_icons[name] = ui_icon(self.root, glyph, color=COLORS["ink_mute"])
            self._navigation[name] = ttk.Button(
                self._sidebar, text=f"  {name}", image=icon, compound="left",
                style="Workbench.PageOn.TButton" if name == "工作台" else "Workbench.Page.TButton",
                command=lambda page=name: self._show_page(page))
            self._navigation[name].pack(fill=tk.X, padx=px(12), pady=(0, px(4)))

        self._navigation_marker = tk.Frame(self._sidebar, background=COLORS["primary"])
        self._navigation_marker.lift()
        self._navigation_marker.bind("<Destroy>", lambda event: self._cancel_animation(event.widget))
        self._navigation["工作台"].bind("<Map>", self._position_initial_marker)

    def _position_initial_marker(self, event):
        event.widget.unbind("<Map>")
        self._move_navigation_marker(self._current_page, animate=False)

    def _show_page(self, name):
        if name == self._current_page:
            return
        existing = self._page_views.get(name)
        if name not in self._page_frames:
            factory = {"数据": self.on_dashboard, "知识库": self.on_kb}[name]
            if factory is None:
                return
            frame = tk.Frame(self._page_host, background=COLORS["canvas_soft"])
            view = factory(frame)
            if view is None:
                frame.destroy()
                return
            self._page_frames[name] = frame
            self._page_views[name] = view
        self._page_frames[self._current_page].pack_forget()
        self._page_frames[name].pack(fill=tk.BOTH, expand=True)
        self._current_page = name
        self._title_label.config(text="数据看板" if name == "数据" else name)
        for label, btn in self._navigation.items():
            btn.configure(style="Workbench.PageOn.TButton" if label == name else "Workbench.Page.TButton")
        self._move_navigation_marker(name)
        if existing is not None:
            self.root.after_idle(existing.on_show)
        self.root.after_idle(self._fit_tree_columns)

    def _on_settings_clicked(self):
        if self.on_settings:
            self.on_settings()

    def _open_web_workbench(self):
        from gui.web_workbench import open_workbench
        open_workbench(self)

    def _create_banner(self):
        """状态横幅：把"为什么现在不干活"直接写在界面上。

        原来的坑：目标软件没打开时扫描会静默 return，界面还写着"运行中"，
        用户完全不知道问题在哪。
        """
        self._banner = tk.Label(self._content, text="", anchor="w", justify="left",
                                wraplength=px(600),
                                font=font("small"), foreground=COLORS["warning"],
                                background=COLORS["warning_bg"],
                                padx=px(12), pady=px(10))

    def set_banner(self, text: str, level: str = "warn", *, blocks_start: bool = False):
        """更新横幅。level: warn=黄 / error=红 / ok=绿（空文本＝隐藏）。"""
        self._web_banner = {"text": text, "level": level}
        self._start_guard_banner = blocks_start
        colors = {
            "warn": (COLORS["warning_bg"], COLORS["warning"]),
            "error": (COLORS["danger_bg"], COLORS["danger"]),
            "ok": (COLORS["success_bg"], COLORS["success"]),
            "info": (COLORS["sidebar"], COLORS["ink_mute"]),
        }
        # Being idle is normal, not a warning. Keep actual fault messages coloured.
        if level == "warn" and text.startswith("未启动"):
            level = "info"
        bg, fg = colors.get(level, colors["warn"])
        try:
            if not text:
                self._banner.pack_forget()
                return
            self._banner.config(text=text, background=bg, foreground=fg)
            self._banner.pack(fill=tk.X, before=self._footer, padx=px(28),
                              pady=(0, px(4)))
        except Exception:
            pass

    def _create_status_bar(self, parent):
        """创建状态栏"""
        status_frame = tk.Frame(parent, background=COLORS["canvas"])
        status_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=SPACE["md"], pady=SPACE["xs"])

        self._stats_label = tk.Label(
            status_frame, text="已回复 0　待人工 0", font=font("small"),
            background=COLORS["canvas"], foreground=COLORS["ink_mute"])
        self._stats_label.pack(side=tk.LEFT)

    def _create_tabs(self, parent):
        """创建标签页"""
        tab_frame = tk.Frame(parent, background=COLORS["canvas_soft"])
        tab_frame.pack(fill=tk.BOTH, expand=True, padx=px(24), pady=(px(8), px(24)))

        # 标签栏
        tab_bar = tk.Frame(tab_frame, background=COLORS["canvas_soft"])
        tab_bar.pack(fill=tk.X, pady=(0, px(20)))

        ttk.Button(tab_bar, text="清空记录", style="Workbench.ToolbarDanger.TButton",
                   command=self._clear_records).pack(side=tk.RIGHT)
        ttk.Button(tab_bar, text="导出记录", style="Workbench.Toolbar.TButton",
                   command=self._export_csv).pack(side=tk.RIGHT, padx=(0, SPACE["sm"]))

        self._tab_buttons = {}
        # ★ 2026-10-06 店主："取消全部这一栏，只需要两个格子" ——
        #   ① 待人工（功能同原来，放第一个，默认打开）
        #   ② 已回复（**软件发出去的所有消息 + 时间**）
        #   原来的「全部」被去掉了：它和「已回复」在功能上重叠，
        #   而店主真正要看的就是"该我处理的有哪些"和"它替我发了什么"。
        tabs = ["待人工", "已回复"]
        for tab in tabs:
            btn = ttk.Button(
                tab_bar, text=tab, style="Workbench.Segment.TButton",
                command=lambda t=tab: self._switch_tab(t),
            )
            btn.pack(side=tk.LEFT, padx=(0, SPACE["xs"]))
            self._tab_buttons[tab] = btn

        self._current_tab = "待人工"
        # 初始化时也要点亮一次选中态，否则一进来两个标签看着都"没选中"
        for name, b in self._tab_buttons.items():
            b.configure(style="Workbench.SegmentOn.TButton" if name == self._current_tab
                        else "Workbench.Segment.TButton")

        body = tk.Frame(tab_frame, background=COLORS["canvas"],
                        highlightbackground=COLORS["hairline"], highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True)
        self._list_frame = ttk.Frame(body, style="Workbench.Card.TFrame")
        self._list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        columns = ("time", "customer", "message", "action")
        self._tree = ttk.Treeview(self._list_frame, columns=columns, show="headings", style="Workbench.Treeview")
        for column, label, width in (("time", "时间", 110), ("customer", "客户", 120),
                                     ("message", "消息", 300), ("action", "处理结果", 100)):
            self._tree.heading(column, text=label, anchor="w")
            self._tree.column(column, width=px(width), anchor="w")

        scrollbar = ttk.Scrollbar(self._list_frame, orient=tk.VERTICAL, style="Workbench.Vertical.TScrollbar", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._history_empty = self._empty_label(self._tree, "暂无已发送记录")

        self.root.after(120, self._fit_tree_columns)
        self._tree.tag_configure("replied", foreground=COLORS["ink_secondary"])
        self._tree.tag_configure("escalated", foreground=COLORS["warning"])

        # ── 待人工列表（点「待人工」标签时显示）──────────────────────
        # 置信度不足的消息会进这里，附带 AI 推荐回复，可【发送】或【编辑】

        self._pending_frame = ttk.Frame(body, style="Workbench.Card.TFrame")
        self._pending_frame.bind("<Map>", lambda event: self.root.after_idle(self._fit_tree_columns))
        self._pending_frame.grid_rowconfigure(0, weight=1)
        self._pending_frame.grid_columnconfigure(2, weight=1)
        self._queue_panel = tk.Frame(self._pending_frame, width=px(320), background=COLORS["canvas"])
        self._queue_panel.grid(row=0, column=0, sticky="nsew")
        self._queue_panel.pack_propagate(False)
        queue_header = tk.Frame(self._queue_panel, background=COLORS["canvas"])
        queue_header.pack(fill=tk.X, padx=px(20), pady=(px(24), px(20)))
        tk.Label(queue_header, text="消息队列", font=font("h3", True),
                 background=COLORS["canvas"], foreground=COLORS["ink"]).pack(anchor="w")
        self._pending_stats_label = ttk.Label(
            queue_header, text="共 0 条待人工", style="Workbench.Mute.TLabel")
        self._pending_stats_label.pack(anchor="w", pady=(px(8), 0))
        tk.Frame(self._queue_panel, height=1, background=COLORS["hairline"]).pack(fill=tk.X)
        tk.Frame(self._pending_frame, width=1, background=COLORS["hairline"]).grid(
            row=0, column=1, sticky="ns")

        # Keep all original values and stable keys. The list is a compact preview;
        # the adjacent reading panel presents the complete selected message.
        p_columns = ("ptime", "pcustomer", "pmsg", "preply", "pconf", "paction")
        self._pending_tree = ttk.Treeview(
            self._queue_panel, columns=p_columns, displaycolumns=(), show="tree",
            selectmode="browse", style="Queue.Workbench.Treeview")
        self._pending_tree.column("#0", width=px(280), minwidth=px(180))
        p_scrollbar = ttk.Scrollbar(
            self._queue_panel, orient=tk.VERTICAL, style="Workbench.Vertical.TScrollbar",
            command=self._pending_tree.yview)
        self._pending_tree.configure(yscrollcommand=p_scrollbar.set)
        p_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._pending_tree.pack(fill=tk.BOTH, expand=True, padx=(px(8), 0), pady=px(8))

        self._create_pending_detail()
        self._pending_detail.grid(row=0, column=2, sticky="nsew")
        self._pending_tree.bind("<<TreeviewSelect>>", self._sync_pending_actions)
        self._sync_pending_actions()
        self._pending_empty = self._empty_label(self._pending_tree, "暂无待处理消息")
        self._pending_empty.place(relx=.5, rely=.5, anchor="center")
        self._switch_tab(self._current_tab)

    def _create_pending_detail(self):
        self._pending_content = {}
        self._pending_status = {}
        self._pending_detail = tk.Frame(self._pending_frame, background=COLORS["canvas"])
        self._pending_detail.grid_columnconfigure(0, weight=1)
        self._pending_detail.grid_rowconfigure(1, weight=2)
        self._pending_detail.grid_rowconfigure(2, weight=3)
        heading = tk.Frame(self._pending_detail, background=COLORS["canvas"])
        heading.grid(row=0, column=0, sticky="ew", padx=px(28), pady=(px(12), px(8)))
        self._detail_title = tk.Label(
            heading, text="选择一条消息", anchor="w",
            background=COLORS["canvas"], foreground=COLORS["ink"], font=font("h2", True))
        self._detail_title.pack(fill=tk.X)
        self._detail_meta = tk.Label(
            heading, text="从左侧队列查看客户问题与回复",
            background=COLORS["canvas"], foreground=COLORS["ink_mute"], font=font("small"))
        self._detail_meta.pack(anchor="w", pady=(px(8), 0))

        self._detail_texts = []
        for index, title in enumerate(("客户消息", "AI 推荐回复")):
            background = COLORS["canvas"] if index == 0 else COLORS["canvas_soft"]
            group = tk.Frame(self._pending_detail, background=background)
            group.grid(row=index + 1, column=0, sticky="nsew",
                       padx=px(28), pady=(0, px(8)))
            inset = px(12) if index else 0
            tk.Label(group, text=title, font=font("small", True), background=background,
                     foreground=COLORS["ink_mute"]).pack(
                         anchor="w", padx=inset, pady=(inset, px(8)))
            area = tk.Frame(group, background=background)
            area.pack(fill=tk.BOTH, expand=True, padx=inset, pady=(0, inset))
            text = tk.Text(
                area, height=1, width=1, wrap="word", font=font("reading"),
                background=background, foreground=COLORS["ink"],
                relief="flat", borderwidth=0, highlightthickness=0,
                exportselection=False, selectbackground=COLORS["primary_subtle"],
                selectforeground=COLORS["ink"], spacing1=px(2), spacing3=px(6),
                state="disabled", cursor="arrow")
            scrollbar = ttk.Scrollbar(
                area, orient=tk.VERTICAL, style="Workbench.Vertical.TScrollbar",
                command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text.pack(fill=tk.BOTH, expand=True)
            self._detail_texts.append(text)

        footer = tk.Frame(self._pending_detail, background=COLORS["canvas"])
        footer.grid(row=3, column=0, sticky="ew")
        tk.Frame(footer, height=1, background=COLORS["hairline"]).pack(fill=tk.X)
        actions = tk.Frame(footer, background=COLORS["canvas"])
        actions.pack(fill=tk.X, padx=px(24), pady=px(8))
        self._pending_actions = []
        for label, style, command, side in (
            ("发送回复", "Workbench.Primary.TButton", self._handle_pending_send, tk.RIGHT),
            ("编辑回复", "Workbench.Secondary.TButton", self._handle_pending_edit, tk.RIGHT),
            ("忽略", "Workbench.Ghost.TButton", self._handle_pending_ignore, tk.LEFT),
        ):
            button = ttk.Button(actions, text=label, style=style, command=command)
            button.pack(side=side, padx=(px(8), 0) if side == tk.RIGHT else 0)
            self._pending_actions.append(button)

    @staticmethod
    def _empty_label(tree, text):
        icon = ui_icon(tree, "inbox", 40, color=COLORS["ink_mute"])
        label = tk.Label(tree, text=f"\n{text}", image=icon, compound="top",
                         font=font("body"), background=COLORS["canvas"],
                         foreground=COLORS["ink_mute"])
        label._icon = icon
        return label

    def _create_footer(self):
        """Always show service status and the window pin control."""
        self._footer = tk.Frame(self._content, background=COLORS["canvas"])
        self._footer.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(self._footer, height=1, background=COLORS["hairline"]).pack(fill=tk.X)

        # ★ 窗口置顶开关（2026-10-06 店主反馈"软件强制置顶在所有页面前面"）。
        #   原来是硬编码 `attributes('-topmost', True)` —— 想不置顶只能改代码。
        #   现在：默认**不置顶**，这里一键开/关，写回 config.json 重启也记得。
        #   留在底部是因为它在所有标签页都可见（设置页翻起来麻烦）。
        self._topmost_on = tk.BooleanVar(value=always_on_top_enabled())
        ttk.Checkbutton(self._footer, text="窗口置顶", style="Workbench.TCheckbutton", variable=self._topmost_on,
                        command=self._toggle_topmost).pack(side=tk.RIGHT, padx=SPACE["lg"],
                                                         pady=SPACE["xs"])
        self._create_status_bar(self._footer)

    def _toggle_topmost(self):
        """勾/取消置顶 → 立刻生效 + 写回配置。

        写盘失败就把勾选状态改回去 —— 不让界面显示一个假的"已置顶"。
        """
        want = bool(self._topmost_on.get())
        try:
            set_always_on_top(want)
        except Exception as e:
            self._topmost_on.set(not want)
            logger.warning("置顶设置写回失败: %s", e)
            return
        try:
            self.root.attributes("-topmost", want)
        except Exception as e:
            logger.warning("应用置顶失败: %s", e)


    def _start_allowed(self):
        """问一下守卫能不能开始。守卫自己出错就当允许（别把它变成锁死程序的东西）。"""
        # getattr：单元测试会用 MainWindow.__new__ 造"半成品"实例，不能假设属性都在
        guard = getattr(self, "can_start", None)
        if guard is None:
            return True, ""
        try:
            ok, why = guard()
            return bool(ok), (why or "")
        except Exception:
            return True, ""

    def _refuse_start(self, why: str):
        """配置不完整 → 不让开始，并直接把人送到「设置」。"""
        self._pause_btn.config(text="开始")
        self._status_label.config(text="状态：未启动")
        one_line = " ".join((why or "").split())
        self.set_banner(f"⚠️ {one_line}", level="error", blocks_start=True)
        try:
            go = messagebox.askyesno("还不能开始", f"{why}\n\n现在打开「设置」？")
        except Exception:
            go = False
        if go and self.on_settings:
            try:
                self.on_settings()
            except Exception:
                pass

    def _toggle_pause(self):
        """切换运行/停止状态（默认是「未启动」）"""
        if self._paused:                      # 即将「开始」→ 先过守卫
            ok, why = self._start_allowed()
            if not ok:
                self._refuse_start(why)
                return
        self._paused = not self._paused
        if hasattr(self, "_run_icons"):
            self._pause_btn.configure(image=self._run_icons["play" if self._paused else "stop"])
            self._paint_service_status()
        if self._paused:
            self._pause_btn.config(text="开始")
            self._status_label.config(text="状态：未启动")
            self.set_banner("未启动。点「开始」运行，或点「设置」重新配置。", level="warn")
            if self.on_pause:
                self.on_pause()
        else:
            self._pause_btn.config(text="停止")
            self._status_label.config(text="状态：运行中")
            # 清掉"未启动"横幅；若目标软件不在，扫描线程下一轮会用红字顶回来
            self.set_banner("")
            if self.on_resume:
                self.on_resume()

    def toggle_pause(self):
        """公开的暂停切换方法（供全局热键调用）"""
        self._toggle_pause()

    def _switch_tab(self, tab: str):
        """切换标签页"""
        self._current_tab = tab
        # 选中的标签用"选中态"样式（靛蓝浅底 + 靛蓝字），一眼看出在看哪一页
        for name, btn in self._tab_buttons.items():
            btn.configure(style="Workbench.SegmentOn.TButton" if name == tab
                          else "Workbench.Segment.TButton")
        if tab == "待人工":
            self._list_frame.pack_forget()
            self._pending_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self._pending_frame.pack_forget()
            self._list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            self._refresh_list()

    def _refresh_list(self):
        """刷新「已回复」列表 —— **软件发出去的所有消息**（含占位语/欢迎语）。

        ★ 2026-10-06 修：原来过滤条件是 `action == "replied"`，
        看似能用（自动发送那条记录确实传 "replied"），但它漏掉了：
          · 占位语（`hold`）—— 客户收到的就是这句，凭什么不算"已回复"；
          · 欢迎语（`greeting`）；
          · 以及任何将来新增的发送类型，一加就得记得回来改这里。
        现在用**显式的"发出去"集合**，语义写清楚。
        另外记录顺序改成**最新在上** —— 这是一个"它替我发了什么"的流水账，
        往下滚找最新一条很别扭。
        """
        for item in self._tree.get_children():
            self._tree.delete(item)

        filtered = [r for r in self._records if r.action in OUTBOUND_ACTIONS]
        empty = getattr(self, "_history_empty", None)
        if empty is not None:
            if filtered:
                empty.place_forget()
            else:
                empty.place(relx=.5, rely=.5, anchor="center")

        for record in reversed(filtered):        # 最新在上
            self._tree.insert(
                "", tk.END,
                values=(
                    record.timestamp,
                    record.customer,
                    record.message[:50] + ("..." if len(record.message) > 50 else ""),
                    self._get_action_text(record.action),
                ),
                tags=(record.action,),
            )

    def _get_action_text(self, action: str) -> str:
        """把内部代号翻成人话（别把 escalate / no_reply 这种词漏给店主看）"""
        mapping = {
            "replied": "已自动回复",
            "auto_send": "已自动回复",
            "escalated": "已转人工",
            "escalate": "已转人工",
            "human_handle": "已转人工",
            "human_confirm": "待人工确认",
            "no_reply": "无需回复",
            "hold": "已回占位语",
            "greeting": "已发欢迎语",
        }
        return mapping.get(action, action)

    def _export_csv(self):
        """导出记录为 CSV"""
        if not self._records:
            messagebox.showinfo("导出", "没有记录可导出")
            return

        filename = f"records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join("data", filename)

        os.makedirs("data", exist_ok=True)

        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "customer", "message", "action", "reply"])
            writer.writeheader()
            for record in self._records:
                writer.writerow(record.to_dict())

        messagebox.showinfo("导出", f"记录已导出到: {filepath}")

    def _clear_records(self):
        """清空记录"""
        if messagebox.askyesno("清空", "确定要清空所有记录吗？"):
            self._records.clear()
            self._stats = {
                "replied": 0,
                "escalated": 0,
            }
            self._refresh_list()
            self._update_stats()

    def _update_stats(self):
        """更新统计信息（本次会话；历史统计在「数据」看板里）"""
        self._stats_label.config(
            text=f"已回复 {self._stats['replied']}　待人工 {self._stats['escalated']}"
        )

    def _on_close(self):
        """关闭窗口"""
        import logging as _log
        if getattr(self, "_web_page_busy", False):
            messagebox.showinfo("请稍候", "资料操作仍在进行，完成后再退出可避免中断保存。")
            return
        if messagebox.askyesno("退出", "确定要退出吗？"):
            self._should_exit = True
            self._paused = True
            if self.on_pause:
                self.on_pause()
            _log.getLogger(__name__).info("_on_close: 用户确认退出")
            self.root.destroy()
        else:
            _log.getLogger(__name__).info("_on_close: 用户取消退出")

    # ═══ 公开接口 ═══════════════════════════

    def add_record(self, customer: str, message: str, action: str,
                   reply: str = "", **metadata):
        """添加消息记录"""
        # 带日期：这一页是"它替我发了什么"的流水账，跨天只写 HH:MM 分不清是哪天
        timestamp = datetime.now().strftime("%m-%d %H:%M")
        record = MessageRecord(timestamp, customer, message, action, reply, **metadata)
        self._records.append(record)

        # 更新统计
        if action in self._stats:
            self._stats[action] += 1

        # 刷新列表
        self._refresh_list()
        self._update_stats()

    def is_paused(self) -> bool:
        """是否暂停"""
        return self._paused

    def run(self):
        """运行主循环"""
        self.root.mainloop()

    def update(self):
        """更新界面（非阻塞）"""
        self.root.update_idletasks()
        self.root.update()

    # ── 待人工页 ───────────────────────────────────────────────────

    def set_pending_callbacks(self,
                              on_send: Callable = None,
                              on_edit: Callable = None,
                              on_ignore: Callable = None,
                              on_get_reply: Callable = None):
        """注册待人工页的动作回调。"""
        self._on_pending_send = on_send
        self._on_pending_edit = on_edit
        self._on_pending_ignore = on_ignore
        self._on_get_reply = on_get_reply

    def refresh_pending_queue(self, pending_items: list):
        """按 PendingItem 列表刷新待人工页，并在标签上显示条数。

        **一条消息一行**（不是一个人一行）：同一个人问了两件事就要处理两次。
        行定位用 ``item.key`` 而不是客户名 —— 否则同一个人的两行点哪行都一样。
        """
        from gui.web_workbench import serialize_pending
        self._web_pending_rows = serialize_pending(pending_items)
        selection = self._pending_tree.selection()
        selected_key = str(self._pending_tree.item(selection[0], "values")[5]) if selection else None
        if hasattr(self, "_pending_content"):
            self._pending_content = {
                str(item.key): (item.customer_name, item.customer_message, item.ai_reply or "")
                for item in pending_items
            }
        if hasattr(self, "_pending_status"):
            self._pending_status = {}
        for item in self._pending_tree.get_children():
            self._pending_tree.delete(item)

        # 同一个人有几条待处理 → 客户名后面标一下，免得以为重复了
        per_person = {}
        for item in pending_items:
            per_person[item.customer_name] = per_person.get(item.customer_name, 0) + 1

        for item in pending_items:
            ts = item.timestamp
            time_str = (datetime.fromtimestamp(ts).strftime("%H:%M")
                        if ts > 100000 else "")
            # 没草稿时要说清**为什么** —— 不然用户看到空白只会以为程序坏了。
            # （AI 答不上来时给的是内部信号"需要人工处理"，不会当草稿递过来）
            draft = (item.ai_reply or "").strip() or "（AI 没给草稿，点【编辑】自己写）"
            status = getattr(item, "send_status", "pending")
            label = {"queued": "待发送", "failed": "发送失败·可重试", "unknown": "待核实·勿重复发送"}.get(status)
            if hasattr(self, "_pending_status"):
                self._pending_status[str(item.key)] = label or "待人工确认"
            if label:
                draft = f"【{label}】{draft}"
            who = item.customer_name
            if per_person[item.customer_name] > 1:
                who = f"{who} [{per_person[item.customer_name]}条]"
            row_id = self._pending_tree.insert(
                "", tk.END,
                text=f"{who}  ·  {time_str}\n{item.customer_message[:14]}{'…' if len(item.customer_message) > 14 else ''}",
                values=(
                    time_str,
                    who,
                    item.customer_message[:28]
                    + ("..." if len(item.customer_message) > 28 else ""),
                    draft[:44] + ("..." if len(draft) > 44 else ""),
                    f"{item.confidence:.0%}",
                    item.key,             # hidden: 动作时按它定位这一行
                ),
            )
            if str(item.key) == selected_key:
                self._pending_tree.selection_set(row_id)

        n = len(pending_items)
        people = len(per_person)
        extra = f"（{people} 个客户）" if people and people != n else ""
        self._pending_stats_label.config(
            text=f"共 {n} 条待人工{extra}")
        empty = getattr(self, "_pending_empty", None)
        if empty is not None:
            if n:
                empty.place_forget()
            else:
                empty.place(relx=.5, rely=.5, anchor="center")
        btn = self._tab_buttons.get("待人工")
        if btn is not None:
            btn.config(text=f"待人工 ({n})" if n else "待人工")

        if hasattr(self, "_pending_actions"):
            self._sync_pending_actions()

    def _sync_pending_actions(self, _event=None):
        state = ("!disabled",) if self._pending_tree.selection() else ("disabled",)
        for button in self._pending_actions:
            button.state(state)
        selection = self._pending_tree.selection()
        key = str(self._pending_tree.item(selection[0], "values")[5]) if selection else None
        content = self._pending_content.get(key)
        self._detail_title.configure(
            text=content[0] if content else "选择一条消息")
        if selection:
            row_values = self._pending_tree.item(selection[0], "values")
            status = self._pending_status.get(key, "待人工确认")
            self._detail_meta.configure(text=f"{row_values[0]}  ·  置信度 {row_values[4]}  ·  {status}")
        else:
            self._detail_meta.configure(text="从左侧队列查看客户问题与回复")
        values = (content[1], content[2] or "AI 未提供草稿，可点「编辑」填写回复") if content else ("", "")
        for text, value in zip(self._detail_texts, values):
            if text.get("1.0", "end-1c") == value:
                continue
            text.configure(state="normal")
            text.delete("1.0", tk.END)
            text.insert("1.0", value)
            text.configure(state="disabled")

    def _selected_pending_key(self):
        """选中那一行的 key（``人::消息指纹``），界面动作全靠它。"""
        sel = self._pending_tree.selection()
        if not sel:
            messagebox.showinfo("待人工", "请先在列表里选中一条")
            return None
        return self._pending_tree.item(sel[0], "values")[5]

    def _handle_pending_send(self):
        key = self._selected_pending_key()
        if key and self._on_pending_send:
            self._on_pending_send(key)

    def _handle_pending_ignore(self):
        key = self._selected_pending_key()
        if key and self._on_pending_ignore:
            self._on_pending_ignore(key)

    def _handle_pending_edit(self):
        key = self._selected_pending_key()
        if not key:
            return
        current = ""
        if self._on_get_reply:
            current = self._on_get_reply(key) or ""
        item = self._pending_item_for(key) or {}
        customer = item.get("customer_name") or "客户"
        question = item.get("customer_message") or ""

        # 窗口本身在 gui/pending_edit.py 里 —— 抽出去才能测布局
        # （踩过：按钮最后 pack + 尺寸硬编码不缩放 → 高 DPI 下按钮被挤成 1px，
        #   店主反馈"编辑的框太小、下面两个按钮被吞了"）
        from gui.pending_edit import open_editor
        edited = open_editor(self.root, customer, question, current).wait()
        if edited and self._on_pending_edit:
            self._on_pending_edit(key, edited)

    def _pending_item_for(self, key: str) -> dict:
        """把 key 那一行的客户名/问题取回来（编辑窗要显示"客户问的是…"）。"""
        for row in self._pending_tree.get_children():
            vals = self._pending_tree.item(row, "values")
            if vals[5] == key:
                who = str(vals[1]).split(" [")[0]      # 去掉"[2条]"这种标注
                return {"customer_name": who,
                        "customer_message": str(vals[2]).rstrip(".")}
        return {}
