# executor/

Live order execution daemon for Polymarket CLOB V2.

## Deployment
- Runtime: Server 2 (62.60.233.100), `/opt/executor/app/`
- Service: `systemd live-executor.service`
- Secrets: `/opt/executor/secrets/` (NOT in git, chmod 600)
- Accounts: `/opt/executor/app/accounts/*.env` (NOT in git, chmod 600)

## Files
- `live_executor_daemon.py` — main daemon (pull-model, polls live_orders on S1 DB)
- `executor.py` — diag/dry-run tool (Account 1)
- `executor_account2.py` — diag/dry-run tool (Account 2)
- `restart_executor.sh` — restart + verify helper
- `POLYMARKET_V2_CONNECTION.md` — V2 connection notes
- `account2_diag.py` — Account 2 diagnostics
- `account2_setup.py` — Account 2 setup

## Governance
- Daemon code changes: edit `/opt/executor/app/live_executor_daemon.py` on S2,
  then `cp` to `/root/polymarket-bot/executor/` and commit from S2.
- Secrets stay in `/opt/executor/secrets/` and `/opt/executor/app/accounts/*.env` — never in git.
