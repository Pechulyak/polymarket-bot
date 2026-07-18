# ШАБЛОН — Еженедельный мониторинг китов (промоут/даунгрейд)

**Версия**: 1.0 (2026-07-18 — по итогам первого полного прогона: leaderboard
+ whale_audit + whale_status + paper-ревью + расчёт live-PnL. Заменяет
черновик 0.1).
**Проект**: Polymarket Following Bot.
**Рекомендуемая модель**: Sonnet для этого чата (оркестратор — анализ,
решения, money-adjacent `UPDATE whales`). Механика сбора — `scripts/mm.sh`
(executor, вызывается inline из этого же чата) для объёмных data-задач;
точечные read-only SQL-проверки (whale_status.sql на 1 кошелёк, короткие
агрегаты) — оркестратор делает сам напрямую.

---

## Триггер

Оператор пишет короткую команду — «проводим еженедельный мониторинг китов» —
без деталей. Запускает поток ниже без уточняющих вопросов, кроме явных
confirmed-гейтов (money-adjacent) и блокеров цикла отказов.

---

## Роли

- **scripts/mm.sh (executor)**: механика — запуск `fetch_leaderboard_candidates.py`/
  `score_leaderboard_candidates.py` (долгие, с сетевыми вызовами). Каждое ТЗ —
  отчёт в `scratchpad/<task>_report.md`, команды напрямую (без `bash -c`/heredoc),
  см. хэндофф-правило в корневом `CLAUDE.md`. Таймаут ставить с запасом: score
  по ~50-60 кандидатам с settlement-запросами к CLOB может не уложиться в 25
  минут — закладывать 40+.
- **Этот чат (оркестратор)**: интерпретация метрик, отбор кандидатов, все
  `UPDATE whales` (money-adjacent — не делегируется), расчёт `estimated_capital`,
  ручной tier-refresh, финальное предложение оператору.
- **Оператор**: confirmed-гейты перед любым `UPDATE whales.copy_status`
  (и перед любым `DELETE`/`TRUNCATE` — см. «Технические ограничения» ниже).

---

## Обзор 4 этапов

Этапы **не строго последовательны** — Этап 1 (leaderboard) выполняется долго
(fetch + score могут занять 20-40 минут на сетевых вызовах), поэтому пока он
крутится в фоне у executor'а, можно параллельно вести Этап 2 (whale_audit —
чистый SQL по уже существующим китам, от leaderboard не зависит).

| Этап | Источник кандидатов | Возможные исходы |
|------|---------------------|-------------------|
| 1. Leaderboard | Новые с Polymarket Leaderboard | `none → tracked` |
| 2. Whale audit | Все существующие `none`/`tracked` киты | `none → tracked`, `tracked → excluded` |
| 3. Whale status (точечно) | Кандидаты с этапов 1-2, требующие подтверждения перед paper | `tracked → paper` |
| 4. Paper-ревью (необязательный) | Текущие `paper` киты | `paper → live`, `paper → excluded` |

`whale_status.sql` (точечная проверка на 1 кошелёк) **не привязан к этапу 3** —
применяется на любом этапе анализа, когда нужны точные детальные метрики по
конкретному кошельку (в этом прогоне использовался и для проверки
leaderboard-аномалии (excluded-кит с подозрительно хорошими цифрами), и для
paper-китов на этапе 4).

---

## Этап 1 — Leaderboard pipeline

`scripts/mm.sh "<ТЗ>" 40` — запустить строго последовательно:
```
python3 scripts/fetch_leaderboard_candidates.py
python3 scripts/score_leaderboard_candidates.py
```
Продакшн-таблицы (`whales`, `whale_trades`) не затрагиваются — только
`leaderboard_candidates` / `leaderboard_candidate_trades` /
`leaderboard_candidate_roundtrips` (см. `docs/pipeline_map/
PIPELINE_MAP_LEADERBOARD_SCORING.md`). Перед запуском проверить
`MAX(fetched_at)` — если фетч уже был сегодня и полностью проскорен, решить
самому, нужен ли повторный запуск (не money-adjacent).

**Если фоновая задача упёрлась в таймаут** (лог обрывается на середине,
`EXIT:124`) — score не считать выполненным по факту "completed" в уведомлении;
проверять реальный прогресс через `COUNT(*) FILTER (WHERE roundtrips_total IS
NULL)` и перезапускать только незавершённый скрипт с увеличенным лимитом
(скрипты идемпотентны, `ON CONFLICT DO UPDATE`).

