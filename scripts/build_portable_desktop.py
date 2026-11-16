"""Assemble the desktop app with the existing signed, bundled Python runtime.

This distribution needs neither a system Python installation nor an unsigned
PyInstaller launcher. Content assets come from the privacy-checked build folder.
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'dist' / 'WeComBot-Desktop'
ASSETS = ROOT / 'dist' / 'WeComBot'
PACKAGES = ('config', 'debug', 'gateway', 'gui', 'notify', 'pipeline', 'rag', 'stats', 'wxbot')


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    ignored = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    runtime = DEST / '_internal' / 'python'
    shutil.copytree(ROOT / 'runtime', runtime, ignore=ignored)
    shutil.copytree(ROOT / '.venv/Lib/site-packages', runtime / 'Lib/site-packages',
                    dirs_exist_ok=True, ignore=ignored)
    for package in PACKAGES:
        for source in (ROOT / package).rglob('*.py'):
            target = DEST / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for name in ('main.py', 'launch_local.py', 'app_paths.py', 'app_session.py', 'app_version.py'):
        shutil.copy2(ROOT / name, DEST / name)
    for name in ('config.json', '.env.example', '使用说明.txt', '使用说明-详细.md', '界面更新-1.5.0.md', 'UI-开源许可.txt'):
        shutil.copy2(ASSETS / name, DEST / name)
    for name in ('data', 'prompts', 'profiles'):
        shutil.copytree(ASSETS / name, DEST / name)
    for name in ('bge_model', 'assets', 'web'):
        shutil.copytree(ASSETS / '_internal' / name, DEST / name)
    shutil.copy2(ASSETS / '_internal/wecom-build-id.txt', DEST / 'wecom-build-id.txt')
    (DEST / 'logs').mkdir(exist_ok=True)
    launcher = '@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\nif not exist ".env" copy /y ".env.example" ".env" >nul\nstart "" "%~dp0_internal\\python\\pythonw.exe" "%~dp0launch_local.py"\n'
    (DEST / '启动.bat').write_text(launcher.replace('\n', '\r\n'), encoding='utf-8')
    subprocess.run([sys.executable, str(ROOT / 'scripts/privacy_check.py'), '--path', str(DEST)], check=True)
    print('Desktop package:', DEST, flush=True)


if __name__ == '__main__':
    main()
