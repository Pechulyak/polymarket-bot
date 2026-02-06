# Performance Data - Benchmarks & Metrics

*Consolidated from 9 Level 2 repository analyses*

---

## Executive Summary

| Metric | Copy Trading | Arbitrage | Best Source |
|--------|-------------|-----------|-------------|
| Detection Latency | 50-200ms | 50-100ms | hodlwarden |
| Execution Speed | 200-500ms | 60-100ms | hodlwarden |
| Daily Opportunities | 5-20 | 1-5 | crypmancer |
| Win Rate | 60-70% | 80-90% | realfishsam |
| Avg Profit/Trade | $0.10-0.40 | $2-10 | consolidated |
| Gas per Trade | $0.005-0.02 | $0.005-0.02 | Polygon baseline |

---

## Latency Benchmarks

### End-to-End Latency by Mode

| Component | REST API | Raw TX | WebSocket |
|-----------|----------|--------|-----------|
| Price Discovery | 100-500ms | 50-100ms | 5-50ms |
| Order Building | 10-50ms | 20-50ms | N/A |
| Signing | 5-20ms | 5-20ms | N/A |
| Network | 50-200ms | 50-200ms | 20-50ms |
| Confirmation | 2000-5000ms | 2000-5000ms | N/A |
| **Total** | **2165-5770ms** | **2125-5370ms** | **25-100ms** |

### WebSocket vs REST Comparison

```
┌────────────────────────────────────────────────────────────┐
│                    LATENCY COMPARISON                      │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  REST Polling (3s interval):                               │
│  ████████████████████████████████████████  3000ms          │
│                                                            │
│  REST Polling (1s interval):                               │
│  █████████████  1000ms                                     │
│                                                            │
│  WebSocket (real-time):                                    │
│  █  50ms                                                   │
│                                                            │
│  Improvement: 20-60x faster                                │
└────────────────────────────────────────────────────────────┘
```

### Execution Speed by Method

| Method | Latency | Use Case | Source |
|--------|---------|----------|--------|
| REST API (GTC order) | 200-500ms | Copy trading | realfishsam |
| REST API (FOK order) | 150-400ms | Arbitrage | CarlosIbCu |
| Raw TX (medium priority) | 60-150ms | Fast execution | hodlwarden |
| Raw TX (high priority) | 40-80ms | MEV competition | hodlwarden |
| Rust Native | 1-10ms | HFT (overkill) | 0xRustElite1111 |

---

## Latency Breakdown by Component

### Detection Pipeline

```
Component               Best Case    Typical      Worst Case
─────────────────────────────────────────────────────────────
WebSocket receive       5ms          20ms         100ms
JSON parsing            0.1ms        2ms          10ms
Strategy calculation    0.05ms       1ms          5ms
Risk check              0.1ms        1ms          5ms
─────────────────────────────────────────────────────────────
Detection Total         5.25ms       24ms         120ms
```

### Execution Pipeline

```
Component               Best Case    Typical      Worst Case
─────────────────────────────────────────────────────────────
Order construction      5ms          20ms         50ms
Transaction signing     0.5ms        5ms          20ms
RPC submission          20ms         50ms         200ms
─────────────────────────────────────────────────────────────
Execution Total         25.5ms       75ms         270ms

Block confirmation      2000ms       2500ms       5000ms
─────────────────────────────────────────────────────────────
Full Cycle              2025.5ms     2575ms       5270ms
```

---

## Success Rate Data

### Copy Trading Success Rates

| Metric | Conservative | Average | Optimistic | Source |
|--------|--------------|---------|------------|--------|
| Trade Execution Rate | 95% | 98% | 99% | hodlwarden |
| Fill Rate (full) | 80% | 90% | 95% | crypmancer |
| Whale Signal Quality | 50% | 60% | 70% | crypmancer |
| **Net Win Rate** | **55%** | **62%** | **70%** | calculated |

### Arbitrage Success Rates

| Metric | Conservative | Average | Optimistic | Source |
|--------|--------------|---------|------------|--------|
| Opportunity Detection | 90% | 95% | 99% | realfishsam |
| Both Legs Execute | 75% | 85% | 95% | realfishsam |
| Profitable After Fees | 80% | 90% | 95% | calculated |
| **Net Win Rate** | **70%** | **85%** | **90%** | calculated |

---

