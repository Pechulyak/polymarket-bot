#!/usr/bin/env python3
"""
Daily Data Audit Snapshot Script

Performs daily audit of key database tables:
- whales, whale_trades, paper_trades, paper_trade_notifications, trades, bankroll

Collects:
- row counts
- activity in last 24h / 48h
- table freshness
- quality indicators
- cross-table consistency checks

Output: docs/data_checks/latest.md and docs/data_checks/data_check_YYYY-MM-DD.md
Old snapshots (>2 days) are automatically deleted.

Uses: docker exec to run psql commands
"""

import os
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "data_checks"
SNAPSHOT_RETENTION_DAYS = 2
CONTAINER_NAME = "polymarket_postgres"


def run_sql(query):
    """Execute SQL query via docker exec."""
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "psql", "-U", "postgres", "-d", "polymarket",
        "-t", "-A", "-F", "|"
    ]
    cmd.append("-c")
    cmd.append(query)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"SQL Error: {result.stderr}")
        return None
    return result.stdout.strip()


def get_whales_audit():
    """Audit whales table."""
    query = """
SELECT row_count, unique_addresses, default_risk_score, null_qualification_path, 
       first_row_timestamp, last_row_timestamp, rows_last_24h, rows_last_48h, 
       active_24h, active_48h
FROM (
    SELECT 
        COUNT(*) as row_count,
        COUNT(DISTINCT wallet_address) as unique_addresses,
        COUNT(*) FILTER (WHERE risk_score = 5) as default_risk_score,
        COUNT(*) FILTER (WHERE qualification_path IS NULL) as null_qualification_path,
        MIN(created_at)::text as first_row_timestamp,
        MAX(created_at)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as rows_last_24h,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '48 hours') as rows_last_48h,
        COUNT(*) FILTER (WHERE is_active = true AND last_active_at > NOW() - INTERVAL '24 hours') as active_24h,
        COUNT(*) FILTER (WHERE is_active = true AND last_active_at > NOW() - INTERVAL '48 hours') as active_48h
    FROM whales
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 10:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'unique_addresses': int(parts[1].strip()) if parts[1].strip() else 0,
            'default_risk_score': int(parts[2].strip()) if parts[2].strip() else 0,
            'null_qualification_path': int(parts[3].strip()) if parts[3].strip() else 0,
            'first_row_timestamp': parts[4].strip(),
            'last_row_timestamp': parts[5].strip(),
            'rows_last_24h': int(parts[6].strip()) if parts[6].strip() else 0,
            'rows_last_48h': int(parts[7].strip()) if parts[7].strip() else 0,
            'active_24h': int(parts[8].strip()) if parts[8].strip() else 0,
            'active_48h': int(parts[9].strip()) if parts[9].strip() else 0,
        }
    return {}


def get_whale_trades_audit():
    """Audit whale_trades table."""
    query = """
SELECT row_count, unique_whales, first_row_timestamp, last_row_timestamp, 
       rows_last_24h, rows_last_48h, unique_whales_24h, null_price, null_size
FROM (
    SELECT 
        COUNT(*) as row_count,
        COUNT(DISTINCT whale_id) as unique_whales,
        MIN(traded_at)::text as first_row_timestamp,
        MAX(traded_at)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE traded_at > NOW() - INTERVAL '24 hours') as rows_last_24h,
        COUNT(*) FILTER (WHERE traded_at > NOW() - INTERVAL '48 hours') as rows_last_48h,
        COUNT(DISTINCT whale_id) FILTER (WHERE traded_at > NOW() - INTERVAL '24 hours') as unique_whales_24h,
        COUNT(*) FILTER (WHERE price IS NULL) as null_price,
        COUNT(*) FILTER (WHERE size_usd IS NULL) as null_size
    FROM whale_trades
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 9:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'unique_whales': int(parts[1].strip()) if parts[1].strip() else 0,
            'first_row_timestamp': parts[2].strip(),
            'last_row_timestamp': parts[3].strip(),
            'rows_last_24h': int(parts[4].strip()) if parts[4].strip() else 0,
            'rows_last_48h': int(parts[5].strip()) if parts[5].strip() else 0,
            'unique_whales_24h': int(parts[6].strip()) if parts[6].strip() else 0,
            'null_price': int(parts[7].strip()) if parts[7].strip() else 0,
            'null_size': int(parts[8].strip()) if parts[8].strip() else 0,
        }
    return {}


