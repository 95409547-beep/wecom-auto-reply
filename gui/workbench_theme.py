"""Scoped workbench styling, inspired by Damir Sokolovsky's unslop.
Reference: https://github.com/heydamir/unslop (CC BY 4.0).
"""
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
from gui.theme import COLORS as BASE_COLORS, FONT_FAMILY, _control_plate, px

COLORS = {
    **BASE_COLORS,
    "canvas": "#1b1b1d", "canvas_soft": "#151517", "canvas_sunken": "#262629",
    "sidebar": "#111113", "hairline": "#303034", "hairline_strong": "#45454b",
    "ink": "#ededee", "ink_secondary": "#c0c0c5", "ink_mute": "#a1a1aa",
    "ink_faint": "#91919b", "primary": "#ededee", "on_primary": "#18181b",
    "primary_subtle": "#303034", "primary_soft": "#a1a1aa",
    "success": "#77d7ae", "success_bg": "#20372e",
    "warning": "#e4c17b", "warning_bg": "#393122",
    "danger": "#f09595", "danger_bg": "#3c2528",
}


def font(role="body", bold=False):
    sizes = {"h1": 26, "h2": 20, "h3": 16, "reading": 16, "body": 14, "small": 12, "micro": 11}
    return (FONT_FAMILY, -px(sizes.get(role, 14)), "bold" if bold else "normal")


def apply_workbench_theme(root):
    """Use distinct style names so dialogs and other pages retain their theme."""
    c = COLORS
    style = ttk.Style(root)
    style.configure("Workbench.Card.TFrame", background=c["canvas"])
    style.configure("Workbench.Mute.TLabel", background=c["canvas"],
                    foreground=c["ink_mute"], font=font("small"))
    style.configure("Workbench.TCheckbutton", background=c["canvas"],
                    foreground=c["ink_mute"], font=font("small"))
    style.map("Workbench.TCheckbutton", background=[("active", c["canvas"])],
              foreground=[("active", c["ink"])])
    style.configure("Workbench.Treeview", background=c["canvas"],
                    fieldbackground=c["canvas"], foreground=c["ink_secondary"],
                    font=font("body"), rowheight=px(40), borderwidth=0)
    style.configure("Queue.Workbench.Treeview", rowheight=px(88), font=font("body"))
    style.layout("Queue.Workbench.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Workbench.Treeview.Heading", background=c["canvas"],
                    foreground=c["ink_mute"], font=font("small"),
                    padding=(px(8), px(12)), relief="flat")
    style.map("Workbench.Treeview", background=[("selected", c["primary_subtle"])],
              foreground=[("selected", c["ink"])])
    style.map("Workbench.Treeview.Heading", background=[("active", c["canvas_sunken"])])
    style.configure("Workbench.Vertical.TScrollbar", background=c["hairline_strong"],
                    troughcolor=c["canvas"], bordercolor=c["canvas"],
                    lightcolor=c["canvas"], darkcolor=c["canvas"],
                    borderwidth=0, arrowsize=px(12),
                    arrowcolor=c["ink_mute"])
    style.map("Workbench.Vertical.TScrollbar",
              background=[("active", "#62626b"), ("pressed", "#73737e")])
    specs = {
        "Primary": (c["primary"], "#ffffff", c["on_primary"], c["canvas"]),
        "Secondary": (c["canvas_sunken"], "#36363b", c["ink"], c["canvas"]),
        "Service": (c["canvas_sunken"], "#36363b", c["ink"], c["sidebar"]),
        "Toolbar": (c["canvas_soft"], c["canvas_sunken"], c["ink_secondary"], c["canvas_soft"]),
        "ToolbarDanger": (c["canvas_soft"], c["danger_bg"], c["ink_mute"], c["canvas_soft"]),
        "Ghost": (c["canvas"], c["canvas_sunken"], c["ink_secondary"], c["canvas"]),
        "Danger": (c["canvas"], c["danger_bg"], c["danger"], c["canvas"]),
        "Segment": (c["canvas_soft"], c["canvas_sunken"], c["ink_mute"], c["canvas_soft"]),
        "SegmentOn": (c["canvas_sunken"], c["primary_subtle"], c["ink"], c["canvas_soft"]),
        "Page": (c["sidebar"], c["canvas_sunken"], c["ink_mute"], c["sidebar"]),
        "PageOn": (c["canvas_sunken"], c["primary_subtle"], c["ink"], c["sidebar"]),
    }
    assets = root._root().__dict__.setdefault("_workbench_images", {})
    thumb = f"Workbench{px(4)}.Scrollbar.thumb"
    if thumb not in assets:
        images = [_control_plate(root, px(4), color) for color in
                  (c["hairline_strong"], "#62626b")]
        assets[thumb] = images
        style.element_create(thumb, "image", images[0], ("active", images[1]),
                             ("pressed", images[1]), border=px(4), sticky="nswe")
    style.layout("Workbench.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            (thumb, {"sticky": "nswe"})]})])
    radius = px(8)
    for name, (fill, hover, ink, backing) in specs.items():
        element = f"WorkbenchV2.{radius}.{name}.plate"
        if element not in assets:
            images = [
                _control_plate(root, radius, fill, c["hairline_strong"] if name in ("PageOn", "Secondary", "Service") else None),
                _control_plate(root, radius, hover),
                _control_plate(root, radius, c["canvas_sunken"]),
                _control_plate(root, radius, fill, c["ink_mute"]),
            ]
            assets[element] = images
            style.element_create(element, "image", images[0], ("disabled", images[2]),
                                 ("pressed", images[1]), ("focus", images[3]),
                                 ("active", images[1]), border=radius, sticky="nswe")
        key = f"Workbench.{name}.TButton"
        style.layout(key, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        horizontal = 20 if name in ("Primary", "Secondary") else 12
        style.configure(key, foreground=ink, background=backing, font=font("body"),
                        width=0, padding=(px(horizontal), px(6)),
                        anchor="w" if name.startswith("Page") else "center")
        style.map(key, background=[("active", backing), ("disabled", backing)],
                  foreground=[("disabled", c["ink_faint"])])

    for name, selected in (("Segment", False), ("SegmentOn", True)):
        element = f"WorkbenchTab{px(2)}.{name}"
        if element not in assets:
            picture = Image.new("RGB", (12, 12), c["canvas_soft"])
            if selected:
                ImageDraw.Draw(picture).rectangle((0, 10, 11, 11), fill=c["ink"])
            plate = ImageTk.PhotoImage(picture, master=root)
            assets[element] = plate
            style.element_create(element, "image", plate, border=(2, 2, 2, 2), sticky="nswe")
        key = f"Workbench.{name}.TButton"
        style.layout(key, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        style.configure(key, foreground=c["ink"] if selected else c["ink_mute"],
                        font=font("body", selected), padding=(px(12), px(12)),
                        background=c["canvas_soft"])
        style.map(key, foreground=[("active", c["ink"])])
