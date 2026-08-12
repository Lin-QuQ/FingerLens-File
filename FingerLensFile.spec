# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs


ROOT = Path(SPEC).resolve().parent
IS_MACOS = sys.platform == "darwin"
mediapipe_binaries = collect_dynamic_libs("mediapipe")
ffmpeg_datas, ffmpeg_binaries, ffmpeg_hidden = collect_all("imageio_ffmpeg")

a = Analysis(
    [str(ROOT / "finger_lens_file.py")],
    pathex=[str(ROOT)],
    binaries=mediapipe_binaries + ffmpeg_binaries,
    datas=[
        (str(ROOT / "models" / "hand_landmarker.task"), "models"),
        (str(ROOT / "assets" / "fingerlens-icon.png"), "assets"),
    ] + ffmpeg_datas,
    hiddenimports=ffmpeg_hidden,
    excludes=["matplotlib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
icon_path = ROOT / "assets" / ("fingerlens.icns" if IS_MACOS else "fingerlens.ico")
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FingerLensFile",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FingerLensFile",
)
if IS_MACOS:
    app = BUNDLE(
        coll,
        name="FingerLens File.app",
        icon=str(icon_path),
        bundle_identifier="com.linmenmen.fingerlensfile",
        version="1.6.4",
        info_plist={
            "CFBundleDisplayName": "FingerLens 文件版",
            "CFBundleName": "FingerLens File",
            "CFBundleShortVersionString": "1.6.4",
            "CFBundleVersion": "15",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        },
    )