def get_paper_trades_audit():
    """Audit paper_trades table."""
    query = """
SELECT row_count, unique_whales, first_row_timestamp, last_row_timestamp,
       rows_last_24h, rows_last_48h, unique_whales_24h, null_market_title,
       null_price, null_size, distinct_kelly_size, min_kelly_size, max_kelly_size, avg_kelly_size
FROM (
    SELECT 
        COUNT(*) as row_count,
        COUNT(DISTINCT whale_address) as unique_whales,
        MIN(created_at)::text as first_row_timestamp,
        MAX(created_at)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as rows_last_24h,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '48 hours') as rows_last_48h,
        COUNT(DISTINCT whale_address) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as unique_whales_24h,
        COUNT(*) FILTER (WHERE market_title IS NULL) as null_market_title,
        COUNT(*) FILTER (WHERE price IS NULL) as null_price,
        COUNT(*) FILTER (WHERE size IS NULL) as null_size,
        COUNT(DISTINCT kelly_size) as distinct_kelly_size,
        MIN(kelly_size) as min_kelly_size,
        MAX(kelly_size) as max_kelly_size,
        AVG(kelly_size)::numeric(20,2) as avg_kelly_size
    FROM paper_trades
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 14:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'unique_whales': int(parts[1].strip()) if parts[1].strip() else 0,
            'first_row_timestamp': parts[2].strip(),
            'last_row_timestamp': parts[3].strip(),
            'rows_last_24h': int(parts[4].strip()) if parts[4].strip() else 0,
            'rows_last_48h': int(parts[5].strip()) if parts[5].strip() else 0,
            'unique_whales_24h': int(parts[6].strip()) if parts[6].strip() else 0,
            'null_market_title': int(parts[7].strip()) if parts[7].strip() else 0,
            'null_price': int(parts[8].strip()) if parts[8].strip() else 0,
            'null_size': int(parts[9].strip()) if parts[9].strip() else 0,
            'distinct_kelly_size': int(parts[10].strip()) if parts[10].strip() else 0,
            'min_kelly_size': parts[11].strip(),
            'max_kelly_size': parts[12].strip(),
            'avg_kelly_size': parts[13].strip(),
        }
    return {}


def get_paper_notifications_audit():
    """Audit paper_trade_notifications table."""
    query = """
SELECT row_count, first_row_timestamp, last_row_timestamp,
       rows_last_24h, rows_last_48h, null_market_title, latest_notification_timestamp
FROM (
    SELECT 
        COUNT(*) as row_count,
        MIN(created_at)::text as first_row_timestamp,
        MAX(created_at)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as rows_last_24h,
        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '48 hours') as rows_last_48h,
        COUNT(*) FILTER (WHERE market_title IS NULL) as null_market_title,
        MAX(created_at)::text as latest_notification_timestamp
    FROM paper_trade_notifications
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 7:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'first_row_timestamp': parts[1].strip(),
            'last_row_timestamp': parts[2].strip(),
            'rows_last_24h': int(parts[3].strip()) if parts[3].strip() else 0,
            'rows_last_48h': int(parts[4].strip()) if parts[4].strip() else 0,
            'null_market_title': int(parts[5].strip()) if parts[5].strip() else 0,
            'latest_notification_timestamp': parts[6].strip(),
        }
    return {}


def get_trades_audit():
    """Audit trades table."""
    query = """
SELECT row_count, first_row_timestamp, last_row_timestamp, virtual_rows, open_trades, closed_trades
FROM (
    SELECT 
        COUNT(*) as row_count,
        MIN(executed_at)::text as first_row_timestamp,
        MAX(executed_at)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE exchange = 'VIRTUAL') as virtual_rows,
        COUNT(*) FILTER (WHERE status = 'open') as open_trades,
        COUNT(*) FILTER (WHERE status = 'closed') as closed_trades
    FROM trades
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 6:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'first_row_timestamp': parts[1].strip(),
            'last_row_timestamp': parts[2].strip(),
            'virtual_rows': int(parts[3].strip()) if parts[3].strip() else 0,
            'open_trades': int(parts[4].strip()) if parts[4].strip() else 0,
            'closed_trades': int(parts[5].strip()) if parts[5].strip() else 0,
        }
    return {}


def get_bankroll_audit():
    """Audit bankroll table."""
    query = """