## Profitability Data

### Expected Returns by Strategy

#### Copy Trading ($70 Capital)

| Scenario | Daily Trades | Win Rate | Avg Profit | Daily Return | Monthly |
|----------|--------------|----------|------------|--------------|---------|
| Pessimistic | 2-3 | 55% | $0.10 | $0.15 | $4.50 |
| Expected | 5-8 | 62% | $0.25 | $0.80 | $24.00 |
| Optimistic | 10-15 | 70% | $0.40 | $2.50 | $75.00 |

#### Arbitrage ($25 Capital)

| Scenario | Daily Opps | Success Rate | Avg Profit | Daily Return | Monthly |
|----------|------------|--------------|------------|--------------|---------|
| Pessimistic | 0-1 | 70% | $1.50 | $0.30 | $9.00 |
| Expected | 1-3 | 85% | $3.00 | $1.20 | $36.00 |
| Optimistic | 3-5 | 90% | $5.00 | $5.00 | $150.00 |

### Combined Returns ($100 Capital)

| Scenario | Copy ($70) | Arb ($25) | Total Monthly | Monthly ROI |
|----------|------------|-----------|---------------|-------------|
| Pessimistic | $4.50 | $9.00 | $13.50 | 13.5% |
| Expected | $24.00 | $36.00 | $60.00 | 60% |
| Optimistic | $75.00 | $150.00 | $225.00 | 225% |

---

## Gas Cost Analysis

### Polygon Gas Costs (Current)

| Metric | Low | Medium | High | Spike |
|--------|-----|--------|------|-------|
| Gas Price (gwei) | 30 | 50 | 100 | 500+ |
| Typical TX (200k gas) | $0.003 | $0.005 | $0.01 | $0.05+ |
| Daily (10 trades) | $0.03 | $0.05 | $0.10 | $0.50 |
| Monthly (300 trades) | $0.90 | $1.50 | $3.00 | $15.00 |

### Gas Impact on Profitability

```
Trade Size vs Gas Impact (at $0.01/trade gas):
─────────────────────────────────────────────
$5 trade   → Gas = 0.20% of trade
$10 trade  → Gas = 0.10% of trade
$20 trade  → Gas = 0.05% of trade
$50 trade  → Gas = 0.02% of trade

Minimum profitable trade (5% spread, 2% fees):
Net margin = 5% - 2% - gas = 3% - gas
At $0.01 gas: Min trade = $0.33 for break-even
Recommended min: $5 (gas = 0.20%)
```

---

## Opportunity Frequency

### Copy Trading Signals

| Market Condition | Signals/Day | Quality | Best Hours (UTC) |
|------------------|-------------|---------|------------------|
| Quiet market | 2-5 | Medium | Random |
| Normal activity | 5-15 | Good | 13:00-21:00 |
| Major news | 15-50+ | Variable | Event-driven |
| Election day | 100+ | High volume | 00:00-24:00 |

### Arbitrage Windows

| Platform Pair | Avg Opps/Day | Avg Spread | Duration |
|---------------|--------------|------------|----------|
| Poly + Manifold | 2-8 | 4-8% | 30s-5min |
| Poly + Kalshi | 1-3 | 5-10% | 1-10min |
| Bundle (deprecated) | 0-1 | <3% | N/A |

### Opportunity by Time of Day (UTC)

```
Hour  | Copy Signals | Arb Opps | Notes
──────┼──────────────┼──────────┼─────────────────────
00-04 |     ██       |    █     | Low activity
04-08 |     ███      |    ██    | Europe wake
08-12 |     ████     |    ███   | EU active
12-16 |     █████    |    ████  | US+EU overlap (BEST)
16-20 |     ████     |    ███   | US afternoon
20-24 |     ███      |    ██    | US evening
```

---

## Historical Performance (from Analyses)

### Repository Reported Metrics

| Repository | Period | Trades | Win Rate | Total PnL | Notes |
|------------|--------|--------|----------|-----------|-------|
| crypmancer | 30 days | 150 | 62% | +$45 | $100 capital |
| hodlwarden | 14 days | 80 | 68% | +$35 | $100 capital |
| realfishsam | 7 days | 25 | 88% | +$18 | Poly+Manifold |

*Note: Self-reported, not independently verified*

### Backtesting Results (apemoonspin)

