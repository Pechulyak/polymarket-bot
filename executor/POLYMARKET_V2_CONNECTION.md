# Polymarket V2 — рабочая конфигурация подключения

# Аккаунт: PechaArt. Проверено on-chain 2026-06-13. Все адреса публичные

## СЕТЬ

chain_id: 137 (Polygon mainnet)
RPC (read-only, работает): <https://polygon.drpc.org>
  ВНИМАНИЕ: бесплатные polygon-rpc.com и rpc.ankr.com/polygon закрыли
  публичный доступ в 2026 (требуют API-ключ). drpc.org работает без ключа.

## АДРЕСА (три разные роли — не путать)

Deposit Wallet (funder, maker, signer ордера; ДЕНЬГИ ЗДЕСЬ):
  0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1

- на PolygonScan помечен "Polymarket: Deposit Wallet", ERC-1967 proxy
EOA-владелец (приватный ключ от него; подписывает):
  0x435FC6316B6AA047C2c39aBF4Ef936e55581fb8E
- зашит в bytecode proxy-контракта Deposit Wallet
API-адрес (ТОЛЬКО для API; денег нет; НЕ funder):
  0xF94809b91d7257c76d32E5F1F3dfa34748100F68

## КОНТРАКТЫ V2 (Polygon mainnet)

pUSD (collateral, ERC-20, 6 decimals, 1:1 к USDC):
  0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
CollateralOnramp (USDC.e -> pUSD):
  0x93070a847efEf7F70739046A929D47a521F5B8ee
USDC.e (старый, для справки):
  0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174

## ПОДПИСЬ

signature_type = 3 (POLY_1271)
maker И signer ордера = адрес Deposit Wallet (0x3fC83D2b...)

## КЛИЕНТСКАЯ БИБЛИОТЕКА

py-clob-client-v2 == 1.0.1  (установлен на СЕРВЕРЕ 2: /opt/executor/app/venv)
ВНИМАНИЕ: старый py-clob-client 0.17.5 (V1) НЕ работает с V2-контрактами.

Инициализация (рабочая, проверена 2026-06-13):
  from py_clob_client.client import ClobClient
  c = ClobClient(
      "<https://clob.polymarket.com>",
      chain_id=137,
      key=<приватный ключ из файла>,
      signature_type=3,
      funder="0x3fC83D2b40F9f243Cbcd51a53cFdd7E9A6D366a1",
  )
  c.set_api_creds(c.create_or_derive_api_creds())

## ЧТЕНИЕ БАЛАНСА pUSD (read-only, ключ НЕ нужен)

eth_call -> pUSD.balanceOf(Deposit Wallet) -> результат / 10^6
selector balanceOf = 0x70a08231
Проверено 2026-06-13: 9.834473 pUSD.

## СЕКРЕТЫ (лежат на СЕРВЕРЕ 2, не на Сервере 1)

Приватный ключ signer: СЕРВЕР 2, /opt/executor/secrets/.signer_key

- права 600, владелец root
- сверен: выводит адрес 0x435FC6316B6AA047C2c39aBF4Ef936e55581fb8E
- в этот документ НЕ включён (и не должен включаться)

## СТАТУС (на 2026-06-21) — ПРОГРАММНЫЙ LIVE РАБОТАЕТ

РАБОТАЕТ ПОЛНОСТЬЮ: чтение баланса, инициализация клиента, derive API-ключа,
          чтение стакана, СБОРКА+ПОДПИСЬ ордера, РАЗМЕЩЕНИЕ live-ордера.
Подтверждено on-chain 2026-06-21: ордер $1 FOK -> status=matched,
          orderID 0x129fbc783a096a3e83fb6057e8d5256990b9d3c13cde5c8de3298ac145215433,
          tx 0xbc79caf24d5c5586f3940df8f6e7dc84d8d85fa5b256aba1de7f1d2c2c4790df.
          UI: "Will USA win 2026 FIFA World Cup? Yes 4.1c, 25 долей, -$1.03".

ОПРОВЕРЖЕНИЕ прежнего вердикта "Path A закрыт апстрим-багом L1-auth":
  Апстрим-бага НЕТ. Существующий ключ a5a51770 через derive_api_key()
  проходит авторизацию ордера под sig3 БЕЗ ERC-7739 обёртки.
  Реальный прежний блокер — НЕ auth, а формат/цена ордера:
    - maker_amount (price*size) должен укладываться в 2 знака
      (ROUNDING_CONFIG tick 0.001: price=3, size=2, amount=5);
    - price ДОЛЖНА быть ВЫШЕ best_ask (пересечь спред), иначе FOK kill.
  Пример рабочего $1: --price 0.05 --size 20 -> maker = 1.00 ровно.
  Файлы l1_7739_auth.py / step3_enumerate.py — ТУПИКОВЫЕ, не нужны (в архив).
  
ИСПОЛНИТЕЛЬ: executor.py теперь принимает рынок через CLI
  (--token-id --price --size --side [--neg-risk]), рынок НЕ хардкодится.
  api_key a5a51770... привязан к API-адресу 0xF94809b9...; derive его выводит,
  для торговли этого достаточно (create нового не требуется).

# ============================================================================

# ACCOUNT 2 (Justfuuun) — программный live ДОСТИГНУТ. Проверено on-chain 2026-06-21

# Все адреса публичные. Блок Account1 (PechaArt) выше не изменялся

