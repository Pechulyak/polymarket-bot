#!/bin/bash
# Restart live-executor daemon and verify

set -e

echo "=== Restarting live-executor ==="
systemctl restart live-executor

echo ""
echo "=== systemctl is-active live-executor ==="
systemctl is-active live-executor

echo ""
echo "=== ps -ef | grep live_executor ==="
ps -ef | grep -v grep | grep live_executor || echo "(no process found)"

echo ""
echo "=== tail -20 /opt/executor/logs/live_executor.log ==="
tail -20 /opt/executor/logs/live_executor.log
