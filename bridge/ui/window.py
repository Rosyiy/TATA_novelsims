# -*- coding: utf-8 -*-
"""Native Windows desktop shell for NovelSims (standard resizable window)."""
import logging

log = logging.getLogger("novelsims.window")
TITLE = "NovelSims"
QUIT_TEXT = "确定退出 NovelSims 吗？退出后，游戏将无法连接后端。"
WIDTH, HEIGHT = 1280, 800


class NativeWindowApi(object):
    def minimize(self):
        import webview
        window = webview.active_window()
        if window:
            window.minimize()
        return True

    def maximize(self):
        import webview
        window = webview.active_window()
        if not window:
            return False
        try:
            if getattr(self, "_maximized", False):
                window.restore()
                self._maximized = False
            else:
                window.maximize()
                self._maximized = True
        except Exception:
            window.toggle_fullscreen()
        return True

    def close(self):
        import webview
        window = webview.active_window()
        if window:
            window.destroy()
        return True


def run_native_window(url, title=TITLE):
    """Launch the embedded Edge WebView as a normal desktop window."""
    try:
        import webview
        window = webview.create_window(
            title, url=url, width=WIDTH, height=HEIGHT,
            min_size=(960, 640), resizable=True,
            frameless=True, easy_drag=False, transparent=True, shadow=True,
            confirm_close=True, background_color="#ECEBE1",
            js_api=NativeWindowApi(),
            localization={"global.quitConfirmation": QUIT_TEXT},
        )
        webview.start(gui="edgechromium", debug=False)
        return True
    except Exception as exc:
        log.exception("NovelSims 桌面窗口启动失败：%s", exc)
        return False
