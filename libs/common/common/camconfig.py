"""Конфигурация камер для горячего пути (ingest, analytics).

Источник правды — camera-service: он пишет полную конфигурацию каждой камеры в Redis
(hash `config:cameras`) и публикует `config.updated`. Горячий путь читает Redis, а не REST,
поэтому продолжает работать, даже если camera-service лежит.

Пока camera-service нет (или Redis пуст), конфигурация берётся из YAML (infra/cameras.yml).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml

from common.bus import Bus
from common.logging import get_logger
from common.messages import CameraConfig, Channels, Keys

log = get_logger(__name__)


def load_yaml(path: str | Path) -> tuple[list[dict], dict[str, CameraConfig]]:
    """Читает infra/cameras.yml: sites → areas → cameras (с zones и rules).
    Возвращает исходные площадки (для seed camera-service) и плоский словарь камер."""
    p = Path(path)
    if not p.exists():
        return [], {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    sites = data.get("sites", [])
    cameras: dict[str, CameraConfig] = {}
    for site in sites:
        for area in site.get("areas", []):
            for cam in area.get("cameras", []):
                cfg = CameraConfig.model_validate({**cam, "area_id": area.get("id"), "area_name": area.get("name"), "site_id": site.get("id")})
                cameras[cfg.id] = cfg
    return sites, cameras


class CameraRegistry:
    """Кэш конфигурации камер с горячей перезагрузкой."""

    def __init__(self, bus: Bus, yaml_path: str | None = None, resync_s: float = 30):
        self.bus = bus
        self.yaml_path = yaml_path
        self.resync_s = resync_s
        self.cameras: dict[str, CameraConfig] = {}
        self.source = "none"

    async def _read(self) -> dict[str, CameraConfig]:
        raw = await self.bus.redis.hgetall(Keys.CAMERA_CONFIGS)
        if raw:
            self.source = "redis"
            out = {}
            for k, v in raw.items():
                try:
                    cfg = CameraConfig.model_validate_json(v)
                    out[cfg.id] = cfg
                except ValueError:
                    log.error("bad_camera_config", camera=k)
            return out
        if self.yaml_path:
            _, cams = load_yaml(self.yaml_path)
            if cams:
                self.source = "yaml"
                return cams
        self.source = "none"
        return {}

    async def refresh(self) -> set[str]:
        """Перечитывает конфигурацию и возвращает id камер, которые изменились, появились или исчезли."""
        new = await self._read()
        changed = {cid for cid in new.keys() | self.cameras.keys()
                   if (cid not in new or cid not in self.cameras
                       or new[cid].model_dump(mode="json") != self.cameras[cid].model_dump(mode="json"))}
        self.cameras = new
        return changed

    async def watch(self, on_change: Callable[[set[str]], Awaitable[None]]) -> None:
        """Подписка на config.updated + периодическая сверка на случай потерянного сообщения."""

        async def periodic():
            while True:
                await asyncio.sleep(self.resync_s)
                changed = await self.refresh()
                if changed:
                    log.info("config_resync", changed=sorted(changed))
                    await on_change(changed)

        task = asyncio.create_task(periodic())
        try:
            async for _, _data in self.bus.listen([Channels.CONFIG_UPDATED]):
                changed = await self.refresh()
                if changed:
                    log.info("config_updated", changed=sorted(changed), source=self.source)
                    await on_change(changed)
        finally:
            task.cancel()


async def publish_camera_configs(bus: Bus, configs: list[CameraConfig], deleted: list[str] = (), replace_all: bool = False) -> None:
    """Для camera-service: записать конфигурацию в Redis и разослать config.updated."""
    pipe = bus.redis.pipeline()
    if replace_all:
        pipe.delete(Keys.CAMERA_CONFIGS)
    for cfg in configs:
        pipe.hset(Keys.CAMERA_CONFIGS, cfg.id, cfg.model_dump_json(by_alias=True))
    for cid in deleted:
        pipe.hdel(Keys.CAMERA_CONFIGS, cid)
    await pipe.execute()
    targets = [c.id for c in configs] + list(deleted)
    if replace_all or len(targets) != 1:
        await bus.redis.publish(Channels.CONFIG_UPDATED, json.dumps({"camera_id": None}))
    else:
        await bus.redis.publish(Channels.CONFIG_UPDATED, json.dumps({"camera_id": targets[0], "deleted": bool(deleted)}))
