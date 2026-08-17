# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FRIDAY OS.

Build with (from the project root, on Windows, inside the project's venv):
    pyinstaller installer/friday_os.spec --noconfirm

Output lands in dist/FridayOS/ (onedir build — deliberately NOT --onefile;
a onefile build re-extracts the entire bundle to a temp directory on
every single launch, which is a genuinely bad experience for an app
that's meant to auto-start with Windows and stay resident. onedir starts
fast and only needs the initial install to unpack anything).

This file is invoked by scripts/build_installer.ps1, which runs this
step and then hands dist/FridayOS/ to Inno Setup. You normally shouldn't
need to run this directly — use that script instead, it also verifies
prerequisites (venv active, Inno Setup found) before starting.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

block_cipher = None

# --- Packages that need their full data/binaries/hidden-imports collected ---
# (native libs, model files, or dynamic-import patterns PyInstaller's
# static analysis can't discover on its own — each comment explains why
# that specific package needs this rather than working automatically)
datas = []
binaries = []
hiddenimports = []

for pkg in [
    "faster_whisper",   # ships model config as package data
    "ctranslate2",       # faster-whisper's inference backend; native shared libs
    "pvporcupine",        # ships .ppn/.pv keyword+model files as package data
    "playwright",          # spawns a bundled Node driver subprocess found via package data
    "mplfinance",            # ships style/config data
    "matplotlib",              # ships font and rc config data; also needs the Agg backend hidden-imported
    "tiktoken_ext",              # transitive: some tokenizer backends probe this via plugin discovery
]:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        # A package not installed in THIS build environment (e.g. an
        # optional TTS/STT engine the person building didn't install)
        # must not abort the whole build -- skip it, the resulting exe
        # just won't have that optional capability.
        pass

# App resources that are read at runtime relative to project_root (see
# app/core/config.py's PROJECT_ROOT / user_data_root split) -- these are
# READ-ONLY bundled resources, not user data, so they belong in the
# frozen bundle itself, not in %LOCALAPPDATA%.
datas += [
    (os.path.join(PROJECT_ROOT, "config", "settings.yaml"), "config"),
    (os.path.join(PROJECT_ROOT, "alembic.ini"), "."),
    (os.path.join(PROJECT_ROOT, "alembic"), "alembic"),
    (os.path.join(PROJECT_ROOT, "installer", "app_icon.ico"), "."),
]

hiddenimports += [
    "sqlalchemy.dialects.sqlite.pysqlite",
    "matplotlib.backends.backend_agg",
    "PySide6.QtSvg",  # icon rendering used by several Qt widgets even when not imported directly
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "app", "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dev/test-only tooling that has no business in a shipped build.
        "pytest", "pytest_asyncio", "pytest_mock", "pytest_cov",
        "black", "ruff", "mypy",
    ],
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
    name="FridayOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed PyInstaller exes get flagged by some AV/SmartScreen heuristics far more often
    console=False,  # windowed app -- no console window behind the GUI
    icon=os.path.join(PROJECT_ROOT, "installer", "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FridayOS",
)
