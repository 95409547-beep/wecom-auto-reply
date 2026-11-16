"""Windowed local launcher for the installed source distribution."""
import os
import runpy
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def configure_runtime(app_dir: Path) -> None:
    os.chdir(app_dir)
    # This bundled Tcl runtime needs paths relative to the application directory.
    if (app_dir / "runtime/tcl/tcl8.6/init.tcl").is_file():
        os.environ["TCL_LIBRARY"] = "runtime/tcl/tcl8.6"
        os.environ["TK_LIBRARY"] = "runtime/tcl/tk8.6"
    os.environ["WECOM_AUTOSTART"] = "0"
    os.environ.setdefault("HF_HOME", str(app_dir / "models/huggingface"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    for directory in ("logs", "data/chat_raw", "data/context", "data/pending",
                      "data/qdrant", "data/state"):
        (app_dir / directory).mkdir(parents=True, exist_ok=True)


def show_startup_error(log_path: Path) -> None:
    root = None
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "企业微信智能客服 — 启动失败",
            f"请查看错误日志：\n{log_path}", parent=root,
        )
    except Exception:
        # A broken Tk installation must not replace the original startup error.
        print("无法显示错误窗口，详细信息已写入：", log_path, file=sys.stderr)
        traceback.print_exc()
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def main() -> None:
    configure_runtime(APP_DIR)
    with (APP_DIR / "logs/launcher.log").open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            try:
                runpy.run_path(str(APP_DIR / "main.py"), run_name="__main__")
            except Exception:
                traceback.print_exc()
                show_startup_error(APP_DIR / "logs/launcher.log")
                raise


if __name__ == "__main__":
    main()
