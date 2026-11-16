"""Bridge configuration. Priority: CLI args > config file > environment > defaults."""
import argparse
import json
import os
import sys
from dataclasses import dataclass, field, fields


def portable_data_dir():
    """Data directory beside a frozen exe when the install is marked portable.

    A file named portable.flag, or an existing data directory, next to the
    executable selects <exe dir>\\data. That keeps logs, the database and
    caches off the system drive when the program itself is installed elsewhere.
    Development runs (not frozen) stay on the default per-user directory.
    """
    if not getattr(sys, "frozen", False):
        return None
    folder = os.path.dirname(os.path.abspath(sys.executable))
    flag = os.path.join(folder, "portable.flag")
    data = os.path.join(folder, "data")
    if os.path.isfile(flag) or os.path.isdir(data):
        return data
    return None


def default_data_dir():
    env = os.environ.get("NOVELSIMS_DIR")
    if env:
        return env
    portable = portable_data_dir()
    if portable:
        return portable
    # Use a simpler, more reliable location to avoid Documents permission issues
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "NovelSims")


@dataclass
class Config:
    host: str = "127.0.0.1"          # local only by default (spec 11.6)
    http_port: int = 8765
    tcp_port: int = 8766
    data_dir: str = field(default_factory=default_data_dir)
    examples_dir: str = ""
    llm_provider: str = "mock"       # mock | ollama
    mock_mode: str = "ok"            # ok | bad_json | ooc | wrongid | slow | error
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: float = 25.0
    token: str = ""                  # optional access token; never logged
    max_context_chars: int = 6000
    max_dialogue_chars: int = 200
    enable_http: bool = True
    enable_tcp: bool = True
    enable_file_ipc: bool = True
    ipc_poll_interval_s: float = 0.2
    ipc_stale_s: float = 120.0
    worker_threads: int = 4
    open_dashboard: bool = True
    native_window: bool = True

    def redacted(self):
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["token"] = "***" if self.token else ""
        return d


def load_config(argv=None):
    p = argparse.ArgumentParser(description="NovelSims bridge")
    p.add_argument("--data-dir")
    p.add_argument("--examples-dir")
    p.add_argument("--http-port", type=int)
    p.add_argument("--tcp-port", type=int)
    p.add_argument("--llm", dest="llm_provider", choices=["mock", "ollama"])
    p.add_argument("--mock-mode")
    p.add_argument("--ollama-url")
    p.add_argument("--ollama-model")
    p.add_argument("--no-http", action="store_true")
    p.add_argument("--no-tcp", action="store_true")
    p.add_argument("--no-file-ipc", action="store_true")
    p.add_argument("--no-native-window", action="store_true", help="disable the native desktop window (dashboard will not open)")
    p.add_argument("--no-dashboard", action="store_true", help="do not open the dashboard window")
    args = p.parse_args(argv)

    cfg = Config()
    if os.environ.get("NOVELSIMS_TOKEN"):
        cfg.token = os.environ["NOVELSIMS_TOKEN"]
    if args.data_dir:
        cfg.data_dir = args.data_dir

    cfg_file = os.path.join(cfg.data_dir, "bridge_config.json")
    if os.path.isfile(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            names = {f.name for f in fields(Config)}
            for k, v in data.items():
                if k in names:
                    setattr(cfg, k, v)
        except (OSError, ValueError):
            pass  # a broken config file must not stop the bridge

    for name in ("examples_dir", "http_port", "tcp_port", "llm_provider",
                 "mock_mode", "ollama_url", "ollama_model"):
        v = getattr(args, name)
        if v is not None:
            setattr(cfg, name, v)
    if args.no_http:
        cfg.enable_http = False
    if args.no_tcp:
        cfg.enable_tcp = False
    if args.no_file_ipc:
        cfg.enable_file_ipc = False
    if args.no_dashboard:
        cfg.open_dashboard = False
    if args.no_native_window:
        cfg.native_window = False
    if not cfg.examples_dir:
        cfg.examples_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "examples")
    return cfg
