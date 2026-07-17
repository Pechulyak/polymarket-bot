# CHANGELOG
## 2026-07-17

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-17 | ACT-003 | Cron для ежедневного fetch account_activity + account_positions_snapshot: обёртка scripts/run_account_activity_fetch.sh (env-pattern из .env, последовательный запуск обоих fetch-скриптов), крон-строка 10 4 * * * с flock -n (паттерн проекта, см. category_backfill/copy_live_sweep). Установлено в crontab. Верификация первого прогона — 2026-07-18. Попутно: политика доступа к crontab (deny→allow read-only + запись в repo-файлы) и протокол оркестрации Claude Code (CLAUDE.md, .claude/settings.json, субагенты reviewer/debugger, mm.sh executor). |
| 2026-07-17 | SEC-504 (partial) | Ротация logs/mm_executor.log: size 50M/rotate 5/copytruncate в /etc/logrotate.d/polymarket (confirmed), вынесен из-под общего glob `*.log` через bracket-исключение — попутно найден и исправлен идентичный pre-existing дубль-баг для retention_cron.log (оба файла матчились и общим, и своим блоком → logrotate падал с "duplicate log entry", exit 1, каждый прогон). Бэкап: backups/logrotate_polymarket_bak_20260717_2038.txt. Фильтр scripts/mm_log_filter.py перед tee в scripts/mm.sh: оставляет только assistant/user/result, режет thinking, обрезает tool_result >2000 символов ([truncated]). cleanupPeriodDays=7 в .claude/settings.json. Journalctl/docker часть SEC-504 не затронута. |

## 2026-07-15

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-15 | FARM-038 | Фикс share-модели: comp_pts = min(bid,ask) + abs(bid−ask)/3 (Polymarket Qmin) в calc_farm_economics + farm_screen. Заменяет min-модель (завышение 2-5x) и сумму сторон (занижение 2-2.5x). Вычет собственных ордеров (--our-bid/--our-ask). pts_k = comp_pts/1000. Калибровка факт/прогноз ~0.3-0.4. Паритет верифицирован (Alito, share=0.0304). |

## 2026-07-14

| Дата | TASK_ID | Описание |
|------|---------|---------|
| 2026-07-14 | ACT-002 | Таблицы account_activity + account_positions_snapshot (DDL: partial-unique индексы по trade-key и redeem-key). Fetch-скрипты: fetch_account_activity.py, fetch_account_positions_snapshot.py. Бэкфилл: PechaArt 88 + Justfuuun 220 = 308 строк. Known limitation: несколько on-chain fill'ов идентичного (size, price, side) в одном tx схлопываются в одну строку по trade-ключу. Счётчик collapsed (fetched − inserted) логируется каждым прогоном в stderr — считает и истинные API-дубли, и мультифилл-коллизии (неразличимы без on-chain log_index). Наблюдаемо ~0.5% farming-записей (1/221), 0% copy. Приемлемо для наблюдательного лога; при росте частоты пересмотреть → A-lite (log_index в ключ). MAKER_REBATE — обнаружен как незадокументированный тип (reward-класс). Reward-агрегат = REWARD + MAKER_REBATE. |
| 2026-07-11

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-11 | PIPE-049 | Fetch кандидатов из 9 категорий leaderboard (POLITICS, ESPORTS, CRYPTO, CULTURE, MENTIONS, WEATHER, ECONOMICS, TECH, FINANCE; TOP_N_PER_CATEGORY=5). Migration pipe_049: добавлены колонки best_category VARCHAR(32) и categories TEXT в leaderboard_candidates. Fetch: 43 кандидата с best_category IS NOT NULL. Воронка: 8 is_lp=TRUE, 41 is_hft_burst=TRUE, 7 оба, 1 прошёл оба фильтра (252, POLITICS; is_lp=NULL = проверен, не LP). Кросс-категория: donthackme и balthazar (TECH+FINANCE). |
| 2026-07-11 | PIPE-050 | NULL-guard в score_leaderboard_candidates.py: close_price IS NULL или open_price IS NULL → treat as OPEN (pnl_status="OPEN", gross_pnl/net_pnl=NULL). Root cause: SELL-группы с size_usd=0 → NULLIF(0,0)=NULL в weighted average. 11 групп обработано как OPEN. |
| 2026-07-12 | HYG | PART D выделен в live_004d, retention перенесён в migrations/, черновик live004 удалён; push-канал live_copy существует в БД, текущий live-executor работает pull-моделью. |

## 2026-07-11

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-11 | FARM-033-fix | condition_id lookup для рынков вне status='active' (DB_QUERY_BY_TOKEN, rotated-out рынки сохраняют реальные cid/gamma_id/name). Верификация: 09.07 Σ=3.107 сходится с API, 10.07 Σ=3.577. Cron на S2 12:35 UTC. |
| 2026-07-11 | FARM-035 | BACKLOG: HOLD-путь не восстанавливает недостающую ногу (ASK skipped по locked_sell при requote, Phillies 9ч на ⅓ score). |
| 2026-07-11 | FARM-036 | BACKLOG: алерт-латч 🟢/🟡 сбрасывается на API-ошибке get_open_orders → ложные «Обе стороны». |
| 2026-07-11 | FARM-037 | Деплой US Soft Landing + Raquel Lyra, нога 100, параметры 100/100/50/300, осознанный override thin-вето по soft landing (ask $255<$300), капитал +$192. Демон: 2262a0f с S2. |

## 2026-07-10

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-10 | FARM-033 | Дневной снапшот фарминга: таблица farming_daily_snapshot (migration_farm033.sql, PK: snap_date+token) + скрипт farming/tools/farming_snapshot.py. Источники: reward_usd из c.get_earnings_for_user_for_day(date) (dict по condition_id, один вызов за прогон); inv из on-chain ERC-1155 balanceOf(FUNDER, token); mid из CLOB /midpoint; capital_usd = inv×mid + bid_notional; fees_usd из c.get_trades(TradeParams) — только taker (trader_side/taker_address vs FUNDER), формула TRD-448 при отсутствии fee в ответе; legs_state/hours_both реконструкция из fills+open orders+halted. markets с earnings но не в active — token=condition_id, legs_state=none, log=not_in_active_markets. UPSERT idempotent. |

## 2026-07-09

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-09 | FARM-025 | level-gate после адверс-филла: (1) запись last_adverse_fill в fill-ветке: side + price + ts первого нашего maker-филла; (2) level-gate при resume: mid должен вернуться в ±1 tick от уровня фила — иначе halted=True; (3) halted state: early-gate в цикле (мониторинг только, no place/requote/unload), независим от pause_until; (4) edge_notify на HALT/снятие; (5) персистентность halted + last_adverse_fill в farming_state.json (save + load). Manual reset: /stop → убрать halted из farming_state.json → /start. Первый боевой тест 09.07: Arena adverse → level-gate → halted, персистентность подтверждена рестартом. Урок: min_size играет двойную роль — биржевой минимум и размер ноги; plan строит bid/ask_size=min_size (~строки 1022-1023); center≠нога вызывает авторазгрузку ручных докупок; зазор max_inv ≥ нога+хвост. |
| 2026-07-09 | FARM-026 | Ротация портфолио фарминга (NL→Phillies+Requião) + F3-допуск дробного хвоста. |
| 2026-07-09 | FARM-027 | calc_farm_economics.py: добавлены колонки %ср (marginal/капитал шага к средней $/д на $100) и marg/$100; порог метки деградации 50%→70%; backup .bak-farm027. Тест на Phillies: метка на size=150 (%ср=63). |

