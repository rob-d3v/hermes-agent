# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — avatar_voice
# Gera: dist/avatar_voice/avatar_voice.exe
#
# Uso:
#   cd avatar_voice
#   pyinstaller build.spec

import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# ── Coleta de dados dos pacotes complexos ─────────────────────────────────────
ctk_datas                          = collect_data_files("customtkinter")
ow_datas,  ow_bins,  ow_hidden     = collect_all("openwakeword")
fw_datas,  fw_bins,  fw_hidden     = collect_all("faster_whisper")
ct_datas,  ct_bins,  ct_hidden     = collect_all("ctranslate2")
ort_datas, ort_bins, ort_hidden    = collect_all("onnxruntime")
sd_datas,  sd_bins,  sd_hidden     = collect_all("sounddevice")
tok_datas, tok_bins, tok_hidden    = collect_all("tokenizers")

all_datas = (
    ctk_datas + ow_datas + fw_datas + ct_datas + ort_datas + sd_datas + tok_datas +
    [("config.yaml.example", ".")]
)
all_bins    = ow_bins + fw_bins + ct_bins + ort_bins + sd_bins + tok_bins
all_hidden  = (
    ow_hidden + fw_hidden + ct_hidden + ort_hidden + sd_hidden + tok_hidden +
    [
        # Módulos do pipeline
        "main", "config", "agent_client", "audio_player",
        "phrases", "stt_whisper", "tts_piper", "wake_word", "web_dashboard",
        # Deps padrão
        "yaml", "requests", "requests.adapters", "requests.auth",
        "numpy", "pyaudio",
        # FastAPI / uvicorn
        "fastapi", "uvicorn",
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan",
        "uvicorn.lifespan.on", "anyio", "starlette",
        # Outros
        "scipy", "scipy.signal", "winreg",
    ]
)

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["app.py"],
    pathex=[os.path.abspath(".")],   # inclui main.py, config.py, etc.
    binaries=all_bins,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "PIL", "IPython", "notebook", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE ───────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="avatar_voice",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # sem janela de terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # troque por "icon.ico" se tiver
)

# ── COLLECT (onedir) ──────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="avatar_voice",
)
