"""Local Web workbench. UI commands are dispatched on the existing Tk thread.

This adapter never sends messages itself or opens the persistent queue. The
coordinator's existing callbacks remain responsible for validation and delivery.
"""
from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs
from concurrent.futures import ThreadPoolExecutor
from app_session import APPLICATION, save_session, clear_session

ASSETS = Path(__file__).resolve().parent.parent / "web" / "workbench" / "bundle"


def serialize_pending(items):
    rows = []
    for item in items:
        row = {name: getattr(item, name, default) for name, default in (
            ("key", ""), ("customer_name", ""), ("customer_message", ""),
            ("ai_reply", ""), ("timestamp", 0), ("confidence", 0),
            ("guard_decision", ""), ("send_status", "pending"), ("send_error", ""))}
        row["revision"] = hashlib.sha256(json.dumps(row, sort_keys=True,
                                                   ensure_ascii=False).encode()).hexdigest()
        rows.append(row)
    return rows


class WorkbenchServer:
    """A bounded command mailbox and immutable snapshots; no Tk calls in HTTP threads."""
    def __init__(self, snapshot, dispatch, *, assets=ASSETS, port=0, resources=None):
        self.snapshot = snapshot
        self.dispatch = dispatch
        self.resources = resources
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workbench-pages")
        self.assets = Path(assets).resolve()
        self.token = secrets.token_urlsafe(32)
        self.commands = queue.Queue(maxsize=32)
        self.lock = threading.RLock()
        self.operations = {}
        self.state = {}
        self.closed = False
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Customer content and session credentials must not enter access logs.

            def respond(self, code, payload, content_type="application/json; charset=utf-8"):
                body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, dict) else payload
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def authorized(self):
                valid = (self.headers.get("Host") == bridge.address and
                         secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge.token) and
                         self.headers.get("Origin", bridge.origin) == bridge.origin)
                if not valid:
                    self.respond(403, {"error": "会话已失效，请从桌面程序重新打开工作台。"})
                return valid

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/api/identity":
                    if self.authorized():
                        with bridge.lock:
                            self.respond(200, {"application": APPLICATION, "connected": bridge.state.get("connected", False),
                                               "desktopFocus": bridge.state.get("desktopFocus", 0)})
                    return
                if path == "/api/state":
                    if self.authorized():
                        with bridge.lock:
                            summary = {key: {k: v for k, v in result.items() if k != "result"} for key, result in bridge.operations.items()}
                            self.respond(200, {**bridge.state, "operations": summary, "application": APPLICATION})
                    return
                if path in ("/api/resource", "/api/result"):
                    if not self.authorized():
                        return
                    params = {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}
                    try:
                        if path == "/api/result":
                            with bridge.lock:
                                result = copy.deepcopy(bridge.operations.get(params.get("id"), {}))
                            self.respond(200, result)
                        elif bridge.resources:
                            self.respond(200, bridge.resources(params.pop("name", ""), params))
                        else:
                            self.respond(404, {"error": "此预览不支持该页面"})
                    except ValueError as error:
                        self.respond(400, {"error": str(error)})
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception("读取 Web 页面失败")
                        self.respond(500, {"error": "页面读取失败，请刷新重试或检查程序日志。"})
                    return
                relative = unquote(path).lstrip("/") or "index.html"
                file = (bridge.assets / relative).resolve()
                if not file.is_relative_to(bridge.assets) or not file.is_file():
                    self.respond(404, {"error": "页面不存在"})
                    return
                mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix)
                self.respond(200, file.read_bytes(), mime or mimetypes.guess_type(file.name)[0] or "application/octet-stream")

            def do_POST(self):
                if not self.authorized():
                    return
                if self.path != "/api/command":
                    self.respond(404, {"error": "操作不存在"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 32 * 1024 * 1024:
                        raise ValueError("请求过长或为空")
                    command = json.loads(self.rfile.read(length))
                    if not isinstance(command, dict) or not isinstance(command.get("action"), str):
                        raise ValueError("操作格式无效")
                    request_id = command.get("requestId")
                    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
                        raise ValueError("请求标识无效")
                    with bridge.lock:
                        if request_id not in bridge.operations:
                            if bridge.commands.full() or sum(r["status"] == "pending" for r in bridge.operations.values()) >= 32:
                                self.respond(429, {"error": "正在处理其他操作，请稍后重试。"})
                                return
                            # Keep unfinished operations and a bounded set of completed ones.
                            for key in list(bridge.operations):
                                if len(bridge.operations) < 96:
                                    break
                                if bridge.operations[key]["status"] != "pending":
                                    del bridge.operations[key]
                            bridge.operations[request_id] = {"status": "pending"}
                            bridge.commands.put_nowait(command)
                    self.respond(202, {"requestId": request_id})
                except (ValueError, UnicodeDecodeError, TypeError):
                    self.respond(400, {"error": "操作格式无效，请刷新页面重试。"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.address = f"127.0.0.1:{self.httpd.server_port}"
        self.origin = "http://" + self.address
        self.url = self.origin + "/#session=" + self.token
        self.publish()
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="workbench-http", daemon=True)
        self.thread.start()

    def publish(self):
        state = copy.deepcopy(self.snapshot())
        with self.lock:
            self.state = state

    def tick(self):
        """Called by root.after. All business callbacks run on this caller's thread."""
        if self.closed:
            return
        for _ in range(4):
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            if command["action"].startswith("page."):
                self.worker.submit(self._execute, command)
            else:
                self._execute(command)
        self.publish()

    def _execute(self, command):
        try:
            output = self.dispatch(command) or "操作已处理"
            result = {"status": "done", "message": output.get("message", "操作已处理") if isinstance(output, dict) else output}
            if isinstance(output, dict):
                result["result"] = output
        except ValueError as error:
            result = {"status": "error", "message": str(error)}
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Web 工作台操作失败")
            result = {"status": "error", "message": "操作失败，请检查程序日志后重试。"}
        with self.lock:
            self.operations[command["requestId"]] = result

    def close(self):
        if not self.closed:
            self.closed = True
            self.worker.shutdown(wait=False, cancel_futures=True)
            self.httpd.shutdown()
            self.httpd.server_close()


class WindowAdapter:
    def __init__(self, window):
        self.window = window

    def snapshot(self):
        w = self.window
        # Settings are saved by the page worker. Refresh the banner here on the
        # Tk thread once the start guard sees the reloaded configuration.
        can_start, _ = getattr(w, "_start_allowed", lambda: (True, ""))()
        if getattr(w, "_start_guard_banner", False) and can_start:
            w.set_banner("")
        from rag import archives, reply_learning
        try:
            reviews = [row for row in reply_learning.reviews(archives.active_id())
                       if row["status"] in ("ready", "analyzing", "error", "disabled")]
        except (OSError, ValueError):
            reviews = []
        return {"items": getattr(w, "_web_pending_rows", []), "paused": w.is_paused(),
                "canStart": can_start,
                "banner": getattr(w, "_web_banner", {"text": "", "level": "info"}),
                "demo": False, "connected": not w._should_exit,
                "pageBusy": bool(getattr(w, "_web_page_busy", False)),
                "desktopFocus": getattr(w, "_desktop_focus", 0),
                "learning": {"archive": archives.active_id(), "reviews": reviews[-50:]}}

    def resources(self, name, params):
        if name == "records":
            from rag import archives, reply_learning
            services = getattr(self.window, "web_services", None)
            rows = [r.to_dict() for r in list(self.window._records)[-1000:][::-1]]
            current = archives.active_id()
            reviews = {row["id"]: row for row in reply_learning.reviews(current)}
            by_record = {row["record"]: row for row in reviews.values() if row.get("record")}
            for row in rows:
                row["learning"] = {"status": "unrecorded", "label": "尚无学习记录", "entries": []}
                if row.get("archive") and row["archive"] != current:
                    row["learning"]["label"] = "其他档案，切换后查看"
                review = by_record.get(row.get("record_id")) or reviews.get(
                    reply_learning.reply_key(row.get("question", ""), row.get("reply", "")))
                if (not row.get("archive") or row["archive"] == current) and review:
                    row["learning"] = reply_learning.status(
                        current, row.get("question", ""), row.get("reply", ""),
                        getattr(services, "qdrant", None), review=review,
                    )
            return {"rows": rows, "archive": current, "archiveName": archives.active_name()}
        services = getattr(self.window, "web_services", None)
        if services is None:
            raise ValueError("页面服务尚未准备好，请等待程序完成启动。")
        return services.read(name, params)

    def dispatch(self, command):
        w = self.window
        action = command["action"]
        if w._should_exit:
            raise ValueError("桌面程序已退出，请重新打开。")
        if action == "focus":
            open_workbench(w)
            return "已打开客服窗口"
        if action.startswith("page."):
            services = getattr(w, "web_services", None)
            if services is None:
                raise ValueError("页面服务尚未准备好")
            w._web_page_busy = True
            try:
                return services.command(action[5:], command)
            finally:
                w._web_page_busy = False
        if action == "records.clear":
            w._records.clear()
            w._stats = {"replied": 0, "escalated": 0}
            w._refresh_list()
            w._update_stats()
            return "已清空当前列表，磁盘历史日志仍保留"
        if action in ("exit", "restart"):
            if getattr(w, "_web_page_busy", False):
                raise ValueError("资料操作仍在进行，请完成后再退出或重启。")
            if action == "restart":
                import subprocess, sys, os
                args = [sys.executable, "--restart-delay"] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"), "--restart-delay"]
                subprocess.Popen(args, cwd=str(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            w._paused = True
            if w.on_pause:
                w.on_pause()
            w._should_exit = True
            return "正在重启程序" if action == "restart" else "程序正在退出"
        if action in ("send", "edit", "ignore"):
            row = next((r for r in getattr(w, "_web_pending_rows", []) if r["key"] == command.get("key")), None)
            if not row:
                raise ValueError("这条消息已被处理，队列已更新。")
            if row["revision"] != command.get("revision"):
                raise ValueError("这条消息的状态或草稿已更新，请核对后再操作。")
            if row["send_status"] == "queued" and action != "ignore":
                raise ValueError("这条回复已进入发送队列，请等待发送结果。")
            callback = getattr(w, "_on_pending_" + action)
            if callback is None:
                raise ValueError("发送服务尚未准备好，请稍后重试。")
            if row["send_status"] == "unknown" and action != "ignore":
                # Preserve the existing native confirmation, making its window visible.
                w.root.deiconify()
                w.root.lift()
            if action == "edit":
                text = command.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                    raise ValueError("请填写回复内容，最多 10,000 字。")
                callback(row["key"], text.strip())
            else:
                callback(row["key"])
            current = next((r for r in getattr(w, "_web_pending_rows", []) if r["key"] == row["key"]), None)
            if action == "ignore":
                return "已忽略这条消息"
            if current and current["send_status"] != "queued":
                raise ValueError(getattr(w, "_web_banner", {}).get("text") or "本次未提交发送，请查看桌面程序提示。")
            return "已提交发送，送达结果以队列状态为准"
        if action == "service":
            was_paused = w.is_paused()
            if was_paused:
                allowed, reason = getattr(w, "_start_allowed", lambda: (True, ""))()
                if not allowed:
                    raise ValueError("请先在左侧「设置」填写并保存有效的模型接口，再启动自动回复。")
            w.toggle_pause()
            if w.is_paused() == was_paused:
                raise ValueError(getattr(w, "_web_banner", {}).get("text") or "状态未改变，请查看桌面程序提示。")
            return "自动回复已停止" if w.is_paused() else "自动回复已启动"
        if action == "native":
            target = command.get("target")
            if target not in ("全部", "已回复", "设置", "数据", "知识库"):
                raise ValueError("页面不存在")
            w.root.deiconify()
            w.root.lift()
            if target in ("全部", "已回复"):
                w._show_page("工作台")
                w._switch_tab(target)
            elif target == "设置":
                w._on_settings_clicked()
            else:
                w._show_page(target)
            return f"已在桌面窗口打开{target}"
        raise ValueError("不支持的操作")


def open_workbench(window):
    if not (ASSETS / "index.html").exists():
        window.root.deiconify()
        window.set_banner("Web 工作台资源未构建，请在 web/workbench 运行 npm ci 和 npm run build。", "error")
        return
    server = getattr(window, "_web_workbench", None)
    if server is None or server.closed:
        adapter = WindowAdapter(window)
        server = WorkbenchServer(adapter.snapshot, adapter.dispatch, resources=adapter.resources)
        window._web_workbench = server
        save_session(server.url)

        def pump():
            if not window._should_exit and not server.closed:
                server.tick()
                window.root.after(150, pump)

        def destroyed(event):
            if event.widget is window.root:
                clear_session(server.url)
                server.close()

        window.root.bind("<Destroy>", destroyed, add="+")
        window.root.after(150, pump)
    from gui.desktop_host import open_desktop_window
    open_desktop_window(window)
    if getattr(window, "_web_mode", False):
        window.root.withdraw()


def demo(port=4181):
    """Isolated design preview; neither imports main nor touches customer data."""
    from types import SimpleNamespace
    from gui.web_demo_services import DemoServices
    pages = DemoServices()
    now = time.time()
    examples = [
        ("林先生", "你好，昨天买的账号今天登录提示密码错误，换了设备也是一样的。能帮我看下怎么处理吗？", "您好，麻烦您提供一下订单编号和登录报错截图，我帮您核对账号情况。先不要重复尝试登录，避免触发安全限制。", .62, "pending", ""),
        ("陈女士", "这个号可以改绑手机号吗？需要等多久？", "您好，改绑方式和时间需要结合账号信息确认。麻烦您发一下商品链接，我帮您具体核实。", .48, "pending", ""),
        ("小周", "刚才付款成功了，但是还没有收到账号信息。订单尾号 8026。", "收到，我帮您核查订单 8026 的交付进度，请稍等。", .71, "failed", "发送失败，请确认企业微信窗口可用后重试。"),
        ("林先生", "还有一个问题，这个账号支持退款吗？", "", .31, "pending", ""),
        ("阿远", "我已经把截图发过去了，现在可以处理了吗？", "截图已收到，我正在核对，确认后会在这里回复您。", .55, "unknown", "发送结果待核实，请先检查客户会话，避免重复发送。"),
    ]
    items = [SimpleNamespace(key=f"demo-{i}", customer_name=name, customer_message=message,
             ai_reply=reply, timestamp=now-i*186, confidence=score, guard_decision="人工确认",
             send_status=status, send_error=error) for i, (name, message, reply, score, status, error) in enumerate(examples)]
    state = {"items": serialize_pending(items), "demo": True, "paused": True,
             "connected": True, "banner": {"text": "", "level": "info"}}

    def dispatch(command):
        action = command["action"]
        if action.startswith("page."):
            return pages.command(action[5:], command)
        if action in ("records.clear", "exit", "restart"):
            return pages.command(action, command)
        if action == "native":
            return "演示模式：正式工作台会在桌面窗口打开" + command.get("target", "")
        if action == "service":
            if state["paused"] and not pages.model_saved:
                raise ValueError("请先连接模型。")
            state["paused"] = not state["paused"]
            return "已切换演示状态，未启动自动回复"
        row = next((r for r in state["items"] if r["key"] == command.get("key")), None)
        if row is None or row["revision"] != command.get("revision"):
            raise ValueError("这条消息已更新，请重新选择。")
        if action not in ("send", "edit", "ignore"):
            raise ValueError("不支持的操作")
        if action != "ignore" and not (command.get("text") if action == "edit" else row["ai_reply"]).strip():
            raise ValueError("请先填写回复内容。")
        state["items"].remove(row)
        return "演示操作已完成，未向客户发送消息"

    def snapshot():
        return {**state, "canStart": pages.model_saved}

    server = WorkbenchServer(snapshot, dispatch, port=port, resources=pages.read)
    print(server.url, flush=True)
    try:
        while True:
            server.tick()
            time.sleep(.1)
    except KeyboardInterrupt:
        server.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="隔离的工作台视觉预览，不连接业务服务")
    parser.add_argument("--demo", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=4181)
    demo(parser.parse_args().port)