## 2026-07-08

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-08 | FARM-015 | markets.json schema + export script (FARM-015 subset). Schema: version=1, markets[] с полями name, token, min_size, inv_center, inv_deadband, max_inv, weight, gamma_id, condition_id. Миграция farm024: ALTER TABLE farming_active_markets ADD min_size/inv_center/inv_deadband/max_inv/weight DEFAULT (200/200/200-100/400/1). scripts/export_farming_markets.py: docker exec psql → JSON, валидация (непустой, уникальный token, numeric>0, inv_center≤max_inv), exit 1 на ошибку. Pre-gate часть готова (schema + migration + export). Post-gate: загрузка markets.json в демон, cash-аллокатор, параллельный поллинг. |
| 2026-07-08 | FARM-025 | level-gate после адверс-филла: (1) запись last_adverse_fill в fill-ветке: side + price + ts первого нашего maker-филла; (2) level-gate при resume: mid должен вернуться в ±1 tick от уровня фила — иначе halted=True; (3) halted state: early-gate в цикле (мониторинг только, no place/requote/unload), независим от pause_until; (4) edge_notify на HALT/снятие; (5) персистентность halted + last_adverse_fill в farming_state.json (save + load). Manual reset: /stop → убрать halted из farming_state.json → /start. S2 (авто-resume после level recovery) — отдельный операторский шаг. |

## 2026-07-05

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-05 | FARM-010 | Скринер v4 (S1, LIVE-006 N/A). Phase A: CLOB /sampling-markets→Gamma /markets (liquidity-диапазоны + order=liquidityNum; «нечинимость пагинации» опровергнута). Метрика: our_daily=our_share×pool вместо средней $/kpts. offset B' внутри reward-зоны, отсечка mv2c>8/pts_k<0.5, гейт пустой книги, POOL_MIN 30→5. Вывод: farm при $231 маргинален (центы-$3.5/д), подтверждено внешними кейсами. Хвост: пагинация 20-50k неполна (FARM-018). |
| 2026-07-05 | LIVE-007 | Root cause: live-кит (0x033f0346, TheVeryGoodCow) не собирался в whale_trades — _fetch_paper_whale_trades WHERE copy_status='paper' не включал 'live', при этом триггер copy_whale_trade_to_paper (IN paper,live) и copy_paper_to_live (='live') для live готовы. Разрыв только в fetch. Fix: whale_detector.py:1682 → IN ('paper','live'). Live-киты теперь на paper-цикле 30s, whale_trades→trigger→paper_trades→notify→live_orders цепь замкнута. Долг: last_targeted_fetch_at застрял 2026-04-04 (отдельный тикет). |

## 2026-07-07

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-07 | FARM-019 | Telegram control bot (farming_control_bot.py): long-polling getUpdates, whitelist по chat_id, команды /status (per-market с last log line + UTC+3), /stop + /confirm_stop, /start + /confirm_start, /cancel. html.escape на всех динамических значениях, fallback в plain text при 400. systemd unit farming-control-bot.service (Restart=on-failure, RestartSec=15, TimeoutStopSec=120), logrotate 10M/keep7. Деплой подтверждён. |
| 2026-07-07 | FARM-020 | Graceful shutdown: SIGTERM handler → _graceful_shutdown() → cancel all orders → save state → exit 0. TimeoutStopSec=120 в farming-daemon.service. |
| 2026-07-07 | FARM-020-fix2 | one_sided latch bug fix: источник истины — place_two_sided return (bid_id, ask_id), one_sided=XOR. Requote tick → place_one_sided. Non-requote tick → rec["one_sided"] только если reconcile ran full path (ids_before_reseed is not None). Early-return skip latch. Верификация: рестарт при latch=True → нет ложного 🟢. |
| 2026-07-07 | — | Repo hygiene: удалён легаси-дубль farming/farming_daemon.py; канонический путь executor/farming_daemon.py. В BACKLOG: INFRA-050 — farming-daemon.service отсутствует в репо (добавить в deploy/). |
| 2026-07-07 | FARM-022 | (K1) farm_screen.py v4.9→DB: farming_market_candidates INSERT, 30d retention, cron 2×/день. Миграция: our_daily_usd, fees_enabled, neg_risk, tick, moves2c, dead_book. (K2) degradation-watch: check_farm_degradation() в pipeline_monitor, edge-triggered (system_state), мониторит pool/max_spread/feesEnabled/end_date против baselines из farming_active_markets. (K3) TG-дайджест: send_farm_screen_digest.py — топ-5 по our_daily_usd + дельты vs предыдущий прогон, 💰/NR флаги, HTML parse_mode. Cron after farm_screen. scan_farming_candidates.py удалён (заменён farm_screen.py v4.9). |
| 2026-07-07 | FARM-023 | book_depth per-side + thin_book фильтр: bid_depth_usd = Σ(price×size) по bids в окне max_spread от mid; ask_depth_usd = Σ((1-price)×size) по asks. thin_book = min(bid_depth_usd, ask_depth_usd) < THIN_BOOK_MULT×OUR_SIZE. liquidity_clob = reward pool sum (sum clobRewards[].rewardsDailyRate) — НЕ глубина книги, комментарий добавлен. Скринер: farm_screen.py считает dollar depth по /book. Дайджест: WHERE thin_book=FALSE (IS NOT TRUE для старых прогонов с NULL). Footer: "отфильтровано thin_book: N". Миграция: ALTER TABLE farming_market_candidates ADD bid_depth_usd NUMERIC, ask_depth_usd NUMERIC, thin_book BOOLEAN DEFAULT FALSE. |

## 2026-07-04

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-04 | FARM-014/017 | ROUND_HALF_UP в _round (оба пути). FARM-017: deadband=размер ноги (200/50), max_inv=center+2×нога (600/150) безусловным капом в place_two_sided (поглощает FARM-004j), long_unload переведён с bid_size=0 на BID-widening ×2 (лечит one-sided 57% аптайма 03.07). Мультирыночный конфиг: US×Iran (200/нога) + Bardella FR-2027 (50/нога, neg_risk). 6ч соак DRY_RUN обеих версий пройден: ноль крашей, паузы только US×Iran на реальных движениях, Bardella тихий, изоляция пауз подтверждена. Деплой 19:43, коммит после соака. |
| 2026-07-04 | FARM-011/012/016 | FARM-011 circuit breaker: размах mid ≥2¢ за 10 мин → cancel all + пауза 15 мин, recovery-гейт размах ≤1¢/10мин при ≥300с истории. FARM-012: fill или missing-leg → enter_pause 120с, кулдауны merge через max, pause_until персистится в farming_state.json. FARM-016: save_state_file больше не теряет курсоры токенов вне текущего MARKETS (регрессия n=93). DRY-тест: fill-пауза, recovery, RESUME, ноль ложных срабатываний. Соак 6ч: 15 циклов PAUSE/RESUME, CB держал демона вне книги ~70% новостного дня — подтверждение нефармабельности US×Iran-класса. |
| 2026-07-04 | FARM-010 | ОТМЕНЁН. Gamma-пагинационный баг (offset cap ~2100 маскируется под пустой батч) нечиним на стороне клиента. Замена: CLOB /sampling-markets одним эндпоинтом + ручной скрининг с S1 (снапшот /tmp/sampling_markets.json, протухает за часы). Вывод разведки: тонкие+новостные рынки нефармабельны структурно (adverse selection первого филла); рабочий сегмент — зрелые стабильные (выборы 2027-28), yield 0.04-0.26%/д. Таблица farming_market_candidates не дропнута (retention 30д вычистит). |
| 2026-07-04 | FARM-013 | ЗАМОРОЖЕН по данным катастрофы 03.07: факт −$105/д, с FARM-011/012 −$46, +WSS −$41 (добавляет $4.86/д). Хвосты каскадов — burst-филлы внутри секунды, WSS их не ловит. |

