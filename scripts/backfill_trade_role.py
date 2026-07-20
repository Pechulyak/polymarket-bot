#!/usr/bin/env python3
"""
ACT-008: Determine maker/taker role per TRADE row in account_activity via
on-chain OrderFilled event matching (same methodology validated in ACT-009's
scripts/act009_onchain_audit.py). Read-only by default (--dry-run); writes
account_activity.trade_role when run without --dry-run.

Role determines fee: TRD-448 formula applies only to TAKER fills; MAKER
fills are $0 (matches TRD-448 changelog: fee only charged on the taker leg).

Matching: for each tx_hash, decode every OrderFilled log where maker or
taker is one of our proxy wallets into (account, role, given_amt, received_amt)
-  MAKER gives makerAmountFilled, receives takerAmountFilled
-  TAKER gives takerAmountFilled, receives makerAmountFilled
Then for each DB row of that (tx_hash, account), compute what WE actually
gave/received from side+size+usdc_size and match within a relative tolerance
(usdc_size sometimes already includes a fee premium over price*size, so an
exact match isn't always possible - see ACT-006 §5.4). Matched logs are
consumed so duplicate-amount fills (ACT-009 collisions) don't double-assign.
"""
import json
import sys
import time
import urllib.request

import psycopg2
import psycopg2.extras

RPC_URLS = [
    "https://polygon.drpc.org",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

# Two distinct exchange contracts emit OrderFilled: the standard CTFExchange
# for binary markets, and the NegRiskCTFExchange/Adapter for multi-outcome
# ("neg risk") markets - e.g. Nigel Farage vote-share brackets. Same event
# ABI, different contract address depending on the market. Discovered when
# ACT-008's role matching returned zero candidates for a neg_risk market.
EXCHANGE_ADDRESSES = {
    "0xe111180000d2663c0091e4f400237545b87b996b",  # CTFExchange
    "0xe2222d279d744050d28e00520010520000310f59",  # NegRiskCTFExchange
}
ORDER_FILLED_SIG = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
OUR_WALLETS = {
    "0x3fc83d2b40f9f243cbcd51a53cfdd7e9a6d366a1": "PechaArt",
    "0x5f032ff0e9376538ac240417ea5863756e1f2634": "Justfuuun",
}
REL_TOLERANCE = 0.05  # usdc_size can include an embedded fee premium (ACT-006 §5.4)


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


def decode_logs_for_account(receipt, account_wallet):
    """Return list of (role, given_amt, received_amt) for our wallet's fills."""
    out = []
    for log in receipt.get("logs", []):
        if log["address"].lower() not in EXCHANGE_ADDRESSES:
            continue
        topics = log["topics"]
        if len(topics) < 4 or topics[0] != ORDER_FILLED_SIG:
            continue
        maker = "0x" + topics[2][-40:]
        taker = "0x" + topics[3][-40:]
        data = log["data"][2:]
        maker_amt = int(data[128:192], 16) / 1e6
        taker_amt = int(data[192:256], 16) / 1e6
        if maker.lower() == account_wallet:
            out.append(("MAKER", maker_amt, taker_amt))
        elif taker.lower() == account_wallet:
            out.append(("TAKER", taker_amt, maker_amt))
    return out


def approx_match(a, b, tol=REL_TOLERANCE):
    if a == 0 and b == 0:
        return True
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def match_row_to_log(row, candidates):
    """row: dict with side, size, usdc_size. candidates: list of (role, given, received).
    Returns (index, role) of best match, or (None, None)."""
    if row["side"] == "BUY":
        actual_given, actual_received = float(row["usdc_size"]), float(row["size"])
    else:
        actual_given, actual_received = float(row["size"]), float(row["usdc_size"])

    for i, (role, given, received) in enumerate(candidates):
        if approx_match(given, actual_given) and approx_match(received, actual_received):
            return i, role
    return None, None


def main():
    dry_run = "--dry-run" in sys.argv
    conn = psycopg2.connect(host="localhost", port=5433, dbname="polymarket", user="postgres", password="postgres")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, tx_hash, account, side, size, usdc_size, fill_seq FROM account_activity "
        "WHERE event_type = 'TRADE' ORDER BY tx_hash, account"
    )
    rows = cur.fetchall()
    print(f"total TRADE rows: {len(rows)}", file=sys.stderr)

    by_tx = {}
    for r in rows:
        by_tx.setdefault(r["tx_hash"], []).append(r)

    wallet_by_account = {v: k for k, v in OUR_WALLETS.items()}

    matched = 0
    unmatched = 0
    rpc_failed = 0
    role_updates = []  # (id, role)
    unmatched_rows = []

    checked = 0
    for tx_hash, tx_rows in by_tx.items():
        checked += 1
        if checked % 25 == 0:
            print(f"...{checked}/{len(by_tx)} tx processed", file=sys.stderr)
        receipt = rpc_call(tx_hash)
        time.sleep(0.15)
        if receipt is None:
            rpc_failed += len(tx_rows)
            continue

        candidates_by_account = {}
        for row in tx_rows:
            acc = row["account"]
            if acc not in candidates_by_account:
                wallet = wallet_by_account[acc]
                candidates_by_account[acc] = decode_logs_for_account(receipt, wallet)

        for row in tx_rows:
            candidates = candidates_by_account[row["account"]]
            idx, role = match_row_to_log(row, candidates)
            if idx is not None:
                candidates.pop(idx)
                matched += 1
                role_updates.append((row["id"], role))
            else:
                unmatched += 1
                unmatched_rows.append(row["id"])

    print(f"checked_tx={checked} matched={matched} unmatched={unmatched} rpc_failed_rows={rpc_failed}", file=sys.stderr)
    role_counts = {}
    for _id, role in role_updates:
        role_counts[role] = role_counts.get(role, 0) + 1
    print(f"role breakdown: {role_counts}", file=sys.stderr)

    if dry_run:
        print(f"DRY_RUN: would update {len(role_updates)} rows, unmatched_ids={unmatched_rows[:20]}"
              f"{'...' if len(unmatched_rows) > 20 else ''}")
    else:
        with conn.cursor() as ucur:
            psycopg2.extras.execute_batch(
                ucur,
                "UPDATE account_activity SET trade_role = %s WHERE id = %s",
                [(role, row_id) for row_id, role in role_updates],
            )
        conn.commit()
        print(f"wrote trade_role for {len(role_updates)} rows", file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    main()
