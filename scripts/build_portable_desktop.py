"""Assemble the desktop app with bundled Python and ONNX Runtime.

Prepare bge_model/ and install onnx==1.17.0 on the build machine before
building. Use --empty-library when delivering the knowledge files separately.
"""
import argparse
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'dist' / 'WeComBot'
MODEL = ROOT / 'bge_model'
PACKAGES = ('config', 'debug', 'gateway', 'gui', 'notify', 'pipeline', 'rag', 'stats', 'wxbot')
CRT_FILES = ('msvcp140.dll', 'msvcp140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dest', type=Path, nargs='?', default=ROOT / 'dist' / 'WeComBot-Desktop')
    parser.add_argument('--empty-library', action='store_true')
    args = parser.parse_args()
    dest = args.dest.resolve()
    model = MODEL / 'model.onnx'
    weights = MODEL / 'model.safetensors'
    if not model.is_file() or model.stat().st_mtime < weights.stat().st_mtime:
        subprocess.run([sys.executable, str(ROOT / 'scripts/export_bge_onnx.py')], check=True)

    dest.mkdir(parents=True, exist_ok=False)
    common_ignores = ('__pycache__', '*.pyc', '*.pyo')
    runtime = dest / '_internal' / 'python'
    shutil.copytree(ROOT / 'runtime', runtime, ignore=shutil.ignore_patterns(*common_ignores))
    # Copy the matching Visual C++ runtime that was collected by the Windows build.
    for name in CRT_FILES:
        shutil.copy2(ASSETS / '_internal' / name, runtime / name)
    shutil.copytree(ROOT / '.venv/Lib/site-packages', runtime / 'Lib/site-packages',
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        *common_ignores, 'torch', 'torch-*.dist-info', 'torchgen', 'functorch',
                        'sentence_transformers', 'sentence_transformers-*.dist-info',
                        'transformers', 'transformers-*.dist-info', 'onnx', 'onnx-*.dist-info',
                    ))
    for package in PACKAGES:
        for source in (ROOT / package).rglob('*.py'):
            target = dest / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for name in ('main.py', 'launch_local.py', 'app_paths.py', 'app_session.py', 'app_version.py'):
        shutil.copy2(ROOT / name, dest / name)
    (dest / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/assistant_mcp.py', dest / 'scripts/assistant_mcp.py')
    for name in ('.env.example', '使用说明.txt', '使用说明-详细.md', '界面更新-1.5.0.md', 'UI-开源许可.txt'):
        shutil.copy2(ASSETS / name, dest / name)
    config = json.loads((ASSETS / 'config.json').read_text(encoding='utf-8'))
    config.setdefault('customers', {})['whitelist'] = []
    (dest / 'config.json').write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    for name in ('prompts', 'profiles'):
        shutil.copytree(ASSETS / name, dest / name)
    if not args.empty_library:
        shutil.copytree(ASSETS / 'data', dest / 'data')
    else:
        manifest = Path('data/kb/archives.json')
        if (ASSETS / manifest).is_file():
            (dest / manifest.parent).mkdir(parents=True)
            shutil.copy2(ASSETS / manifest, dest / manifest)
    shutil.copytree(ASSETS / '_internal/assets', dest / 'assets')
    shutil.copytree(ROOT / 'web/workbench/bundle', dest / 'web/workbench/bundle')
    (dest / 'bge_model').mkdir()
    for source in (model, MODEL / 'tokenizer.json'):
        shutil.copy2(source, dest / 'bge_model' / source.name)
    version = runpy.run_path(str(ROOT / 'app_version.py'))
    (dest / version['BUILD_FILE']).write_text(version['source_build_id'](), encoding='utf-8')
    (dest / 'logs').mkdir()
    launcher = '@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\nif not exist ".env" copy /y ".env.example" ".env" >nul\nstart "" "%~dp0_internal\\python\\pythonw.exe" "%~dp0launch_local.py"\n'
    (dest / '启动.bat').write_text(launcher, encoding='utf-8', newline='\r\n')
    # Test the shipped model and native DLLs with the same Python as the launcher.
    subprocess.run([
        str(runtime / 'python.exe'), '-B', '-c',
        'import importlib.util; from rag.embed_query import embed_query; '
        'assert importlib.util.find_spec("torch") is None; '
        'assert len(embed_query("资料库")) == 512',
    ], cwd=dest, check=True, timeout=60)
    subprocess.run([sys.executable, str(ROOT / 'scripts/privacy_check.py'), '--path', str(dest)], check=True)
    print('Desktop package:', dest, flush=True)


if __name__ == '__main__':
    main()
