# -*- coding: utf-8 -*-
"""NovelSims Windows entry point with a startup crash reporter.

The app logic is unchanged: this only wraps bridge.main.main([]) so that a failed
start never ends silently. Any exception or non-zero exit code is written to
startup_error.log under the data directory (beside the exe when portable.flag
or a data folder is present, otherwise %LOCALAPPDATA%\\NovelSims) and shown in
a Windows message box.
NovelSims_debug.exe (console build) additionally prints everything to the console
and waits for Enter before closing.
"""
import multiprocessing
import os
import sys
import time
import traceback

APP = "NovelSims"
EXE_NAME = os.path.basename(sys.executable or "").lower()
DEBUG = "debug" in EXE_NAME or os.environ.get("NOVELSIMS_DEBUG") == "1"

EXIT_HINTS = {
    1: "端口 8765 或 8766 已被占用，所以这次没有启动新的窗口。\n"
       "多半还有一个旧的 NovelSims 或 NovelSims_Bridge 在运行。请打开任务管理器，结束 NovelSims.exe 和 pythonw.exe 后再试。\n"
       "新程序不会再悄悄连上旧后端。",
    2: "桌面窗口无法启动。\n请确认已安装 Microsoft Edge WebView2 Runtime 和 .NET Framework 4.8，"
       "并检查杀毒软件是否拦截了 NovelSims。\n"
       "WebView2 下载：https://developer.microsoft.com/microsoft-edge/webview2/",
}

WEBVIEW2_MISSING = (
    "未检测到 Microsoft Edge WebView2 运行库，NovelSims 无法显示窗口。\n"
    "请从微软官网下载并安装 WebView2 Runtime：\n"
    "https://developer.microsoft.com/microsoft-edge/webview2/"
)


def _apply_portable_data_dir():
    """Point NOVELSIMS_DIR at <exe>\\data when this frozen copy is portable.

    bridge.config.default_data_dir reads the same marker. Setting the variable
    here also covers startup_error.log and native_crash.log, and the watchdog
    child inherits it.
    """
    if os.environ.get("NOVELSIMS_DIR"):
        return
    try:
        from bridge.config import portable_data_dir
        path = portable_data_dir()
    except Exception:
        return
    if path:
        os.environ["NOVELSIMS_DIR"] = path


def _data_dir():
    _apply_portable_data_dir()
    env = os.environ.get("NOVELSIMS_DIR")
    if env:
        return env
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP)


def _candidate_log_paths():
    yield os.path.join(_data_dir(), "startup_error.log")
    yield os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"), "NovelSims_startup_error.log")
    yield os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "startup_error.log")


def _write_log(text):
    for path in _candidate_log_paths():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except Exception:
            continue
    return None


def _message_box(text, title="NovelSims 启动失败"):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x10000)  # MB_ICONERROR | MB_SETFOREGROUND
    except Exception:
        pass


def _console(msg):
    if (DEBUG or os.environ.get("NOVELSIMS_DEBUG") == "1") and sys.stdout is not None:
        try:
            print(msg, flush=True)
        except Exception:
            try:
                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
                sys.stdout.buffer.write((msg + "\n").encode(enc, "replace"))
                sys.stdout.flush()
            except Exception:
                pass


def _tail(path, n=25):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-n:])
    except Exception:
        return ""


def _environment_report():
    lines = ["time: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "exe: %s" % sys.executable,
             "python: %s" % sys.version.replace("\n", " "),
             "frozen: %s  bundle: %s" % (getattr(sys, "frozen", False), getattr(sys, "_MEIPASS", "")),
             "data_dir: %s" % _data_dir()]
    try:
        import platform
        lines.append("windows: %s" % platform.platform())
    except Exception:
        pass
    try:
        import winreg
        key = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        found = []
        for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + key),
                          (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + key),
                          (winreg.HKEY_CURRENT_USER, "Software\\" + key)):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    found.append(winreg.QueryValueEx(k, "pv")[0])
            except OSError:
                pass
        lines.append("webview2_runtime: %s" % (", ".join(found) if found else "NOT FOUND"))
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
                lines.append(".NET Framework 4 release: %s" % winreg.QueryValueEx(k, "Release")[0])
        except OSError:
            lines.append(".NET Framework 4: NOT FOUND")
    except Exception:
        pass
    return "\n".join(lines)


