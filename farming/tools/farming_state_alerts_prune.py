#!/usr/bin/env python3
"""
FARM-042 — разовая очистка phantom/stale ключей _alerts в farming_state.json.

До этого пакета farming_daemon.save_state_file() никогда не чистил _alerts от
токенов, ротированных из MARKETS (см. FARM-042 в save_state_file()) — теперь
чистит сам на каждом save, но уже накопленный мусор в текущем
farming_state.json на S2 остаётся до первого запуска этого скрипта или до
следующего save демона после деплоя.

Логика идентична очистке в farming_daemon.save_state_file(): ключ
"<type>:<token>" сохраняется, только если token есть в текущем markets.json.
Ничего кроме _alerts не трогает (токен-курсоры, halted, pause_until,
unload_id, last_adverse_fill остаются как есть — FARM-016/FARM-025 не
затрагиваются).

Использование на S2:
    python3 /opt/executor/app/farming_state_alerts_prune.py           # dry-run, печатает diff
    python3 /opt/executor/app/farming_state_alerts_prune.py --apply   # применяет атомарной записью

Безопаснее запускать при остановленном демоне (/stop) — иначе следующий
save демона (раз в POLL_INTERVAL сек) перезапишет файл поверх в любом случае
(и сам всё почистит благодаря FARM-042), так что штатный путь — просто
подождать; этот скрипт нужен только если хочется почистить немедленно, не
дожидаясь следующего тика.
"""
import argparse
import json
import os
import sys

DEFAULT_STATE = "/opt/executor/app/farming_state.json"
DEFAULT_MARKETS = "/opt/executor/app/markets.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--markets", default=DEFAULT_MARKETS)
    ap.add_argument("--apply", action="store_true",
                    help="Записать очищенный файл (по умолчанию — только показать diff)")
    args = ap.parse_args()

    with open(args.markets) as f:
        markets = json.load(f)["markets"]
    current_tokens = {m["token"] for m in markets}

    with open(args.state) as f:
        state = json.load(f)

    alerts = state.get("_alerts", {})
    kept = {k: v for k, v in alerts.items()
            if ":" not in k or k.rsplit(":", 1)[-1] in current_tokens}
    removed = sorted(set(alerts) - set(kept))

    if not removed:
        print("OK: нет phantom/stale ключей в _alerts, менять нечего")
        return 0

    print(f"Phantom/stale ключи в _alerts ({len(removed)} из {len(alerts)}):")
    for k in removed:
        print(f"  - {k}: {alerts[k]}")

    if not args.apply:
        print("\nDry-run (по умолчанию). Для применения: --apply")
        return 0

    state["_alerts"] = kept
    tmp = args.state + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, args.state)
    print(f"\nПрименено: {args.state} обновлён, удалено {len(removed)} ключей")
    return 0


if __name__ == "__main__":
    sys.exit(main())