## 2026-07-03

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-03 | FARM-006 | TG-алерты только onset+recovery (re-nudge удалён). Reseed st[ids] при рестарте — усыновление одной лучшей ноги на сторону (drift ≤ REQUOTE_FRAC×QUOTE_OFFSET), прочие cancel; epoch score переживает рестарт. Ревью-фиксы — unload_id трекается в reconcile (не отменяется как orphan, recovery latch при пропаже из книги, независимая ветка force_requote для прочих ног), st[center] после adoption, DRY_RUN-гейт авторазгрузки. Деплой подтверждён. |
| 2026-07-03 | FARM-005 | Dynamic BID cap по free cash (read_cash_balance on-chain pUSD), парсер #4 balance-reject. Фикс inv-overshoot при partial fill (инцидент inv=236 02.07): Fix1 — partial BUY не отменяется при drift ≤ REQUOTE_FRAC×QUOTE_OFFSET; Fix2 — overshoot-гейт inv+bid_sz > center+dead, только в skew=reseed_buy; Fix3 — авторазгрузка излишка >20 шер maker SELL, Decimal-safe тик-округление. Деплой подтверждён, two-sided восстановлен. |
| 2026-07-03 | FARM-007 | Unified inv-cap MAX_INV=450 в place_two_sided: единый гейт inv=None или inv+bid_size>MAX_INV → skip BID (fail-closed). Fix 1/Fix 2 удалены (поглощены MAX_INV). Код-комментарии сохраняют исторические ID (004c/d, 004e/f/g, 004h). Деплой подтверждён. |
| 2026-07-03 | DOC-609 | EPIC FARM: ренумерация TASK_ID. Mapping: 004c/d→005, 004e/f/g→006, 004h→007, старые 005/006→008/009. TASK_BOARD: новый ## EPIC: FARM, перенесены FARM-строки из EPIC: LIVE. Код-комментарии ([FARM-004*]) НЕ трогались — история ревизий кода, переименование создало бы рассинхрон с .bak-файлами. |