def _unblock_bundle():
    """Remove the 'downloaded from the internet' mark (Zone.Identifier) from bundled files.

    When a zip downloaded from the web is extracted with Explorer, every DLL inherits this
    mark and .NET then refuses to load Python.Runtime.dll / WebView2 assemblies, so the
    window never appears. Harmless no-op when the mark is absent.
    """
    root = getattr(sys, "_MEIPASS", None)
    if os.name != "nt" or not root:
        return 0
    removed = 0
    for base, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith((".dll", ".pyd", ".exe")):
                try:
                    os.remove(os.path.join(base, f) + ":Zone.Identifier")
                    removed += 1
                except OSError:
                    pass
    return removed


def _report(title, detail, code=None, summary=None):
    bridge_log = os.path.join(_data_dir(), "bridge.log")
    text = ("\n==================== %s ====================\n%s\n\n%s\n\n--- bridge.log (last lines) ---\n%s\n"
            % (title, _environment_report(), detail, _tail(bridge_log)))
    path = _write_log(text)
    _console(text)
    summary_text = summary or detail.strip()[-900:]
    if "webview2_runtime: NOT FOUND" in text:
        summary_text = WEBVIEW2_MISSING + "\n\n" + summary_text
    box = "%s\n\n%s\n\n详细信息已保存到：\n%s\n\n运行日志：\n%s" % (
        title, summary_text, path or "(无法写入日志)", bridge_log)
    _message_box(box)


REPORTED = 100   # child exit code offset meaning "error already reported to the user"


def _run_app():
    """Child process: run the real app, report Python-level failures itself."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            if stream is not None:
                stream.reconfigure(errors="replace")   # never let a non-UTF-8 console crash logging
        except Exception:
            pass
    native_log = None
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        import faulthandler
        native_log = open(os.path.join(_data_dir(), "native_crash.log"), "a", encoding="utf-8")
        native_log.write("\n--- start %s pid %s ---\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
        native_log.flush()
        faulthandler.enable(file=native_log, all_threads=True)
    except Exception:
        pass
    try:
        n = _unblock_bundle()
        if n:
            _console("removed internet download mark from %d bundled files" % n)
    except Exception:
        pass

    code = 0
    try:
        from bridge.main import main as bridge_main
        code = bridge_main([])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if code:
            _report("NovelSims 异常退出 (SystemExit %s)" % exc.code, traceback.format_exc(), code)
            return REPORTED + code
    except BaseException:
        _report("NovelSims 启动时出错", traceback.format_exc(), 3)
        return REPORTED + 3
    if code:
        _report("NovelSims 已退出（代码 %s）" % code, EXIT_HINTS.get(code, "未知原因，请查看日志。"), code)
        return REPORTED + code
    return 0


def _native_crash_detail(rc):
    tail = _tail(os.path.join(_data_dir(), "native_crash.log"), 60)
    marker = tail.rfind("--- start")
    tail = tail[marker:] if marker >= 0 else tail
    return ("程序在 Python 之外崩溃（退出代码 %s / 0x%08X）。\n"
            "常见原因：缺少 .NET Framework 4.8 或 WebView2 Runtime，或杀毒软件拦截了 DLL。\n"
            "WebView2 下载：https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "--- native_crash.log ---\n%s" % (rc, rc & 0xFFFFFFFF, tail))


def main():
    multiprocessing.freeze_support()
    _apply_portable_data_dir()
    if os.environ.get("NOVELSIMS_CHILD") == "1" or not getattr(sys, "frozen", False):
        return _run_app()
    # Watchdog parent: run the app in a child process so that even a native crash
    # (which kills Python instantly) still produces a message box and a log entry.
    if DEBUG:
        _console("NovelSims debug console\n" + _environment_report() + "\n")
    env = dict(os.environ, NOVELSIMS_CHILD="1")
    if DEBUG:
        env["NOVELSIMS_DEBUG"] = "1"
    try:
        import subprocess
        kwargs = {}
        if not DEBUG:
            kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rc = subprocess.call([sys.executable] + sys.argv[1:], env=env, **kwargs)
    except BaseException:
        _report("NovelSims 无法启动子进程", traceback.format_exc(), 3)
        rc = REPORTED + 3
    if rc == 0:
        code = 0
    elif rc >= REPORTED and rc < REPORTED + 50:
        code = rc - REPORTED
    else:
        code = rc
        _report("NovelSims 意外崩溃", _native_crash_detail(rc), rc,
                summary=_native_crash_detail(rc).split("--- native_crash.log ---")[0].strip()
                + "\n\n崩溃堆栈见 native_crash.log。")
    if DEBUG:
        _console("\nNovelSims exited with code %s." % code)
        try:
            input("按回车键关闭窗口 / Press Enter to close...")
        except Exception:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
