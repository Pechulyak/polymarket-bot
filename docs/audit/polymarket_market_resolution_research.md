# Polymarket Market Resolution Research

Date: 2026-03-12

## Context
This research supports the paper settlement engine in the Polymarket bot project. The project is in paper phase; live is disabled until edge is proven. The settlement engine needs a reliable way to determine whether a market is resolved, what the winning outcome is, and what settlement price to apply.

## Executive Summary

**Recommended source of truth for settlement detection:** **Gamma API** (`GET /markets/{id}` or `GET /markets?condition_id=...` depending on local identifiers) for application-level polling, with the **Market WebSocket `market_resolved` event** as an optional low-latency trigger.

**Ultimate protocol-level truth:** the onchain resolution / payout vector recorded in the CTF after UMA reports payouts. The docs describe this as the oracle reporting the outcome via `reportPayouts()` and the CTF recording the payout vector.

**Not recommended as primary settlement source:** Builder/CLOB APIs. They are built for order routing, orderbooks, and trading rather than canonical market resolution metadata.

**Settlement logic for binary markets:**
- Use Gamma market metadata to detect terminal state.
- Read `outcomes` and `outcomePrices` together.
- On a resolved binary market, the winning outcome should correspond to settlement at **1.0** and the losing outcome to **0.0**.
- For YES/NO markets:
  - `outcomePrices = ["1", "0"]` or equivalent => YES wins
  - `outcomePrices = ["0", "1"]` or equivalent => NO wins

## Architecture of Resolution on Polymarket

Polymarket documentation describes resolution as a process where the market’s end condition is met, the UMA Adapter reports payouts via `reportPayouts()`, and the Conditional Token Framework (CTF) records the payout vector. After that, winning tokens redeem for $1 and losing tokens redeem for $0.

This means there are two layers:
1. **Onchain truth**: UMA + CTF payout vector
2. **Application/API layer**: Gamma API market metadata indexing that resolution state

For a trading bot settlement engine, Gamma is the practical API to poll; onchain/subgraph is the fallback verification path.

## Where Settlement Is Determined

### Source of truth hierarchy
1. **Onchain payout vector / CTF state** — ultimate truth
2. **Gamma API market metadata** — best practical source for bot settlement
3. **Market WebSocket `market_resolved` event** — optional trigger for fast detection
4. **Subgraph / Goldsky** — useful for analytics or verification, but not the simplest primary integration
5. **Builder / CLOB API** — not the right primary source for resolution

## Gamma API Analysis

Gamma is the market metadata API. Official docs show:
- `GET /markets`
- `GET /markets/{id}`
- `GET /markets/slug/{slug}`

The market schema includes fields directly relevant to settlement workflows:
- `closed`
- `closedTime`
- `resolvedBy`
- `umaResolutionStatus`
- `outcomes`
- `outcomePrices`
- `conditionId`
- `questionID`
- `endDate`, `umaEndDate`
- `acceptingOrders`

### Practical meaning of the fields
- **`endDate`**: when the event is scheduled to end / become eligible for resolution. This is **not** enough for settlement.
- **`closed`**: market is closed in Gamma metadata. This is the first important terminal-state signal.
- **`umaResolutionStatus`**: indicates the UMA-side resolution state; this is the strongest resolution-specific field exposed in Gamma schema.
- **`resolvedBy`**: indicates a resolver/resolution actor reference if present.
- **`outcomePrices`**: maps 1:1 to `outcomes`; after resolution, this is the most useful application-layer field for deriving the winning outcome.
- **`acceptingOrders`**: trading availability flag; useful, but not sufficient as a settlement trigger by itself.

### Recommended Gamma polling rule
Use `GET /markets/{id}` as the primary check when you already have the market id stored locally.

Treat a market as **resolved/settleable** only when:
- `closed == true`, **and**
- `umaResolutionStatus` indicates a final resolved state, **and**
- `outcomePrices` is present and reflects a terminal payout shape for the binary market

In practice, for binary markets, the settlement engine should wait until `outcomePrices` collapses to a 1/0 payout pattern before closing the paper position.

## Builder API / CLOB API Analysis

Polymarket’s trading docs describe the CLOB / Builder stack as the order-routing and trading interface: signed orders, order management, orderbooks, prices, and trade execution.

This makes it the wrong primary source for settlement because:
- it is focused on **trading mechanics**, not canonical market resolution metadata
- docs do not present Builder/CLOB endpoints as the place to fetch final market outcomes
- market discovery and metadata live under **Gamma**, not Builder/CLOB

### Recommendation
Do **not** use Builder/CLOB as the source of truth for market resolution.
Use it only for trading/orderbook logic.

## Subgraph Analysis

Polymarket docs describe subgraphs as indexed onchain data exposed through GraphQL and hosted by Goldsky. Available subgraphs cover positions, orders, activity, open interest, and PnL.

The docs also point to broader blockchain data resources (Goldsky, Dune, Allium) for onchain trades, balances, positions, and redeems.

### What this means for settlement
Subgraph/onchain data is excellent when you need:
- verification of final onchain state
- analytics pipelines
- redundancy if Gamma is unavailable

But for a settlement engine inside a bot, subgraph is usually:
- more complex to integrate
- less direct than polling `GET /markets/{id}`
- better as a fallback / audit layer than as first choice

## How to Determine That a Market Is Closed

### Correct trigger
The correct settlement trigger is **not `endDate`**.

