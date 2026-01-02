# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

project_root = Path.cwd()

resource_datas = []
for folder in ("data", "ffmpeg_bin"):
    src = project_root / folder
    if src.exists():
        resource_datas.append((str(src), folder))

credentials_file = project_root / "credentials.json"
if credentials_file.exists():
    resource_datas.append((str(credentials_file), "."))

hiddenimports = collect_submodules("local_ffmpeg") + [
    "hotkey_listener",
]
resource_datas.extend(collect_data_files("azure.cognitiveservices.speech"))
resource_datas.extend(collect_data_files("tiktoken", includes=["**/*.json", "**/*.tiktoken"]))

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=resource_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MaddiePly',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MaddiePly',
)
