#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket V2 executor — Account1 (PechaArt), DepositWallet / POLY_1271 (sig_type=3).

СТАТУС (2026-06-21): ПРОГРАММНЫЙ LIVE РАБОТАЕТ.
  Подтверждено on-chain: ордер $1 FOK прошёл status=matched
  (orderID 0x129fbc78..., tx 0xbc79caf2...), UI/баланс сверены.

  ВАЖНО — опровержение прежнего вердикта "Path A закрыт апстримом":
    Никакого апстрим-бага L1-auth НЕТ. Тот же ключ a5a51770 через
    derive_api_key() проходит авторизацию ордера под sig3 БЕЗ всякой
    ERC-7739 обёртки. Прежний блокер был НЕ auth, а формат/цена ордера:
      - maker_amount (price*size) должен укладываться в 2 знака;
      - price ДОЛЖНА быть ВЫШЕ best_ask (пересечь спред), иначе FOK kill.
    Файлы l1_7739_auth.py / step3_enumerate.py — тупиковые, не нужны.

ИСПОЛНЕНИЕ: только Server 2 (Server 1 = Польша, геоблок Polymarket на запись).
            На Server 1 файл годится лишь как версионирование/проверка импорта.

РЕЖИМЫ (флаг --mode):
  diag  -> read-only: коннект, signer, funder, стакан, tick, api_keys. Денег не трогает.
  dry   -> diag + локальная сборка+подпись ордера. Денег НЕ трогает.
  live  -> dry + РЕАЛЬНАЯ отправка post_order. ДЕНЬГИ ДВИГАЮТСЯ.
           Требует --mode live И --live-confirm.

ПАРАМЕТРЫ РЫНКА — через CLI (рынок НЕ хардкодится):
  --token-id <id> --price <0..1> --size <shares> --side buy|sell [--neg-risk]

ПРАВИЛО ОДНОГО ВЫСТРЕЛА: live запускается вручную, ОДИН раз. Упал — стоп,
сырой трейс оператору, без автоповтора.

ФОРМАТ ОРДЕРА (чтобы пройти валидацию сервера):
  ROUNDING_CONFIG tick 0.001 = price=3, size=2, amount=5.
  maker_amount = price*size должен укладываться в 2 знака.
  Пример $1: --price 0.05 --size 20  -> maker = 1.00 ровно, price выше ask -> кросс.
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

# ─────────────────────────── КОНФИГУРАЦИЯ (Account1 / PechaArt) ─────
# Все адреса публичные.
HOST       = "https://clob.polymarket.com"
CHAIN_ID   = POLYGON                                                  # 137
FUNDER     = "0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1"             # deposit wallet (деньги тут, ~9.83 pUSD)
SIG_TYPE   = int(SignatureTypeV2.POLY_1271)                           # 3 (DepositWallet)
KEY_PATH   = "/opt/executor/secrets/.signer_key"                     # приватный ключ EOA-signer (600, root)

# ─────────────────────────── ПАРАМЕТРЫ ОРДЕРА (для dry/live) ────────
# Заполняется в main() из argparse. order_type фиксирован FOK.
ORDER = {
    "token_id":   None,
    "price":      None,
    "size":       None,
    "side":       None,
    "neg_risk":   False,
    "order_type": OrderType.FOK,
}

# ─────────────────────────── РЕЖИМ ─────────────────────────────────
MODE         = "diag"
LIVE_CONFIRM = False


def _load_signer_key() -> str:
    """Читает приватный ключ. НИКОГДА не печатает и не логирует его значение."""
    if not os.path.exists(KEY_PATH):
        sys.exit(f"FATAL: signer key not found at {KEY_PATH}")
    with open(KEY_PATH) as f:
        return f.read().strip()


def build_client() -> ClobClient:
    """V2-клиент под deposit wallet (sig3 + funder) + L2-creds."""
    _key = _load_signer_key()
    c = ClobClient(
        host=HOST,
        chain_id=CHAIN_ID,
        key=_key,
        signature_type=SIG_TYPE,
        funder=FUNDER,
    )
    del _key  # сбросить plaintext ключ из локали как можно раньше
    # derive_api_key() выводит существующий ключ (a5a51770...) без попытки create.
    # Подтверждено: этого достаточно для авторизации ордера под sig3.
    creds = c.derive_api_key()
    c.set_api_creds(creds)
    return c


def run_diag(c: ClobClient):
    """READ-ONLY. Денег не трогает. Возвращает tick для последующих режимов."""
    print("─── DIAG (read-only) ───")
    print("signer EOA (public)    :", c.get_address())
    print("funder (public)        :", FUNDER)
    print("signature_type         :", SIG_TYPE)
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
    opts = PartialCreateOrderOptions(tick_size=tick, neg_risk=ORDER["neg_risk"])
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
    print("neg_risk               :", ORDER["neg_risk"])
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
    ap.add_argument("--neg-risk", action="store_true",
                    help="рынок neg-risk (свойство РЫНКА, не аккаунта); по умолчанию False")
    a = ap.parse_args()
    MODE = a.mode
    LIVE_CONFIRM = a.live_confirm or LIVE_CONFIRM

    if a.token_id is not None:
        ORDER["token_id"] = a.token_id
    if a.price is not None:
        ORDER["price"] = a.price
    if a.size is not None:
        ORDER["size"] = a.size
    if a.side is not None:
        ORDER["side"] = BUY if a.side == "buy" else SELL
    ORDER["neg_risk"] = a.neg_risk

    c = build_client()
    tick = run_diag(c)

    if MODE == "diag":
        return

    signed = run_dry(c, tick)

    if MODE == "live":
        run_live(c, signed)


if __name__ == "__main__":
    main()
