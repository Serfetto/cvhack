"""Реестр сценариев. Все модули пакета импортируются автоматически: новый сценарий = новый файл.
Сломанный модуль не валит сервис — ошибка попадает в лог и в `LOAD_ERRORS`."""

import importlib
import pkgutil
import traceback

from scenarios.base import REGISTRY, catalog, effective_params, register  # noqa: F401

LOAD_ERRORS: dict[str, str] = {}

for _m in pkgutil.iter_modules(__path__):
    if _m.name == "base" or _m.name.startswith("_"):
        continue
    try:
        importlib.import_module(f"{__name__}.{_m.name}")
    except Exception:  # noqa: BLE001
        LOAD_ERRORS[_m.name] = traceback.format_exc()
