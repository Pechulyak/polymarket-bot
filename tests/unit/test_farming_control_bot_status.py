# -*- coding: utf-8 -*-
"""Unit tests for executor/farming_control_bot.build_status_report (FARM-039 / FARM-030).

Импортируется farming_control_bot напрямую: у него НЕТ зависимости от
py_clob_client_v2, в отличие от farming_daemon.py. Поэтому эти тесты
могут крутиться без CLOB SDK.

Что покрываем:
  - markets.json подгружается через monkeypatch load_markets_file (на
    сам markets_config ссылается sibling-импортом `from markets_config
    import load_markets_file`, поэтому патчим имя
    `farming_control_bot.load_markets_file` — это та же функция);
  - FARMING_STATE_FILE подменяется на tmp JSON с двумя рынками, один из
    которых halted=True;
  - проверяем, что:
      * в отчёте есть строка "HALTED" для halted-рынка;
      * НЕТ "HALTED" для не-halted;
      * markets_error отображается при ошибке load_markets_file, и
        секция Markets пропускается.

Deploy-замечание: executor/ на S2 — flat-каталог без __init__.py, и
farming_control_bot.py делает sibling-импорт `from markets_config import ...`.
На S2 это работает потому, что systemd запускает бота с
WorkingDirectory=/opt/executor/app, и script-dir автоматически попадает в
sys.path[0]. Здесь executor/ временно добавляется в sys.path ТОЛЬКО на время
exec_module() (см. _load_farming_control_bot) и сразу убирается — иначе
исполняемая модификация sys.path на уровне импорта этого тест-файла делает
имя `executor` резолвящимся в executor/executor.py (там py_clob_client_v2,
не установлен здесь) для ЛЮБОГО другого теста, собираемого позже в этом же
pytest-прогоне (FARM-036 review: `pytest tests/unit/` без явного списка
файлов падал коллекцией test_markets_config.py из-за именно этой утечки).
"""

import importlib.util
import json
import logging
import sys
import tempfile
from pathlib import Path

# Sibling-import shim — same trick S2 gets for free via WorkingDirectory.
# Импортируем farming_control_bot как top-level модуль, НЕ как
# `executor.farming_control_bot`: при импорте через `executor.*` Python
# сканирует namespace-пакет executor/ и подтягивает executor.py (там
# py_clob_client_v2, не установлен в этой среде). Дополнительно — модуль
# на уровне import-time открывает /opt/executor/logs/farming_control_bot.log
# через logging.FileHandler(LOG_FILE). На S2 это работает, потому что есть
# /opt/executor. Здесь его нет — подменяем LOG_FILE на tmp-файл через
# переписывание исходника до загрузки (compile-and-exec не сработает:
# LOG_FILE = "..." перезапишет monkeypatch).
_EXECUTOR_DIR = Path(__file__).resolve().parent.parent.parent / "executor"


def _load_farming_control_bot() -> "module":
    """Load executor/farming_control_bot.py with LOG_FILE redirected to tmp.

    Без этого на S1/CI ModuleNotFoundError: /opt/executor/logs при попытке
    открыть лог. Остальные хардкод-пути (FARMING_STATE_FILE и т.п.) используются
    только внутри функций — патчатся через monkeypatch в фикстурах."""
    src_path = _EXECUTOR_DIR / "farming_control_bot.py"
    src = src_path.read_text()
    original = 'LOG_FILE = "/opt/executor/logs/farming_control_bot.log"'
    replacement = 'LOG_FILE = "/tmp/farm039_test_control_bot.log"'
    if original not in src:
        raise RuntimeError(
            f"LOG_FILE line not found in {src_path} — переписывание не сработает"
        )
    patched = src.replace(original, replacement, 1)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(patched)
        tmp_path = f.name
    spec = importlib.util.spec_from_file_location(
        "farming_control_bot", tmp_path
    )
    mod = importlib.util.module_from_spec(spec)
    # executor/ нужен на sys.path ТОЛЬКО на время exec_module() — внутри него
    # выполняется `from markets_config import ...` (sibling-импорт). Сразу
    # после — убираем, чтобы не подсовывать executor/executor.py как
    # содержимое пакета "executor" при коллекции других тестовых файлов.
    path_inserted = str(_EXECUTOR_DIR) not in sys.path
    if path_inserted:
        sys.path.insert(0, str(_EXECUTOR_DIR))
    try:
        spec.loader.exec_module(mod)
    finally:
        if path_inserted:
            try:
                sys.path.remove(str(_EXECUTOR_DIR))
            except ValueError:
                pass
    sys.modules["farming_control_bot"] = mod
    return mod


