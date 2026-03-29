# -*- coding: utf-8 -*-
"""Diagnostic script for STRAT-701-DIAG - Paper trading pipeline diagnosis.

Diagnoses why paper-trade pipeline isn't generating trades by:
1. Querying Polymarket Data API for target whale addresses
2. Checking whale_trades table in DB
3. Verifying trigger logic (copy_status, whale_id FK)
4. Generating comparison report

Usage:
    python scripts/diagnose_pipeline.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from src.config.settings import settings
except ImportError:
    # Fallback if settings not available
    settings = None

logger = structlog.get_logger(__name__)

# Target whale addresses
TARGET_WHALES = [
    "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960",
    "0xa9e8faf20424f3efbf12abaea0e7069d7546c443",
    "0xd48a81db62f742c4e42d86dfc23a7ee345366e90",
]

# Polymarket Data API
DATA_API_BASE = "https://data-api.polymarket.com"

# Rate limiting delay (0.5s)
REQUEST_DELAY = 0.5

# Time window for analysis (7 days)
LOOKBACK_DAYS = 7


def get_database_url() -> str:
    """Get database URL from settings or environment."""
    if settings and hasattr(settings, "database_url"):
        return settings.database_url
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:password@localhost:5433/polymarket"
    )


def get_db_connection_params() -> Dict[str, Any]:
    """Parse DATABASE_URL into connection params."""
    db_url = get_database_url()
    
    # Handle postgresql://user:pass@host:port/db format
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "")
        parts = db_url.split("@")
        if len(parts) == 2:
            auth, rest = parts
            user_pass = auth.split(":")
            host_db = rest.split("/")
            if len(user_pass) == 2 and len(host_db) == 2:
                return {
                    "user": user_pass[0],
                    "password": user_pass[1],
                    "host": host_db[0].split(":")[0],
                    "port": int(host_db[0].split(":")[1]) if ":" in host_db[0] else 5432,
                    "database": host_db[1].split("?")[0],
                }
    
    # Fallback to defaults
    return {
        "user": "postgres",
        "password": "password",
        "host": "localhost",
        "port": 5433,
        "database": "polymarket",
    }


async def query_db(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """Execute a read-only SQL query and return results."""
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed, using psycopg2-binary")
        import psycopg2
    
    conn_params = get_db_connection_params()
    
    try:
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = True
        cursor = conn.cursor()
        
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        
        columns = [desc[0] for desc in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        
        cursor.close()
        conn.close()
        
        return results
    except Exception as e:
        logger.error("db_query_failed", sql=sql[:100], error=str(e))
        return []


async def fetch_api_trades(address: str, session: aiohttp.ClientSession) -> Dict[str, Any]:
    """Fetch trades from Polymarket Data API for a specific address."""
    url = f"{DATA_API_BASE}/trades"
    params = {
        "user": address.lower(),
        "limit": 50,
    }
    
    result = {
        "address": address,
        "trades_count": 0,
        "last_trade_ts": None,
        "last_trade_date": None,
        "recent_trades": [],
        "error": None,
    }
    
    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                result["error"] = f"API error: {response.status}"
                return result
            
            data = await response.json()
            
            if not isinstance(data, list):
                data = [data]
            
            # Filter to last 7 days
            cutoff_ts = int((datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
            
            trades_7d = []
            for item in data:
                ts = int(item.get("timestamp", 0))
                if ts >= cutoff_ts:
                    trades_7d.append({
                        "timestamp": ts,
                        "date": datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else None,
                        "market_id": item.get("conditionId", ""),
                        "side": item.get("side", ""),
                        "size_usd": float(Decimal(str(item.get("size", 0))) * Decimal(str(item.get("price", 0)))),
                        "price": float(Decimal(str(item.get("price", 0)))),
                    })
            
            result["trades_count"] = len(trades_7d)
            
            if trades_7d:
                # Sort by timestamp descending
                trades_7d.sort(key=lambda x: x["timestamp"], reverse=True)
                result["last_trade_ts"] = trades_7d[0]["timestamp"]
                result["last_trade_date"] = trades_7d[0]["date"]
                result["recent_trades"] = trades_7d[:3]  # Last 3 trades
            
            logger.info("api_trades_fetched", address=address[:10], count=result["trades_count"])
            
    except Exception as e:
        result["error"] = str(e)
        logger.error("api_fetch_failed", address=address[:10], error=str(e))
    
    return result


async def step1_query_polymarket_api() -> Dict[str, Any]:
    """Step 1: Query Polymarket Data API for target whales."""
    logger.info("STEP1_start", step="Query Polymarket Data API")
    
    results = {}
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for address in TARGET_WHALES:
            result = await fetch_api_trades(address, session)
            results[address] = result
            
            # Rate limiting
            await asyncio.sleep(REQUEST_DELAY)
    
    logger.info("STEP1_complete", whales_queried=len(results))
    return results


async def step2_query_whale_trades() -> Dict[str, Any]:
    """Step 2: Query whale_trades table in database."""
    logger.info("STEP2_start", step="Query whale_trades table")
    
    # Get count and last trade per whale
    # Build IN clause with proper quoting
    in_clause = ", ".join([f"'{addr}'" for addr in TARGET_WHALES])
    sql = f"""
        SELECT wallet_address, COUNT(*) as in_db, MAX(traded_at) as last_in_db
        FROM whale_trades 
        WHERE wallet_address IN ({in_clause})
        GROUP BY wallet_address;
    """
    
    results = await query_db(sql)
    
    # Format results by address
    by_address = {}
    for row in results:
        addr = row.get("wallet_address", "")
        by_address[addr] = {
            "in_db": row.get("in_db", 0),
            "last_in_db": row.get("last_in_db"),
        }
    
    # Also check whale_id FK status
    in_clause = ", ".join([f"'{addr}'" for addr in TARGET_WHALES])
    sql2 = f"""
        SELECT wallet_address, whale_id, COUNT(*) as trades
        FROM whale_trades 
        WHERE wallet_address IN ({in_clause})
        GROUP BY wallet_address, whale_id;
    """
    
    fk_results = await query_db(sql2)
    
    # Check for NULL whale_id (orphan trades)
    fk_by_address = {}
    for row in fk_results:
        addr = row.get("wallet_address", "")
        if addr not in fk_by_address:
            fk_by_address[addr] = {"with_fk": 0, "without_fk": 0}
        
        if row.get("whale_id") is None:
            fk_by_address[addr]["without_fk"] = row.get("trades", 0)
        else:
            fk_by_address[addr]["with_fk"] = row.get("trades", 0)
    
    logger.info("STEP2_complete", whales_found=len(by_address))
    
    return {
        "counts": by_address,
        "fk_status": fk_by_address,
    }


async def step3_check_trigger_logic() -> Dict[str, Any]:
    """Step 3: Check trigger logic (copy_status, paper_trades)."""
    logger.info("STEP3_start", step="Check trigger logic")
    
    # Check whales table for copy_status
    in_clause = ", ".join([f"'{addr}'" for addr in TARGET_WHALES])
    sql1 = f"""
        SELECT id, wallet_address, copy_status
        FROM whales 
        WHERE wallet_address IN ({in_clause});
    """
    
    whales_results = await query_db(sql1)
    whales_by_addr = {}
    for row in whales_results:
        whales_by_addr[row.get("wallet_address", "")] = {
            "id": row.get("id"),
            "copy_status": row.get("copy_status"),
        }
    
    # Check if whale trades appear in paper_trades
    in_clause = ", ".join([f"'{addr}'" for addr in TARGET_WHALES])
    sql2 = f"""
        SELECT whale_address, COUNT(*) as paper_trades, MAX(created_at) as last_paper
        FROM paper_trades
        WHERE whale_address IN ({in_clause})
        GROUP BY whale_address;
    """
    
    paper_results = await query_db(sql2)
    paper_by_addr = {}
    for row in paper_results:
        paper_by_addr[row.get("whale_address", "")] = {
            "paper_trades": row.get("paper_trades", 0),
            "last_paper": row.get("last_paper"),
        }
    
    logger.info("STEP3_complete", whales_in_table=len(whales_by_addr), paper_trades=len(paper_by_addr))
    
    return {
        "whales_table": whales_by_addr,
        "paper_trades": paper_by_addr,
    }


def generate_diagnosis(
    api_results: Dict[str, Any],
    whale_trades_results: Dict[str, Any],
    trigger_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate final diagnosis based on all collected data."""
    
    diagnosis = {
        "diagnosis_timestamp": datetime.utcnow().isoformat(),
        "whales_analyzed": [],
        "diagnosis": "UNKNOWN",
        "details": {
            "a_no_api_activity": [],
            "b_ingestion_gap": [],
            "c_trigger_issue": [],
        },
    }
    
    table_rows = []
    
    for address in TARGET_WHALES:
        # API data
        api = api_results.get(address, {})
        api_count = api.get("trades_count", 0)
        api_last = api.get("last_trade_date", "Never")
        api_error = api.get("error")
        
        # DB whale_trades data
        wt_counts = whale_trades_results.get("counts", {})
        wt_data = wt_counts.get(address, {"in_db": 0, "last_in_db": None})
        wt_count = wt_data.get("in_db", 0)
        wt_last = wt_data.get("last_in_db")
        if wt_last:
            wt_last = wt_last.strftime("%Y-%m-%d") if hasattr(wt_last, "strftime") else str(wt_last)
        else:
            wt_last = "Never"
        
        # FK status
        fk_status = whale_trades_results.get("fk_status", {}).get(address, {})
        orphan_count = fk_status.get("without_fk", 0)
        
        # Whales table status
        whales_table = trigger_results.get("whales_table", {}).get(address, {})
        whale_id = whales_table.get("id")
        copy_status = whales_table.get("copy_status", "unknown")
        
        # Paper trades
        paper = trigger_results.get("paper_trades", {}).get(address, {})
        paper_count = paper.get("paper_trades", 0)
        paper_last = paper.get("last_paper")
        if paper_last:
            paper_last = paper_last.strftime("%Y-%m-%d") if hasattr(paper_last, "strftime") else str(paper_last)
        else:
            paper_last = "None"
        
        # Diagnose
        whale_info = {
            "address": address,
            "short_address": address[:10] + "...",
            "api_trades_7d": api_count,
            "last_in_api": api_last,
            "api_error": api_error,
            "db_whale_trades": wt_count,
            "last_in_db": wt_last,
            "orphan_trades": orphan_count,
            "whale_id": whale_id,
            "copy_status": copy_status,
            "paper_trades": paper_count,
            "last_paper_trade": paper_last,
        }
        
        # Determine diagnosis category
        if api_count == 0 or api_error:
            # A) No activity in Polymarket API
            whale_info["diagnosis"] = "A"
            whale_info["diagnosis_label"] = "No activity in Polymarket API"
            diagnosis["details"]["a_no_api_activity"].append(address)
        elif wt_count == 0:
            # B) Trading but not in whale_trades
            whale_info["diagnosis"] = "B"
            whale_info["diagnosis_label"] = "Ingestion gap (TRD-413)"
            diagnosis["details"]["b_ingestion_gap"].append(address)
        else:
            # C) In whale_trades but not in paper_trades
            if paper_count == 0:
                if copy_status != "paper":
                    whale_info["diagnosis"] = "C1"
                    whale_info["diagnosis_label"] = f"copy_status='{copy_status}' not 'paper'"
                elif whale_id is None:
                    whale_info["diagnosis"] = "C2"
                    whale_info["diagnosis_label"] = "whale_id is NULL (orphan trades)"
                else:
                    whale_info["diagnosis"] = "C3"
                    whale_info["diagnosis_label"] = "Unknown trigger issue"
                diagnosis["details"]["c_trigger_issue"].append(address)
            else:
                # Has paper trades - might be working or delayed
                whale_info["diagnosis"] = "OK"
                whale_info["diagnosis_label"] = "Pipeline working"
        
        diagnosis["whales_analyzed"].append(whale_info)
        
        # Build table row
        table_rows.append([
            address[:10] + "...",
            api_count,
            api_last,
            wt_count,
            wt_last,
            paper_count,
            paper_last,
            whale_info.get("diagnosis", "?"),
        ])
    
    # Determine overall diagnosis
    if diagnosis["details"]["a_no_api_activity"]:
        diagnosis["diagnosis"] = "A"
    elif diagnosis["details"]["b_ingestion_gap"]:
        diagnosis["diagnosis"] = "B"
    elif diagnosis["details"]["c_trigger_issue"]:
        diagnosis["diagnosis"] = "C"
    else:
        diagnosis["diagnosis"] = "OK"
    
    return diagnosis, table_rows


