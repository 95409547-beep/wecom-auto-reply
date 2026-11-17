"""MCP stdio bridge to an already running local WeComBot workbench."""

import http.client
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def request(method, path, body=None):
    saved = json.loads((ROOT / "data/state/workbench_session.json").read_text(encoding="utf-8"))
    parsed = urlsplit(saved["url"])
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("本机软件会话无效，请重新打开软件。")
    token = parse_qs(parsed.fragment).get("session", [""])[0]
    if not token:
        raise ValueError("本机软件会话缺少授权，请重新打开软件。")
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=120)
    try:
        connection.request(method, "/api/" + path,
                           body=json.dumps(body) if body is not None else None,
                           headers={"Authorization": "Bearer " + token,
                                    "Content-Type": "application/json"})
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status >= 400:
            raise ValueError(result.get("error", "软件接口请求失败"))
        return result
    finally:
        connection.close()


def call(action, **arguments):
    key = str(uuid4())
    request("POST", "command", {"requestId": key, "action": "page." + action, **arguments})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = request("GET", "result?" + urlencode({"id": key}))
        if result.get("status") == "error":
            raise ValueError(result["message"])
        if result.get("status") == "done":
            return result.get("result", {"message": result["message"]})
        time.sleep(0.2)
    raise ValueError("操作仍在处理，请在软件里核对结果。")


def handle(method, params):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "wecom-workbench", "version": "1.6.0"},
                "instructions": "修改先生成预览，取得用户确认后再调用 apply_change。"}
    if method == "ping":
        return {}
    if method == "tools/list":
        resource = request("GET", "resource?name=assistant")
        tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
                  "inputSchema": t["function"]["parameters"]} for t in resource["tools"]]
        tools.append({"name": "apply_change", "description": "用户审阅并确认后应用已生成的变更。",
                      "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                                      "required": ["id"], "additionalProperties": False}})
        tools.append({"name": "undo_change", "description": "撤销本会话通过助手应用的一次提示词或资料变更。",
                      "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                                      "required": ["id"], "additionalProperties": False}})
        return {"tools": tools}
    if method == "tools/call":
        try:
            if params["name"] == "apply_change":
                result = call("assistant.apply", id=params["arguments"]["id"])
            elif params["name"] == "undo_change":
                result = call("assistant.undo", id=params["arguments"]["id"])
            else:
                result = call("assistant.tool", tool=params["name"], arguments=params.get("arguments", {}))
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except (ValueError, OSError, KeyError) as error:
            return {"isError": True, "content": [{"type": "text", "text": str(error)}]}
    raise ValueError("不支持的 MCP 方法")


def main():
    for line in sys.stdin:
        message = {}
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            result = handle(message["method"], message.get("params", {}))
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": message.get("id"),
                        "error": {"code": -32603, "message": str(error)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    main()