# ============================================================================

## ИТОГ (одной строкой)

Plan B УСПЕШЕН. Программный live-ордер прошёл под sig3 (POLY_1271) +
funder=DepositWallet + neg_risk=True. L1-auth баг #70 (закрывший Path A на
PechaArt) на Account2 НЕ воспроизвёлся — сервер принял ордер с
order-signer = funder != owner-api-key и исполнил.

## АДРЕСА ACCOUNT 2 (три роли — не путать)

DepositWallet (funder, maker, signer ордера; ДЕНЬГИ ЗДЕСЬ):
  0x5F032FF0e9376538ac240417EA5863756e1f2634

- EIP-1167 minimal proxy, eip712Domain name="DepositWallet" (sig3-эталон,
    байты совпадают с PechaArt DepositWallet)
- UI помечает "только для API" — это ВВОДИТ В ЗАБЛУЖДЕНИЕ, funder именно здесь
EOA-владелец (приватный ключ; ECDSA-подпись; embedded owner в proxy-bytecode):
  0xdDb1Ac6215857437dD6d5b629f4dF6b4c572E368
Deposit-вход (внешние USDC сюда, не задерживаются; НЕ торговый):
  0x302F067006A958604365c94d73d7632081294a10
API key (UUID, не секрет): 73bc2eb4-eaff-6577-1e7f-b1dfcd2ed311
Профиль Polymarket: Justfuuun

## ТИП КОШЕЛЬКА — установлено on-chain

DepositWallet (sig3 / POLY_1271), НЕ Magic-proxy sig1.
ВАЖНО: предпосылка Plan B "новый email-аккаунт = sig1" ОПРОВЕРГНУТА.
Email-аккаунты после миграции 2026-04-28 получают DepositWallet (sig3).

## ПОДПИСЬ ACCOUNT 2

signature_type = 3 (POLY_1271)
maker И signer ордера = адрес DepositWallet (0x5F032...) = funder

- в py-clob-client-v2: _v2_order_signer() при POLY_1271 возвращает funder,
    поэтому signer-поле ордера = funder (совпало со структурой рабочего
    ручного трейда, декодированного on-chain)
neg_risk = True (рынок Japan WC — neg-risk; обязателен в опциях ордера)

## ЧТЕНИЕ БАЛАНСА pUSD (read-only)

eth_call -> pUSD.balanceOf(0x5F032...) / 10^6
ВНИМАНИЕ: SDK get_balance_allowance() врёт (возвращает 0) — доверять
ТОЛЬКО on-chain eth_call, как и для Account1.

## РАБОЧАЯ КОМАНДА LIVE-ОРДЕРА (подтверждена, $1 buy)

Файл: /opt/executor/app/executor_account2.py (Server 2)
  python3 executor_account2.py --mode live --live-confirm \
    --token-id <id> --price <выше best_ask> --size <shares> --side buy
Зашито в файле: SIG_TYPE=POLY_1271, neg_risk=True, order_type=FOK.

КРИТИЧНО для FOK fill:

- price ДОЛЖНА быть ВЫШЕ best_ask (пересечь спред), иначе FOK kill
    ("order couldn't be fully filled"). Лимит РОВНО по ask — пограничный, киляется.
- size = shares (доли токена) для limit-ордера (OrderArgsV2 + create_order)
- формат amounts (ROUNDING_CONFIG для tick 0.001: price=3, size=2, amount=5):
    maker_amount должен укладываться в 2 знака. Пример $1: size=40 @ price=0.025
    -> maker = 40 * 0.025 = 1.00 ровно.

## ПОДТВЕРЖДЁННЫЙ ТРЕЙД (трёхсторонняя сверка)

Рынок: "Will Japan win the 2026 FIFA World Cup?" Yes
token_id: 19159976531313550247579355752030367100657092033093647047491459813592996250034
Параметры: size=40, price=0.025, side=buy, FOK, neg_risk=True
API-ответ: status='matched', success=True,
  takingAmount=41.666665, makingAmount=0.999999,
  orderID=0xde5acb70ca46f60eaf9c846069c6f8f65c5f9fc3b9187a8955c6233ac959ae2a
  tx=0x8e74440a7abbc3ff4ccad4eb082dc4b6a18bd645d0c6e1c59af99000b0972a07
UI: позиция "Yes 2.5¢, 41.7 доли", стоимость -$1.03
Баланс: портфель $2.94, доступно $0.97 (двинулся)

## FEE / SLIPPAGE — живое измерение (для fee-модели проекта)

makingAmount API = $0.999999, но UI-стоимость входа = -$1.03.
Дельта ~$0.03 на $1-ордере (~3%): часть — спред/проскальзывание (вход 2.5¢
при ask 2.4¢), часть — fee. ПОДТВЕРЖДАЕТ: реальная стоимость входа != makingAmount.
На микро-ордерах эта дельта съедает edge. Учесть в PnL-модели и Kelly.

## КОНТРАКТЫ — общие с Account1 (см. блок выше): pUSD, CTF/neg_risk Exchange

CTF/neg_risk Exchange: 0xe2222d279d744050d28e00520010520000310F59

## СЕКРЕТЫ ACCOUNT 2 (на Server 2, не в документ)

PRIVATE_KEY / API_SECRET / API_PASSPHRASE:
  /opt/executor/app/accounts/account2.env (chmod 600, root)