**Анализ и шорт-лист** (сам, без executor): `is_copyable` всегда `NULL`
(пайплайн не расставляет барьер программно — RF2) — фильтрую сам:
- исключить `is_lp = TRUE` (маркет-мейкер);
- исключить `is_hft_burst = TRUE` (бот, порог `burst_trade_pct > 50%`, PIPE-051);
- из оставшихся — сортировка по `calc_pnl_usd`/`win_rate`, сверить с текущим
  `whales.copy_status` (LEFT JOIN) — часть сильных кандидатов уже `excluded`
  (см. «Аномалии» ниже) или вообще не зарегистрирована в `whales`.

**Исход**: `none → tracked`. **Tier — НЕ блокатор промоута** (уточнено
оператором 2026-07-18): если кандидат COLD, проверить реальную дату последней
сделки и **вручную обновить tier** перед промоутом (формула — см. «Tier
refresh» ниже), а не откладывать решение.

**Закрытие leaderboard-трека** (после того, как решения по всем кандидатам
батча приняты):
```sql
UPDATE leaderboard_candidates SET reviewed_at = NOW()
WHERE fetched_at::date = CURRENT_DATE;

UPDATE leaderboard_candidates SET approved_for_tracking = TRUE, reviewed_at = NOW()
WHERE wallet_address IN (<одобренные>);
```
Затем очистить staging (см. «Технические ограничения» — этот DELETE
исполнитель/чат сделать не может, только оператор):
```sql
DELETE FROM leaderboard_candidate_trades;
```
`leaderboard_candidates` и `leaderboard_candidate_roundtrips` НЕ трогать —
там живут решения (`approved_for_tracking`, метрики).

**Аномалии** (встречалось в этом прогоне): leaderboard может показать сильные
метрики для уже `excluded` кита. Не считать это автоматическим recovery-сигналом
— прогнать `whale_status.sql` по этому кошельку: если внутренний
`whale_trades`/roundtrips знает только о малой части истории (наш ingestion
не покрывает период до промоута/эксклюзии), leaderboard-цифра может
драматически (в разы, до 30x+) расходиться с нашей — по governance
(§11.2 `WHALE_STATUS_TRANSITIONS.md`) внутренние данные авторитетны.

---

## Этап 2 — Whale audit (действующие `none`/`tracked` киты)

Можно вести **параллельно** с Этапом 1 (не зависит от leaderboard).

```
docker exec polymarket_postgres psql -U postgres -d polymarket -f scripts/whale_audit.sql
```
Возвращает много строк (сотни) — сохранять в файл, не читать целиком в
контекст, выбирать нужное через `grep`/секции.

Критерии (`docs/WHALE_STATUS_TRANSITIONS.md`):
- **`none → tracked`**: tier HOT/WARM (или refresh — не блокатор, см. ниже);
  `tracking_source = 'leaderboard'`, если адрес есть в `leaderboard_candidates`,
  иначе `'discovery'`; сильные WR/PnL post-reset, низкая концентрация
  (`max_win_share` не должен доминировать — кандидат, где один выигрыш даёт
  >100% итогового PnL, отклонять).
- **`tracked → excluded`**: **отрицательный** `net_pnl_post` → `negative_pnl`.
  Перед exclusion — проверить открытые paper-позиции (`paper_trades`/
  `paper_simulation_pnl` по wallet) — по факту `tracked`-киты обычно не имеют
  paper-истории, но проверять всегда явно, не предполагать.
- **Неактивные `tracked` (14+ дней без сделок)** — отдельная проверка (join
  `whales`+`whale_trades`, `MAX(traded_at)`), кандидаты на `excluded`
  (`edge_degraded`, если раньше показывали edge, а не `negative_pnl`).

---

## Этап 3 — Whale status (точечно) → `tracked → paper`

**`none → paper` запрещён напрямую** (уточнено оператором 2026-07-18) —
промежуточный `tracked` обязателен, **минимум неделю** до рассмотрения paper
(даёт время накопить post-reset историю и увидеть tier в динамике). Это
дополняет (не то же самое, что) формальный P&L Gate ниже — обе проверки
обязательны.

P&L Gate (`docs/WHALE_STATUS_TRANSITIONS.md` §3.2/§11.2):
- WR ≥ 60%, N ≥ 5 закрытых RT, PnL > 0;
- **post-reset отдельно**: RT ≥ 10 И WR ≥ 60% (иначе STOP — edge не
  подтверждён на текущем режиме);
- tier HOT/WARM на момент решения.

