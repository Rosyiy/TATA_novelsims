"""Entry point:  python -m bridge.main [--llm ollama --ollama-model qwen2.5:7b]"""
import json
import logging
import os
import sys
import time

from .api.file_ipc import FileIpcServer
from .api.http_server import start_http
from .api.tcp_server import start_tcp
from .app import App
from .config import load_config


def _setup_logging(data_dir):
    """File log always (the exe runs without a console); console too when there is one."""
    import logging.handlers
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream) is None:          # pythonw.exe
            setattr(sys, stream, open(os.devnull, "w"))
    handlers = []
    try:
        os.makedirs(data_dir, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            os.path.join(data_dir, "bridge.log"), maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers or None, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _port_taken(port):
    """Return a Chinese explanation if something is already listening, else ''."""
    import socket
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/v1/health" % port, timeout=0.6) as resp:
            raw = resp.read(500)
        ver = "未知版本"
        try:
            ver = str(json.loads(raw.decode("utf-8", "replace")).get("version") or ver)
        except ValueError:
            pass
        return "8765/8766 上已有 NovelSims %s 在回答。请先关掉旧窗口或任务管理器中的 NovelSims.exe / pythonw.exe" % ver
    except Exception:
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return "端口 %d 已被其他程序占用。若刚关过 NovelSims，请在任务管理器中结束残留进程后再打开" % port
    finally:
        sock.close()
    return ""


def main(argv=None):
    cfg = load_config(argv)
    try:
        os.makedirs(cfg.data_dir, exist_ok=True)
    except Exception as e:
        print("无法创建数据目录:", cfg.data_dir, e)
        raise
    _setup_logging(cfg.data_dir)
    log = logging.getLogger("novelsims.main")
    app = App(cfg)
    log.info("config: %s", cfg.redacted())

    for cid, name in app.imported:
        log.info("character %s  %s", cid, name)

    taken = _port_taken(cfg.http_port) or _port_taken(cfg.tcp_port)
    if taken:
        log.error("端口已被占用：%s。请先关闭旧的 NovelSims / NovelSims_Bridge / pythonw，再重新打开。", taken)
        return 1
    servers = []
    try:
        if cfg.enable_http:
            servers.append(start_http(app.router, cfg.host, cfg.http_port, app.dashboard_html))
            log.info("HTTP  http://%s:%d/api/v1/", cfg.host, cfg.http_port)
        if cfg.enable_tcp:
            servers.append(start_tcp(app.router, cfg.host, cfg.tcp_port))
            log.info("TCP   %s:%d", cfg.host, cfg.tcp_port)
    except OSError as exc:
        log.error("端口被占用或无法监听（%s）。请结束仍在运行的旧 NovelSims 后再打开。", exc)
        for s in servers:
            s.shutdown()
            s.server_close()
        return 1
    ipc = None
    if cfg.enable_file_ipc:
        ipc = FileIpcServer(app.router, cfg.data_dir, cfg.ipc_poll_interval_s,
                            cfg.ipc_stale_s, cfg.worker_threads)
        ipc.start()
        log.info("FILE  %s", cfg.data_dir)
    url = "http://127.0.0.1:%d/" % cfg.http_port
    try:
        if cfg.enable_http and cfg.open_dashboard:
            log.info("管理界面 Dashboard: %s", url)
            from .ui.window import run_native_window
            if not cfg.native_window:
                log.error("当前版本要求使用原生桌面窗口；已禁用浏览器回退。")
                return 2
            if not run_native_window(url):
                log.error("原生桌面窗口无法启动；未打开浏览器。请检查 WebView2 Runtime。")
                return 2
            log.info("desktop window closed -> shutting down")
            return 0
        elif cfg.enable_http:
            log.info("管理界面 Dashboard: %s", url)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        for s in servers:
            s.shutdown()
            s.server_close()
        if ipc:
            ipc.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