def print_comparison_table(rows: List[List[Any]]) -> None:
    """Print formatted comparison table."""
    header = ["Whale", "API Trades", "Last in API", "DB whale_trades", "Last in DB", "Paper Trades", "Last Paper", "Diag"]
    
    # Calculate column widths
    widths = [15, 12, 18, 15, 12, 14, 12, 6]
    
    # Print header
    print("\n" + "+" + "+".join("-" * (w + 2) for w in widths) + "+")
    print("|" + "|".join(f" {h:<{w}} " for h, w in zip(header, widths)) + "|")
    print("+" + "+".join("-" * (w + 2) for w in widths) + "+")
    
    # Print rows
    for row in rows:
        formatted = []
        for val, width in zip(row, widths):
            s = str(val)
            formatted.append(f" {s:<{width}} ")
        print("|" + "|".join(formatted) + "|")
    
    print("+" + "+".join("-" * (w + 2) for w in widths) + "+")


def print_diagnosis_report(diagnosis: Dict[str, Any]) -> None:
    """Print diagnosis report."""
    print("\n" + "=" * 80)
    print("DIAGNOSIS REPORT (STRAT-701-DIAG)")
    print("=" * 80)
    
    print(f"\nDiagnosis: {diagnosis['diagnosis']}")
    
    if diagnosis["diagnosis"] == "A":
        print("\nA) NO ACTIVITY IN POLYMARKET API")
        print("   These whales have no trades in the last 7 days according to the API.")
        for addr in diagnosis["details"]["a_no_api_activity"]:
            print(f"   - {addr}")
    
    elif diagnosis["diagnosis"] == "B":
        print("\nB) INGESTION GAP (TRD-413)")
        print("   These whales have API activity but are NOT in the whale_trades table.")
        print("   Possible causes:")
        print("   - Whale discovery/ingestion not finding these addresses")
        print("   - Time window mismatch between API and DB queries")
        print("   - Ingestion worker errors")
        for addr in diagnosis["details"]["b_ingestion_gap"]:
            print(f"   - {addr}")
    
    elif diagnosis["diagnosis"] == "C":
        print("\nC) TRIGGER LOGIC ISSUE")
        print("   These whales ARE in whale_trades but NOT generating paper_trades.")
        print("   Possible causes:")
        print("   - whales.copy_status != 'paper'")
        print("   - whale_trades.whale_id IS NULL (orphan trades)")
        print("   - Trigger SQL not matching conditions")
        for whale in diagnosis["whales_analyzed"]:
            if whale.get("diagnosis", "").startswith("C"):
                print(f"\n   {whale['address'][:20]}...")
                print(f"   - whales.copy_status: {whale['copy_status']}")
                print(f"   - whale_id: {whale['whale_id']}")
                print(f"   - diagnosis: {whale.get('diagnosis_label', 'unknown')}")
    
    elif diagnosis["diagnosis"] == "OK":
        print("\n✓ PIPELINE APPEARS TO BE WORKING")
        print("   All analyzed whales have consistent data across API, DB, and paper_trades.")
    
    print("\n" + "-" * 80)
    print("DETAILED WHALE ANALYSIS:")
    print("-" * 80)
    
    for whale in diagnosis["whales_analyzed"]:
        print(f"\n  {whale['address']}")
        print(f"    API (7d): {whale['api_trades_7d']} trades, last: {whale['last_in_api']}")
        print(f"    whale_trades DB: {whale['db_whale_trades']} trades, last: {whale['last_in_db']}")
        print(f"    whale_id FK: {whale['whale_id']}, copy_status: {whale['copy_status']}")
        print(f"    paper_trades: {whale['paper_trades']} trades, last: {whale['last_paper_trade']}")
        print(f"    Status: {whale.get('diagnosis', '?')} - {whale.get('diagnosis_label', '')}")
    
    print("\n" + "=" * 80)