`scripts/whale_status.sql` **захардкожен** адрес/id в строках 1 и 4 — перед
каждым запуском подставлять текущий `wallet_address`:
```
tail -n +3 scripts/whale_status.sql | sed "s/<старый_адрес>/<новый_адрес>/" \
  | docker exec -i polymarket_postgres psql -U postgres -d polymarket
```
(строка 1 файла — самостоятельный нерелевантный запрос по `id`, `tail -n +3`
её пропускает.)

Сверка обязательна (§11.2 п.5): расхождение WR > 5пп или PnL > 10% между
`whale_audit.sql` и `whale_status.sql` → `whale_status.sql` авторитетен.

**estimated_capital перед промоутом в paper — всегда пересчитать заново**,
даже если поле уже заполнено на стадии `tracked` (могло устареть >30д или
кит мог материально вырасти — за 26 дней объём может измениться в 10-20 раз).
Метод:
```sql
SELECT MAX(daily_vol) AS max_30d, percentile_cont(0.5) WITHIN GROUP (ORDER BY daily_vol) AS median_30d
FROM (SELECT DATE(traded_at) d, SUM(size_usd) daily_vol FROM whale_trades
      WHERE wallet_address='<addr>' AND traded_at >= NOW() - INTERVAL '30 days'
      GROUP BY DATE(traded_at)) t;
```
- История ≥30 календарных дней → `max_daily_volume_30d`. Если 30-дневное окно
  малонаселено (мало торговых дней) или дало разовый выброс — сверить с
  full-history max/median, при большом расхождении обсудить с оператором
  (медиана или full-history max могут быть честнее, метод тогда `manual` с
  пояснением в `whale_comment`).
- История <30 календарных дней → `manual`, max за доступное окно.
- **⚠️ Проверить skip-rate при новом капитале** (`skip_threshold = 1% ×
  estimated_capital`): если пересчёт капитала кратно (в разы) больше старого,
  доля сделок кита ниже нового порога может подскочить до 95-99%+ — это
  «edge exists but incompatible with sizing» (открытый вопрос §5
  `WHALE_STATUS_TRANSITIONS.md`, кандидаты reason: `edge_insufficient_for_sizing`/
  `scale_mismatch`, формально ещё не заведены в enum). Явно показать
  оператору цифру нового skip-rate перед решением — оставить старый капитал
  без объяснения нельзя, это осознанный компромисс оператора, документировать
  в `whale_comment`.

---

## Этап 4 — Paper-ревью (необязательный)

Не обязателен на каждом еженедельном цикле — включать, если есть время/повод
(давно не проверяли, подозрение на деградацию).

Для каждого `paper`-кита прогнать `whale_status.sql` и смотреть **обе**
стороны:
- **Whale-side** (`whale_trade_roundtrips_context`, post-reset WR/PnL) —
  качество самого кита.
- **Наша копи-симуляция** (`paper_simulation_pnl`: `our_pnl_sum`,
  `our_wr_via_result_rate`) — что реально получаем МЫ. Может сильно
  расходиться с whale-side (наблюдалось: whale WR 61%, наш WR 40%) —
  расхождение само по себе не повод для exclude кита (кит может быть в
  порядке, проблема в execution/matching на нашей стороне) — заводить debug-
  задачу отдельно, не путать с решением по кита.

Критерии:
- **`paper → excluded` (`negative_pnl`)**: наша копи-симуляция (`our_pnl_sum`)
  отрицательна — это первичный сигнал (а не только whale-side PnL).
- **`paper → excluded` (`edge_degraded`)**: явный простой (проверить `MAX(traded_at)`
  из `whale_trades`, не полагаться на сохранённый `tier`/`last_active_at` —
  бывает устаревшим) при исторически сильных цифрах — не `negative_pnl`, кит
  не проигрывал, просто перестал торговать/изменил поведение.
- **`paper → live`**: критерии формально не определены (открытый вопрос §6
  `WHALE_STATUS_TRANSITIONS.md`) — это самое money-critical действие из всех.
  Не предлагать конкретный промоут без отдельного явного запроса
  оператора на определение критериев. Ориентир на разведку: смотреть именно
  `our_pnl_sum`/`our_wr_via_result_rate` (не whale-side) на статистически
  значимой выборке — киты с посредственной нашей WR (<50%) не кандидаты,
  даже если сам кит силён.