A market can pass `endDate` and still not be resolved. The docs describe resolution as a later process involving the oracle and payout reporting.

### Recommended trigger order
1. Market exists in Gamma
2. `closed == true`
3. `umaResolutionStatus` is final / resolved
4. `outcomePrices` reflects terminal payout
5. Settle paper trade

## How to Get Final Outcome

### Binary market logic
Docs state that outcome arrays map 1:1 with price arrays. They also state that after resolution the payout vector is:
- YES wins => `[1, 0]`
- NO wins => `[0, 1]`

Therefore, for Gamma market responses:
- parse `outcomes`
- parse `outcomePrices`
- align by array index
- whichever outcome has settlement price `1` is the winner

### Example interpretation
- `outcomes = ["Yes","No"]`
- `outcomePrices = ["1","0"]` => YES resolved winner
- `outcomePrices = ["0","1"]` => NO resolved winner

## How to Get Settlement Price

For paper settlement, use **terminal `outcomePrices`** from Gamma after resolution.

### Binary paper PnL rule
- winning side settlement price = **1.0**
- losing side settlement price = **0.0**

This matches Polymarket’s CTF redemption mechanics, where winning tokens redeem for $1 and losing tokens for $0.

### Important nuance
Before resolution, `outcomePrices` are just market-implied probabilities. After resolution, the same field becomes useful as a terminal payout proxy because the market settles into 1/0.

## Can Resolution Be Queried by `market_id`?

Yes. Official docs provide:
- `GET /markets/{id}`

That is the cleanest endpoint when your bot stores Gamma market ids.

If your local system stores `conditionId` or token ids instead of Gamma market id, you may need an initial lookup/mapping step using Gamma market discovery fields such as `conditionId` and `clobTokenIds`.

## Fields That Indicate Closed / Resolved State

Most relevant fields exposed by Gamma docs:
- `closed`
- `closedTime`
- `umaResolutionStatus`
- `resolvedBy`
- `outcomePrices`
- `outcomes`
- `endDate`
- `umaEndDate`
- `acceptingOrders`

### How to interpret them
- `endDate`: scheduled event end only
- `closed`: closed in market metadata
- `umaResolutionStatus`: resolution workflow state
- `outcomePrices`: terminal payout proxy after full resolution
- `acceptingOrders`: trading flag, not definitive settlement truth

## Webhooks / Events / Streams

The docs do **not** describe webhooks for market resolution.

They **do** describe a **Market WebSocket** with a `market_resolved` event, available when subscribing with `custom_feature_enabled: true`.

### Recommendation for streaming
Use websocket only as a **trigger**:
- on `market_resolved`, enqueue market for immediate Gamma re-check
- then confirm via `GET /markets/{id}` before settling

This avoids settling based only on a stream event.

## Recommended Method for Settlement Engine

### Best application design

#### Primary path
1. Query open paper positions from `trades` where `exchange='VIRTUAL'` and `status='open'`
2. For each unique market, call **Gamma `GET /markets/{id}`**
3. Check:
   - `closed == true`
   - final `umaResolutionStatus`
   - terminal `outcomePrices`
4. Derive winning outcome from `outcomes` + `outcomePrices`
5. Apply settlement price:
   - YES winner => YES positions close at 1.0, NO at 0.0
   - NO winner => NO positions close at 1.0, YES at 0.0
6. Update trade PnL and mark trade `closed`

#### Optional fast path
- Subscribe to Market WebSocket with `custom_feature_enabled: true`
- On `market_resolved`, trigger immediate Gamma refresh for that market

#### Fallback / audit path
- If Gamma data is inconsistent or delayed, verify against onchain/subgraph payout state

## Recommended Final Decision

### Use this as the main source of truth
**Gamma API market endpoint** (`GET /markets/{id}`)

### Use these fields
- `closed`
- `umaResolutionStatus`
- `outcomes`
- `outcomePrices`
- optionally `closedTime`, `resolvedBy`, `acceptingOrders`

### Do not use as sole trigger
- `endDate`
- `acceptingOrders`

### Do not use as primary settlement source
- Builder API / CLOB API

## Example API Shape to Implement Against

From official `GET /markets/{id}` docs, relevant response shape includes:

```json
{
  "id": "<string>",
  "conditionId": "<string>",
  "question": "<string>",
  "endDate": "2023-11-07T05:31:56Z",
  "outcomes": "<string>",
  "outcomePrices": "<string>",
  "closed": true,
  "closedTime": "<string>",
  "resolvedBy": "<string>",
  "umaEndDate": "<string>",
  "umaResolutionStatus": "<string>",
  "acceptingOrders": true,
  "clobTokenIds": "<string>"
}
```

### Settlement interpretation example

```json
{
  "outcomes": "[\"Yes\",\"No\"]",
  "outcomePrices": "[\"1\",\"0\"]",
  "closed": true,
  "umaResolutionStatus": "<final resolved state>"
}
```

Interpretation:
- market is resolved
- YES is the winner
- YES settlement price = 1.0
- NO settlement price = 0.0

## Bottom Line

For this bot, the cleanest and most reliable implementation is:
- **Gamma REST** for polling and final confirmation
- **Market WebSocket `market_resolved`** for fast notification
- **Onchain/subgraph** only as fallback or audit verification

That is the least ugly version of reality, which is about the nicest thing APIs ever allow.