async def main():
    """Main diagnostic workflow."""
    logger.info("diagnostic_script_started", whales=len(TARGET_WHALES))
    
    print("\n" + "=" * 80)
    print("POLYMARKET BOT - PIPELINE DIAGNOSTIC SCRIPT")
    print("STRAT-701-DIAG: Why paper-trade pipeline isn't generating trades")
    print("=" * 80)
    print(f"\nAnalyzing {len(TARGET_WHALES)} target whales:")
    for addr in TARGET_WHALES:
        print(f"  - {addr}")
    print(f"\nTime window: Last {LOOKBACK_DAYS} days")
    
    # Step 1: Query Polymarket Data API
    print("\n" + "-" * 40)
    print("STEP 1: Query Polymarket Data API")
    print("-" * 40)
    api_results = await step1_query_polymarket_api()
    
    for addr, result in api_results.items():
        print(f"\n  {addr[:20]}...")
        print(f"    Trades (7d): {result['trades_count']}")
        print(f"    Last trade: {result['last_trade_date'] or 'Never'}")
        if result.get("error"):
            print(f"    ERROR: {result['error']}")
        if result.get("recent_trades"):
            print("    Recent trades:")
            for t in result["recent_trades"]:
                print(f"      - {t['date']} | {t['side']} | ${t['size_usd']:.2f} @ {t['price']}")
    
    # Step 2: Query whale_trades table
    print("\n" + "-" * 40)
    print("STEP 2: Query whale_trades table")
    print("-" * 40)
    whale_trades_results = await step2_query_whale_trades()
    
    print("\n  Whale trades in DB:")
    for addr, data in whale_trades_results.get("counts", {}).items():
        print(f"    {addr[:20]}...: {data['in_db']} trades, last: {data['last_in_db']}")
    
    print("\n  FK status (whale_id):")
    for addr, data in whale_trades_results.get("fk_status", {}).items():
        print(f"    {addr[:20]}...: with FK={data['with_fk']}, without FK={data['without_fk']}")
    
    # Step 3: Check trigger logic
    print("\n" + "-" * 40)
    print("STEP 3: Check trigger logic")
    print("-" * 40)
    trigger_results = await step3_check_trigger_logic()
    
    print("\n  whales table copy_status:")
    for addr, data in trigger_results.get("whales_table", {}).items():
        print(f"    {addr[:20]}...: id={data['id']}, copy_status={data['copy_status']}")
    
    print("\n  paper_trades:")
    for addr, data in trigger_results.get("paper_trades", {}).items():
        print(f"    {addr[:20]}...: {data['paper_trades']} trades, last: {data['last_paper']}")
    
    # Step 4: Generate comparison report
    print("\n" + "-" * 40)
    print("STEP 4: Generate Comparison Report")
    print("-" * 40)
    
    diagnosis, table_rows = generate_diagnosis(
        api_results, whale_trades_results, trigger_results
    )
    
    # Print comparison table
    print_comparison_table(table_rows)
    
    # Print diagnosis report
    print_diagnosis_report(diagnosis)
    
    # Save to JSON
    output_file = os.path.join(os.path.dirname(__file__), "pipeline_diagnosis.json")
    with open(output_file, "w") as f:
        json.dump(diagnosis, f, indent=2, default=str)
    
    print(f"\n✓ Diagnosis saved to: {output_file}")
    
    logger.info("diagnostic_script_completed", diagnosis=diagnosis["diagnosis"])
    
    return diagnosis


if __name__ == "__main__":
    asyncio.run(main())