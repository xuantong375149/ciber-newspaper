#!/usr/bin/env python3
"""本地新闻站服务：提供页面，并支持页面上的「立即更新」按钮触发抓取。

只监听 127.0.0.1，不对外网开放。
用法：pythonw server.py（或双击 start_server.bat）
"""
from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import config
import fetch_news


def log(message: str) -> None:
    line = f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        print(line, flush=True)
    except (UnicodeEncodeError, OSError):
        pass
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "server.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


_state_lock = threading.Lock()
_state = {
    "running": False,
    "last_started": None,
    "last_finished": None,
    "last_ok": None,
    "last_message": "",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def snapshot() -> dict:
    with _state_lock:
        data = dict(_state)
    index = config.SITE_DIR / "index.html"
    if index.exists():
        data["generated_at"] = (
            datetime.fromtimestamp(index.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        )
    else:
        data["generated_at"] = None
    return data


def _run_update() -> None:
    ok = False
    message = ""
    try:
        code = fetch_news.main()
        ok = code == 0
        message = "更新完成" if ok else "没有抓到新内容，已保留旧页面"
    except Exception as exc:  # noqa: BLE001 - 记录到状态供页面显示
        message = f"{type(exc).__name__}: {exc}"
        log("更新失败：\n" + traceback.format_exc())
    finally:
        with _state_lock:
            _state.update(
                running=False,
                last_finished=_now_iso(),
                last_ok=ok,
                last_message=message,
            )
        log(f"更新结束：{message}")


def start_update() -> bool:
    with _state_lock:
        if _state["running"]:
            return False
        _state.update(running=True, last_started=_now_iso(), last_message="")
    threading.Thread(target=_run_update, daemon=True, name="news-update").start()
    return True


def _host_allowed(host: str) -> bool:
    host = (host or "").split(":")[0].strip().lower()
    return host in ("127.0.0.1", "localhost", "[::1]")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(config.SITE_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):  # 不把每个静态请求写进日志，避免噪音
        pass

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            self._send_json(200, snapshot())
            return
        if not _host_allowed(self.headers.get("Host", "")):
            self._send_json(403, {"error": "forbidden host"})
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/update":
            self._send_json(404, {"error": "not found"})
            return
        # 自定义请求头用于阻止其他网页的跨站触发
        if self.headers.get("X-News-Update") != "1":
            self._send_json(403, {"error": "missing X-News-Update header"})
            return
        if not _host_allowed(self.headers.get("Host", "")):
            self._send_json(403, {"error": "forbidden host"})
            return
        started = start_update()
        self._send_json(202 if started else 409, {"started": started, "status": snapshot()})
        if started:
            log("收到页面更新请求，开始抓取")


def main() -> int:
    try:
        server = ThreadingHTTPServer((config.SERVER_HOST, config.SERVER_PORT), Handler)
    except OSError as exc:
        log(f"启动失败（端口 {config.SERVER_PORT} 可能已被占用）：{exc}")
        return 1
    log(f"新闻服务已启动：http://{config.SERVER_HOST}:{config.SERVER_PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log("新闻服务已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