SELECT row_count, first_row_timestamp, last_row_timestamp, rows_last_24h, rows_last_48h, earliest_timestamp, latest_timestamp
FROM (
    SELECT 
        COUNT(*) as row_count,
        MIN(timestamp)::text as first_row_timestamp,
        MAX(timestamp)::text as last_row_timestamp,
        COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '24 hours') as rows_last_24h,
        COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '48 hours') as rows_last_48h,
        MIN(timestamp)::text as earliest_timestamp,
        MAX(timestamp)::text as latest_timestamp
    FROM bankroll
) t
"""
    output = run_sql(query)
    if not output:
        return {}
    parts = output.split("|")
    if len(parts) >= 7:
        return {
            'row_count': int(parts[0].strip()) if parts[0].strip() else 0,
            'first_row_timestamp': parts[1].strip(),
            'last_row_timestamp': parts[2].strip(),
            'rows_last_24h': int(parts[3].strip()) if parts[3].strip() else 0,
            'rows_last_48h': int(parts[4].strip()) if parts[4].strip() else 0,
            'earliest_timestamp': parts[5].strip(),
            'latest_timestamp': parts[6].strip(),
        }
    return {}


def get_cross_table_metrics():
    """Get cross-table consistency metrics."""
    metrics = {}
    
    # whale_trades -> paper_trades conversion (48h)
    q1 = "SELECT COUNT(*) as cnt FROM whale_trades WHERE traded_at > NOW() - INTERVAL '48 hours'"
    whale_48h = run_sql(q1)
    q2 = "SELECT COUNT(*) as cnt FROM paper_trades WHERE created_at > NOW() - INTERVAL '48 hours'"
    paper_48h = run_sql(q2)
    
    try:
        w48 = int(whale_48h.strip()) if whale_48h and whale_48h.strip() else 0
        p48 = int(paper_48h.strip()) if paper_48h and paper_48h.strip() else 0
        metrics['whale_trades_48h'] = w48
        metrics['paper_trades_48h'] = p48
        if w48 > 0:
            metrics['whale_to_paper_conversion_ratio_48h'] = round(p48 / w48 * 100, 2)
        else:
            metrics['whale_to_paper_conversion_ratio_48h'] = 0
    except:
        metrics['whale_to_paper_conversion_ratio_48h'] = 0
    
    # paper_trades -> notifications coverage (48h)
    q3 = "SELECT COUNT(*) as cnt FROM paper_trade_notifications WHERE created_at > NOW() - INTERVAL '48 hours'"
    notif_48h = run_sql(q3)
    try:
        n48 = int(notif_48h.strip()) if notif_48h and notif_48h.strip() else 0
        if p48 > 0:
            metrics['notification_coverage_48h'] = round(n48 / p48 * 100, 2)
        else:
            metrics['notification_coverage_48h'] = 0
    except:
        metrics['notification_coverage_48h'] = 0
    
    # Stale tables
    tables_ts = [
        ('whales', 'created_at'),
        ('whale_trades', 'traded_at'),
        ('paper_trades', 'created_at'),
        ('paper_trade_notifications', 'created_at'),
        ('trades', 'executed_at'),
        ('bankroll', 'timestamp'),
    ]
    
    stale_24h = []
    stale_48h = []
    
    for table, col in tables_ts:
        q = f"SELECT MAX({col})::text as latest FROM {table}"
        result = run_sql(q)
        if result and result.strip() and result.strip() != '':
            try:
                latest = result.strip()
                # Parse timestamp
                dt = datetime.strptime(latest[:19], "%Y-%m-%d %H:%M:%S")
                if datetime.now() - dt > timedelta(hours=24):
                    stale_24h.append(table)
                if datetime.now() - dt > timedelta(hours=48):
                    stale_48h.append(table)
            except:
                stale_24h.append(table)
                stale_48h.append(table)
        else:
            stale_24h.append(table)
            stale_48h.append(table)
    
    metrics['stale_tables_24h'] = stale_24h
    metrics['stale_tables_48h'] = stale_48h
    
    return metrics


def format_timestamp(ts):
    """Format timestamp for display."""
    if not ts or ts == '' or ts == 'None':
        return "N/A"
    return ts[:19] if len(ts) > 19 else ts


def generate_markdown_report(audit_results, cross_table_metrics):
    """Generate markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md = f"""# Daily Data Audit Snapshot

**Generated:** {now}

---

## Table Overview

| Table | Row Count | Rows 24h | Rows 48h | First Row | Last Row |
|-------|-----------|----------|----------|-----------|----------|
"""
    
    table_map = [
        ('whales', 'whales'),
        ('whale_trades', 'whale_trades'),
        ('paper_trades', 'paper_trades'),
        ('paper_trade_notifications', 'paper_trade_notifications'),
        ('trades', 'trades'),
        ('bankroll', 'bankroll'),
    ]
    
    for display_name, data_key in table_map:
        data = audit_results.get(data_key, {})
        md += f"| {display_name} | {data.get('row_count', 0)} | {data.get('rows_last_24h', 'N/A')} | {data.get('rows_last_48h', 'N/A')} | {format_timestamp(data.get('first_row_timestamp', ''))} | {format_timestamp(data.get('last_row_timestamp', ''))} |\n"
    
    md += """
---

## Quality Checks

### whales
"""
    w = audit_results.get('whales', {})
    md += f"""
- Unique addresses: {w.get('unique_addresses', 0)}
- Default risk_score (5): {w.get('default_risk_score', 0)}
- NULL qualification_path: {w.get('null_qualification_path', 0)}
- Active whales (24h): {w.get('active_24h', 0)}
- Active whales (48h): {w.get('active_48h', 0)}
"""
    
    md += """
### whale_trades
"""
    wt = audit_results.get('whale_trades', {})
    md += f"""
- Unique whales: {wt.get('unique_whales', 0)}
- Unique whales (24h): {wt.get('unique_whales_24h', 0)}
- NULL price: {wt.get('null_price', 0)}
- NULL size: {wt.get('null_size', 0)}
- Latest trade: {format_timestamp(wt.get('last_row_timestamp', ''))}
"""
    
    md += """
### paper_trades
"""
    pt = audit_results.get('paper_trades', {})
    md += f"""
- Unique whales: {pt.get('unique_whales', 0)}
- Unique whales (24h): {pt.get('unique_whales_24h', 0)}
- NULL market_title: {pt.get('null_market_title', 0)}
- NULL price: {pt.get('null_price', 0)}
- NULL size: {pt.get('null_size', 0)}
- Distinct kelly_size: {pt.get('distinct_kelly_size', 0)}
- Min/Max/Avg kelly_size: {pt.get('min_kelly_size', 'N/A')} / {pt.get('max_kelly_size', 'N/A')} / {pt.get('avg_kelly_size', 'N/A')}
"""
    
    md += """
### paper_trade_notifications
"""
    ptn = audit_results.get('paper_trade_notifications', {})
    md += f"""
- NULL market_title: {ptn.get('null_market_title', 0)}
- Latest notification: {format_timestamp(ptn.get('latest_notification_timestamp', ''))}
"""
    
    md += """
### trades
"""
    t = audit_results.get('trades', {})
    md += f"""
- VIRTUAL rows: {t.get('virtual_rows', 0)}
- Open trades: {t.get('open_trades', 0)}
- Closed trades: {t.get('closed_trades', 0)}
"""
    
    md += """
### bankroll
"""
    b = audit_results.get('bankroll', {})
    md += f"""
- Rows 24h: {b.get('rows_last_24h', 0)}
- Rows 48h: {b.get('rows_last_48h', 0)}
- Earliest: {format_timestamp(b.get('earliest_timestamp', ''))}
- Latest: {format_timestamp(b.get('latest_timestamp', ''))}
"""
    
    md += f"""
---

## Cross-Table Consistency

- whale_trades → paper_trades conversion (48h): {cross_table_metrics.get('whale_to_paper_conversion_ratio_48h', 'N/A')}%
- paper_trades → notifications coverage (48h): {cross_table_metrics.get('notification_coverage_48h', 'N/A')}%
- Stale tables (>24h no new rows): {', '.join(cross_table_metrics.get('stale_tables_24h', [])) or 'None'}
- Stale tables (>48h no new rows): {', '.join(cross_table_metrics.get('stale_tables_48h', [])) or 'None'}

---

*This report is automatically generated by scripts/run_data_check.py*
"""
    
    return md


