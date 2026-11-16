# gui/theme.py
"""Shared colours, typography and controls for the Windows desktop UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

# Neutral surfaces and monochrome controls; colour is reserved for status.
COLORS = {
    "canvas": "#ffffff",
    "canvas_soft": "#ffffff",
    "canvas_sunken": "#f0f0f0",
    "sidebar": "#f9f9f9",
    "hairline": "#ebebeb",
    "hairline_strong": "#d4d4d4",
    "ink": "#202020",
    "ink_secondary": "#404040",
    "ink_mute": "#707070",
    "ink_faint": "#767676",
    "on_primary": "#ffffff",
    "primary": "#212121",
    "primary_deep": "#383838",
    "primary_press": "#111111",
    "primary_soft": "#858585",
    "primary_subtle": "#eaeaea",
    "success": "#187343",
    "success_bg": "#e8f6ee",
    "warning": "#7a530a",
    "warning_bg": "#fff4dc",
    "danger": "#a2263b",
    "danger_bg": "#fbecef",
    "info": "#145faa",
    "info_bg": "#e8f2fd",
}

FONT_FAMILY = "Microsoft YaHei UI"

# ── 缩放：整个界面按一个因子等比放大/缩小 ─────────────────────────────────
#
# 为什么要它：tkinter 里字号是 pt、间距是 px，**窗口变大时它们不会跟着变**，
# 于是同一个界面在小窗口里挤成一团、在大窗口里中间一坨空白。
# 更麻烦的是高 DPI 屏：系统缩放 150% 时，写死的 720px 窗口装不下按 pt 放大的文字
# （实测主窗口的「知识库/设置」、看板的「近 7 天/自定义」就是这么被裁掉的）。
#
# 做法：所有尺寸都过一遍 px()/font()，由 _SCALE 统一放大。
#   * 基准：屏幕 DPI（96 → 1.0，144 → 1.5）
#   * 再乘：窗口宽度相对设计宽度的比例（看板会用它做"随窗口等比缩放"）
_SCALE = 1.0
MIN_SCALE, MAX_SCALE = 0.8, 2.0


def set_scale(factor: float) -> float:
    """设置全局缩放因子（会夹在 [0.8, 2.0] 内），返回实际生效值。"""
    global _SCALE
    _SCALE = max(MIN_SCALE, min(MAX_SCALE, float(factor)))
    return _SCALE


def scale() -> float:
    return _SCALE


def px(value: float) -> int:
    """把设计稿上的像素值换算成当前缩放下的实际值。"""
    return int(round(value * _SCALE))


def detect_dpi_scale(root: tk.Misc) -> float:
    """按屏幕 DPI 推断缩放（96dpi=1.0，常见的 125%/150% 会得到 1.25/1.5）。"""
    try:
        return max(MIN_SCALE, min(MAX_SCALE, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        return 1.0


# ── 字号（**单位是像素，不是点**）──────────────────────────────────────────
#
# ★ 2026-10-04 踩的坑：原来这里写的是"点"（如 body=12），而 Tk 会把点按
#   `tk scaling`（本机 2.0，即 144dpi）换算成像素 —— 于是"我自己的 DPI 缩放 1.5"
#   与"Tk 的点→像素 ×2"**叠乘**：一个 12pt 正文渲染成 36px 宽的汉字，
#   按钮 273px 宽、标题 422px 宽、窗口被撑到 1600+（用户反馈"主页面怎么变这么大"）。
#   改成**像素字号**（tkinter 里负数即像素）后，字号与 px() 间距同单位，
#   缩放只由我们自己控制一次，尺寸可预测。
SIZES = {
    "kpi": 28,       # 大数字
    "h1": 20,        # 页面标题
    "h2": 18,        # 卡片标题
    "h3": 14,        # 小节标题
    "body": 14,      # 正文
    "small": 12,     # 辅助说明
    "micro": 11,     # 标签/角标
}


def font(size_key: str = "body", bold: bool = False):
    """按语义取字体元组。**像素字号**（负数）—— 见上面 SIZES 的说明。"""
    return (FONT_FAMILY, -px(SIZES.get(size_key, SIZES["body"])),
            "bold" if bold else "normal")


# ── 间距（8px 栅格）────────────────────────────────────────────────────────
SPACE = {"xxs": 2, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

RADIUS = {"card": 12, "control": 10, "pill": 999}   # 自绘圆角用


def _control_plate(master, radius, fill, border=None):
    size = 2 * radius + 3
    image = Image.new("RGBA", (3 * size, 3 * size))
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, 3 * size - 1, 3 * size - 1), radius=3 * radius,
        fill=fill, outline=border, width=3)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=master)


def _configure_buttons(root, style):
    """Give ttk buttons rounded, stretchable backgrounds and native focus/input."""
    c = COLORS
    # Default and selected controls share the same geometry and keyboard layout.
    specs = {
        "TButton": (c["canvas"], c["canvas_sunken"], c["hairline"], c["ink"], False),
        "Primary.TButton": (c["primary"], c["primary_deep"], None, c["on_primary"], True),
        "Secondary.TButton": (c["canvas"], c["primary_subtle"], c["hairline"], c["primary_deep"], False),
        "Ghost.TButton": (c["canvas"], c["canvas_sunken"], None, c["ink_secondary"], False),
        "Danger.TButton": (c["canvas"], c["danger_bg"], None, c["danger"], False),
        "Segment.TButton": (c["canvas"], c["canvas_sunken"], None, c["ink_mute"], False),
        "SegmentOn.TButton": (c["canvas_sunken"], c["primary_subtle"], None, c["ink"], False),
        "Page.TButton": (c["sidebar"], c["hairline"], None, c["ink"], False),
        "PageOn.TButton": (c["primary_subtle"], "#e2e2e2", None, c["ink"], False),
    }
    app = root._root()
    assets = getattr(app, "_button_images", None)
    if assets is None:
        assets = app._button_images = {}
    radius = px(RADIUS["control"])
    for name, (fill, hover, border, ink, bold) in specs.items():
        element = f"Desk{radius}.{name}.plate"
        if element not in assets:
            pressed_fill = c["primary_press"] if name == "Primary.TButton" else hover
            disabled_fill = c["canvas_sunken"] if fill != c["sidebar"] else fill
            normal, active, pressed, disabled, focused = assets[element] = (
                _control_plate(root, radius, fill, border),
                _control_plate(root, radius, hover, border),
                _control_plate(root, radius, pressed_fill, border),
                _control_plate(root, radius, disabled_fill),
                _control_plate(root, radius, fill, c["primary_soft"]))
            style.element_create(element, "image", normal, ("disabled", disabled),
                                 ("pressed", pressed), ("focus", focused), ("active", active),
                                 border=radius, padding=0, sticky="nswe")
        style.layout(name, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        page = name.startswith("Page")
        style.configure(name, foreground=ink, background=c["sidebar"] if page else c["canvas"],
                        font=font("body", bold), width=0,
                        padding=(px(12), px(11 if page else 8)),
                        anchor="w" if page else "center",
                        focusthickness=1, focuscolor=c["primary_soft"])
        backing = c["sidebar"] if page else c["canvas"]
        style.map(name, foreground=[("disabled", c["ink_faint"])],
                  background=[("disabled", backing), ("active", backing)])

    tab = f"Desk{radius}.Notebook.plate"
    if tab not in assets:
        off, hover, on = assets[tab] = (
            _control_plate(root, radius, c["canvas_soft"]),
            _control_plate(root, radius, c["canvas_sunken"]),
            _control_plate(root, radius, c["primary_subtle"]))
        style.element_create(tab, "image", off, ("selected", on), ("active", hover),
                             border=radius, padding=0, sticky="nswe")
    style.layout("TNotebook.Tab", [(tab, {"sticky": "nswe", "children": [
        ("Notebook.padding", {"sticky": "nswe", "children": [
            ("Notebook.focus", {"sticky": "nswe", "children": [
                ("Notebook.label", {"sticky": ""})]})]})]})])


def ui_icon(root, name, size=18, *, tile=False, color=None):
    """Draw small line icons with Windows-independent geometry."""
    dim = px(size)
    image = Image.new("RGBA", (dim * 3, dim * 3))
    draw = ImageDraw.Draw(image)
    step = dim * 3 / 24
    stroke = max(2, round(step * 1.7))
    ink = color or COLORS["ink_secondary"]

    def points(*values):
        return tuple(round(v * step) for v in values)

    def line(*values):
        draw.line(points(*values), fill=ink, width=stroke, joint="curve")

    def rectangle(x1, y1, x2, y2, radius):
        draw.rounded_rectangle(points(x1, y1, x2, y2), radius=round(radius * step),
                               outline=ink, width=stroke)

    if tile:
        draw.rounded_rectangle(points(0, 0, 23.8, 23.8), radius=round(6 * step),
                               fill=COLORS["primary_subtle"])
    if name == "conversation":
        rectangle(4.5, 5.5, 19.5, 16, 3)
        line(8, 16, 7, 19, 11, 16)
        line(8, 10, 16, 10)
    elif name == "inbox":
        rectangle(3.5, 5, 20.5, 19, 2.5)
        line(4, 12, 9, 12, 10.5, 15, 13.5, 15, 15, 12, 20, 12)
    elif name == "chart":
        line(4, 4, 4, 20, 21, 20)
        for x, top in ((8, 13), (13, 8), (18, 5)):
            line(x, top, x, 17)
    elif name == "book":
        line(12, 7, 9, 5, 4, 5, 4, 17, 8, 17, 12, 19, 16, 17, 20, 17, 20, 5, 15, 5, 12, 7, 12, 19)
    elif name == "settings":
        for x, y in ((6, 8), (12, 16), (18, 10)):
            line(x, 4, x, y - 2)
            line(x, y + 2, x, 20)
            draw.ellipse(points(x - 2, y - 2, x + 2, y + 2), outline=ink, width=stroke)
    elif name == "play":
        draw.polygon(points(8, 5, 19, 12, 8, 19), fill=ink)
    elif name == "stop":
        draw.rounded_rectangle(points(6, 6, 18, 18), radius=round(2 * step), fill=ink)
    return ImageTk.PhotoImage(image.resize((dim, dim), Image.Resampling.LANCZOS), master=root)


# ═══ ttk 样式 ═════════════════════════════════════════════════════════════

def apply_theme(root: tk.Misc, scale_factor: float | None = None) -> ttk.Style:
    """给整个应用上色 + 定缩放。**必须在创建控件之前调用**。

    ``scale_factor`` 不传就按屏幕 DPI 推断；传了就用它（看板会按窗口宽度动态传，
    做到"框随窗口等比放大缩小"）。可以重复调用：样式会被覆盖成新值 ——
    注意**已经建好的 tk 控件不会自动改字号**，调用方需要重建那部分界面。

    返回 ttk.Style 方便调用方继续加样式。
    """
    set_scale(scale_factor if scale_factor is not None else detect_dpi_scale(root))
    style = ttk.Style(root)
    # ★ 必须切 clam：Windows 默认的 vista 主题把大部分颜色配置忽略掉，
    #   只改 foreground/background 是没反应的（这是 tkinter 上色最常见的坑）
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    c = COLORS
    style.configure(".", background=c["canvas_soft"], foreground=c["ink"],
                    font=font("body"))
    # 具名字体（对话框、Treeview 默认值、messagebox 等都用它）也要改成像素字号，
    # 否则那些地方还是按点渲染，尺寸对不上
    from tkinter import font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                 "TkTooltipFont", "TkIconFont"):
        try:
            tkfont.nametofont(name).configure(family=FONT_FAMILY,
                                              size=-px(SIZES["body"]))
        except Exception:
            pass

    # ── 容器 ────────────────────────────────────────────────────────────
    style.configure("TFrame", background=c["canvas_soft"])
    style.configure("Card.TFrame", background=c["canvas"])
    style.configure("Soft.TFrame", background=c["canvas_soft"])
    style.configure("Sunken.TFrame", background=c["canvas_sunken"])
    style.configure("Header.TFrame", background=c["canvas"])
    style.configure("Divider.TFrame", background=c["hairline"])

    # ── 文本 ────────────────────────────────────────────────────────────
    style.configure("TLabel", background=c["canvas_soft"], foreground=c["ink"])
    style.configure("Card.TLabel", background=c["canvas"], foreground=c["ink"])
    style.configure("H1.TLabel", background=c["canvas"], foreground=c["ink"],
                    font=font("h1", True))
    style.configure("H2.TLabel", background=c["canvas"], foreground=c["ink"],
                    font=font("h2", True))
    style.configure("H3.TLabel", background=c["canvas"], foreground=c["ink_secondary"],
                    font=font("h3", True))
    style.configure("Body.TLabel", background=c["canvas"], foreground=c["ink_secondary"])
    style.configure("Mute.TLabel", background=c["canvas"], foreground=c["ink_mute"],
                    font=font("small"))
    style.configure("Micro.TLabel", background=c["canvas"], foreground=c["ink_faint"],
                    font=font("micro"))
    style.configure("Kpi.TLabel", background=c["canvas"], foreground=c["ink"],
                    font=font("kpi", True))
    style.configure("KpiUnit.TLabel", background=c["canvas"], foreground=c["ink_mute"],
                    font=font("small"))
    style.configure("Link.TLabel", background=c["canvas"], foreground=c["primary"],
                    font=font("small"))

    _configure_buttons(root, style)

    # ── 表格 ────────────────────────────────────────────────────────────
    style.configure("Treeview", background=c["canvas"], fieldbackground=c["canvas"],
                    foreground=c["ink"], rowheight=px(38), borderwidth=0, relief="flat",
                    font=font("body"))
    style.layout("Treeview", [("Treeview.padding", {"sticky": "nswe", "children": [
        ("Treeview.treearea", {"sticky": "nswe"})]})])
    style.configure("Treeview.Heading", background=c["sidebar"],
                    foreground=c["ink_mute"], font=font("small"),
                    relief="flat", padding=(px(12), px(12)))
    style.map("Treeview.Heading", background=[("active", c["canvas_sunken"])])
    style.map("Treeview", background=[("selected", c["primary_subtle"])],
              foreground=[("selected", c["ink"])])

    # ── 输入 ────────────────────────────────────────────────────────────
    style.configure("TEntry", fieldbackground=c["canvas"], foreground=c["ink"],
                    bordercolor=c["hairline"], lightcolor=c["canvas"],
                    darkcolor=c["canvas"], insertcolor=c["ink"], padding=(px(8), px(6)))
    style.configure("TCombobox", fieldbackground=c["canvas"], background=c["canvas"],
                    foreground=c["ink"], arrowcolor=c["ink_mute"],
                    bordercolor=c["hairline"], lightcolor=c["canvas"],
                    darkcolor=c["canvas"], padding=(px(8), px(5)))
    # clam 的 readonly 下拉框默认是灰底（#dcdad5），和旁边白色输入框不一致 —— 拉平
    style.map("TCombobox",
              fieldbackground=[("readonly", c["canvas"])],
              foreground=[("readonly", c["ink"])],
              selectbackground=[("readonly", c["canvas"])],
              selectforeground=[("readonly", c["ink"])])
    style.configure("TCheckbutton", background=c["canvas"], foreground=c["ink_secondary"])
    style.configure("TRadiobutton", background=c["canvas"], foreground=c["ink_secondary"])

    # ── 滚动条：细一点，别抢视觉 ────────────────────────────────────────
    style.configure("Vertical.TScrollbar", background=c["canvas_sunken"],
                    troughcolor=c["canvas_soft"], bordercolor=c["canvas_soft"],
                    arrowcolor=c["ink_mute"], borderwidth=0, width=px(11))
    style.configure("Horizontal.TScrollbar", background=c["canvas_sunken"],
                    troughcolor=c["canvas_soft"], bordercolor=c["canvas_soft"],
                    arrowcolor=c["ink_mute"], borderwidth=0)
    # A quiet track and rounded thumb, without the native desktop arrow boxes.
    assets = root._root()._button_images
    thumb = f"Desk{px(4)}.Scrollbar.thumb"
    if thumb not in assets:
        normal, active = assets[thumb] = (
            _control_plate(root, px(4), c["hairline_strong"]),
            _control_plate(root, px(4), c["ink_faint"]))
        style.element_create(thumb, "image", normal, ("active", active),
                             border=px(4), sticky="nswe")
    for direction, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
        style.layout(f"{direction}.TScrollbar", [
            (f"{direction}.Scrollbar.trough", {"sticky": "nswe", "children": [
                (thumb, {"sticky": sticky, "expand": True})]})])
        style.configure(f"{direction}.TScrollbar", troughcolor=c["canvas"],
                        bordercolor=c["canvas"], lightcolor=c["canvas"], darkcolor=c["canvas"],
                        arrowsize=px(10), gripcount=0)

    # ── 标签页 + 分区框 ─────────────────────────────────────────────────
    # 这两个是"所有对话框共用"的容器：在 theme 里统一定义一次，
    # 知识库 / 学到的 / 待人工 等面板就一起升级了（不然每个文件都要改一遍）
    style.configure("TNotebook", background=c["canvas_soft"], borderwidth=0,
                    bordercolor=c["canvas_soft"], lightcolor=c["canvas_soft"],
                    darkcolor=c["canvas_soft"], padding=0, tabmargins=(0, 0, 0, px(8)))
    style.layout("TNotebook", [("Notebook.client", {"sticky": "nswe"})])
    style.configure("TNotebook.Tab", background=c["canvas_sunken"],
                    foreground=c["ink_mute"], padding=(px(14), px(7)), borderwidth=0,
                    lightcolor=c["canvas_soft"], darkcolor=c["canvas_soft"],
                    font=font("body"))
    style.map("TNotebook.Tab",
              background=[("selected", c["primary_subtle"])],
              foreground=[("selected", c["primary_deep"])])
    style.configure("TLabelframe", background=c["canvas"], bordercolor=c["hairline"],
                    borderwidth=1, relief="solid", padding=px(6))
    style.configure("TLabelframe.Label", background=c["canvas"],
                    foreground=c["ink"], font=font("h3", True))

    return style


# ═══ 常用控件（自绘圆角 / 卡片 / 条形图）═══════════════════════════════════

def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r: int = RADIUS["card"], **kw):
    """在 Canvas 上画圆角矩形（tkinter 没有原生圆角，用平滑多边形近似）。

    做法：取 4 个圆角的点，用 `smooth=True` 让 Tk 自己插值成弧。
    """
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def card(parent, *, padding: int | None = None, bg: str | None = None) -> tk.Canvas:
    """A rounded surface with a regular frame for focusable content."""
    parent_bg = COLORS["canvas_soft"]
    if isinstance(parent, (tk.Frame, tk.Toplevel)):
        parent_bg = parent.cget("background")
    outer = tk.Canvas(parent, width=1, height=1, background=parent_bg,
                      highlightthickness=0, borderwidth=0)
    fill = bg or COLORS["canvas"]
    inner = tk.Frame(outer, background=fill, highlightthickness=0, bd=0)
    inner.pack(fill="both", expand=True, padx=px(7), pady=px(5))
    inner._pad = padding

    def paint(event):
        outer.delete("surface")
        if event.width > px(16) and event.height > px(16):
            rounded_rect(outer, 1, 1, event.width - 1, event.height - 1, px(12),
                         fill=fill, outline=COLORS["hairline"], tags="surface")

    outer.bind("<Configure>", paint)
    return outer

def card_body(outer) -> tk.Frame:
    """取卡片里真正放内容的那层（配合 card() 用）。"""
    return outer.winfo_children()[0]


def section_title(parent, text: str, *, bg: str | None = None) -> tk.Label:
    """小节标题：小字大写感的"标签"，比正文更靠近说明文字。"""
    return tk.Label(parent, text=text, font=font("h3", True),
                    background=bg or COLORS["canvas"],
                    foreground=COLORS["ink"], anchor="w")


def hint(parent, text: str, *, bg: str | None = None) -> tk.Label:
    return tk.Label(parent, text=text, font=font("small"),
                    background=bg or COLORS["canvas"],
                    foreground=COLORS["ink_mute"], anchor="w")


def kpi_card(parent, label: str, value: str, *, unit: str = "",
             tone: str = "ink", note: str = "") -> tk.Frame:
    """KPI 卡：大数字 + 标签 + 可选单位/备注。返回卡片（用 card_body 拿内容层）。"""
    outer = card(parent)
    body = card_body(outer)
    tk.Label(body, text=label, font=font("small"), background=COLORS["canvas"],
             foreground=COLORS["ink_mute"], anchor="w").pack(
        anchor="w", padx=SPACE["lg"], pady=(SPACE["md"], 0))
    row = tk.Frame(body, background=COLORS["canvas"])
    row.pack(anchor="w", padx=SPACE["lg"], pady=(0, SPACE["md"]))
    tk.Label(row, text=value, font=font("kpi", True), background=COLORS["canvas"],
             foreground=COLORS.get(tone, COLORS["ink"])).pack(side="left")
    if unit:
        tk.Label(row, text=unit, font=font("small"), background=COLORS["canvas"],
                 foreground=COLORS["ink_mute"]).pack(side="left", padx=(3, 0), pady=(9, 0))
    if note:
        tk.Label(body, text=note, font=font("micro"), background=COLORS["canvas"],
                 foreground=COLORS["ink_faint"], anchor="w").pack(
            anchor="w", padx=SPACE["lg"], pady=(0, SPACE["md"]))
    return outer


def bar_row(parent, name: str, value: int, total: int, *, width: int | None = None,
            color: str | None = None) -> tk.Frame:
    """分布条：名称 + 迷你条形 + 数值（看板的"客户在问什么"用它）。"""
    width = px(108) if width is None else width
    row = tk.Frame(parent, background=COLORS["canvas"])
    tk.Label(row, text=name, font=font("body"), background=COLORS["canvas"],
             foreground=COLORS["ink_secondary"], anchor="w",
             width=px(9)).pack(side="left")
    cv = tk.Canvas(row, width=width, height=px(8), background=COLORS["canvas"],
                   highlightthickness=0, bd=0)
    cv.pack(side="left", padx=(SPACE["sm"], SPACE["sm"]))
    ratio = (value / total) if total else 0
    cv.create_rectangle(0, 0, width, px(8), fill=COLORS["canvas_sunken"], outline="")
    if ratio > 0:
        cv.create_rectangle(0, 0, max(2, int(width * ratio)), px(8),
                            fill=color or COLORS["primary_soft"], outline="")
    tk.Label(row, text=str(value), font=font("body", True),
             background=COLORS["canvas"], foreground=COLORS["ink"],
             anchor="e", width=px(4)).pack(side="left")
    pct = f"{ratio * 100:.0f}%" if total else "—"
    tk.Label(row, text=pct, font=font("small"), background=COLORS["canvas"],
             foreground=COLORS["ink_faint"], anchor="e", width=px(4)).pack(side="left")
    return row


def badge(parent, text: str, tone: str = "info") -> tk.Label:
    """小标签（如"实时"、护栏名）。tone: info/success/warning/danger/neutral"""
    bg = {"info": COLORS["info_bg"], "success": COLORS["success_bg"],
          "warning": COLORS["warning_bg"], "danger": COLORS["danger_bg"],
          "neutral": COLORS["canvas_sunken"]}.get(tone, COLORS["info_bg"])
    fg = {"info": COLORS["info"], "success": COLORS["success"],
          "warning": COLORS["warning"], "danger": COLORS["danger"],
          "neutral": COLORS["ink_mute"]}.get(tone, COLORS["info"])
    return tk.Label(parent, text=f" {text} ", font=font("micro"),
                    background=bg, foreground=fg)


def divider(parent, *, pady: int = SPACE["md"]) -> tk.Frame:
    """1px 发丝线分隔（Linear 的做法：靠线分层，不靠阴影）。"""
    line = tk.Frame(parent, height=1, background=COLORS["hairline"])
    line.pack(fill="x", pady=px(pady))
    return line


def scroll_area(parent, *, bg: str | None = None) -> tuple[tk.Frame, tk.Frame]:
    """可滚动内容区：返回 ``(外层, 内容容器)``。

    为什么需要它：设置面板内容比窗口高时，底下那几栏**用户根本看不到**
    （实测「企业微信 API 模式」的凭据栏就是这么消失的 —— 而窗口还设了不可缩放，
    等于死路）。凡是"内容可能超出窗口"的面板都该用它。
    鼠标滚轮只在这个区域内生效，不抢别的窗口。
    """
    bg = bg or COLORS["canvas_soft"]
    outer = tk.Frame(parent, background=bg)
    canvas = tk.Canvas(outer, background=bg, highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, background=bg)
    wid = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(wid, width=e.width))

    def _wheel(ev):
        canvas.yview_scroll(int(-ev.delta / 120), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    return outer, inner


def dialog_geometry(win: tk.Misc, width: int, height: int) -> str:
    """对话框尺寸：按缩放算，并**夹在屏幕内**（高 DPI 下别把窗口顶出屏幕）。"""
    w = min(px(width), win.winfo_screenwidth() - px(60))
    h = min(px(height), win.winfo_screenheight() - px(120))
    x = max(0, (win.winfo_screenwidth() - w) // 2)
    y = max(0, (win.winfo_screenheight() - h) // 3)
    return f"{w}x{h}+{x}+{y}"
