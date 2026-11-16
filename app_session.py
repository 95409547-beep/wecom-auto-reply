"""Reopen an authenticated, running local workbench before loading application libraries."""
import http.client
import json
import uuid
from urllib.parse import urlsplit, parse_qs
from app_paths import app_dir

APPLICATION = "wecom-auto-reply-workbench"


def session_path():
    return app_dir() / "data" / "state" / "workbench_session.json"


def save_session(url):
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"application": APPLICATION, "url": url}), encoding="utf-8")
    temporary.replace(path)


def clear_session(url):
    path = session_path()
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("url") == url:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def reopen_running():
    connection = None
    try:
        saved = json.loads(session_path().read_text(encoding="utf-8"))
        url = saved["url"]
        parsed = urlsplit(url)
        if saved.get("application") != APPLICATION or parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            return False
        token = parse_qs(parsed.fragment).get("session", [""])[0]
        if not token or parsed.username or parsed.password:
            return False
        connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=1)
        connection.request("GET", "/api/identity", headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        if response.status != 200:
            return False
        state = json.loads(response.read(4096))
        if state.get("application") != APPLICATION or not state.get("connected"):
            return False
        body = json.dumps({"action": "focus", "requestId": str(uuid.uuid4())})
        connection.request("POST", "/api/command", body=body,
                           headers={"Authorization": "Bearer " + token,
                                    "Origin": f"http://127.0.0.1:{parsed.port}",
                                    "Content-Type": "application/json"})
        focused = connection.getresponse()
        focused.read()
        # A busy running instance still owns the queue; never start a duplicate.
        return True
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            connection.close()