```
Bundle Arbitrage Backtest (Pre-fee era):
────────────────────────────────────────
Period: 2023-06-01 to 2023-12-01
Opportunities detected: 1,247
Profitable (>1% spread): 423 (34%)
Avg spread: 2.8%
Estimated PnL: +$890 (on $1000 capital)

Post-fee Analysis (3.15% fee):
────────────────────────────────────────
Profitable (>4.5% spread): 47 (3.8%)
Estimated PnL: -$120 (after fees)
CONCLUSION: Bundle arbitrage no longer viable
```

---

## System Requirements

### Minimum Hardware

| Component | Minimum | Recommended | High Performance |
|-----------|---------|-------------|------------------|
| CPU | 1 core | 2 cores | 4 cores |
| RAM | 512MB | 1GB | 2GB |
| Storage | 1GB | 5GB | 10GB |
| Network | 10Mbps | 50Mbps | 100Mbps |
| Latency to Polygon | <200ms | <100ms | <50ms |

### VPS Recommendations

| Provider | Plan | Cost | Latency* | Notes |
|----------|------|------|----------|-------|
| DigitalOcean | Basic $6 | $6/mo | 80-120ms | Good starter |
| Hetzner | CX11 | $4/mo | 60-100ms | Best value EU |
| Vultr | Cloud $5 | $5/mo | 70-110ms | Good US options |
| AWS | t3.micro | $8/mo | 50-80ms | Best latency |

*Latency to Polygon RPC from US East

### RPC Performance

| Provider | Free Tier | Paid | Latency | Mempool |
|----------|-----------|------|---------|---------|
| Alchemy | 300M CU/mo | $49/mo | 50-80ms | Yes |
| Infura | 100k req/day | $50/mo | 60-100ms | No |
| QuickNode | 10M req/mo | $9/mo | 40-70ms | Yes |
| Public RPC | Unlimited | Free | 100-300ms | No |

---

## Benchmarking Your Setup

### Test Script

```python
"""
Performance benchmark script
Run this to test your setup's performance
"""

import asyncio
import time
import statistics
from polymarket_client import PolymarketClient

async def benchmark_latency(client, iterations=20):
    """Benchmark API latency"""
    latencies = []

    for i in range(iterations):
        start = time.time()
        await client.get_markets(active_only=True)
        latency = (time.time() - start) * 1000
        latencies.append(latency)
        print(f"  Request {i+1}: {latency:.1f}ms")

    return {
        "min": min(latencies),
        "max": max(latencies),
        "avg": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0
    }

async def main():
    client = PolymarketClient(
        private_key="YOUR_KEY",
        rpc_url="YOUR_RPC"
    )

    print("Running latency benchmark...")
    results = await benchmark_latency(client)

    print(f"\nResults:")
    print(f"  Min: {results['min']:.1f}ms")
    print(f"  Max: {results['max']:.1f}ms")
    print(f"  Avg: {results['avg']:.1f}ms")
    print(f"  Median: {results['median']:.1f}ms")

    # Performance rating
    if results['avg'] < 100:
        print("\n✅ EXCELLENT - Ready for arbitrage")
    elif results['avg'] < 200:
        print("\n✅ GOOD - Ready for copy trading")
    elif results['avg'] < 500:
        print("\n⚠️ ACCEPTABLE - Consider better RPC")
    else:
        print("\n❌ POOR - Upgrade RPC required")

if __name__ == "__main__":
    asyncio.run(main())
```

### Expected Results

| Rating | Avg Latency | Suitable For |
|--------|-------------|--------------|
| Excellent | <100ms | All strategies |
| Good | 100-200ms | Copy trading |
| Acceptable | 200-500ms | Paper trading only |
| Poor | >500ms | Not recommended |

---

## Performance Optimization Tips

### Quick Wins

1. **Use WebSocket over REST** - 20-60x improvement
2. **Use regional RPC** - 20-50ms improvement
3. **Pre-compute signatures** - 10-20ms improvement
4. **Connection pooling** - 5-15ms improvement

### Advanced Optimizations

1. **Raw TX signing** - 5-10x faster than REST API
2. **Mempool monitoring** - 1-2 block advantage
3. **Priority gas fees** - Better confirmation times
4. **Local state caching** - Reduce API calls

---

*Last updated: 2026-02-03*
*Data sources: 9 Level 2 repository analyses*
