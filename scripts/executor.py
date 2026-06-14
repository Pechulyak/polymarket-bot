#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket V2 executor — deposit wallet / POLY_1271 (sig_type=3).

СТАТУС (2026-06-14):
  - dry build (сборка+подпись ордера) РАБОТАЕТ локально на Server 2.
  - live post_order ЗАБЛОКИРОВАН апстрим-багом py-clob-client-v2 #64/#70:
    L1-auth регистрирует api_key на EOA, а не на deposit wallet, из-за чего
    POST /order -> HTTP 400 "the order signer address has to be the address
    of the API KEY". Фикс (патч L1-auth под POLY_1271) — отдельная задача.

ИСПОЛНЕНИЕ: только Server 2 (Server 1 = Польша, геоблок Polymarket на запись).
            На Server 1 файл годится лишь как проверка импорта/чтения.

РЕЖИМЫ (флаги ниже):
  MODE = "diag"  -> только read-only: коннект, баланс, стакан, tick. Денег не трогает.
  MODE = "dry"   -> diag + локальная сборка+подпись ордера. Денег НЕ трогает.
  MODE = "live"  -> dry + РЕАЛЬНАЯ отправка post_order. ДЕНЬГИ ДВИГАЮТСЯ.
                    Требует ДВУХ подтверждений: MODE="live" И LIVE_CONFIRM=True.

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
# Все адреса публичные.
HOST       = "https://clob.polymarket.com"
CHAIN_ID   = POLYGON                                                  # 137
FUNDER     = "0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1"             # deposit wallet (деньги тут)
SIG_TYPE   = int(SignatureTypeV2.POLY_1271)                           # 3
KEY_PATH   = "/opt/executor/secrets/.signer_key"                     # приватный ключ EOA-signer (600, root)

# ─────────────────────────── ПАРАМЕТРЫ ОРДЕРА (для dry/live) ────────
ORDER = {
    "token_id": "94603648636330087039501304492699481091005420017442244191603206509188088089447",
    "price":    0.025,
    "size":     47.0,
    "side":     BUY,
    "order_type": OrderType.FOK,    # Fill-Or-Kill: либо исполнился целиком, либо отменён
}

# ─────────────────────────── РЕЖИМ ─────────────────────────────────
# По умолчанию — безопасный diag. Переопределяется флагом --mode.
MODE         = "diag"               # "diag" | "dry" | "live"
LIVE_CONFIRM = False                # второй замок для live; должен быть True ВРУЧНУЮ


def _load_signer_key() -> str:
    """Читает приватный ключ. НИКОГДА не печатает и не логирует его значение."""
    if not os.path.exists(KEY_PATH):
        sys.exit(f"FATAL: signer key not found at {KEY_PATH}")
    with open(KEY_PATH) as f:
        return f.read().strip()


def build_client() -> ClobClient:
    """Инициализирует V2-клиент под deposit wallet (sig3 + funder) и L2-creds."""
    _key = _load_signer_key()
    c = ClobClient(
        host=HOST,
        chain_id=CHAIN_ID,
        key=_key,
        signature_type=SIG_TYPE,
        funder=FUNDER,
    )
    del _key  # сбросить plaintext ключ из локали как можно раньше
    # derive_api_key() выводит существующий ключ без попытки create,
    # поэтому не шумит 400 "Could not create api key" (ключ уже существует на сервере).
    creds = c.derive_api_key()
    c.set_api_creds(creds)
    return c


def run_diag(c: ClobClient) -> None:
    """READ-ONLY. Денег не трогает."""
    print("─── DIAG (read-only) ───")
    print("signer EOA (public)   :", c.get_address())
    print("funder/deposit (public):", FUNDER)
    tick = c.get_tick_size(ORDER["token_id"])
    print("tick_size             :", tick)
    book = c.get_order_book(ORDER["token_id"])
    # get_order_book возвращает dict; asks/bids — списки {'price','size'} со строковыми ценами
    asks = book.get("asks") or []
    bids = book.get("bids") or []
    best_ask = min((float(a["price"]) for a in asks), default=None)
    best_bid = max((float(b["price"]) for b in bids), default=None)
    print("best ask              :", best_ask)
    print("best bid              :", best_bid)
    try:
        print("midpoint              :", c.get_midpoint(ORDER["token_id"]).get("mid"))
    except Exception as e:
        print("midpoint ERROR        :", repr(e)[:150])
    # привязка api_key (диагностика бага #64/#70)
    try:
        print("api_keys (server)     :", c.get_api_keys())
    except Exception as e:
        print("api_keys ERROR        :", repr(e)[:200])
    return tick


def build_signed_order(c: ClobClient, tick):
    """Локальная сборка + подпись. НЕ отправляет. Денег не трогает."""
    args = OrderArgsV2(
        token_id=ORDER["token_id"],
        price=ORDER["price"],
        size=ORDER["size"],
        side=ORDER["side"],
    )
    opts = PartialCreateOrderOptions(tick_size=tick)
    signed = c.create_order(args, opts)
    return signed


def run_dry(c: ClobClient, tick) -> None:
    print("─── DRY BUILD (no network send) ───")
    signed = build_signed_order(c, tick)
    sig = getattr(signed, "signature", None)
    print("order obj type        :", type(signed).__name__)
    print("signature present     :", bool(sig), "| hex len:", (len(sig) if sig else 0))
    print("DRY BUILD OK — ордер собран и подписан, деньги НЕ двигались.")
    return signed


def run_live(c: ClobClient, signed) -> None:
    """РЕАЛЬНАЯ отправка. ДЕНЬГИ ДВИГАЮТСЯ. Один выстрел."""
    if not (MODE == "live" and LIVE_CONFIRM):
        sys.exit("REFUSED: live требует MODE='live' И LIVE_CONFIRM=True. Выход без отправки.")
    print("─── LIVE post_order (ОДИН ВЫСТРЕЛ) ───")
    resp = c.post_order(signed, order_type=ORDER["order_type"])
    print("post_order response   :", resp)
    print("ПРОВЕРЬ ВРУЧНУЮ: ответ API == позиция в UI == баланс pUSD уменьшился.")


def main():
    global MODE, LIVE_CONFIRM
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["diag", "dry", "live"], default=MODE)
    ap.add_argument("--live-confirm", action="store_true",
                    help="второй замок для live; без него live откажет")
    a = ap.parse_args()
    MODE = a.mode
    LIVE_CONFIRM = a.live_confirm or LIVE_CONFIRM

    c = build_client()
    tick = run_diag(c)

    if MODE == "diag":
        return

    signed = run_dry(c, tick)

    if MODE == "live":
        run_live(c, signed)


if __name__ == "__main__":
    main()
