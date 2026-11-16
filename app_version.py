"""Version and source revision shown by the running application."""

import re
import subprocess
import sys
from pathlib import Path


APP_VERSION = "1.4.0-dev"
BUILD_FILE = "wecom-build-id.txt"
APP_DIR = Path(__file__).resolve().parent


def source_build_id(root: Path = APP_DIR) -> str:
    """Identify the checkout, including unpublished application code."""
    if not (root / ".git").exists():
        return ""

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()

    try:
        revision = git("rev-parse", "--short", "HEAD")
        local_code = git("status", "--porcelain", "--untracked-files=normal", "--",
                         "*.py", "*.spec", "profiles")
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{revision}+local" if local_code else revision


def version_label() -> str:
    """Read the packaged revision or snapshot the source revision at startup."""
    if getattr(sys, "frozen", False):
        try:
            revision = (APP_DIR / BUILD_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            revision = ""
    else:
        revision = source_build_id()
    if re.fullmatch(r"[0-9a-f]{7,40}(?:\+local)?", revision):
        return f"v{APP_VERSION} ({revision})"
    return f"v{APP_VERSION}（构建号未知）"
