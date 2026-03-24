# FILES CLEANUP CANDIDATES

**Generated:** 2026-03-23 16:55 UTC  
**Task:** SYS-501 - Project Filesystem Cleanup

---

## SUMMARY

| Metric | Value |
|--------|-------|
| total_files_found | 33 |
| total_size | ~2.6 MB |
| oldest_file_date | 2026-02-21 (docs/research/*, docs/changelogs/*) |
| cleanup_scope | logs, backups, docs (archive, audits, old guides) |

---

## 🚨 CRITICAL FINDING

**logs/bot.log** — **1.87 GB** (Mar 23, today)

> This is the main log file, currently **1.87 GB**. It is NOT older than 3 days (today's file), so it is NOT a cleanup candidate. However, this log should be rotated or truncated in production to prevent disk space exhaustion.

---

## FILES TO DELETE (APPROVAL REQUIRED)

### Category: LOGS

| path | size | last_modified | reason |
|------|------|---------------|--------|
| logs/error.log | 2.2 MB | 2026-03-17 18:47 | Old error logs (>3 days) |

### Category: BACKUPS (Special Handling)

| path | size | last_modified | note |
|------|------|---------------|------|
| backups/qualified_whales_2026-03-19.csv | 4 KB | 2026-03-20 15:01 | **Requires separate approval** - whale data backup |

> Per task rules: "НЕ удалять автоматически: backups/whales_backup_*" — this qualifies as qualified whales backup.

### Category: DOCS - ARCHIVE

| path | size | last_modified |
|------|------|---------------|
| docs/_archive/ | 176 KB | Feb 28, 2026 |
| docs/_archive/PROJECT_SUMMARY v1.md | 7.8 KB | Feb 21 |
| docs/_archive/RESEARCH_AGENT_CONTEXT.md | 6 KB | Feb 21 |
| docs/_archive/RESEARCH_INTEGRATION.md | 7.7 KB | Feb 21 |
| docs/_archive/contexts/ | ~20 KB | Feb 28 |
| docs/_archive/root_artifacts/ | ~10 KB | Feb 28 |

### Category: DOCS - AUDITS (Temporary Reports)

| path | size | last_modified |
|------|------|---------------|
| docs/data_capability_audit.md | 8 KB | 2026-02-28 |
| docs/duplicate_suppression_fix.md | 4 KB | (old) |
| docs/paper_execution_gap_audit.md | 4 KB | 2026-03-10 |
| docs/paper_position_settlement_engine.md | 8 KB | (old) |
| docs/paper_settlement_real_market_verification.md | 8 KB | (old) |
| docs/paper_settlement_runtime_integration.md | 8 KB | (old) |
| docs/paper_trade_close_lifecycle_audit.md | 8 KB | 2026-03-12 |
| docs/paper_trade_trigger_audit.md | 4 KB | 2026-03-09 |
| docs/trades_lifecycle_audit.md | 12 KB | 2026-03-09 |
| docs/whale_audit_report.md | 12 KB | 2026-03-09 |
| docs/WHALeS_SNAPSHOT_PRE_CLEANUP.md | 4 KB | (old) |

### Category: DOCS - RESEARCH (Old Guides)

| path | size | last_modified |
|------|------|---------------|
| docs/research/known_whales.md | 3 KB | 2026-02-21 |
| docs/research/polymarket_api_guide.md | 4 KB | 2026-02-21 |
| docs/research/whale_detection_guide.md | 9 KB | 2026-02-21 |

### Category: DOCS - CHANGELOGS (Old History)

| path | size | last_modified |
|------|------|---------------|
| docs/changelogs/architecture.md | 0.5 KB | 2026-02-21 |
| docs/changelogs/CHANGELOG_GUIDE.md | 7 KB | 2026-02-21 |
| docs/changelogs/devops.md | 7.5 KB | 2026-02-28 |
| docs/changelogs/README.md | 5 KB | 2026-02-21 |
| docs/changelogs/risk.md | 0.6 KB | 2026-02-21 |

> Note: Recent changelogs (development.md, MASTER_CHANGELOG.md, research.md, testing.md) are from Mar 2 — kept.

### Category: DOCS - OTHER

| path | size | last_modified |
|------|------|---------------|
| docs/api_rotation_validation.md | 4 KB | (old) |
| docs/CHAT GOVERNANCE.md | 8 KB | (old) |
| docs/CI_CD_SETUP.md | 4 KB | (old) |
| docs/CODE_CHANGES_FOR_OPEN_CLOSE_PRICE.md | 4 KB | (old) |
| docs/polymarket_market_resolution_research.md | 12 KB | (old) |
| docs/QDRANT_AUDIT_20260313.md | 4 KB | 2026-03-13 |
| docs/QDRANT_LOCALHOST_HARDENING.md | 4 KB | (old) |
| docs/SECURITY_AUDIT_20260313.md | 8 KB | 2026-03-13 |
| docs/SECURITY_BASELINE.md | 8 KB | (old) |
| docs/SSH_TUNNEL.md | 4 KB | (old) |
| docs/STRATEGIC PARALLEL LANES PLAN.md | 12 KB | (old) |

---

## EXCLUDED (NOT TOUCH)

These files are explicitly excluded per task rules:

- ✅ docs/PROJECT_STATE.md
- ✅ docs/TASK_BOARD.md
- ✅ docs/TASK_BOARD.html
- ✅ docs/data_checks/ (recent daily checks)
- ✅ docs/bot_development_kit/ (active documentation)
- ✅ docs/changelogs/development.md (recent)
- ✅ docs/changelogs/MASTER_CHANGELOG.md (recent)
- ✅ docs/changelogs/research.md (recent)
- ✅ docs/changelogs/testing.md (recent)
- ✅ backups/whales_pre_arc501_20260322_190604.sql (recent backup)
- ✅ logs/bot.log (today's log, 1.87 GB - needs rotation, not deletion)
- ✅ logs/data_check.log (today)

---

## PROPOSED ACTIONS

### 1. DELETE (after approval):
- logs/error.log
- docs/_archive/ (entire directory)
- docs/research/ (all 3 files)
- docs/changelogs/ (5 old files)
- docs/*_audit.md (all audit reports)
- docs/QDRANT_*.md (2 files)
- docs/SECURITY_*.md (2 files)
- docs/api_rotation_validation.md
- docs/CHAT GOVERNANCE.md
- docs/CI_CD_SETUP.md
- docs/CODE_CHANGES_FOR_OPEN_CLOSE_PRICE.md
- docs/polymarket_market_resolution_research.md
- docs/SSH_TUNNEL.md
- docs/STRATEGIC PARALLEL LANES PLAN.md
- docs/duplicate_suppression_fix.md
- docs/WHALeS_SNAPSHOT_PRE_CLEANUP.md

### 2. SEPARATE APPROVAL NEEDED:
- backups/qualified_whales_2026-03-19.csv — whale data backup

### 3. RECOMMEND (not in task scope):
- **Log rotation for bot.log** — 1.87 GB is too large for production
- Consider: `logrotate` configuration or daily truncation

---

## SPACE ESTIMATE

| Category | Size |
|----------|------|
| Logs to delete | 2.2 MB |
| Docs archive/audits/old | ~500 KB |
| **Total** | **~2.7 MB** |

> The massive **1.87 GB bot.log** is NOT included in cleanup (not >3 days old), but needs attention separately.

---

**Waiting for your approval to proceed with deletion.**