import pytest

farming_control_bot = _load_farming_control_bot()


# ─── fixtures ────────────────────────────────────────────────────────────────
M_TOKEN_HALTED = "1053686257956554329641904967545466502708810704516554306841101666130600000001"
M_TOKEN_NORMAL = "1053686257956554329641904967545466502708810704516554306841101666130600000002"
M_NAME_HALTED = "Test Halted Market"
M_NAME_NORMAL = "Test Normal Market"


def _build_markets_payload() -> list[dict]:
    return [
        {
            "name": M_NAME_HALTED,
            "token": M_TOKEN_HALTED,
            "min_size": 100, "inv_center": 100,
            "inv_deadband": 50, "max_inv": 300,
            "weight": 1.0, "gamma_id": 1,
            "condition_id": "0xa",
        },
        {
            "name": M_NAME_NORMAL,
            "token": M_TOKEN_NORMAL,
            "min_size": 100, "inv_center": 100,
            "inv_deadband": 50, "max_inv": 300,
            "weight": 1.0, "gamma_id": 2,
            "condition_id": "0xb",
        },
    ]


def _build_state(halted: bool) -> dict:
    """State file mimics farming_daemon.py:save_state_file() — token-keyed
    per-market state + опционально _alerts."""
    return {
        M_TOKEN_HALTED: {
            "last_ts": 1700000000,
            "pause_until": 0,
            "halted": halted,
        },
        M_TOKEN_NORMAL: {
            "last_ts": 1700000000,
            "pause_until": 0,
            "halted": False,
        },
    }


@pytest.fixture
def patched_state_and_markets(tmp_path: Path, monkeypatch):
    """Patch markets.json loader (returns _build_markets_payload()) and
    FARMING_STATE_FILE (writes fixture state). Возвращает кортеж
    (markets_payload, halted_value)."""
    halted = True
    state = _build_state(halted=halted)
    state_path = tmp_path / "farming_state.json"
    state_path.write_text(json.dumps(state))

    monkeypatch.setattr(farming_control_bot, "FARMING_STATE_FILE", str(state_path))
    monkeypatch.setattr(farming_control_bot, "load_markets_file",
                        lambda: _build_markets_payload())

    return _build_markets_payload(), halted


# ─── tests ───────────────────────────────────────────────────────────────────
def test_status_report_shows_halted_for_halted_market(patched_state_and_markets):
    """В отчёте строка с halted-рынком содержит 'HALTED'."""
    _, halted = patched_state_and_markets
    assert halted is True
    report = farming_control_bot.build_status_report()
    assert M_NAME_HALTED in report
    assert "HALTED" in report
    # halted -> оператор должен увидеть подсказку про /stop -> правка -> /start
    assert "/stop" in report


def test_status_report_has_no_halted_for_normal_market(patched_state_and_markets):
    """В строке с normal-рынком НЕТ 'HALTED' (только ▶ active или ○ idle)."""
    report = farming_control_bot.build_status_report()
    # Ищем строку normal-рынка и убеждаемся, что в ней нет HALTED
    lines = report.splitlines()
    normal_lines = [l for l in lines if M_NAME_NORMAL in l]
    assert normal_lines, "normal market line missing"
    for line in normal_lines:
        assert "HALTED" not in line, f"unexpected HALTED in normal line: {line}"


