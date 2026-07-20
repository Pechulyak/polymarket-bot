#!/usr/bin/env python3
"""ACT-010: find CTF Exchange transactions absent from account_activity.

Read-only investigation. Scan Polygon OrderFilled logs for both tracked wallets in
both maker and taker roles, then compare every discovered transaction hash with
account_activity. The script never modifies the database.
"""

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2


RPC_URLS = [
    "https://polygon-pokt.nodies.app",
    "https://polygon.api.onfinality.io/public",
    "https://polygon.drpc.org",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

CTF_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
ORDER_FILLED_SIG = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
OUR_WALLETS = {
    "0x3fc83d2b40f9f243cbcd51a53cfdd7e9a6d366a1": "PechaArt",
    "0x5f032ff0e9376538ac240417ea5863756e1f2634": "Justfuuun",
}

START_BLOCK = int(os.environ.get("ACT010_START_BLOCK", "88700000"))
CHUNK_SIZE = int(os.environ.get("ACT010_CHUNK_SIZE", "10000"))
END_BLOCK_OVERRIDE = os.environ.get("ACT010_END_BLOCK")
RPC_SUBRANGE_SIZE = int(os.environ.get("ACT010_RPC_SUBRANGE_SIZE", "250"))
RPC_BATCH_SIZE = int(os.environ.get("ACT010_RPC_BATCH_SIZE", "10"))
RPC_WORKERS = int(os.environ.get("ACT010_RPC_WORKERS", "1"))
RPC_REQUEST_PAUSE_SECONDS = float(os.environ.get("ACT010_RPC_REQUEST_PAUSE", "0.6"))
CHUNK_PAUSE_SECONDS = 0.25
REPORT_EVERY_CHUNKS = 20
REPORT_PATH = "/root/polymarket-bot/scratchpad/act010_report.md"
RPC_TIMEOUT_SECONDS = 45
RPC_ROUNDS = 4
CHECKPOINT_BEGIN = "<!-- ACT010_CHECKPOINT\n"
CHECKPOINT_END = "\nACT010_CHECKPOINT -->"


class RpcClient:
    """JSON-RPC client that starts each request at the primary endpoint."""

    def __init__(self):
        self.attempts = Counter()
        self.successes = Counter()
        self.errors = Counter()
        self.last_errors = {}

    def call(self, method, params):
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }).encode()

        for round_index in range(RPC_ROUNDS):
            for url in RPC_URLS:
                self.attempts[url] += 1
                request = urllib.request.Request(
                    url,
                    data=body,
                    headers=HEADERS,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(
                        request, timeout=RPC_TIMEOUT_SECONDS
                    ) as response:
                        payload = json.loads(response.read())
                    if payload.get("error") is not None:
                        raise RuntimeError(
                            f"JSON-RPC error: {json.dumps(payload['error'], ensure_ascii=False)}"
                        )
                    if "result" not in payload:
                        raise RuntimeError("JSON-RPC response has no result")
                    self.successes[url] += 1
                    return payload["result"]
                except urllib.error.HTTPError as exc:
                    try:
                        response_body = exc.read().decode("utf-8", errors="replace")
                    except Exception:
                        response_body = ""
                    detail = f"HTTPError: HTTP {exc.code} {exc.reason}"
                    if response_body:
                        detail += f"; body={response_body[:1000]}"
                    self.errors[url] += 1
                    self.last_errors[url] = detail
                    print(
                        f"RPC failover: {method} failed via {url}: {detail}",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(0.15)
                except Exception as exc:
                    self.errors[url] += 1
                    self.last_errors[url] = f"{type(exc).__name__}: {exc}"
                    print(
                        f"RPC failover: {method} failed via {url}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(0.15)

            if round_index + 1 < RPC_ROUNDS:
                time.sleep(0.5 * (round_index + 1))

        details = "; ".join(
            f"{url}: {self.last_errors.get(url, 'unknown error')}"
            for url in RPC_URLS
        )
        raise RuntimeError(
            f"all Polygon RPC endpoints failed for {method} after "
            f"{RPC_ROUNDS} rounds ({details})"
        )

    def call_batch(self, method, params_batch):
        """Execute independent JSON-RPC calls in one HTTP batch request."""
        calls = [
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": index + 1,
            }
            for index, params in enumerate(params_batch)
        ]
        body = json.dumps(calls).encode()

        for round_index in range(RPC_ROUNDS):
            for url in RPC_URLS:
                self.attempts[url] += 1
                request = urllib.request.Request(
                    url,
                    data=body,
                    headers=HEADERS,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(
                        request, timeout=RPC_TIMEOUT_SECONDS
                    ) as response:
                        payload = json.loads(response.read())
                    if not isinstance(payload, list):
                        raise RuntimeError(
                            f"batch response is {type(payload).__name__}, expected list: {payload}"
                        )
                    by_id = {item.get("id"): item for item in payload}
                    results = []
                    for call in calls:
                        item = by_id.get(call["id"])
                        if item is None:
                            raise RuntimeError(
                                f"batch response is missing id={call['id']}"
                            )
                        if item.get("error") is not None:
                            raise RuntimeError(
                                f"JSON-RPC batch item error: "
                                f"{json.dumps(item['error'], ensure_ascii=False)}"
                            )
                        if "result" not in item:
                            raise RuntimeError(
                                f"JSON-RPC batch item id={call['id']} has no result"
                            )
                        results.append(item["result"])
                    self.successes[url] += 1
                    time.sleep(RPC_REQUEST_PAUSE_SECONDS)
                    return results
                except urllib.error.HTTPError as exc:
                    try:
                        response_body = exc.read().decode("utf-8", errors="replace")
                    except Exception:
                        response_body = ""
                    detail = f"HTTPError: HTTP {exc.code} {exc.reason}"
                    if response_body:
                        detail += f"; body={response_body[:1000]}"
                    self.errors[url] += 1
                    self.last_errors[url] = detail
                    print(
                        f"RPC batch failover: {method} failed via {url}: {detail}",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(0.15)
                except Exception as exc:
                    self.errors[url] += 1
                    self.last_errors[url] = f"{type(exc).__name__}: {exc}"
                    print(
                        f"RPC batch failover: {method} failed via {url}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(0.15)

            if round_index + 1 < RPC_ROUNDS:
                time.sleep(0.5 * (round_index + 1))

        details = "; ".join(
            f"{url}: {self.last_errors.get(url, 'unknown error')}"
            for url in RPC_URLS
        )
        raise RuntimeError(
            f"all Polygon RPC endpoints failed for batch {method} after "
            f"{RPC_ROUNDS} rounds ({details})"
        )


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def padded_address(address):
    return "0x" + ("0" * 24) + address.removeprefix("0x").lower()


def decode_uint256_words(data, expected_words=5):
    raw = data.removeprefix("0x")
    expected_length = expected_words * 64
    if len(raw) < expected_length:
        raise ValueError(
            f"OrderFilled data is too short: {len(raw)} hex chars, "
            f"expected at least {expected_length}"
        )
    return [int(raw[offset:offset + 64], 16) for offset in range(0, expected_length, 64)]


def decode_order_filled(log):
    topics = log.get("topics", [])
    if len(topics) < 4:
        raise ValueError(f"OrderFilled log has only {len(topics)} topics")

    maker_asset_id, taker_asset_id, maker_amount, taker_amount, fee = (
        decode_uint256_words(log.get("data", "0x"))
    )
    return {
        "tx_hash": log["transactionHash"].lower(),
        "log_index": int(log.get("logIndex", "0x0"), 16),
        "block_number": int(log["blockNumber"], 16),
        "order_hash": topics[1].lower(),
        "maker": ("0x" + topics[2][-40:]).lower(),
        "taker": ("0x" + topics[3][-40:]).lower(),
        "maker_asset_id": str(maker_asset_id),
        "taker_asset_id": str(taker_asset_id),
        "maker_amount_filled": maker_amount,
        "taker_amount_filled": taker_amount,
        "fee": fee,
    }


def event_associations(event):
    associations = set()
    maker_account = OUR_WALLETS.get(event["maker"])
    taker_account = OUR_WALLETS.get(event["taker"])
    if maker_account:
        associations.add((maker_account, "maker"))
    if taker_account:
        associations.add((taker_account, "taker"))
    return associations


def add_logs(transactions, logs, state):
    for raw_log in logs:
        if raw_log.get("address", "").lower() != CTF_EXCHANGE:
            state["ignored_logs"] += 1
            continue
        topics = raw_log.get("topics", [])
        if not topics or topics[0].lower() != ORDER_FILLED_SIG:
            state["ignored_logs"] += 1
            continue

        event = decode_order_filled(raw_log)
        associations = event_associations(event)
        if not associations:
            state["unattributed_logs"] += 1
            continue
        event["associations"] = associations

        tx_hash = event["tx_hash"]
        event_key = (tx_hash, event["log_index"])
        tx = transactions.setdefault(tx_hash, {
            "tx_hash": tx_hash,
            "block_number": event["block_number"],
            "events": {},
        })
        if event_key in tx["events"]:
            existing = tx["events"][event_key]
            existing["associations"].update(associations)
            state["duplicate_log_hits"] += 1
        else:
            tx["events"][event_key] = event
            state["unique_logs"] += 1


def connect_read_only_db():
    connection = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5433")),
        dbname=os.environ.get("PGDATABASE", "polymarket"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )
    connection.set_session(readonly=True, autocommit=True)
    return connection


def update_db_counts(cursor, transactions, db_counts):
    new_hashes = sorted(set(transactions) - set(db_counts))
    for tx_hash in new_hashes:
        cursor.execute(
            "SELECT COUNT(*) FROM account_activity WHERE tx_hash = %s",
            (tx_hash,),
        )
        db_counts[tx_hash] = int(cursor.fetchone()[0])
    return len(new_hashes)


def tx_associations(tx):
    result = set()
    for event in tx["events"].values():
        result.update(event["associations"])
    return result


def decimal_units(value):
    return format(Decimal(value) / Decimal(1_000_000), "f")


def serialize_checkpoint(transactions, db_counts, state):
    serialized_transactions = []
    for tx in transactions.values():
        serialized_events = []
        for event in tx["events"].values():
            serialized_event = dict(event)
            serialized_event["associations"] = [
                list(item) for item in sorted(event["associations"])
            ]
            serialized_events.append(serialized_event)
        serialized_transactions.append({
            "tx_hash": tx["tx_hash"],
            "block_number": tx["block_number"],
            "events": serialized_events,
        })
    return {
        "state": state,
        "db_counts": db_counts,
        "transactions": serialized_transactions,
    }


def load_checkpoint():
    if os.environ.get("ACT010_RESUME") != "1":
        return None
    try:
        with open(REPORT_PATH, "r", encoding="utf-8") as report:
            content = report.read()
    except FileNotFoundError:
        return None
    start = content.rfind(CHECKPOINT_BEGIN)
    end = content.rfind(CHECKPOINT_END)
    if start < 0 or end < start:
        return None
    payload_text = content[start + len(CHECKPOINT_BEGIN):end]
    payload = json.loads(payload_text)

    transactions = {}
    for serialized_tx in payload["transactions"]:
        tx = {
            "tx_hash": serialized_tx["tx_hash"],
            "block_number": serialized_tx["block_number"],
            "events": {},
        }
        for event in serialized_tx["events"]:
            event["associations"] = {
                tuple(item) for item in event["associations"]
            }
            event_key = (event["tx_hash"], event["log_index"])
            tx["events"][event_key] = event
        transactions[tx["tx_hash"]] = tx
    return transactions, payload["db_counts"], payload["state"]


def hashes_for(transactions, account=None, role=None):
    result = set()
    for tx_hash, tx in transactions.items():
        for event_account, event_role in tx_associations(tx):
            if account is not None and event_account != account:
                continue
            if role is not None and event_role != role:
                continue
            result.add(tx_hash)
            break
    return result


def summary_row(label, tx_hashes, db_counts):
    classified = [tx_hash for tx_hash in tx_hashes if tx_hash in db_counts]
    missing = sum(db_counts[tx_hash] == 0 for tx_hash in classified)
    present = sum(db_counts[tx_hash] > 0 for tx_hash in classified)
    return (
        f"| {label} | {len(tx_hashes)} | {missing} | {present} | "
        f"{len(tx_hashes) - len(classified)} |"
    )


def write_report(transactions, db_counts, state, rpc, status, error=None):
    all_hashes = set(transactions)
    missing_hashes = sorted(
        tx_hash for tx_hash in all_hashes if db_counts.get(tx_hash) == 0
    )
    present_hashes = sorted(
        tx_hash for tx_hash in all_hashes if db_counts.get(tx_hash, 0) > 0
    )
    unclassified = sorted(all_hashes - set(db_counts))

    lines = [
        "# ACT-010 — полный on-chain scan CTF Exchange",
        "",
        "## Статус",
        "",
        f"- Состояние: **{status}**",
        f"- Последнее обновление (UTC): `{utc_now()}`",
        f"- Начало запуска (UTC): `{state['started_at']}`",
        "- Режим БД: read-only (`connection.set_session(readonly=True, autocommit=True)`); выполняется только параметризованный `SELECT COUNT(*)`.",
        "- Источник on-chain: Polygon JSON-RPC `eth_blockNumber` + `eth_getLogs`; транзакции и БД не модифицируются.",
        "",
        "## Методология",
        "",
        "ACT-009 начинал с `tx_hash`, уже присутствующих в `account_activity`, и поэтому не мог найти полностью пропущенную транзакцию. ACT-010 независимо сканирует `OrderFilled` CTF Exchange для PechaArt/Justfuuun как maker и taker, агрегирует уникальные события по `(transactionHash, logIndex)` и затем проверяет наличие каждого уникального `transactionHash` в `account_activity`.",
        "",
        "## Прогресс скана",
        "",
        f"- Диапазон: `{state.get('scan_origin', START_BLOCK):,}` — `{state.get('head_block', 'ещё не получен')}` включительно.",
        f"- Завершено block-чанков: **{state['completed_chunks']}/{state.get('total_chunks', '?')}** (по 4 фильтра на чанк).",
        f"- Завершено `eth_getLogs` запросов: **{state['completed_queries']}**.",
        f"- Получено log-hits до дедупликации: **{state['raw_log_hits']}**.",
        f"- Уникальных `OrderFilled` событий: **{state['unique_logs']}**; повторных попаданий из пересекающихся фильтров: **{state['duplicate_log_hits']}**.",
        f"- Уникальных `tx_hash` on-chain: **{len(all_hashes)}**; сверено с БД: **{len(all_hashes) - len(unclassified)}**.",
        "",
        "### RPC failover",
        "",
        "| RPC | попыток | успешно | ошибок | последняя ошибка |",
        "|---|---:|---:|---:|---|",
    ]
    for url in RPC_URLS:
        last_error = rpc.last_errors.get(url, "—").replace("|", "\\|")
        lines.append(
            f"| `{url}` | {rpc.attempts[url]} | {rpc.successes[url]} | "
            f"{rpc.errors[url]} | {last_error} |"
        )

    lines.extend([
        "",
        "## Результаты по аккаунтам и ролям",
        "",
        "`Присутствуют` означает, что в `account_activity` есть хотя бы одна строка с этим `tx_hash`; это только подсчёт известного паттерна ACT-009, без повторного анализа полноты строк внутри транзакции.",
        "",
        "| Аккаунт / роль | уникальных tx on-chain | found_missing (COUNT=0) | присутствуют хотя бы частично (COUNT>0) | ещё не сверено |",
        "|---|---:|---:|---:|---:|",
    ])
    for account in OUR_WALLETS.values():
        for role in ("maker", "taker"):
            role_hashes = hashes_for(transactions, account, role)
            lines.append(summary_row(f"{account} / {role}", role_hashes, db_counts))
        account_hashes = hashes_for(transactions, account=account)
        lines.append(summary_row(f"**{account} / все роли**", account_hashes, db_counts))
    lines.append(summary_row("**Все аккаунты / union**", all_hashes, db_counts))

    lines.extend([
        "",
        "## Полностью отсутствующие транзакции (`found_missing`)",
        "",
        f"Найдено **{len(missing_hashes)}** уникальных `tx_hash` с `SELECT COUNT(*) = 0`.",
        "",
    ])

    if not missing_hashes:
        if status == "завершён":
            lines.append("Полностью отсутствующих транзакций не найдено.")
        else:
            lines.append("На уже просканированной части диапазона полностью отсутствующих транзакций пока не найдено.")
        lines.append("")

    for tx_hash in missing_hashes:
        tx = transactions[tx_hash]
        associations = sorted(
            f"{account}/{role}" for account, role in tx_associations(tx)
        )
        lines.extend([
            f"### `{tx_hash}`",
            "",
            "- `found_missing`: **true**",
            "- строк в `account_activity`: **0**",
            f"- blockNumber: **{tx['block_number']}** (`{hex(tx['block_number'])}`)",
            f"- наши аккаунты/роли: {', '.join(associations)}",
            f"- уникальных найденных `OrderFilled` событий: {len(tx['events'])}",
            "",
        ])
        for event in sorted(
            tx["events"].values(), key=lambda item: item["log_index"]
        ):
            event_roles = ", ".join(
                sorted(f"{account}/{role}" for account, role in event["associations"])
            )
            lines.extend([
                f"#### logIndex {event['log_index']} / orderHash `{event['order_hash']}`",
                "",
                f"- maker: `{event['maker']}`",
                f"- taker: `{event['taker']}`",
                f"- наш аккаунт/роль: {event_roles}",
                f"- makerAssetId: `{event['maker_asset_id']}`",
                f"- takerAssetId: `{event['taker_asset_id']}`",
                f"- makerAmountFilled: **{decimal_units(event['maker_amount_filled'])}** (raw `{event['maker_amount_filled']}`)",
                f"- takerAmountFilled: **{decimal_units(event['taker_amount_filled'])}** (raw `{event['taker_amount_filled']}`)",
                f"- fee: **{decimal_units(event['fee'])}** (raw `{event['fee']}`)",
                "",
            ])

    lines.extend([
        "## Транзакции, присутствующие хотя бы частично",
        "",
        f"Уникальных `tx_hash` с `SELECT COUNT(*) > 0`: **{len(present_hashes)}**.",
        "Подробный re-анализ event-level расхождений не выполнялся: это область ACT-009 и не является целью ACT-010.",
        "",
    ])
    if unclassified:
        lines.extend([
            "## Ещё не сверенные с БД tx_hash",
            "",
            f"Количество: **{len(unclassified)}**. Они будут классифицированы при следующем инкрементальном обновлении.",
            "",
        ])
    if error:
        lines.extend([
            "## Ошибка / причина неполного результата",
            "",
            "```text",
            error.rstrip(),
            "```",
            "",
        ])

    checkpoint = serialize_checkpoint(transactions, db_counts, state)
    lines.extend([
        CHECKPOINT_BEGIN.rstrip("\n"),
        json.dumps(checkpoint, ensure_ascii=False, separators=(",", ":")),
        CHECKPOINT_END.lstrip("\n"),
    ])

    with open(REPORT_PATH, "w", encoding="utf-8") as report:
        report.write("\n".join(lines))
        report.flush()
        os.fsync(report.fileno())


def scan_chunk(rpc, from_block, to_block):
    jobs = []
    for wallet, account in OUR_WALLETS.items():
        for role in ("maker", "taker"):
            topics = [ORDER_FILLED_SIG, None]
            if role == "maker":
                topics.append(padded_address(wallet))
            else:
                topics.extend([None, padded_address(wallet)])

            params_batch = []
            for rpc_from in range(from_block, to_block + 1, RPC_SUBRANGE_SIZE):
                rpc_to = min(rpc_from + RPC_SUBRANGE_SIZE - 1, to_block)
                params_batch.append([{
                    "address": CTF_EXCHANGE,
                    "fromBlock": hex(rpc_from),
                    "toBlock": hex(rpc_to),
                    "topics": topics,
                }])
                if len(params_batch) == RPC_BATCH_SIZE:
                    jobs.append((account, role, params_batch))
                    params_batch = []
            if params_batch:
                jobs.append((account, role, params_batch))

    logs = []
    rpc_query_count = 0
    hit_counts = Counter()
    with ThreadPoolExecutor(max_workers=RPC_WORKERS) as executor:
        futures = {
            executor.submit(rpc.call_batch, "eth_getLogs", params_batch):
                (account, role, params_batch)
            for account, role, params_batch in jobs
        }
        for future in as_completed(futures):
            account, role, params_batch = futures[future]
            results = future.result()
            rpc_query_count += len(params_batch)
            for result in results:
                if not isinstance(result, list):
                    raise RuntimeError(
                        f"eth_getLogs returned {type(result).__name__}, expected list"
                    )
                logs.extend(result)
                hit_counts[(account, role)] += len(result)

    return logs, rpc_query_count, hit_counts


def main():
    state = {
        "started_at": utc_now(),
        "scan_origin": START_BLOCK,
        "next_block": START_BLOCK,
        "head_block": None,
        "total_chunks": 0,
        "completed_chunks": 0,
        "completed_queries": 0,
        "raw_log_hits": 0,
        "unique_logs": 0,
        "duplicate_log_hits": 0,
        "ignored_logs": 0,
        "unattributed_logs": 0,
    }
    transactions = {}
    db_counts = {}
    rpc = RpcClient()
    connection = None
    cursor = None

    checkpoint = load_checkpoint()
    if checkpoint is not None:
        transactions, db_counts, state = checkpoint
        print(
            f"resuming checkpoint: next_block={state['next_block']}, "
            f"completed_chunks={state['completed_chunks']}, "
            f"unique_tx={len(transactions)}",
            flush=True,
        )

    try:
        head_hex = rpc.call("eth_blockNumber", [])
        chain_head_block = int(head_hex, 16)
        head_block = chain_head_block
        if END_BLOCK_OVERRIDE is not None:
            head_block = min(chain_head_block, int(END_BLOCK_OVERRIDE))
        scan_origin = state.get("scan_origin", START_BLOCK)
        if head_block < scan_origin:
            raise RuntimeError(
                f"current Polygon head {head_block} is below scan origin {scan_origin}"
            )
        state["scan_origin"] = scan_origin
        state["head_block"] = head_block
        state["total_chunks"] = (
            (head_block - scan_origin) // CHUNK_SIZE
        ) + 1

        connection = connect_read_only_db()
        cursor = connection.cursor()
        cursor.execute("SELECT current_setting('transaction_read_only')")
        read_only_setting = cursor.fetchone()[0]
        if read_only_setting != "on":
            raise RuntimeError(
                f"database session is not read-only: transaction_read_only={read_only_setting}"
            )

        write_report(
            transactions, db_counts, state, rpc, "выполняется (инициализация завершена)"
        )
        scan_from = max(state.get("next_block", scan_origin), scan_origin)
        print(
            f"ACT-010 scan: blocks {scan_origin}-{head_block}, "
            f"resume_from={scan_from}, chunks={state['total_chunks']}, filters/chunk=4",
            flush=True,
        )

        first_chunk_index = state.get("completed_chunks", 0) + 1
        for chunk_index, from_block in enumerate(
            range(scan_from, head_block + 1, CHUNK_SIZE),
            start=first_chunk_index,
        ):
            to_block = min(from_block + CHUNK_SIZE - 1, head_block)
            logs, rpc_query_count, hit_counts = scan_chunk(
                rpc, from_block, to_block
            )
            state["completed_queries"] += rpc_query_count
            state["raw_log_hits"] += len(logs)
            add_logs(transactions, logs, state)
            for (account, role), hit_count in sorted(hit_counts.items()):
                if hit_count:
                    print(
                        f"chunk {chunk_index}/{state['total_chunks']} "
                        f"{from_block}-{to_block} {account}/{role}: "
                        f"{hit_count} log(s)",
                        flush=True,
                    )

            state["completed_chunks"] = chunk_index
            state["next_block"] = to_block + 1
            should_report = (
                chunk_index == 1
                or chunk_index % REPORT_EVERY_CHUNKS == 0
                or chunk_index == state["total_chunks"]
            )
            if should_report:
                newly_classified = update_db_counts(
                    cursor, transactions, db_counts
                )
                write_report(
                    transactions,
                    db_counts,
                    state,
                    rpc,
                    "выполняется",
                )
                missing_count = sum(count == 0 for count in db_counts.values())
                present_count = sum(count > 0 for count in db_counts.values())
                print(
                    f"progress {chunk_index}/{state['total_chunks']}: "
                    f"unique_tx={len(transactions)}, new_db_checks={newly_classified}, "
                    f"missing={missing_count}, present={present_count}; "
                    f"report updated",
                    flush=True,
                )

            time.sleep(CHUNK_PAUSE_SECONDS)

        update_db_counts(cursor, transactions, db_counts)
        write_report(
            transactions, db_counts, state, rpc, "завершён"
        )
        print(
            f"completed: unique_tx={len(transactions)}, "
            f"missing={sum(count == 0 for count in db_counts.values())}, "
            f"present={sum(count > 0 for count in db_counts.values())}",
            flush=True,
        )
        print(f"report: {REPORT_PATH}", flush=True)
    except Exception:
        error = traceback.format_exc()
        try:
            if cursor is not None:
                update_db_counts(cursor, transactions, db_counts)
            write_report(
                transactions,
                db_counts,
                state,
                rpc,
                "НЕ ЗАВЕРШЁН — сохранён частичный результат",
                error=error,
            )
        except Exception as report_exc:
            print(
                f"failed to update partial report: {report_exc}",
                file=sys.stderr,
                flush=True,
            )
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
