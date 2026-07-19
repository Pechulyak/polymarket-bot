#!/usr/bin/env python3
"""
markets_config: shared loader for /opt/executor/app/markets.json.

FARM-039: единый источник списка активных фарминг-рынков для farming_daemon
и farming_control_bot. Файл на диске — истина (генерируется
farming/tools/farming_markets_sync.py из БД). Если файл недоступен/невалиден —
вызывающий код решает, что делать (демон — fallback на встроенный список;
бот — пустой отчёт с пометкой).

Чистый stdlib: только json + os. Никаких requests, py_clob_client_v2 и прочего —
этот модуль импортируется и тестируется без сетевых/CLOB-зависимостей.

Деплой: ФЛАТ в /opt/executor/app/ рядом с farming_daemon.py и
farming_control_bot.py, импорт — sibling:
    from markets_config import load_markets_file, MARKETS_FILE
"""

import json
import os

# Путь к markets.json на S2. Переопределяется через --out в генераторе, но
# этот константный путь — единая точка обращения демона и контрол-бота.
MARKETS_FILE = "/opt/executor/app/markets.json"

_NUMERIC_FIELDS = ("min_size", "inv_center", "inv_deadband", "max_inv")
_REQUIRED_FIELDS = ("name", "token") + _NUMERIC_FIELDS


def _is_real_number(x) -> bool:
    """True для bool отвергаем явно (bool — подкласс int и валидное >0,
    но в контексте markets.json это явно не то, что нам нужно)."""
    if isinstance(x, bool):
        return False
    return isinstance(x, (int, float))


def load_markets_file(path: str = MARKETS_FILE) -> list[dict]:
    """Load and validate markets.json from `path`.

    Contract (FARM-039):
      - читает {"version": 1, "markets": [...]}
      - markets обязан быть непустым списком
      - каждый элемент содержит name (str), token (str), и числовые поля
        min_size / inv_center / inv_deadband / max_inv (все > 0)
      - token уникален в пределах списка
      - inv_center <= max_inv
      - дополнительные поля (weight / gamma_id / condition_id / etc.)
        сохраняются as-is и возвращаются — мы их не фильтруем, чтобы
        не потерять данные для демона (он использует только name+token+
        min_size+inv_*+max_inv, но запас не мешает).
      - любая проблема (нет файла / битый JSON / провал валидации) ->
        исключение (ValueError / OSError / KeyError). НЕ ловим — пусть
        вызывающий код сам решает, что делать.

    Возвращает list[dict] — содержимое поля "markets" в JSON, в исходном порядке.
    """
    with open(path, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"markets.json at {path} is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            f"markets.json at {path}: top-level must be a JSON object, "
            f"got {type(data).__name__}"
        )

    markets = data.get("markets")
    if not isinstance(markets, list):
        raise ValueError(
            f"markets.json at {path}: 'markets' must be a list, "
            f"got {type(markets).__name__}"
        )
    if len(markets) == 0:
        raise ValueError(f"markets.json at {path}: 'markets' is empty")

    seen_tokens = set()
    for i, m in enumerate(markets):
        if not isinstance(m, dict):
            raise ValueError(
                f"markets.json at {path}: markets[{i}] must be an object, "
                f"got {type(m).__name__}"
            )

        # Обязательные поля + базовые типы
        for field in _REQUIRED_FIELDS:
            if field not in m:
                raise ValueError(
                    f"markets.json at {path}: markets[{i}] missing required "
                    f"field '{field}'"
                )

        name = m["name"]
        token = m["token"]

        if not isinstance(name, str) or not name:
            raise ValueError(
                f"markets.json at {path}: markets[{i}].name must be a non-empty "
                f"string, got {name!r}"
            )
        if not isinstance(token, str) or not token:
            raise ValueError(
                f"markets.json at {path}: markets[{i}].token must be a non-empty "
                f"string, got {token!r}"
            )

        if token in seen_tokens:
            raise ValueError(
                f"markets.json at {path}: duplicate token at markets[{i}]: {token}"
            )
        seen_tokens.add(token)

        # Числовые поля > 0
        for field in _NUMERIC_FIELDS:
            val = m[field]
            if not _is_real_number(val):
                raise ValueError(
                    f"markets.json at {path}: markets[{i}].{field} must be a "
                    f"positive number, got {val!r} ({type(val).__name__})"
                )
            if val <= 0:
                raise ValueError(
                    f"markets.json at {path}: markets[{i}].{field} must be > 0, "
                    f"got {val}"
                )

        inv_center = float(m["inv_center"])
        max_inv = float(m["max_inv"])
        if inv_center > max_inv:
            raise ValueError(
                f"markets.json at {path}: markets[{i}] ({name!r}) has "
                f"inv_center={inv_center} > max_inv={max_inv}"
            )

    return markets


if __name__ == "__main__":
    # Smoke check: вывести список при ручном запуске на S2 для sanity-check.
    try:
        markets = load_markets_file()
    except Exception as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
    print(f"OK: {len(markets)} markets from {MARKETS_FILE}")
    for m in markets:
        print(f"  - {m.get('name')!r}  token={m.get('token')[:20]}...")