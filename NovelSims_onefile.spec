# PyInstaller spec — ONEFILE variant (single NovelSims.exe)
# _decimal.pyd is added explicitly as a binary; on Windows CPython 3.13 libmpdec is statically linked into it.
import sys, os
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "bridge" / "ui" / "dashboard.html"), "bridge/ui"),
    (str(ROOT / "bridge" / "ui" / "assets"), "bridge/ui/assets"),
    (str(ROOT / "data" / "examples"), "data/examples"),
]
binaries = []
_dec = os.path.join(sys.base_prefix, "DLLs", "_decimal.pyd")
if os.path.exists(_dec):
    binaries.append((_dec, "."))
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NovelSims",
    icon=str(ROOT / "assets" / "novelsims.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    # Onefile extraction directory.
    # PyInstaller 6.16 expands %ENV% on Windows, then resolves a relative
    # runtime_tmpdir with _wfullpath against the process working directory,
    # not the directory that contains the exe. "." is therefore not "<exe dir>".
    # The bootloader also has no "try this folder, else another" fallback: if
    # the chosen directory cannot be created, extraction fails and the exe
    # does not start. Keep the cache under %LOCALAPPDATA%\NovelSims\_runtime
    # (stable, per-user, not %TEMP%). To keep the program off a full C: drive,
    # use the installer or the portable folder and install it on another drive;
    # that build does not unpack a onefile cache. A portable.flag (or a data
    # folder) next to the exe still stores logs and the database in <exe>\data.
    runtime_tmpdir=r"%LOCALAPPDATA%\NovelSims\_runtime",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
