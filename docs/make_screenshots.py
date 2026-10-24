"""Скриншоты работающего сервиса для технической документации → docs/img/ui_*.png.

    docker compose up -d                       # стек должен работать, лучше с роликами и TPU
    python docs/make_screenshots.py            # http://localhost:8080, Grafana на :3000
    python docs/make_screenshots.py --base http://localhost:18080 --event <uuid>

Вход — демо-пользователем admin (пароль DEMO_PASSWORD, по умолчанию demo): токены кладутся в localStorage так же,
как это делает экран входа. Карточка события — последнее критичное событие с готовым клипом или --event.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.request
from pathlib import Path

from cdp import Browser

OUT = Path(__file__).resolve().parent / "img"


def api(base: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--grafana", default="http://localhost:3000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default=os.getenv("DEMO_PASSWORD", "demo"))
    ap.add_argument("--event", help="id события для карточки")
    ap.add_argument("--camera", default="cam-01", help="камера для экрана настройки")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    tokens = api(args.base, "/api/auth/login", body={"username": args.user, "password": args.password})
    event = args.event
    if not event:
        items = api(args.base, "/api/events/events?scenario=proximity&demo=false&page_size=50", tokens["access_token"])["items"]
        ready = [e for e in items if e["clip_status"] == "ready" and e["annotated_url"] and e["ended_at"]]
        event = (ready or items)[0]["id"] if (ready or items) else None

    auth = {"state": {"access": tokens["access_token"], "refresh": tokens["refresh_token"], "user": tokens["user"]}, "version": 0}
    ui = {"state": {"theme": "light", "sound": False, "collapsed": False}, "version": 0}
    # имя, путь, ожидание (с), высота окна; сводку непринятых оставляем только в ленте
    shots = [
        ("ui_cameras", "/cameras", 9, 900),
        ("ui_camera_setup", f"/cameras/{args.camera}", 6, 900),
        ("ui_feed", "/feed", 5, 900),
        ("ui_journal", "/journal", 5, 900),
        ("ui_dashboard", "/dashboard", 6, 1500),
        ("ui_performance", "/performance", 6, 1450),
        ("ui_profile", "/profile", 4, 900),
    ]
    if event:
        shots.insert(3, ("ui_event", f"/journal?event={event}", 8, 1250))
    hide = "document.head.insertAdjacentHTML('beforeend', '<style>.ant-notification{display:none!important}</style>'); true"

    async with Browser(os.getenv("CHROME")) as browser:
        page = await browser.page(1440, 900, 1.5)
        await page.goto(f"{args.base}/login", 4)
        await page.screenshot(OUT / "ui_login.png")
        print("ui_login")
        await page.eval(f"localStorage.setItem('linq-auth', {json.dumps(json.dumps(auth))});"
                        f"localStorage.setItem('linq-ui', {json.dumps(json.dumps(ui))}); true")
        for name, path, wait, height in shots:
            await page.send("Emulation.setDeviceMetricsOverride",
                            {"width": 1440, "height": height, "deviceScaleFactor": 1.5, "mobile": False})
            await page.goto(args.base + path, wait)
            if name != "ui_feed":
                await page.eval(hide)
                await asyncio.sleep(0.3)
            await page.screenshot(OUT / f"{name}.png")
            print(name)
        try:
            await page.send("Emulation.setDeviceMetricsOverride",
                            {"width": 1440, "height": 1100, "deviceScaleFactor": 1.5, "mobile": False})
            await page.goto(f"{args.grafana}/d/linq-pipeline?orgId=1&from=now-30m&to=now&kiosk&theme=light", 10)
            await page.screenshot(OUT / "ui_grafana.png")
            print("ui_grafana")
        except Exception as e:  # Grafana не обязательна
            print(f"grafana: {e}")


if __name__ == "__main__":
    asyncio.run(main())
