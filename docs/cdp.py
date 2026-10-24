"""Минимальный клиент Chrome DevTools Protocol: headless Chrome или Edge без Selenium и Playwright.

Нужен только для документации (docs/make_screenshots.py, docs/make_pdf.py); в конвейере не используется.
Зависимость — пакет `websockets`.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str:
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        if path := shutil.which(name):
            return path
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    raise FileNotFoundError("Не найден Chrome или Edge: укажите путь в переменной CHROME")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser:
    def __init__(self, path: str | None = None):
        self.path = path or find_browser()
        self.ids = itertools.count(1)
        self.pending: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> Browser:
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="cdp-")
        self.proc = subprocess.Popen(
            [self.path, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
             "--autoplay-policy=no-user-gesture-required", "--lang=ru-RU", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:
                    url = json.load(r)["webSocketDebuggerUrl"]
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.2)
        self.ws = await websockets.connect(url, max_size=None)
        self.reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc) -> None:
        self.reader.cancel()
        await self.ws.close()
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    async def _read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            fut = self.pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(f"{msg['error']}"))
                else:
                    fut.set_result(msg.get("result", {}))

    async def send(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        mid = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, 120)

    async def page(self, width: int = 1440, height: int = 900, scale: float = 1.0) -> Page:
        target = (await self.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        session = (await self.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        p = Page(self, session)
        await p.send("Page.enable")
        await p.send("Emulation.setDeviceMetricsOverride",
                     {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False})
        return p


class Page:
    def __init__(self, browser: Browser, session: str):
        self.browser, self.session = browser, session

    async def send(self, method: str, params: dict | None = None) -> dict:
        return await self.browser.send(method, params, self.session)

    async def goto(self, url: str, wait_s: float = 3.0) -> None:
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(wait_s)

    async def eval(self, js: str):
        r = await self.send("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        return r.get("result", {}).get("value")

    async def screenshot(self, path: Path, fmt: str = "png", quality: int = 88) -> None:
        params = {"format": fmt}
        if fmt == "jpeg":
            params["quality"] = quality
        data = (await self.send("Page.captureScreenshot", params))["data"]
        path.write_bytes(base64.b64decode(data))

    async def pdf(self, path: Path, **options) -> None:
        data = (await self.send("Page.printToPDF", options))["data"]
        path.write_bytes(base64.b64decode(data))