## 2026-07

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-07-02 | FARM-004 | Telegram alert-система: 6 алертов в TG (#1 one-sided, #2 scoring lost, #3 drift, #4 balance-reject, #5 startup, #6 two-sided restored), остальное → journalctl. Русификация всех текстов. Edge-latch персистится в farming_state.json ("_alerts" key): onset/recovery сохраняются между рестами, осцилляция на рестарте подавлена гейтом st["ids"] is not None. #4 balance-reject: парсинг реальных полей API-ошибки (balance/sum of active orders/order amount → free/need/active), onset при первой ошибке, recovery при следующем успешном BID. LIVE-флип: DRY_RUN=False, one-sided режим активен (reward ⅓). Известные долги: FARM-008 (external heartbeat), FARM-009 (перекотировка). |
| 2026-07-02 | FARM-003 | Разбор инцидента 07-01/02 (слив seed 236→0 за 12ч, 5 первопричин) + фиксы. F1: reconcile_orders() каждый тик, книга=истина (orphans→cancel, missing/undersized→requote, one-sided→throttled). F2: QUOTE_OFFSET 0.015→0.02, REQUOTE_FRAC 0.6→0.4 (порог 1.0c<2.0c) + runtime-инвариант requote<offset. F3: ASK cap по on-chain inv, <min_size→осознанный one-sided (не 400-спам). F4: inv_center=200 в MARKETS, deadband 0.5×min_size, delta от seed, skew reseed_buy. F5: остаток ноги <min_size→requote. last_ts персистентность farming_state.json (atomic tmp+replace) — закрывает долг FARM-001. requote по СМЕНЕ skew (не каждый тик) — score не сжигается. fills→немедленный requote+notify. Верификация: farm_smoke PASS, --diag OK, DRY TICK1 REQUOTE→TICK2 HOLD, рестарт restored cursors. Инцидент P&L −$3.5 (−$5.4 slip + $1.87 reward). Демон DRY_RUN=True, книга пустая. Долг: FARM-004 Telegram-env (notify=только лог), DRY-ветка без F3-cap. |
| 2026-07-01 | FARM-002 | Farming live запущен (Account2/US×Iran). Live-ветка place_two_sided/cancel_quotes реализована (снят NotImplementedError FARM-001). Обе ноги scoring=True (Polymarket), maker fee=0, matched=0. Фиксы SDK-контрактов (пойманы farm_smoke, невидимы в DRY): tick_size=get_tick_size(token)→str (float ломал ROUNDING_CONFIG); cancel_order=OrderPayload(orderID=); is_order_scoring=OrderScoringParams(orderId=); листинг get_open_orders. Структурные: A1 skew мёртв (place_two_sided игнорировал plan → +plan/+params, offsets из плана); A3 reward-score не вызывался (share_avg/тик); A2 neg_risk/tick из params; B1 check_fills курсор newest=max_ts+1; params-fail leak (отмена ног перед continue). Инструменты: farm_smoke.py (пре-флип гейт SDK+skew+score), check_scoring.py (read-only монитор коридора). executor_account2.py: neg_risk True→False. Долг: last_ts персистентность (ОТЛОЖЕНО), самоконтроль живости ног, шум auth/api-key 400. |
| 2026-07-01 | FARM-001 | Демон farming ликвидности (Account2/Justfuuun), автономный two-sided market-maker. read_inventory переписан на on-chain: SDK get_balance_allowance() мёртв (всегда 0), читаем ERC-1155 balanceOf(funder,token_id) на CTF 0x4D97DCd9…, RPC-fallback, fail-closed None. Валидировано на 3 живых позициях acc2 (1029/1000/11.11 shares, MATCH до 6-го знака vs data-api). throttled_log переиспользован из LIVE-003 (HOLD-тики и повторные ошибки — 300s, REQUOTE/fill/новые ошибки — всегда). DRY-loop end-to-end на живом US×Iran (ноль ордеров). systemd farming-daemon.service Type=notify (sd_notify через stdlib socket, python-модуль systemd отсутствует на S2), WatchdogSec=30 — на сервере, вне git (паттерн executor). logrotate 10M/keep7/copytruncate. Money-adjacent stubbed: place_two_sided/cancel_quotes live-пути (NotImplementedError). FUNDER acc2 вписан (on-chain подтверждён). Осталось: бутстрап инвентаря (форма дня 1), live-ветка. |

## 2026-06

| Дата | TASK_ID | Описание |
|------|---------|----------|
| | 2026-06-30 | LIVE-004 | Закрытие: token_id-проброс завершён по всему пайплайну (source→whale_trades→paper_trades→copy_paper_to_live→systemd демон); pull-model S2 готов; watchdog live_copy_daemon (INFRA-048); 3 строки live_orders — исторические тесты, оставлены as-is. INFRA-048 (maker filled_size) переименован в INFRA-049 во избежание коллизии ID. |
| | 2026-06-30 | LIVE-004 | Шаг 3: copy_paper_to_live.py переработан: CLOB-резолв token_id удалён, читает token_id из paper_trades напрямую; fail-closed гейт на NULL token_id (исторические/категориальные сделки не уходят в live); market_title проброшен в live_orders; sweep фильтрует по token_id IS NOT NULL; self-pipe graceful shutdown (os.pipe + signal.set_wakeup_fd); smoke-verified: kill-switch gate + graceful SIGTERM <3s. |
| 2026-06-30 | LIVE-004 | Шаг 4: systemd-юнит polymarket-copy-live-daemon.service (LISTEN, Restart=always, graceful SIGTERM <10ms, развёрнут+enabled на S1); cron */15 sweep под flock добавлен в root crontab; верифицировано: active running, heartbeat, graceful stop без таймаута, sweep early-exit на kill-switch=0. |
| 2026-06-30 | INFRA-048 | WATCHDOG live_copy_daemon heartbeat в pipeline_monitor.py. Копия паттерна INFRA-046 (check_live_executor_heartbeat): DB-side EXTRACT epoch, edge-trigger через live_copy_daemon_alert_state (system_state), порог 180s (константа DAEMON_HEARTBEAT_STALE_SECONDS), first-run guard (last_alerted is None → 'ok'), Telegram-алерт stale→ok/ok→stale. live_copy_sweep не мониторится (cron, не демон). |
| 2026-06-29 | LIVE-003 | Три улучшения live_executor_daemon: (1) throttle повторяющихся ошибок — throttled_log() с_throttle_state dict, 300s по умолчанию / 60s для monitor_order; применён в 4 точках (main ERROR, BALANCE GATE RPC, BOOK ERROR, monitor_order). (2) Колонка route text добавлена в live_orders; submit_taker при успешном fill пишет route=tag (taker_direct/taker_fallback), error=NULL — разделена семантика error (ошибки) и route (путь исполнения). (3) filled_size taker: float(takingAmount) при matched, NULL при отсутствии поля; maker path → INFRA-048 TODO. Код демона на S2 вне git (LIVE-006). |
| 2026-06-29 | LIVE-006 | Executor-код добавлен в репо: папка executor/ (live_executor_daemon.py, executor.py, executor_account2.py, restart_executor.sh, POLYMARKET_V2_CONNECTION.md, account2_diag.py, account2_setup.py). .gitignore дополнен: executor/secrets/, executor/accounts/*.env, __pycache__, venv, logs. Мёртвый код удалён с S2: step3_enumerate.py, l1_7739_auth.py + .bak файлы. Рабочий процесс: правки на S2 в /opt/executor/app/, cp в /root/polymarket-bot/executor/, коммит с S2. |
| 2026-06-29 | LIVE-004 | Шаг 1.2: DDL-миграция LIVE-004. Добавлена колонка token_id (text, nullable) в whale_trades; миграция scripts/migration_live004_whale_token.sql применена; 491672 исторических строки = NULL (fail-closed downstream). Проброс asset/token_id в код Python — следующий шаг. |
| 2026-06-29 | LIVE-004 | Шаг 1.3: проброс token_id (=trade.asset) по коду до INSERT в whale_trades. Правки: whale_trades_repo.py (_INSERT_PLAIN/_INSERT_ON_CONFLICT + save_trade() сигнатура + params), whale_detector.py (save_trade_to_db() + repo call + 3 call-site BACKFILL/PAPER_TRACK/TRACKED), whale_poller.py (POLLER). Default Optional[str]=None — обратная совместимость. Верифицировано на живых данных: token_id 100% непустой по всем source после recreate. ON CONFLICT не тронут. |
| 2026-06-29 | LIVE-004 | Шаг 2: token_id в paper_trades. DDL: ALTER TABLE paper_trades ADD COLUMN token_id text (nullable, idempotent). Функция copy_whale_trade_to_paper() обновлена: token_id добавлен в INSERT (источник NEW.token_id). Backup тела функции в view_definitions_backup (task_id=LIVE-004_paper_token). Проброс верифицирован smoke-тестом: token_id whale_trades→paper_trades совпал, откат чистый. |
| 2026-06-25 | LIVE-003 | filled_size (taker): submit_taker пишет реально исполненный объём в live_orders.filled_size из resp.takingAmount (shares, для BUY = купленные контракты). Применено в боевой демон S2 (рестарт, PID 622481). Maker-путь — TODO INFRA-048 (структура get_order неизвестна, нет боевого maker-fill). Правка демона вне git (S2). |
| 2026-06-25 | INFRA-047 | Watchdog застрявших ордеров в pipeline_monitor.py. Детект строк live_orders в статусах intent/claimed/submitted старше 120с (отсчёт COALESCE(updated_at,created_at)). Edge-trigger булев флаг: 1 alert на clear→stuck (со списком id) / stuck→clear. Состояние в system_state (component='stuck_orders_alert_state'). |
| 2026-06-25 | INFRA-045 | Таблица system_state (k/v реестр компонентов) для cross-server heartbeat. PK=component, поля heartbeat_at/status/detail(jsonb)/updated_at. Grant SELECT/INSERT/UPDATE для order_executor. Расширяема под любой компонент без миграций. |
| 2026-06-25 | INFRA-046 | Heartbeat-alert демона live_executor в pipeline_monitor.py. Edge-trigger: 1 сообщение на переход ok→stale / stale→ok, без спама при длительном простое. Порог stale=120с. Состояние last-alerted в system_state (component='live_executor_alert_state'). Использует system_state из INFRA-045. |
| 2026-06-25 | INFRA-044 | Backfill CPU saturation S1 RESOLVED: причина рекуррентного 100% CPU (hard-reset 2026-06-19) — run_category_backfill.py запускался cron каждые 2ч без lock, прогон длится ~4ч, экземпляры накладывались и копились. Фикс: crontab → flock -n /tmp/category_backfill.lock + интервал 0 */6. Убиты накопленные дубли (4 процесса). CPU-полка упала со ~110% до <2%. |
| 2026-06-24 | LIVE-002 | systemd unit live-executor.service: LoadCredential (DATABASE_URL через LoadCredential (plaintext, chmod 600 root:root, без шифрования at-rest — systemd-creds отсутствует на образе S2)), Restart=on-failure/RestartSec=30, MemoryHigh=200M/MemoryMax=350M. Демон переживает ребут S2 и закрытие сессии. Секрет вне env-файла. |
| 2026-06-24 | LIVE-005 | on-chain balance-gate + фикс $1, boevoy test passed. |
| 2026-06-19 | PIPE-048| | Привязан триггер AFTER INSERT ON paper_trades → notify_paper_trade (orphan-функция реанимирована). paper_trade_notifications: колонка notified boolean заменена на status text (PENDING/SENT/ENRICH_FAILED/SEND_FAILED) + attempt_count, next_retry_at; CHECK-constraint; два частичных индекса (pending / retry). Worker: статус-машина с раздельными потолками ENRICH=3/SEND=5, экспоненциальный backoff (SQL, cap 300s), заморозка + системный send_error при исчерпании. Обогащение: resolve_market_url (CLOB→Gamma, events[0].slug, groupItemTitle), lookup имени кита из whales.notes. telegram_alerts.send_paper_trade_notification: переход на parse_mode=HTML + экранирование (фикс HTTP 400 на спецсимволах в названиях), проброс bool результата (worker метит SENT только при успехе — устранён ложный SENT), _send_message логирует response_body. Алерт показывает Size = kelly_size (наша сумма ордера, дробная), строка Kelly удалена, size_usd (китовая) убрана. Известный долг: 15 строк со старым ложным SENT оставлены как есть; rotation токена Telegram — отдельная задача (SEC-503). |
| 2026-06-21 | TRD-448 | Учёт комиссии Polymarket в PnL. Раньше комиссия = 0, прибыль завышалась. Замерили on-chain: 3% от суммы сделки × max(цена, 1−цена), за каждый вход/выход через стакан; redeem без комиссии. 3C (roundtrip_builder): продажа — комиссия на вход и выход. 3B (settle_resolved_positions): резолв — комиссия только на вход. Paper: view paper_simulation_pnl уже на net_pnl_usd — комиссия доходит автоматически. Не делалось: backfill старых сделок; sizing комиссию не учитывает (фиксированная доля от банка, без edge), правку Kelly в copy_trading_engine откатили (мёртвый код). |
| 2026-06-23 | TRD-449 | Ценовой фильтр входа в copy_whale_trade_to_paper. Whale-сделки с price > max_entry_price (default 0.97, strategy_config) не копируются в paper_trades. Причина: при p>0.97 комиссия съедает payout (1−p), buy-and-hold убыточен даже при выигрыше. Порог строго >, p=0.97 проходит. |
| 2026-06-23 | LIVE-001 | доработан live_executor_daemon.py на S2 до production-ready. Реализован выбор типа ордера по размеру: shares_maker >= min_order_size (из стакана) → GTC maker @ best_bid с 15-мин таймаутом и fallback в taker; shares_maker < min_order_size → сразу FOK market BUY без ожидания. FOK переведён на create_market_order(MarketOrderArgsV2) с долларовым amount (SDK сам считает size, устранён баг точности decimals в market buy). Закрыты баги: None-guard в monitor_order (get_order возвращал None до индексации); neg_risk читается из ответа стакана вместо хардкода True (ловило неверный exchange-контракт); статусы сверяются case-insensitive (API возвращает 'matched' в нижнем регистре); size_usd конвертируется в float в claim_intent (psycopg2 Decimal); обязательный файл-лог /opt/executor/logs/live_executor.log, Telegram опционально поверх. Эмпирически подтверждено живым ордером: min_order_size=5 НЕ гейтит FOK market BUY (ордер на 1.31 шер исполнился, status matched). Не сделано в этой задаче: systemd auto-start (LIVE-002), баланс-гейт против реального pUSD (LIVE-005), slippage-потолок на taker (отложен, оператор), авто-копирование paper_trades → live_orders (LIVE-004), измерение redeem-комиссии on-chain. |
| 2026-06-13 | PIPE-047| | Fix outcome mismatch в paper_simulation_pnl и paper_portfolio_state materialized views. JOIN-условие не учитывало outcome — на рынках, где кит одновременно держал roundtrip-ы по YES и NO с одинаковым side='buy', view мог сматчить нашу сделку с roundtrip-ом противоположного исхода. Добавлено `lower(pt.outcome) = lower(rt.outcome)` в JOIN обоих views (CTE matched / matched_trades). DROP + CREATE внутри транзакции. Верификация: remaining_mismatches=0, row_count=1, realized_pnl=-137.15 (vs -157.89 до фикса, Δ=+20.74), win_rate=57.6% (vs 54.4%). Backup определений в view_definitions_backup (task_id=PIPE-047). |
| | 2026-06-13 | INFRA-043 | Схема live_orders (пулл-модель для live-исполнения): CREATE TABLE + partial index idx_live_orders_intent + GRANT SELECT, UPDATE TO order_executor. Назначение: очередь intent-ордеров для executor'а (pull-модель). Почему order_executor переиспользован: pg_hba line 34 уже существует для 62.60.233.100, новая роль и pg_hba reload не требуются. CHECK-констрейнты: limit_price∈(0,1), size_usd>0, side∈{BUY,SELL}, status∈{intent,claimed,submitted,filled,partial,rejected,failed}. INSERT/DELETE не выданы. Claim-контракт: UPDATE SET status='claimed' WHERE id=$1 AND status='intent' RETURNING * — 0 строк = ордер уже обработан. token_id резолвится вне БД через Gamma API. TASK_BOARD: INFRA-043 → DONE. |
| | 2026-06-09 | INFRA-039 | Data-freshness probe: столбец inserted_at (timestamptz DEFAULT now()) в whale_trades + check_whale_trades_write_freshness() в pipeline_monitor. thresholds: WARNING>35min, CRITICAL>45min. Ловит остановку записи независимо от рыночной активности. DDL: ALTER TABLE, backup-schema, transactional (BEGIN/COMMIT). |
| | 2026-06-10 | BUG-612 | Engine hardening в whale_tracker.py (2-й экземпляр BUG-610):_ENGINE_KWARGS (pool_pre_ping, pool_recycle=1800, connect_timeout=10, statement_timeout=30000) в обоих create_engine — set_database() + _ensure_database(). Repro postgres-restart: busy-spin нет, запись возобновилась. Verify grep: обе точки живой код. |
| | 2026-06-10 | INFRA-040 | Detection DONE, recovery заморожен. Heartbeat перенесён из main-loop (удалён) в _paper_poll_loop (single writer, verify grep). Healthcheck -mmin -10→-3. Устраняет ложный healthy инцидента 06-09. Recovery (autoheal) не доказан → INFRA-041/042; repro невалиден (errors-log 06-10). |
| | 2026-06-09 | BUG-610 | Защита пула соединений whale_detector от заморозки event loop. Голый create_engine (set_database,_ensure_database) без pool-параметров → при разрыве коннекта к PG пул отдавал мёртвый коннект → синхронный psycopg2 busy-spin под GIL → заморозка всего async loop (root cause инцидента 08:47–14:05, ~5ч простоя записи). Fix: pool_pre_ping=True + pool_recycle=1800 + connect_timeout=10 + statement_timeout=30000 (через connect_args options, покрывает read-фазу). Repro-тест (docker restart postgres при живом detector): до фикса заморозка, после — CPU 0.00% (было 90%), age_after=1.33мин, переподключение автоматическое. Покрывает «мёртвый коннект из пула»; полный класс — в BUG-611 (to_thread). |
| | 2026-06-08 | INFRA-038 | Burst detection filter в WhaleTradesRepo: блокировка мелких HFT-сделок (< $50) при превышении 30 сделок в одном маркете за 15 минут. In-memory sliding window (deque), нулевая нагрузка на БД. Крупные сделки (>= $50) не блокируются. Покрыто 3 unit-тестами. |
| | 2026-06-06 | HYG-014 | Удалён deprecated Python settlement path из roundtrip_builder.py: метод `settle_roundtrips_via_gamma()`, `_get_market_resolution()`, `_get_outcome_index()`, константы `GAMMA_API`, `CLOB_API`, импорты `aiohttp`, `asyncio`. Заменён SQL-механизмом `settle_resolved_positions()` (run_settlement.sh, PHASE3-006). −310 строк. Smoke 24/24. |
| | 2026-06-07 | INFRA-037 | Tune work_mem 4MB→32MB (ALTER SYSTEM, postgresql.auto.conf) + vm.swappiness 60→10 (sysctl.conf). Root cause: дисковый спилл сортировки close_sell при work_mem=4MB → выброс 2851s @ 06:15 при конкуренции за I/O. RAM достаточна (OOM нет), swap/RAM не расширялись. |
| | 2026-06-07 | BUG-609 | Исправлен ложный CRITICAL в pipeline_monitor: коммит fdf90c5 формировал сообщение из `last` (последний прогон, 434s) вместо значения, реально превысившего 1800s; триггер срабатывал по `over_1800 >= 2` из прошлого прогона (2851s @ 06:15). Fix: добавлены `max_over_1800` / `max_over_1200` + поле `alert_value` в return dict; CRITICAL-сообщение использует `alert_value`. |
| | 2026-06-08 | PIPE-044 | DDL: таблицы leaderboard-воронки. Создано: leaderboard_candidates, leaderboard_candidate_trades, leaderboard_candidate_roundtrips. Индексы: 7 явных + 3 partial на boolean-колонках + 3 PK + 3 UNIQUE. Миграция: migrations/pipe_044_leaderboard_tables.sql. |
| | 2026-06-08 | PIPE-045 | Скрипт: fetch кандидатов + LP/HFT-фильтры. Файл: scripts/fetch_leaderboard_candidates.py. Загружено кандидатов: 20 (из топ-20 leaderboard ALL-TIME). Отсеяно LP: 9 (REWARD activity). Отсеяно HFT: 11 (peak>20 trades/15min). Прошли в скоринг: 0. Поля API leaderboard и activity задокументированы в логе. |
| | 2026-06-08 | PIPE-046 | Скрипт: roundtrip scoring + settlement. Файл: scripts/score_leaderboard_candidates.py. Дубль алгоритма roundtrip_builder.py (TODO: унифицировать). Обработано кандидатов: 20. Roundtrips: total=1560 | closed=182 (SELL) | open=1378. close_type: SELL=182 | OPEN=1378. Единицы size_usd: USDC, price: вероятность 0-1, implied_contracts = size_usd / price. |
| | 2026-06-06 | HYG-015 | Задокументирована семантика `open_trade_id` в PIPELINE_MAP_3A §9.3: `MIN(whale_trades.id)`, однократная запись, не обновляется. Исправлен неверный COMMENT в migration_whale_trade_roundtrips.sql: `position_key` — plain string без hash и без `open_trade_id`. |
| | 2026-06-06 | DOC-604 | Добавлено правило context-first в CHAT GOVERNANCE §3.1: постановщик читает knowledge base сам перед TASK PACK, к Roo — только за runtime state. |
| | 2026-06-04 | INFRA-030 | Retention whale_trades: процедура retention_whale_trades(p_days=30, p_batch=10000), батчевый DELETE с живым NOT EXISTS, cron 04:00 UTC daily. Боевой прогон A5: удалено 120,000 строк, OPEN-инвариант цел, защищённые SELL=19. Индексы idx_rt_* в init_db.sql. logrotate + pipeline_monitor (last_run_age 25h, error check). |
| 2026-06-01 | INFRA-032 | Fix query bloat in _fetch_and_group_buy_trades и_fetch_and_group_sell_trades: добавлен фильтр traded_at > NOW() - 30 days и исключение excluded-китов. Duration 480s→210s, SELL groups 23K→8.5K |

## 2026-05

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-05-29 | DATA-409 | Миграция fetch_trader_trades на /activity?type=TRADE за фича-Флагом use_activity_endpoint (bool, default=False). usdcSize используется если присутствует, fallback size*price. Верифицировано: endpoint возвращает type=TRADE, usdcSize валиден. Флаг выключен — прод на /trades до явного включения. |
| | 2026-05-30 | DATA-410 | Whitelist для точечного включения /activity endpoint: поле activity_endpoint_whitelist: List[str] = [] в settings. Логика: use_activity_endpoint=True → глобально, whitelist → точечно, оба пусто → /trades. Верифицировано на 0xfea31bc: +50 сделок за 1 цикл, gap 10ч закрыт, дублей 0, остальные киты не затронуты. |
| | 2026-05-30 | DATA-411 | Глобальное переключение всех китов на /activity?type=TRADE. USE_ACTIVITY_ENDPOINT=true в .env. Rebuild не выполнялся. Верифицировано: COUNT растёт для всех китов, gap=0, дублей 0, smoke PASS. DATA-408 и DATA-409 закрыты как верифицированные. |
| 2026-05-29 | DATA-408 | partial UNIQUE INDEX idx_whale_trades_tx_hash_unique на whale_trades(tx_hash) WHERE NOT NULL AND <> ''. ON CONFLICT с предикатом в whale_trades_repo.py. TOCTOU-SELECT сохранён как доп. слой. Деплой: rebuild whale_detector. Верифицировано: INSERT 0 0 на дубле, paper_trades не затронут. |
| 2026-05-23 | TRD-444 | close_size_usd backfill: 52,364 SETTLEMENT rows заполнены (Formula A), forward fix в settle_resolved_positions() deployed |
| 2026-05-21 | TRD-444 | Cleanup roundtrip_builder part 1: HYG-NNN-15 (улучшен help text для --sentinel-method), HYG-NNN-5 (удалён whale_roundtrip_reconstructor.py, 814 строк, 0 active callers). HYG-NNN-3 закрыт как false positive — dead fields не обнаружены. HYG-NNN-1 (close_* fields в SETTLEMENT) перенесён на следующий dev-чат. pytest 12/12 PASSED. |
| 2026-05-20 | HYG-010 | Docker cleanup post-TRD-443. Удалены: контейнер cool_booth (hello-world Exited 3mo), image polymarket-bot-roundtrip_builder:pre-trd443-d9e1b0e30ad8 (rollback artifact), 26 dangling anonymous volumes (~1.26GB, test postgres от pytest TRD-445), build cache старше 24h (1.64GB, дубли pip/apt от параллельных builds). Disk: 75%→65% (-3GB used, +2.8GB avail). Production volumes/images/контейнеры не затронуты. |
| 2026-05-20 | DIAG-TRD443-RATE-LIMIT-04 | DIAG-TRD443-RATE-LIMIT-04 closed. All hypotheses (rate-limit, filter min_size, intraday cycles, ON CONFLICT cycle 2) disproven via API reconciliation on 2 sample whales (0x25257a6a, 0x31c1a77f, 33 trades total, 100%% match with whale_trades after accounting for floating-point precision artefacts). Pipeline OPEN/CLOSE sides correct. 23 DIRECT_SELL/24h explained as natural sparsity — majority of closures via SETTLEMENT, not direct SELL. TASK_BOARD reverted: TRD-443 annotation removed, TRD-447 → CANCELLED. Bonus findings (non-blocking): (1) inconsistency between open_trade_id (MAX id) and opened_at (MIN traded_at) in _save_roundtrips aggregation — candidate for separate low-priority TRD; (2) reconciliation scripts require tolerance ε for float comparison, not exact tuple match — methodological note. |
| 2026-05-19 | TRD-445 | Hardening тестовой инфраструктуры roundtrip_builder. SCHEMA_FILES в tests/integration/conftest.py расширен migration_phase3_007a_pnl_status_legacy.sql (HYG-NNN-12). datetime.utcnow() → datetime.now(timezone.utc) в tests/integration/_helpers.py (2 occ) и tests/integration/test_roundtrip_builder_close.py (5 occ) для совместимости с Python 3.12+ (HYG-NNN-7). HYG-NNN-6 (cleanup test container на pytest startup) — закрыт как already-implemented в 4990000. Verification: pytest 12/12 PASSED (5 smoke + 7 roundtrip_close). |
| 2026-05-19 | TRD-443 | Реактивация _close_roundtrips в roundtrip_builder.py (DORMANT с Phase 2B). Pipeline: host cron `15 * * * *` через scripts/run_close_sell.sh, exact + fuzzy matching, sentinel-method для backfill. Migrations: phase3_006 (is_legacy_close marker, 530 legacy FLIP rows), phase3_007 (extend matching_method whitelist: + FUZZY_FLIP, MANUAL_RUN_TRD443), phase3_007a (extend pnl_status: + EXACT, LEGACY_INVALID, 75 rows). Settlement cron `0 */2 * * *` не тронут. Тесты: conftest + helpers + roundtrip_builder_close tests. Monitoring: pipeline_monitor.py расширен 4 checks (last_run_age, runs_24h, exit_codes_24h, duration_p95) на основе log-parsing. Backfill MANUAL_RUN_TRD443: 160 sentinel rows (HIGH/EXACT, net_pnl_usd sum=$14,485.93). Commits: 4990000 (atomic feat: 14 files, +1979/−176), b1b531f (feat: pipeline_monitor). 8 commits в origin/main. Snapshots: prod_3b1_20260519, prod_pre_task4, prod_pre_task5. |
| 2026-05-17 | TRD-442 | CANCELLED: архитектурное расхождение между context transfer §2.2 и фактической схемой БД (paper_trades — event log, не position store). Закрытие позиций уже реализовано через whale_trade_roundtrips + ARCH-3BC-PIPELINE. Synchronous trigger создавал бы race с cron. Baseline forensics передан в ARCH-3BC-PIPELINE. Artifacts: backups/baseline_*_2026-05-17. |
| 2026-05-15 | DOC-PIPELINE-MAP | Карта магистрали сделки кита (PIPELINE_MAP) — 10 документов. 7 шагов магистрали: PIPELINE_MAP_1 (read_api, ACTIVE), 2A (whale_registration, ACTIVE), 2B (whale_trades_write, ACTIVE), 3A (roundtrip_open, ACTIVE), 3B (close_settlement, ACTIVE), 3C (close_sell, DORMANT), 4 (update_whale_pnl, ACTIVE). 2 sidebar: 1B (market_metadata_cache, ACTIVE), 1C (builder_client, DORMANT). PIPELINE_MAP_INDEX.md — master-карта. verified: магистраль 1→2A→2B→3A→{3B|3C}→4. 3C подтверждён как DORMANT (CLI --close нигде не подключён). Конкуренция 3C↔4 по 7 колонкам whales. |

## 2026-04

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-05-05 | SYNC-TASKBOARD-2026-05-05 | Аудит AUDIT-001 (debug-чат). Закрыты 2 задачи из висевших с 2026-04-19. TRD-404 → DONE: эталоном bankroll-pipeline выбран view-based (paper_portfolio_state materialized view), используется триггером copy_whale_trade_to_paper через kelly_bankroll_source=1 с 2026-04-05. Verification de-facto через эксплуатацию. ANA-404 → BACKLOG: задача нетривиальная по объёму, не критическая, переведена из TODO в backlog для оценки приоритета. TRD-403 эскалирована как BUG-NEW (sell-pipeline в roundtrip_builder не запускается в production) — оформляется отдельно. |
| 2026-04-22 | DOCS-UPDATE-AUDIT-CYCLE | Docs: CHANGELOG + WHALE_STATUS_TRANSITIONS.md v1.1 + CHAT GOVERNANCE. Excluded whale 82244 (edge_degraded, scale mismatch). Batch promotion none→tracked: 12 whales. 4 candidates rejected for paper after whale_status.sql verification. Audit methodology unreliable: 3/3 spot-checks showed material divergence. Reset 2026-04-05 limits observability to 17d. Tier staleness issue identified. |
| 2026-04-20 | WHALE-STATUS-TRANSITION-SPEC | docs: WHALE_STATUS_TRANSITIONS.md — governance spec v1.0 для whale copy_status transitions (none ↔ tracked ↔ paper ↔ excluded). Формула estimated_capital: max_daily_volume_30d. |
| 2026-04-19 | SYNC-TASKBOARD-2026-04-19 | Синхронизация TASK_BOARD с фактическим состоянием по результатам аудита AUDIT-OPEN-TASKS-2026-04-19. Переведены в DONE (10): TRD-402,406,412,417; INFRA-017,020,024; HYG-002,003. Переведены в CANCELLED (8): TRD-407,431; SEC-502; INFRA-022,023; ANA-401,402,403. Переформулированы (2): TRD-403,404 — view-based архитектура. |
| 2026-04-19 | DOC-GOVERNANCE-UPDATE | CHAT GOVERNANCE дополнен пунктами 6-11 (формат, название, inline-запрет, префиксы эпиков, структура, статусы). task_template Шаг 0 — ссылка на новые правила. |
| 2026-04-19 | DOC-603 | Актуализация PROJECT_STATE.md + запрет snapshot-данных в PROJECT_STATE_GOVERNANCE.md. Удалены: конкретные суммы bankroll/ROI/PnL, wallet-адреса, счётчики китов. Добавлены: Weekly AI whale analysis (ANA-502), Paper-trade pipeline (TRD-439), Tracked polling loop (TRD-420-B). GOVERNANCE v1.1: принцип "фундамент, не snapshot". |
| 2026-04-19 | INFRA-TASKBOARD-HTML | Обновлён generate_task_board_html.py: фильтр DONE/CANCELLED (восстановление SYS-313), поддержка LANE/EPIC нового формата, колонка "Тег", приглушение FROZEN LANE, "Все задачи выполнены" для пустых эпиков. HTML теперь валиден. |
| 2026-04-19 | HYG-009 | Рефакторинг TASK_BOARD: 3 LANE + 9 EPIC (PIPE/TRD/DATA/ANA/SEC/INFRA/HYG/DOC/BUG), 139 задач. УДАЛЕНЫ: W-001,W-002,W-003 (дубли работы), W-004 (FROZEN), A-101..A-103 (ARB FROZEN), S-201..S-203 (SMART FROZEN). ПЕРЕНЕСЕНА: WHALE-701 → TRD-441. СХЛОПНУТЫ ДУБЛИ: SYS-322 (2→1), ARC-502-B (2→1). Новые ID: PIPE-*, TRD-401..TRD-441, DATA-404/405/406/407, ANA-401..ANA-503, SEC-401..SEC-505, INFRA-001..INFRA-024, HYG-001..HYG-009, DOC-601..DOC-602, BUG-607 |
| 2026-04-19 | W-001 | Whale Detection Pipeline: whale_detector.py active, реализован |
| 2026-04-19 | W-002 | Whale Tracking Database: WhaleTradesRepo — единая точка записи |
| 2026-04-19 | W-003 | Strategy Metrics Engine: Kelly sizing + materialized views реализованы |
| 2026-04-19 | W-004 | Copy Trading Engine Integration: copy_trading_engine.py отключён |
| 2026-04-19 | TRD-402 | Goals: populate size correctly, populate opportunity_id from paper_trades, populate market_title, fix gas cost units, ensure new VIRTUAL trades are analytically valid |
| 2026-04-19 | SYS-322 | PRE-PROD-SECRETS-ROTATION: ротация секретов перед переходом на live. Приоритет: БЛОКЕР |
| 2026-04-19 | BUG-701 | Исправлена ссылка на days_active_7d в refresh_qualification() и update_whale_activity_counters() |
| 2026-04-19 | TRD-401 | Goals: validate trades data integrity, detect zero-size trades, verify PnL fields, verify gas cost values, check market metadata completeness |
| 2026-04-19 | FIN-401 | Fix virtual bankroll logic: capital blocked only on executed trade open and returned only on trade close |
| 2026-04-19 | TRD-409 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-411 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-412 | Создание whale_trade_roundtrips table и логики реконструкции позиций китов |
| 2026-04-19 | TRD-413 | Whale trades ingestion incomplete (~99% loss for some whales). Root cause: global 500-trade limit + no per-wallet backfill |
| 2026-04-19 | TRD-421 | Completed (details in PROJECT_STATE) |
| 2026-04-19 | TRD-420-A | Targeted fetch trades для китов с copy_status='paper' каждые 30 сек |
| 2026-04-19 | TRD-420-B | Targeted fetch trades для tracked китов каждые 5 мин |
| 2026-04-19 | ANA-502 | Миграция для хранения результатов еженедельного AI анализа |
| 2026-04-19 | ANA-502-SQL | Финальные SQL-запросы для еженедельного AI-анализа китов |
| 2026-04-19 | INFRA-002-004.4 | Применение pg_hba.conf через docker cp + pg_reload_conf |
| 2026-04-19 | INFRA-002-005.2 | Включение SSL в PostgreSQL: mount config/ssl/ + SSL параметры, force-recreate postgres |
| 2026-04-19 | INFRA-002-005.3 | Замена host → hostssl в pg_hba.conf для grafana_reader и order_executor |
| 2026-04-19 | INFRA-002-006.FIREWALL | Firewall hardening: DOCKER-USER chain + conntrack --ctorigdstport 5433 |
| 2026-04-19 | INFRA-002-006.1b | Firewall persistence: systemd unit /etc/systemd/system/docker-firewall-rules.service |
| 2026-04-19 | INFRA-002-007 | Тест полного подключения с Сервера 2: grafana_reader SSL TLSv1.3 AES-256-GCM, SELECT OK, writes denied |
| 2026-04-19 | INFRA-002-008 | 9-этапный read-only security baseline audit |
| 2026-04-19 | INFRA-002-AUDIT-ORDER-EXEC | order_executor permissions: только SELECT на 5 таблицах, нет write |
| 2026-04-19 | INFRA-003 | Backup Policy: нет автоматического backup |
| 2026-04-19 | SEC-501-HOST-HARDENING | SSH hardening: PermitRootLogin=yes, PasswordAuthentication=yes, no fail2ban |
| 2026-04-19 | postgres-logging-hardening | log_connections=off, log_disconnections=off, minimal observability |
| 2026-04-19 | firewall-startup-race-fix | Startup race window ~seconds, pg_hba reject компенсирует |
| 2026-04-19 | user-provisioning-runbook | Процедура добавления user описана в pg_hba.conf комментариях |
| 2026-04-19 | SYS-309 | Daily Data Audit Snapshot: cron intentionally disabled, script kept for manual use |
| 2026-04-19 | SYS-330 | trade_duplicate rate flood: дедупликация работает корректно, риск только рост лог-файла |
| 2026-04-19 | SYS-601 | Очистка TASK_BOARD и CHANGELOG: унификация формата, русские названия, удаление Description |
| 2026-04-19 | BUG-603 | Dedup filter переключён на opportunity_id (paper_trades.id) |
| 2026-04-19 | BUG-604 | Bankroll reconciliation из таблицы trades |
| 2026-04-19 | BUG-801 | Audit pnl_status UNAVAILABLE в whale_trade_roundtrips: backfill 10,123 rows, smoke_test 24/24 PASS |
| 2026-04-19 | BUG-504 | Fixed false new_trades=50 log: save_whale_trade() теперь возвращает bool на основе INSERT rowcount |
| 2026-04-19 | BUG-502 | Verified real-time whale trade ingestion. Paper poll (30s) и tracked poll (5min) loops работают независимо |
| 2026-04-16 | ANA-501 | Daily Whale Alert Monitor: Cron 08:00 UTC, 5 SQL checks, Telegram alerts |
| 2026-04-15 | SYS-336 | Kelly sizing fix: min_trade_size_usd=$0.01 → $1.00, фильтр кита >= 1% депозита, динамический bankroll |
| 2026-04-15 | SYS-335 | smoke_test freshness check: Check A исправлен (MAX → COUNT WHERE), Check B удалён. Результат: 24/24 PASS |
| 2026-04-14 | SEC-501 | SSH hardening: PasswordAuthentication yes → no, PermitRootLogin yes → prohibit-password, fail2ban установлен |
| 2026-04-14 | SYS-331 | Исправление застрявших roundtrips: run_settlement.sh cron не работал. Закрыто 37 roundtrips, обновлено 2979 китов |
| 2026-04-12 | SYS-334 | Исправление market_category в whale_trade_roundtrips: заполнено через JOIN. 17,217 records updated |
| 2026-04-11 | SYS-328-AUDIT | Инвентаризация файлов: 44 .md, 13 migration_*.sql |
| 2026-04-11 | SYS-329 | Политика хранения логов: journald 1G/7d + docker json-file 50m×3 + logrotate daily×7 |
| 2026-04-11 | SYS-333 | Исправление rsyslog flood: missing log files (ufw.log, mail.log, mail.err). Verified: 0 flood entries/min |
| 2026-04-11 | PHASE4-001 | Аудит данных: схема, JOINs, формулы PnL. Report: docs/audit/PHASE4-001-summary.md |
| 2026-04-10 | INFRA-002-006.0b | Ротация POSTGRES_PASSWORD: Audit + rotation completed, containers recreated |
| 2026-04-05 | PHASE3-007 | Верификация end-to-end settlement в БД: Ручной запуск 09:33 UTC — УСПЕШНО |
| 2026-04-05 | PHASE4-003 | Materialized view paper_portfolio_state created: initial_bankroll=$1000, realized_pnl=-$46.62, current_balance=$953.38 |
| 2026-04-05 | PHASE4-004 | Стандартизация PnL формулы на our_pnl_v2 = whale_pnl * (kelly_size / whale_size) |
| 2026-04-05 | PHASE4-005 | Created refresh_views.sh, cron (15 */2* **), 3 view checks to smoke_test.sh. All 23 checks pass |
| 2026-04-05 | PHASE4-006 | Dynamic Kelly: trigger использует dynamic bankroll из paper_portfolio_state view |

---

## 2026-05-05

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-05-05 | TRD-403 — DONE | Верификация settlement behaviour в `whale_trade_roundtrips` выполнена. По итогам обнаружен баг развёртывания: `run_close_positions()` (sell-pipeline) никогда не запускался в production — флаг `--close` отсутствует в docker-compose и crontab. За всю историю таблицы (47 087 записей): `close_type = 'SELL'` — 0, `matching_method = 'FLIP'` — 0. Эскалировано как `BUG-608`. Спецификация: `docs/tasks/BUG-608.md`. |
| 2026-05-05 | BUG-608 — CREATED | Закрытие позиций roundtrip_builder не выполняется в проде. Severity: HIGH. Тег: `feature:roundtrip-close`. Подробная спецификация: `docs/tasks/BUG-608.md`. Статус: TODO. Фикс — отдельный TASK PACK после согласования варианта решения (1/2/3) и стратегии обработки истории (A/B/C) со STRATEGY. |

---

## 2026-03

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-03-31 | BUG-602 | Bankroll restore из БД при рестарте (больше нет $100 hardcode reset) |
| 2026-03-31 | BUG-601-FIX | Settlement переключён с Gamma API на CLOB API (459 trades закрыто) |
| 2026-03-31 | TRD-430 | Pipeline audit завершён (timezone hypothesis отклонена) |
| 2026-03-30 | TRD-408 | Fix traded_at: теперь использует API timestamp вместо DB insert time |
| 2026-03-29 | STRAT-701 | Whale copy selection: добавлен copy_status column, trigger фильтрует по 'paper', pipeline unfrozen |
| 2026-03-27 | ARC-503 | Remove legacy fields is_winner and profit_usd из whale_trades (код + БД) |
| 2026-03-26 | TRD-427b | Fix: исправлен баг TypeError в _update_whales_pnl() — print() аргумент был строкой вместо списка |
| 2026-03-26 | TRD-427 | Fix: roundtrip_builder теперь запускает --settle автоматически каждые 2 часа |
| 2026-03-26 | TRD-426 | Fix: исправлены tier пороги (HOT: 1d, WARM: 7d), пересчитаны тиры |
| 2026-03-26 | SYS-601-FIX | Fix: устранено дублирование roundtrip jobs (main.py → container), увеличен интервал 30min → 2h |
| 2026-03-26 | ARC-502-D | Fix: обновление P&L китов через wallet_address вместо whale_id (+461 whales, +2266 roundtrips) |
| 2026-03-26 | ARC-502-C | Roundtrip Builder: settlement через CLOB API (+2039 CLOSED, +$680K P&L) |
| 2026-03-25 | ARC-502-B | Fix: fuzzy matching close для short selling (+27 CLOSED) |
| 2026-03-22 | TRD-422 | Добавлен market_category в whale_trades, унифицирован INSERT |
| 2026-03-22 | TRD-423 | Fix whale_trades ingestion:_database_url → database_url |
| 2026-03-22 | ARC-501 | Миграция whales: удалены 8 legacy полей, добавлены 7 P&L полей |
| 2026-03-22 | ARC-502-A | Roundtrip Builder: создание OPEN roundtrips из BUY событий |

---

## 2026-05-06

| Дата | TASK_ID | Описание |
|------|---------|----------|
| 2026-05-06 | BUG-608 — ROLLBACK | Фикс развёртывания (правка docker-compose.yml с добавлением --close) откачен из-за обнаружения неизвестного механизма записи SELL-roundtrips в production (530 записей за 46 дней до фикса, с признаками некорректного fuzzy-матчинга). Эффект нашего фикса оказался минимален (+1 запись). BUG-608 переоткрыт для расследования: что пишет SELL-записи помимо roundtrip_builder, и валидны ли существующие 530 записей. Backup сохранён: backups/BUG-608-20260505-192231/. Container polymarket_roundtrip_builder вернулся к pre-fix конфигурации. |

---

## 2026-05-05

| Дата | TASK_ID | Описание |
