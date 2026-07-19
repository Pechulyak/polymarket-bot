#!/usr/bin/env python3
"""ACT-009 investigation: find TRADE rows lost to dedup-key collisions.

Read-only. For every distinct tx_hash among TRADE events in account_activity,
fetch the on-chain receipt (Polygon RPC), count real OrderFilled events (CTF
Exchange) attributable to our two proxy wallets, and compare against the
number of DB rows for that (tx_hash, account). Report every mismatch with
full on-chain order details needed for a backfill.
"""
import json
import time
import urllib.request
import psycopg2

RPC_URLS = [
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


def rpc_call(tx_hash, rpc_index=0):
    if rpc_index >= len(RPC_URLS):
        return None
    body = json.dumps({
        "jsonrpc": "2.0", "method": "eth_getTransactionReceipt",
        "params": [tx_hash], "id": 1,
    }).encode()
    req = urllib.request.Request(RPC_URLS[rpc_index], data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("result")
    except Exception:
        return rpc_call(tx_hash, rpc_index + 1)


def decode_order_filled(log):
    topics = log["topics"]
    order_hash = topics[1]
    maker = "0x" + topics[2][-40:]
    taker = "0x" + topics[3][-40:]
    return order_hash, maker.lower(), taker.lower()


def main():
    conn = psycopg2.connect(host="localhost", port=5433, dbname="polymarket", user="postgres", password="postgres")
    cur = conn.cursor()
    cur.execute(
        "SELECT tx_hash, account, count(*) FROM account_activity "
        "WHERE event_type = 'TRADE' GROUP BY tx_hash, account ORDER BY tx_hash"
    )
    db_counts = {}  # (tx_hash, account) -> db row count
    for tx_hash, account, cnt in cur.fetchall():
        db_counts[(tx_hash, account)] = cnt

    unique_tx = sorted({tx for (tx, _acc) in db_counts})
    print(f"total unique TRADE tx_hash: {len(unique_tx)}", flush=True)

    mismatches = []
    checked = 0
    rpc_failed = []

    for tx_hash in unique_tx:
        checked += 1
        if checked % 25 == 0:
            print(f"...checked {checked}/{len(unique_tx)}", flush=True)
        receipt = rpc_call(tx_hash)
        time.sleep(0.15)
        if receipt is None:
            rpc_failed.append(tx_hash)
            continue

        onchain_by_account = {}  # account -> set of orderHash
        for log in receipt.get("logs", []):
            if log["address"].lower() != CTF_EXCHANGE:
                continue
            if len(log["topics"]) < 4 or log["topics"][0] != ORDER_FILLED_SIG:
                continue
            order_hash, maker, taker = decode_order_filled(log)
            for addr, acc in OUR_WALLETS.items():
                if maker == addr.lower() or taker == addr.lower():
                    onchain_by_account.setdefault(acc, set()).add(order_hash)

        for acc, order_hashes in onchain_by_account.items():
            db_cnt = db_counts.get((tx_hash, acc), 0)
            onchain_cnt = len(order_hashes)
            if onchain_cnt > db_cnt:
                mismatches.append({
                    "tx_hash": tx_hash, "account": acc,
                    "onchain_count": onchain_cnt, "db_count": db_cnt,
                    "order_hashes": list(order_hashes),
                })

    print(f"\nchecked={checked} rpc_failed={len(rpc_failed)} mismatches={len(mismatches)}", flush=True)
    for m in mismatches:
        print(m, flush=True)
    if rpc_failed:
        print("RPC_FAILED tx_hashes:", rpc_failed, flush=True)

    with open("/root/polymarket-bot/scratchpad/act009_scope_report.md", "w") as f:
        f.write("# ACT-009: масштаб потери сделок (TRADE) в account_activity\n\n")
        f.write(f"Проверено уникальных tx_hash (TRADE): {checked}\n\n")
        f.write(f"RPC недоступен для {len(rpc_failed)} tx_hash: {rpc_failed}\n\n")
        f.write(f"Найдено расхождений (on-chain > DB): {len(mismatches)}\n\n")
        for m in mismatches:
            f.write(f"## {m['tx_hash']} / {m['account']}\n")
            f.write(f"- on-chain OrderFilled (уникальных orderHash): {m['onchain_count']}\n")
            f.write(f"- строк в БД: {m['db_count']}\n")
            f.write(f"- orderHash: {m['order_hashes']}\n\n")
    print("report written", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
