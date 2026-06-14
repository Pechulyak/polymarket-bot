# Polymarket V2 — рабочая конфигурация подключения
# Аккаунт: PechaArt. Проверено on-chain 2026-06-13. Все адреса публичные.

## СЕТЬ
chain_id: 137 (Polygon mainnet)
RPC (read-only, работает): https://polygon.drpc.org
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
      "https://clob.polymarket.com",
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

## СТАТУС (на 2026-06-13)
РАБОТАЕТ: чтение баланса, инициализация клиента, генерация API-ключей,
          чтение стакана.
НЕ РАБОТАЕТ: размещение ордера падает локально на create_order с
          py_order_utils ValidationException "Invalid order inputs"
          (ДО отправки на сервер, деньги не двигаются). Причина — формат
          price/size не соответствует tick_size / round_config / min size
          рынка V2. Открытая задача: подобрать корректный формат ордера.
          Детали в CONTEXT_TRANSFER_fix_order_inputs.md.