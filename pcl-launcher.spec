# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：麦块启动器（PCL-Launcher）。

构建（Windows / Wine 均可）：
    pyinstaller --noconfirm --clean pcl-launcher.spec
"""

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

datas = [(str(ROOT / "launcher" / "resources"), "launcher/resources")]

# 捆绑 VC++ 运行库，保证干净系统也能运行
binaries = []
_vc = ROOT / "launcher" / "vcredist"
if _vc.exists():
    binaries += [(str(dll), ".") for dll in sorted(_vc.glob("*.dll"))]

hiddenimports = [
    "launcher",
    "launcher.core",
    "launcher.core.paths",
    "launcher.core.net",
    "launcher.core.config",
    "launcher.core.java",
    "launcher.core.auth",
    "launcher.core.version",
    "launcher.core.installer",
    "launcher.core.launch",
    "launcher.core.instances",
    "launcher.core.modrinth",
    "launcher.ui",
    "launcher.ui.app",
    "launcher.ui.icons",
    "launcher.ui.theme",
    "launcher.ui.widgets",
    "launcher.ui.dialogs",
    "launcher.ui.window",
    "launcher.ui.pages",
    "launcher.ui.pages.home",
    "launcher.ui.pages.download",
    "launcher.ui.pages.versions",
    "launcher.ui.pages.mods",
    "launcher.ui.pages.settings",
    "PySide6.QtSvg",
    "PySide6.QtNetwork",
]

excludes = [
    "tkinter", "unittest", "pydoc", "doctest",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine", "PySide6.QtTest", "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtXmlPatterns",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PCL-Launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "launcher" / "resources" / "app.ico"),
    version=None,
)