def test_status_report_halted_only_marks_one_market(patched_state_and_markets):
    """Из двух рынков HALTED только у одного — это легко проверить, чтобы
    исключить ситуацию, когда глобально ставится '⛔' на оба."""
    report = farming_control_bot.build_status_report()
    # Строка рынка — "  <b>Name</b>  ⛔ HALTED (...)" (имя перед статусом,
    # как и у pause_str) — ищем строки, СОДЕРЖАЩИЕ "⛔ HALTED", не startswith.
    hal_lines = [l for l in report.splitlines() if "⛔ HALTED" in l]
    assert len(hal_lines) == 1, (
        f"expected exactly one ⛔ HALTED line, got {len(hal_lines)}: {hal_lines}"
    )


def test_status_report_daemon_status_line_present(patched_state_and_markets):
    """Первая строка отчёта — статус демона (ACTIVE/INACTIVE).
    is_daemon_active() зовёт `systemctl is-active` — но если systemd
    отсутствует (мы в S1/CI), возвращает False -> 'INACTIVE'.
    Главное, что первая строка начинается с 🟢/🔴 и содержит 'farming-daemon'."""
    report = farming_control_bot.build_status_report()
    first = report.splitlines()[0]
    assert "farming-daemon" in first
    assert first.lstrip()[0] in ("🟢", "🔴")


def test_status_report_markets_section_present(patched_state_and_markets):
    """При валидном markets.json — секция 'Markets:' присутствует."""
    report = farming_control_bot.build_status_report()
    assert "<b>Markets:</b>" in report
    assert "<b>Alerts:</b>" in report


def test_status_report_marks_error_on_bad_markets_json(tmp_path, monkeypatch, caplog):
    """Если load_markets_file падает — markets_error в отчёте, секция Markets
    пропускается (алерты бесполезны без token->name маппинга)."""
    state_path = tmp_path / "farming_state.json"
    state_path.write_text(json.dumps({M_TOKEN_HALTED: {"halted": True}}))
    monkeypatch.setattr(farming_control_bot, "FARMING_STATE_FILE", str(state_path))

    def _bad_loader():
        raise ValueError("simulated file error: parse fail")

    monkeypatch.setattr(farming_control_bot, "load_markets_file", _bad_loader)

    with caplog.at_level(logging.WARNING):
        report = farming_control_bot.build_status_report()

    # markets_error отображается, и знак '⚠️ markets.json:' присутствует
    assert "markets.json:" in report
    assert "simulated file error" in report
    # Секция Markets НЕ рендерится (markets=[] -> ранний return)
    assert "<b>Markets:</b>" not in report
    assert "<b>Alerts:</b>" not in report


def test_status_report_uses_dynamic_markets_not_module_level(
    tmp_path, monkeypatch
):
    """Гарантия: build_status_report подгружает markets на КАЖДЫЙ вызов
    (не из модульной переменной). Делаем два разных состояния markets.json
    между вызовами — обе версии должны отразиться."""
    state_path = tmp_path / "farming_state.json"
    state_path.write_text(json.dumps({
        M_TOKEN_HALTED: {"halted": False, "last_ts": 0},
    }))
    monkeypatch.setattr(farming_control_bot, "FARMING_STATE_FILE", str(state_path))

    # Первый вызов — только halted-рынок
    only_halted = [_build_markets_payload()[0]]
    # Второй вызов — только normal-рынок
    only_normal = [_build_markets_payload()[1]]

    seq = iter([only_halted, only_normal])
    monkeypatch.setattr(farming_control_bot, "load_markets_file",
                        lambda: next(seq))

    r1 = farming_control_bot.build_status_report()
    r2 = farming_control_bot.build_status_report()

    # В r1 halted-рынок есть и HALTED-строки нет (halted=False)
    assert M_NAME_HALTED in r1
    assert "HALTED" not in r1
    # В r2 halted-рынка нет, normal-рынок есть
    assert M_NAME_NORMAL in r2
    assert M_NAME_HALTED not in r2