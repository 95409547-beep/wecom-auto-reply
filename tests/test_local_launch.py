"""Exercise actual Windows batch exit codes and preserve the original startup error."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import launch_local


@pytest.mark.skipif(os.name != "nt", reason="Windows CMD regression")
@pytest.mark.parametrize("exit_code", [0, 23])
def test_source_batch_preserves_application_exit_code(tmp_path, exit_code):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "source app"
    target.mkdir()
    shutil.copy2(root / "启动.bat", target / "启动.bat")
    (target / ".env").write_text("", encoding="utf-8")
    (target / "launch_local.py").write_text(
        f"import sys; print('LOCAL_ENTRY_RAN'); sys.exit({exit_code})", encoding="utf-8",
    )
    subprocess.run(
        [str(Path(sys.base_prefix) / "python.exe"), "-m", "venv", "--without-pip", str(target / ".venv")],
        check=True, capture_output=True, timeout=30,
    )
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(target / "启动.bat")],
        cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
    )
    assert b"LOCAL_ENTRY_RAN" in result.stdout, result.stderr
    assert result.returncode == exit_code


def test_launcher_logs_original_error_and_restores_streams(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launch_local, "APP_DIR", tmp_path)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(launch_local.runpy, "run_path", Mock(side_effect=RuntimeError("original startup failure")))
    show_error = Mock()
    monkeypatch.setattr(launch_local, "show_startup_error", show_error)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    with pytest.raises(RuntimeError, match="original startup failure"):
        launch_local.main()
    assert "original startup failure" in (tmp_path / "logs/launcher.log").read_text(encoding="utf-8")
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    assert os.environ["WECOM_AUTOSTART"] == "0"
    show_error.assert_called_once_with(tmp_path / "logs/launcher.log")


def test_missing_tk_can_still_report_failure_to_log(monkeypatch, capsys):
    import tkinter
    monkeypatch.setattr(tkinter, "Tk", Mock(side_effect=RuntimeError("Tk unavailable")))
    launch_local.show_startup_error(Path("logs/launcher.log"))
    assert "Tk unavailable" in capsys.readouterr().err
