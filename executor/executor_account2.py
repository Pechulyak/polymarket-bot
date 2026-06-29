#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket V2 executor — Account2, Magic-wallet / POLY_PROXY (sig_type=1).

СТАТУС:
  - Аккаунт: Magic-wallet (НЕ TSS), создан email-входом на polymarket.com.
  - Баланс: $3.00 pUSD подтверждён on-chain (eth_call к pUSD-контракту
    0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB на funder 0x5F032...).
  - Путь sig1/POLY_PROXY рекомендован самим Polymarket (issue #70) как
    единственный рабочий программный путь для новых аккаунтов — обходит
    баг #64/#70, который блокирует sig3/POLY_1271.

ИСПОЛНЕНИЕ: только Server 2 (Server 1 = Польша, геоблок Polymarket на запись).

РЕЖИМЫ (флаг --mode):
  diag  -> read-only: коннект, signer, funder, стакан, tick, api_keys. Денег не трогает.
  dry   -> diag + локальная сборка+подпись ордера. Денег НЕ трогает.
  live  -> dry + РЕАЛЬНАЯ отправка post_order. ДЕНЬГИ ДВИГАЮТСЯ.
           Требует --mode live И --live-confirm.

ПРАВИЛО ОДНОГО ВЫСТРЕЛА: live запускается вручную, ОДИН раз. Упал — стоп,
сырой трейс оператору, без автоповтора.
"""

import os
import sys
import argparse

from py_clob_client_v2 import (
    ClobClient,
    OrderArgsV2,
    OrderType,
    SignatureTypeV2,
    PartialCreateOrderOptions,
)
from py_clob_client_v2.order_builder.constants import BUY, SELL
from py_clob_client_v2.constants import POLYGON

# ─────────────────────────── КОНФИГУРАЦИЯ ───────────────────────────
# Все адреса публичные. Приватный ключ — только из env-файла, в чат не попадает.
HOST       = "https://clob.polymarket.com"
CHAIN_ID   = POLYGON                                                  # 137
FUNDER     = "0x5F032FF0e9376538ac240417EA5863756e1f2634"             # Account2: collateral-адрес, $3 pUSD on-chain
SIG_TYPE   = int(SignatureTypeV2.POLY_1271)                           # 3 (DepositWallet)
ENV_PATH   = "/opt/executor/app/accounts/account2.env"               # PRIVATE_KEY=0x... (chmod 600, root)

# ─────────────────────────── ПАРАМЕТРЫ ОРДЕРА (для dry/live) ────────
# Рынок НЕ хардкодится — задаётся флагами при запуске:
#   --token-id <id> --price <0..1> --size <shares> --side buy|sell
# Заполняется в main() из argparse. order_type фиксирован FOK.
ORDER = {
    "token_id":   None,
    "price":      None,
    "size":       None,
    "side":       None,
    "order_type": OrderType.FOK,
}

# ─────────────────────────── РЕЖИМ ─────────────────────────────────
MODE         = "diag"
LIVE_CONFIRM = False


def _load_signer_key() -> str:
    """Читает PRIVATE_KEY из env-файла. НИКОГДА не печатает значение."""
    if not os.path.exists(ENV_PATH):
        sys.exit(f"FATAL: env file not found at {ENV_PATH}")
    key = None
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("PRIVATE_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        sys.exit(f"FATAL: PRIVATE_KEY not found in {ENV_PATH}")
    return key


def build_client() -> ClobClient:
    """V2-клиент под Magic-wallet (sig1 + funder) + L2-creds."""
    _key = _load_signer_key()
    c = ClobClient(
        host=HOST,
        chain_id=CHAIN_ID,
        key=_key,
        signature_type=SIG_TYPE,
        funder=FUNDER,
    )
    del _key
    # create_or_derive: вернёт существующий ключ либо создаст новый — не падает 400.
    creds = c.create_or_derive_api_key()
    c.set_api_creds(creds)
    return c


def run_diag(c: ClobClient):
    """READ-ONLY. Денег не трогает. Возвращает tick для последующих режимов."""
    print("─── DIAG (read-only) ───")
    print("signer EOA (public)    :", c.get_address())
    print("funder (public)        :", FUNDER)
    print("signature_type         :", SIG_TYPE)

    # привязка api_key (если signer != привязанный адрес — увидим здесь)
    try:
        print("api_keys (server)      :", c.get_api_keys())
    except Exception as e:
        print("api_keys ERROR         :", repr(e)[:200])

    if not ORDER["token_id"]:
        print("token_id               : не задан (--token-id) — стакан/tick пропущены, нужен для dry/live")
        return None

    tick = c.get_tick_size(ORDER["token_id"])
    print("tick_size              :", tick)
    book = c.get_order_book(ORDER["token_id"])
    asks = book.get("asks") or []
    bids = book.get("bids") or []
    best_ask = min((float(a["price"]) for a in asks), default=None)
    best_bid = max((float(b["price"]) for b in bids), default=None)
    print("best ask               :", best_ask)
    print("best bid               :", best_bid)
    try:
        print("midpoint               :", c.get_midpoint(ORDER["token_id"]).get("mid"))
    except Exception as e:
        print("midpoint ERROR         :", repr(e)[:150])
    return tick


def build_signed_order(c: ClobClient, tick):
    """Локальная сборка + подпись. НЕ отправляет."""
    args = OrderArgsV2(
        token_id=ORDER["token_id"],
        price=ORDER["price"],
        size=ORDER["size"],
        side=ORDER["side"],
    )
    opts = PartialCreateOrderOptions(tick_size=tick, neg_risk=True)
    signed = c.create_order(args, opts)
    return signed


def run_dry(c: ClobClient, tick):
    print("─── DRY BUILD (no network send) ───")
    missing = [k for k in ("token_id", "price", "size", "side") if ORDER[k] is None]
    if missing:
        sys.exit(f"REFUSED: не заданы параметры ордера: {missing}. Нужны --token-id --price --size --side.")
    if tick is None:
        sys.exit("REFUSED: tick не получен (см. diag). Без tick подпись невозможна.")
    signed = build_signed_order(c, tick)
    sig = getattr(signed, "signature", None)
    print("order obj type         :", type(signed).__name__)
    print("signature present      :", bool(sig), "| hex len:", (len(sig) if sig else 0))
    print("DRY BUILD OK — ордер собран и подписан, деньги НЕ двигались.")
    return signed


def run_live(c: ClobClient, signed):
    """РЕАЛЬНАЯ отправка. ДЕНЬГИ ДВИГАЮТСЯ. Один выстрел."""
    if not (MODE == "live" and LIVE_CONFIRM):
        sys.exit("REFUSED: live требует --mode live И --live-confirm. Выход без отправки.")
    print("─── LIVE post_order (ОДИН ВЫСТРЕЛ) ───")
    resp = c.post_order(signed, order_type=ORDER["order_type"])
    print("post_order response    :", resp)
    print("ПРОВЕРЬ ВРУЧНУЮ: ответ API == позиция в UI == баланс pUSD уменьшился.")


def main():
    global MODE, LIVE_CONFIRM
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["diag", "dry", "live"], default=MODE)
    ap.add_argument("--live-confirm", action="store_true",
                    help="второй замок для live; без него live откажет")
    ap.add_argument("--token-id", help="token_id рынка (для dry/live)")
    ap.add_argument("--price", type=float, help="цена 0..1 (для dry/live)")
    ap.add_argument("--size", type=float, help="кол-во shares (для dry/live)")
    ap.add_argument("--side", choices=["buy", "sell"], help="сторона (для dry/live)")
    a = ap.parse_args()
    MODE = a.mode
    LIVE_CONFIRM = a.live_confirm or LIVE_CONFIRM

    # заполнить ORDER из CLI (остаётся None если не передано — diag это допускает)
    if a.token_id is not None:
        ORDER["token_id"] = a.token_id
    if a.price is not None:
        ORDER["price"] = a.price
    if a.size is not None:
        ORDER["size"] = a.size
    if a.side is not None:
        ORDER["side"] = BUY if a.side == "buy" else SELL

    c = build_client()
    tick = run_diag(c)

    if MODE == "diag":
        return

    signed = run_dry(c, tick)

    if MODE == "live":
        run_live(c, signed)


if __name__ == "__main__":
    main()