**Расчёт PnL уже промоутнутого `live`-кита** — нет отдельной PnL-таблицы для
live. Считать вручную из `live_orders` (`status='filled'`) + settlement из
`whale_trade_roundtrips` (join по `condition_id=market_id`, `outcome`):
`filled_size` в `live_orders` — это `1/цена_исполнения` (payout-мультипликатор
на $1), не количество акций (проверено эмпирически: значения 1.0-10.0,
1/filled_size даёт правдоподобные вероятности 0.1-0.9). PnL на исполненную
позицию: WIN → `size_usd × (filled_size − 1)`, LOSS → `−size_usd`. Отдельно
показывать: ещё открытые (не расчитаны), `status='failed'` (капитал не
потрачен, не считать как убыток, но % отказов — сигнал по надёжности
исполнения, возможно отдельная debug-задача).

---

## Tier refresh (применимо на любом этапе)

Формула из живого кода (`src/research/whale_detector.py:1156-1163`,
`_determine tier`): дней с последней сделки → `≤1 HOT`, `≤7 WARM`, `>7 COLD`.
Хранимый `whales.tier` может быть устаревшим (обновляется только для активно
поллящихся китов — `paper`/`tracked`/`HOT` контуром; для `none`-китов вне
discovery-цикла годами не трогается). Перед любым promotion-решением, где
tier важен — пересчитать вручную:
```sql
SELECT MAX(traded_at), ROUND(EXTRACT(EPOCH FROM (NOW()-MAX(traded_at)))/86400,1) AS days_since,
  CASE WHEN EXTRACT(EPOCH FROM (NOW()-MAX(traded_at)))/86400.0 <= 1 THEN 'HOT'
       WHEN EXTRACT(EPOCH FROM (NOW()-MAX(traded_at)))/86400.0 <= 7 THEN 'WARM'
       ELSE 'COLD' END AS computed_tier
FROM whale_trades WHERE wallet_address = '<addr>';
```
Если реальный tier выше сохранённого — обновить (`UPDATE whales SET tier=...`)
до/вместе с promotion. Обратное (реальный tier ниже) тоже возможно —
не скрывать, показать оператору.

---

## Технические ограничения (deny-правила, не обходить)

`DELETE FROM`/`TRUNCATE`/`ALTER TABLE`/`DROP` через `docker exec psql`
заблокированы на уровне `.claude/settings.json` **технически** — подтверждение
оператора в чате их не снимает (это не permission-prompt, а hard deny). Для
таких команд (очистка `leaderboard_candidate_trades` и т.п.) — дать оператору
готовую команду для самостоятельного запуска, после — сверить результат
самому (`SELECT` разрешён).

---

## Критические правила

1. Вывод оператору — таблицы и решения, не рассуждения.
2. Любой `UPDATE whales.copy_status` — только после «confirmed», выполняется
   этим чатом, не executor'ом.
3. Executor: команды напрямую, без `bash -c`/heredoc/`python3 -c`; отчёт —
   обязательно в `scratchpad/<task>_report.md`; таймаут с запасом (см. Этап 1).
4. Цикл отказов ТЗ — по CLAUDE.md (2 попытки → debugger → стоп, без исключений).
5. `estimated_capital` не обнуляется при downgrade (design decision 13.1
   `WHALE_STATUS_TRANSITIONS.md`), но пересчитывается заново перед КАЖДЫМ
   промоутом в paper (см. Этап 3).
6. Открытые paper-позиции при exclusion не закрываются автоматически —
   явно упомянуть оператору (design decision 13.2).
7. Секреты (DATABASE_URL, ключи) в вывод не попадают.
8. Уборка: временные scratchpad-файлы задачи удаляются в конце.
9. **Сам мониторинг не документируется** в TASK_BOARD/CHANGELOG (рутинная
   операционная активность, как и ежедневный фарм-мониторинг). **Но** новые
   баги/аномалии, найденные по ходу (расхождения PnL, execution failures и
   т.п.) — заводятся как отдельные backlog-задачи с TASK_ID в подходящий
   EPIC (TRD — trading correctness, LIVE — live execution, DATA — целостность
   данных) в момент обнаружения, не откладывать на «потом».

---

## Перед началом работы — прочитать

| Документ | Зачем |
|----------|-------|
| `docs/pipeline_map/PIPELINE_MAP_LEADERBOARD_SCORING.md` | Механика Этапа 1, RED FLAGs (RF2/RF3/RF5) |
| `docs/WHALE_STATUS_TRANSITIONS.md` | Governance-переходы, P&L Gate, SQL-шаблоны, open questions §5/§6 |
| `scripts/whale_audit.sql`, `scripts/whale_status.sql` | Готовые запросы Этапов 2-3 |
| Корневой `CLAUDE.md` | Общий протокол: хэндофф, money-adjacent гейты, цикл отказов |
