"""Exercise the main window's actual page layout at its minimum size."""
import tkinter as tk

import pytest

from gui.dashboard import DashboardWindow
from gui.kb_dialog import KbDialog
from gui.main_window import MainWindow


def test_main_pages_share_one_window_and_keep_their_state(monkeypatch):
    from gui import kb_dialog
    from rag import archives, learn_store

    try:
        probe = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk display: {exc}")
    probe.destroy()

    monkeypatch.setattr(kb_dialog.ps, "ensure_files", lambda: None)
    monkeypatch.setattr(archives, "all_archives", lambda: [{"id": "default", "name": "测试资料库"}])
    monkeypatch.setattr(archives, "active_id", lambda: "default")
    monkeypatch.setattr(learn_store, "enabled", lambda _cfg: True)
    monkeypatch.setattr(KbDialog, "_learn_load", lambda self: None)
    monkeypatch.setattr(DashboardWindow, "refresh", lambda self: self._sync_segments())
    window = MainWindow(
        on_dashboard=lambda parent: DashboardWindow(parent, embedded=True),
        on_kb=lambda parent: KbDialog(parent, embedded=True),
    )
    root = window.root
    try:
        min_width, min_height = root.minsize()
        root.geometry(f"{min_width}x{min_height}")
        root.update()
        assert window._current_page == "工作台"
        assert set(window._page_frames) == {"工作台"}

        window._navigation["数据"].invoke()
        root.update()
        dashboard = window._page_views["数据"]
        assert dashboard.win.winfo_toplevel() is root
        dashboard._pick_range("week")
        assert dashboard._seg["custom"].winfo_viewable()

        window._navigation["知识库"].invoke()
        root.update()
        kb = window._page_views["知识库"]
        assert kb.win.winfo_toplevel() is root
        assert kb._nb.tab(kb._nb.select(), "text") == "资料库"
        assert root.title().startswith("企业微信智能客服")
        assert root.grab_current() is None
        kb._kb_kw.insert(0, "测试搜索")
        prompt_page = next(tab for tab in kb._nb.tabs() if kb._nb.tab(tab, "text") == "提示词")
        kb._nb.select(prompt_page)
        kb._text.delete("1.0", tk.END)
        kb._text.insert("1.0", "未保存的提示词")

        window._navigation["数据"].invoke()
        root.update()
        assert window._page_views["数据"] is dashboard
        assert dashboard._range == "week"
        assert not kb.win.winfo_viewable()

        window._navigation["知识库"].invoke()
        root.update()
        assert window._page_views["知识库"] is kb
        assert kb._kb_kw.get() == "测试搜索"
        assert kb._text.get("1.0", "end-1c") == "未保存的提示词"
        assert kb._nb.tab(kb._nb.select(), "text") == "提示词"
        assert window._footer.winfo_viewable()
        assert window._settings_btn.winfo_viewable()

        window._navigation["工作台"].invoke()
        root.update()
        assert window._pending_frame.winfo_viewable()
        assert not kb.win.winfo_viewable()
    finally:
        root.destroy()
