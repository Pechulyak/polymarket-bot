# -*- coding: utf-8 -*-
"""Unit tests for executor/markets_config.load_markets_file (FARM-039).

Covers all validation branches:
  - успешный файл (валидный JSON, все поля в норме)
  - файл отсутствует (OSError)
  - невалидный JSON (ValueError)
  - пустой markets (ValueError)
  - дубликат token (ValueError)
  - отрицательный min_size (ValueError)
  - inv_center > max_inv (ValueError)

Контрактная инвариантность с экспортом на диск проверяется
write-через-tmp в integration-прогоне farming_markets_sync.py;
здесь — только чистая логика load_markets_file.
"""

import json
from pathlib import Path

import pytest

from executor import markets_config


def _write_json(tmp_path: Path, obj) -> str:
    p = tmp_path / "markets.json"
    p.write_text(json.dumps(obj))
    return str(p)


def _valid_market(token_suffix: str = "abc") -> dict:
    return {
        "name": f"Market {token_suffix}",
        "token": f"10536862579565543296419049675454665027088107045165543068411016661306{token_suffix}",
        "min_size": 100,
        "inv_center": 100,
        "inv_deadband": 50,
        "max_inv": 300,
        "weight": 1.0,
        "gamma_id": 123,
        "condition_id": "0xdeadbeef",
    }


def test_load_markets_file_success(tmp_path):
    """Валидный JSON с одним рынком -> возвращается список как есть."""
    m = _valid_market()
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    result = markets_config.load_markets_file(path=path)
    assert isinstance(result, list)
    assert len(result) == 1
    # Возвращается содержимое "markets" as-is, лишние поля не фильтруются.
    assert result[0] == m
    assert result[0]["weight"] == 1.0
    assert result[0]["gamma_id"] == 123


def test_load_markets_file_multiple_markets_preserves_order_and_extras(tmp_path):
    """Несколько рынков, лишние поля в каждом — порядок и extras сохранены."""
    a = _valid_market("aaaa")
    b = _valid_market("bbbb")
    b["custom_extra"] = {"nested": True}
    path = _write_json(tmp_path, {"version": 1, "markets": [a, b]})
    result = markets_config.load_markets_file(path=path)
    assert [r["name"] for r in result] == ["Market aaaa", "Market bbbb"]
    assert result[1]["custom_extra"] == {"nested": True}


def test_load_markets_file_missing_raises(tmp_path):
    """Файл не существует -> OSError (конкретно FileNotFoundError)."""
    path = str(tmp_path / "does_not_exist.json")
    with pytest.raises(OSError):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_invalid_json_raises_value_error(tmp_path):
    """Битый JSON -> ValueError с человеческим текстом (НЕ JSONDecodeError —
    ловим и перепаковываем в `load_markets_file`)."""
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    with pytest.raises(ValueError, match="not valid JSON"):
        markets_config.load_markets_file(path=str(p))


def test_load_markets_file_top_level_not_object_raises(tmp_path):
    """Корень — не объект -> ValueError (а не KeyError на data.get)."""
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(["just", "a", "list"]))
    with pytest.raises(ValueError, match="top-level must be a JSON object"):
        markets_config.load_markets_file(path=str(p))


def test_load_markets_file_markets_missing_raises(tmp_path):
    """Нет ключа 'markets' -> ValueError."""
    path = _write_json(tmp_path, {"version": 1})
    with pytest.raises(ValueError, match="'markets' must be a list"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_empty_markets_raises(tmp_path):
    """markets == [] -> ValueError (явно запрещено — нечего фармить)."""
    path = _write_json(tmp_path, {"version": 1, "markets": []})
    with pytest.raises(ValueError, match="'markets' is empty"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_duplicate_token_raises(tmp_path):
    """Два рынка с одинаковым token -> ValueError."""
    a = _valid_market("xxxx")
    b = _valid_market("xxxx")  # тот же token
    path = _write_json(tmp_path, {"version": 1, "markets": [a, b]})
    with pytest.raises(ValueError, match="duplicate token"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_negative_min_size_raises(tmp_path):
    """min_size <= 0 -> ValueError."""
    m = _valid_market()
    m["min_size"] = -1
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"min_size must be > 0"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_zero_min_size_raises(tmp_path):
    """min_size == 0 -> ValueError (валидация строго > 0)."""
    m = _valid_market()
    m["min_size"] = 0
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"min_size must be > 0"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_min_size_is_string_raises(tmp_path):
    """min_size как строка — не число -> ValueError (type guard)."""
    m = _valid_market()
    m["min_size"] = "100"
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"min_size must be a positive number"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_min_size_is_bool_raises(tmp_path):
    """bool отвергаем явно — это подкласс int и пройдёт isinstance(int),
    но семантически это не валидный размер."""
    m = _valid_market()
    m["min_size"] = True
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"min_size must be a positive number"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_inv_center_gt_max_inv_raises(tmp_path):
    """inv_center > max_inv -> ValueError (известный инвариант демона:
    при inv > max_inv он начинает гнать one-sided и unload)."""
    m = _valid_market()
    m["inv_center"] = 500
    m["max_inv"] = 100
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"inv_center.*>.*max_inv"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_missing_required_field_raises(tmp_path):
    """Без token -> ValueError."""
    m = _valid_market()
    del m["token"]
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match="missing required field 'token'"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_empty_token_raises(tmp_path):
    """Пустой token -> ValueError (валидация non-empty)."""
    m = _valid_market()
    m["token"] = ""
    path = _write_json(tmp_path, {"version": 1, "markets": [m]})
    with pytest.raises(ValueError, match=r"token must be a non-empty string"):
        markets_config.load_markets_file(path=path)


def test_load_markets_file_default_path_constant():
    """MARKETS_FILE — строковая константа с абсолютным путём по S2."""
    assert isinstance(markets_config.MARKETS_FILE, str)
    assert markets_config.MARKETS_FILE.startswith("/")
    assert markets_config.MARKETS_FILE.endswith("markets.json")