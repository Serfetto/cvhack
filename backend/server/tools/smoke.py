"""Сквозная проверка работающей системы через шлюз: вход → камеры → событие по WebSocket → статус → статистика.

    python backend/server/tools/smoke.py                       # http://localhost:8080
    python backend/server/tools/smoke.py --base http://<vps>:8080 --timeout 120
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx
import websockets


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--user", default="operator")
    ap.add_argument("--password", default="demo")
    ap.add_argument("--timeout", type=float, default=90)
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    api = f"{args.base}/api"

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{api}/auth/login", json={"username": args.user, "password": args.password})
        if r.status_code != 200:
            fail(f"вход: {r.status_code} {r.text[:200]}")
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ok(f"вход как {args.user} ({r.json()['user']['role_title']})")

        cams = (await c.get(f"{api}/config/cameras", headers=h)).json()
        ok("камеры: " + ", ".join(f"{x['id']}={x['stream']['state']}/{x['stream']['fps']}fps" for x in cams))
        scen = (await c.get(f"{api}/config/scenarios", headers=h)).json()
        ok("сценарии: " + ", ".join(s["code"] for s in scen))
        models = (await c.get(f"{api}/inference/models")).json()
        ok(f"инференс: {models.get('active_backend')}, {models.get('fps')} кадр/с")

        ws_url = args.base.replace("http", "ws", 1) + f"/ws?access_token={token}"
        event = None
        t_start = time.time()
        async with websockets.connect(ws_url) as ws:
            hello = json.loads(await ws.recv())
            ok(f"WebSocket: {hello['type']} {hello['user']['username']}")
            while time.time() - t_start < args.timeout:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                except TimeoutError:
                    continue
                if msg["type"] == "event.created":
                    event = msg["event"]
                    break
        if not event:
            fail(f"за {args.timeout:.0f} с не пришло ни одного event.created")
        lag = time.time() - event["frame_ts"] if event.get("frame_ts") else None
        ok(f"событие {event['scenario']} на {event['camera_id']}, снапшот {event['snapshot_url']}"
           + (f", задержка кадр→браузер {lag:.2f} с" if lag is not None else ""))

        if event.get("snapshot_url"):
            r = await c.get(args.base + event["snapshot_url"])
            ok(f"снапшот доступен: {r.status_code}, {len(r.content)} байт") if r.status_code == 200 else fail(f"снапшот {r.status_code}")

        r = await c.patch(f"{api}/events/events/{event['id']}/status", headers=h, json={"status": "confirmed", "comment": "smoke"})
        if r.status_code != 200:
            fail(f"смена статуса: {r.status_code} {r.text[:200]}")
        ok(f"статус → {r.json()['status']}, действий в истории: {len(r.json()['actions'])}")

        page = (await c.get(f"{api}/events/events", headers=h, params={"page_size": 5})).json()
        ok(f"журнал: всего {page['total']}")
        s = (await c.get(f"{api}/events/stats/summary", headers=h)).json()
        ok(f"статистика: сегодня {s['today']}, непринятых {s['unaccepted']}, precision {s['precision']}")

        await asyncio.sleep(12)
        e = (await c.get(f"{api}/events/events/{event['id']}", headers=h)).json()
        ok(f"клип: {e['clip_status']} {e.get('clip_url') or ''}")
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
