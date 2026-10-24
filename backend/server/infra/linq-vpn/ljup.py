#!/usr/bin/env python3
"""Клиент удалённого JupyterHub стенда LinQ (hackathon.lin-q.ru) для работы из контейнера linq-vpn.

  ljup login                       войти в Hub, поднять сервер, сохранить API-токен
  ljup ls [путь]                   содержимое папки на стенде
  ljup get <удалённый> [локальный] скачать файл
  ljup put <локальный> [удалённый] загрузить файл (папки создаются)
  ljup py <код | -> [-t СЕК]       выполнить Python в постоянном ядре («-» — код из stdin)
  ljup sh <команда> [-t СЕК]       выполнить shell-команду на стенде (в окружении ядра)
  ljup interrupt | restart         прервать / перезапустить ядро
  ljup kernels                     доступные kernelspec и запущенные ядра

Настройки — JUPYTER_URL, JUPYTER_USER, JUPYTER_PASSWORD (secrets/jupyter.env), LJUP_KERNEL (kernelspec).
"""
import argparse
import base64
import datetime
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests
import websocket

URL = os.environ.get("JUPYTER_URL", "http://hackathon.lin-q.ru").rstrip("/")
USER = os.environ.get("JUPYTER_USER", "")
PASSWORD = os.environ.get("JUPYTER_PASSWORD", "")
STATE = Path(os.environ.get("LJUP_STATE", Path.home() / ".ljup.json"))
CHUNK = 8 * 1024 * 1024
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Hub:
    def __init__(self):
        self.state = json.loads(STATE.read_text()) if STATE.exists() else {}
        self.http = requests.Session()
        if self.state.get("token"):
            self.http.headers["Authorization"] = f"token {self.state['token']}"

    def save(self):
        STATE.write_text(json.dumps(self.state))

    # --- вход и сервер ---------------------------------------------------------------------
    def login(self):
        if not (USER and PASSWORD):
            sys.exit("нет JUPYTER_USER/JUPYTER_PASSWORD (secrets/jupyter.env)")
        s = requests.Session()
        s.get(f"{URL}/hub/login", timeout=15).raise_for_status()
        xsrf = s.cookies.get("_xsrf", "")
        r = s.post(f"{URL}/hub/login?next=", data={"username": USER, "password": PASSWORD, "_xsrf": xsrf},
                   allow_redirects=False, timeout=30)
        if r.status_code != 302 or "/login" in r.headers.get("location", ""):
            sys.exit(f"вход не удался: HTTP {r.status_code}")
        # после входа Hub выдаёт новый XSRF-токен; берём его со страницы /hub/token, как это делает браузер
        page = s.get(f"{URL}/hub/token", timeout=15).text
        xsrf = re.search(r'xsrf_token:\s*"([^"]+)"', page).group(1)
        r = s.post(f"{URL}/hub/api/users/{quote(USER)}/tokens", json={"note": "linq-vpn ljup", "expires_in": 7 * 86400},
                   headers={"X-XSRFToken": xsrf}, timeout=15)
        r.raise_for_status()
        self.state = {"token": r.json()["token"]}
        self.http.headers["Authorization"] = f"token {self.state['token']}"
        self.state["user"] = self.hub("GET", "/user")["name"]
        self.save()
        self.ensure_server()
        print(f"вход выполнен: {self.state['user']}, сервер {self.base}")

    def hub(self, method, path, **kw):
        r = self.http.request(method, f"{URL}/hub/api{path}", timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def ensure_server(self):
        user = self.state["user"]
        info = self.hub("GET", f"/users/{quote(user)}")
        server = info.get("servers", {}).get("")
        if not (server and server.get("ready")):
            if not (server and server.get("pending")):
                self.hub("POST", f"/users/{quote(user)}/server")
            for _ in range(120):
                server = self.hub("GET", f"/users/{quote(user)}").get("servers", {}).get("")
                if server and server.get("ready"):
                    break
                time.sleep(2)
            else:
                sys.exit("сервер Jupyter не поднялся за 4 минуты")
        self.state["server"] = server["url"].rstrip("/")
        self.save()

    @property
    def base(self):
        return f"{URL}{self.state['server']}"

    def api(self, method, path, **kw):
        r = self.http.request(method, f"{self.base}/api{path}", timeout=kw.pop("timeout", 60), **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def ready(self):
        if not self.state.get("token"):
            self.login()
            return
        try:
            self.ensure_server()
        except requests.HTTPError as e:
            if e.response.status_code in (401, 403):
                self.login()
            else:
                raise

    # --- файлы ---------------------------------------------------------------------------
    def ls(self, path):
        item = self.api("GET", f"/contents/{quote(path)}", params={"content": 1})
        if item["type"] != "directory":
            print(f"{item['size'] or 0:>12}  {item['last_modified'][:19]}  {item['path']}")
            return
        for c in sorted(item["content"], key=lambda c: (c["type"] != "directory", c["name"])):
            size = "<dir>" if c["type"] == "directory" else c.get("size") or 0
            print(f"{size:>12}  {c['last_modified'][:19]}  {c['name']}{'/' if c['type'] == 'directory' else ''}")

    def get(self, remote, local):
        dest = Path(local or Path(remote).name)
        if dest.is_dir():
            dest = dest / Path(remote).name
        with self.http.get(f"{self.base}/files/{quote(remote)}", stream=True, timeout=60) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for block in r.iter_content(1 << 20):
                    f.write(block)
        print(f"{remote} -> {dest} ({dest.stat().st_size} байт)")

    def mkdirs(self, remote):
        parts = [p for p in Path(remote).parent.as_posix().split("/") if p not in ("", ".")]
        for i in range(len(parts)):
            d = "/".join(parts[: i + 1])
            r = self.http.get(f"{self.base}/api/contents/{quote(d)}", params={"content": 0}, timeout=30)
            if r.status_code == 404:
                self.api("PUT", f"/contents/{quote(d)}", json={"type": "directory"})

    def put(self, local, remote):
        src = Path(local)
        remote = remote or src.name
        if remote.endswith("/"):
            remote += src.name
        self.mkdirs(remote)
        size = src.stat().st_size
        with src.open("rb") as f:
            if size <= CHUNK:
                body = {"type": "file", "format": "base64", "content": base64.b64encode(f.read()).decode()}
                self.api("PUT", f"/contents/{quote(remote)}", json=body, timeout=300)
            else:
                n = 1
                while block := f.read(CHUNK):
                    last = f.tell() >= size
                    body = {"type": "file", "format": "base64", "chunk": -1 if last else n,
                            "content": base64.b64encode(block).decode()}
                    self.api("PUT", f"/contents/{quote(remote)}", json=body, timeout=300)
                    print(f"  {f.tell() * 100 // size}%", file=sys.stderr)
                    n += 1
        print(f"{src} -> {remote} ({size} байт)")

    # --- ядро ----------------------------------------------------------------------------
    def kernel(self, fresh=False):
        kid = self.state.get("kernel")
        if kid and not fresh:
            r = self.http.get(f"{self.base}/api/kernels/{kid}", timeout=30)
            if r.ok:
                return kid
        # path="" — рабочая папка ядра = корень файлов Jupyter (там же, куда кладут put/get), а не $HOME
        body = {"path": "", **({"name": os.environ["LJUP_KERNEL"]} if os.environ.get("LJUP_KERNEL") else {})}
        kid = self.api("POST", "/kernels", json=body)["id"]
        self.state["kernel"] = kid
        self.save()
        return kid

    def execute(self, code, timeout, rc_expr=None):
        kid = self.kernel()
        ws_url = re.sub(r"^http", "ws", f"{self.base}/api/kernels/{kid}/channels")
        ws = websocket.create_connection(ws_url, header=[f"Authorization: {self.http.headers['Authorization']}"],
                                         timeout=timeout)
        msg_id = uuid.uuid4().hex
        ws.send(json.dumps({
            "header": {"msg_id": msg_id, "msg_type": "execute_request", "username": self.state["user"],
                       "session": uuid.uuid4().hex, "version": "5.3",
                       "date": datetime.datetime.now(datetime.timezone.utc).isoformat()},
            "parent_header": {}, "metadata": {}, "channel": "shell", "buffers": [],
            "content": {"code": code, "silent": False, "store_history": False, "allow_stdin": False,
                        "stop_on_error": True, "user_expressions": {"rc": rc_expr} if rc_expr else {}},
        }))
        rc, idle, reply = 0, False, False
        try:
            while not (idle and reply):
                m = json.loads(ws.recv())
                if m.get("parent_header", {}).get("msg_id") != msg_id:
                    continue
                t, c = m["msg_type"], m["content"]
                if t == "stream":
                    (sys.stdout if c["name"] == "stdout" else sys.stderr).write(c["text"])
                    (sys.stdout if c["name"] == "stdout" else sys.stderr).flush()
                elif t in ("execute_result", "display_data"):
                    print(c["data"].get("text/plain", "<" + ", ".join(c["data"]) + ">"))
                elif t == "error":
                    print(ANSI.sub("", "\n".join(c["traceback"])), file=sys.stderr)
                    rc = 1
                elif t == "execute_reply":
                    reply = True
                    val = c.get("user_expressions", {}).get("rc", {})
                    if val.get("status") == "ok":
                        rc = int(val["data"]["text/plain"])
                elif t == "status" and c["execution_state"] == "idle":
                    idle = True
        except websocket.WebSocketTimeoutException:
            print(f"\n[ljup] нет ответа {timeout} с — код продолжает выполняться в ядре {kid} "
                  f"(ljup interrupt — прервать)", file=sys.stderr)
            rc = 124
        finally:
            ws.close()
        return rc

    def sh(self, cmd, timeout):
        code = (
            "import subprocess as _sp, sys as _sys\n"
            f"_p = _sp.Popen({cmd!r}, shell=True, stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True, bufsize=1)\n"
            "for _l in _p.stdout: print(_l, end='', flush=True)\n"
            "_ljup_rc = _p.wait()\n"
        )
        return self.execute(code, timeout, rc_expr="_ljup_rc")


def main():
    p = argparse.ArgumentParser(prog="ljup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("ls").add_argument("path", nargs="?", default="")
    for name in ("get", "put"):
        sp = sub.add_parser(name)
        sp.add_argument("src")
        sp.add_argument("dst", nargs="?")
    for name in ("py", "sh"):
        sp = sub.add_parser(name)
        sp.add_argument("code")
        sp.add_argument("-t", "--timeout", type=float, default=600)
    sub.add_parser("interrupt")
    sub.add_parser("restart")
    sub.add_parser("kernels")
    a = p.parse_args()

    hub = Hub()
    if a.cmd == "login":
        hub.login()
        return
    hub.ready()
    if a.cmd == "ls":
        hub.ls(a.path)
    elif a.cmd == "get":
        hub.get(a.src, a.dst)
    elif a.cmd == "put":
        hub.put(a.src, a.dst)
    elif a.cmd == "py":
        sys.exit(hub.execute(sys.stdin.read() if a.code == "-" else a.code, a.timeout))
    elif a.cmd == "sh":
        sys.exit(hub.sh(a.code, a.timeout))
    elif a.cmd == "interrupt":
        hub.api("POST", f"/kernels/{hub.kernel()}/interrupt")
    elif a.cmd == "restart":
        hub.api("POST", f"/kernels/{hub.kernel()}/restart", timeout=120)
    elif a.cmd == "kernels":
        specs = hub.api("GET", "/kernelspecs")
        print("kernelspecs:", ", ".join(f"{k}{' (default)' if k == specs['default'] else ''}"
                                        for k in specs["kernelspecs"]))
        for k in hub.api("GET", "/kernels"):
            mark = " <- ljup" if k["id"] == hub.state.get("kernel") else ""
            print(f"  {k['id']}  {k['name']}  {k['execution_state']}  {k['last_activity'][:19]}{mark}")


if __name__ == "__main__":
    main()
