# PyInstaller spec — prefer onedir for reliability (avoids _decimal.pyd extract failures)
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "bridge" / "ui" / "dashboard.html"), "bridge/ui"),
    (str(ROOT / "bridge" / "ui" / "assets"), "bridge/ui/assets"),
    (str(ROOT / "data" / "examples"), "data/examples"),
]
binaries = []
hiddenimports = [
    "webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
    "bottle", "clr", "clr_loader", "clr_loader.util.find", "pythonnet",
    "pythonnet.runtime", "webview.util", "webview.menu",
    "decimal", "_decimal",
]
for package in ("webview", "bottle", "clr_loader", "pythonnet"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "novelsims_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Use onedir (more reliable than onefile for this error)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NovelSims",
    icon=str(ROOT / "assets" / "novelsims.ico"),
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NovelSims",
)