def cleanup_old_snapshots():
    """Delete snapshots older than SNAPSHOT_RETENTION_DAYS."""
    if not OUTPUT_DIR.exists():
        return []
    
    cutoff = datetime.now() - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    deleted = []
    
    for file in OUTPUT_DIR.glob("data_check_*.md"):
        if file.stem == "latest":
            continue
        try:
            date_str = file.stem.replace("data_check_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                file.unlink()
                deleted.append(file.name)
        except (ValueError, OSError):
            pass
    
    return deleted


def update_project_state(audit_results, cross_table_metrics):
    """Update PROJECT_STATE.md with daily snapshot."""
    PROJECT_STATE_PATH = Path(__file__).parent.parent / "docs" / "PROJECT_STATE.md"
    if not PROJECT_STATE_PATH.exists():
        print("PROJECT_STATE.md not found, skipping update")
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Generate snapshot content
    snapshot = f"""
### {today}

snapshot_date: {today}
database: polymarket
schema: public

whales_rows: {audit_results.get('whales', {}).get('row_count', 0)}
whale_trades_rows: {audit_results.get('whale_trades', {}).get('row_count', 0)}
paper_trades_rows: {audit_results.get('paper_trades', {}).get('row_count', 0)}
paper_trade_notifications_rows: {audit_results.get('paper_trade_notifications', {}).get('row_count', 0)}
trades_rows: {audit_results.get('trades', {}).get('row_count', 0)}
bankroll_rows: {audit_results.get('bankroll', {}).get('row_count', 0)}

whale_trades_last_24h: {audit_results.get('whale_trades', {}).get('rows_last_24h', 0)}
paper_trades_last_24h: {audit_results.get('paper_trades', {}).get('rows_last_24h', 0)}
notifications_last_24h: {audit_results.get('paper_trade_notifications', {}).get('rows_last_24h', 0)}

conversion_whale_to_paper_48h: {cross_table_metrics.get('whale_to_paper_conversion_ratio_48h', 0)}%
conversion_paper_to_notifications_48h: {cross_table_metrics.get('notification_coverage_48h', 0)}%

stale_tables_24h:
{chr(10).join(f"- {t}" for t in cross_table_metrics.get('stale_tables_24h', []))}

notes:
- bankroll contains only test data
- trades table contains only virtual test trades
"""
    
    # Read current PROJECT_STATE.md
    content = PROJECT_STATE_PATH.read_text()
    
    # Find the DAILY DATA SNAPSHOT section (may have section number prefix like "## 9.")
    marker_start = "DAILY DATA SNAPSHOT"
    marker_end = "<!-- END AUTO-GENERATED -->"
    
    if marker_start in content and marker_end in content:
        # Extract existing snapshots (use find to get FIRST end marker)
        start_idx = content.find(marker_start)
        end_idx = content.find(marker_end) + len(marker_end)
        
        # Get everything before and after the auto-generated section
        before = content[:start_idx]
        after = content[end_idx:]
        
        # Extract existing snapshots (between markers)
        current_section = content[start_idx:end_idx]
        
        # Parse existing dates
        existing_snapshots = []
        lines = current_section.split('\n')
        current_date = None
        current_lines = []
        
        for line in lines:
            if line.startswith('### '):
                if current_date:
                    existing_snapshots.append((current_date, '\n'.join(current_lines)))
                current_date = line.replace('### ', '').strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        
        if current_date:
            existing_snapshots.append((current_date, '\n'.join(current_lines)))
        
        # Add new snapshot (replace if same date already exists)
        existing_snapshots = [(d, c) for d, c in existing_snapshots if d != today]
        existing_snapshots.append((today, snapshot.strip()))
        
        # Keep only last 3 days
        existing_snapshots = existing_snapshots[-3:]
        
        # Rebuild section
        new_section = f"""{marker_start}

<!-- AUTO-GENERATED: This section is updated by scripts/run_data_check.py -->
"""
        for date, snap_content in existing_snapshots:
            new_section += snap_content + "\n\n"
        
        new_section += f"""<!-- END AUTO-GENERATED -->"""
        
        # Reconstruct file
        new_content = before + new_section + after
        PROJECT_STATE_PATH.write_text(new_content)
        print(f"Updated: {PROJECT_STATE_PATH}")
    else:
        print("DAILY DATA SNAPSHOT section not found in PROJECT_STATE.md")


def main():
    """Main execution."""
    print("Starting daily data audit...")
    
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Run audits
    print("Collecting audit data...")
    audit_results = {
        'whales': get_whales_audit(),
        'whale_trades': get_whale_trades_audit(),
        'paper_trades': get_paper_trades_audit(),
        'paper_trade_notifications': get_paper_notifications_audit(),
        'trades': get_trades_audit(),
        'bankroll': get_bankroll_audit(),
    }
    
    cross_table_metrics = get_cross_table_metrics()
    
    # Generate report
    report = generate_markdown_report(audit_results, cross_table_metrics)
    
    # Write latest report
    latest_path = OUTPUT_DIR / "latest.md"
    latest_path.write_text(report)
    print(f"Written: {latest_path}")
    
    # Write dated snapshot
    today = datetime.now().strftime("%Y-%m-%d")
    snapshot_path = OUTPUT_DIR / f"data_check_{today}.md"
    snapshot_path.write_text(report)
    print(f"Written: {snapshot_path}")
    
    # Cleanup old snapshots
    deleted = cleanup_old_snapshots()
    if deleted:
        print(f"Deleted old snapshots: {deleted}")
    else:
        print("No old snapshots to delete")
    
    # Update PROJECT_STATE.md
    update_project_state(audit_results, cross_table_metrics)
    
    print("Data audit complete.")


if __name__ == "__main__":
    main()
