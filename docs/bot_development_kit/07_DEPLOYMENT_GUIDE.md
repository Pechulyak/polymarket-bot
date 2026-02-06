# Deployment Guide - Production Setup

*Step-by-step guide for deploying the Polymarket hybrid bot*

---

## Deployment Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT PATH                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. LOCAL DEVELOPMENT                                       │
│     └── Paper trading, testing                              │
│              │                                              │
│              ▼                                              │
│  2. LOCAL LIVE (Small Capital)                              │
│     └── $10-20 real trading, validation                     │
│              │                                              │
│              ▼                                              │
│  3. VPS DEPLOYMENT                                          │
│     └── 24/7 operation, full capital                        │
│              │                                              │
│              ▼                                              │
│  4. PRODUCTION HARDENING                                    │
│     └── Monitoring, backups, scaling                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Local Development

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | 3.11+ |
| RAM | 512MB | 2GB |
| Storage | 1GB | 5GB |
| Network | Stable | Low latency |

### Setup Steps

```bash
# 1. Clone your bot repository
git clone https://github.com/your-username/polymarket-bot.git
cd polymarket-bot

# 2. Create virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create environment file
cp .env.example .env
```

### Configure .env

```bash
# .env - NEVER COMMIT THIS FILE

# Wallet (use a fresh wallet for testing!)
PRIVATE_KEY=0x...your_private_key...

# RPC Endpoints
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
POLYGON_WSS_URL=wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# Telegram Alerts
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Trading Config
PAPER_TRADING=true
COPY_CAPITAL=70
ARB_CAPITAL=25

# Whale Addresses (comma separated)
WHALE_ADDRESSES=0x123...,0x456...,0x789...
```

### Run Paper Trading

```bash
# Start in paper trading mode
python main.py --mode=paper

# Or with explicit flag
PAPER_TRADING=true python main.py
```

### Validate Setup

```bash
# Run tests
python -m pytest tests/ -v

# Check connectivity
python scripts/check_connectivity.py

# Verify wallet balance
python scripts/check_balance.py
```

---

## Phase 2: Local Live Trading

### Pre-Flight Checklist

- [ ] Paper trading ran 48+ hours without errors
- [ ] Kill switch tested and working
- [ ] Telegram alerts configured
- [ ] Wallet funded ($10-20 for testing)
- [ ] Whale addresses verified active
- [ ] Gas reserve adequate ($2-5 MATIC)

### Reduce Capital for Testing

```bash
# .env for initial live testing
PAPER_TRADING=false
COPY_CAPITAL=10      # Reduced from $70
ARB_CAPITAL=5        # Reduced from $25
MAX_POSITION=5       # Small positions
```

### Monitor First Trades

```bash
# Run with verbose logging
python main.py --verbose

# Watch logs
tail -f logs/bot.log

# Monitor positions
python scripts/show_positions.py
```

### Validate Performance

Run for 24-48 hours with small capital before scaling up:

```python
# Expected metrics after 24h testing
min_trades = 3
max_losses_in_row = 2
expected_win_rate = 0.5  # At least break-even

# If metrics not met, investigate before scaling
```

---

## Phase 3: VPS Deployment

### VPS Selection

| Provider | Plan | Cost | Region | Latency* |
|----------|------|------|--------|----------|
| **Hetzner** | CX11 | $4/mo | Germany | 70-100ms |
| **DigitalOcean** | Basic | $6/mo | NYC/AMS | 60-90ms |
| **Vultr** | Cloud | $5/mo | Various | 50-80ms |
| **Linode** | Nanode | $5/mo | Various | 60-90ms |

*Latency to Polygon RPC

### Server Setup (Ubuntu 22.04)

```bash
# 1. Connect to VPS
ssh root@your_server_ip

# 2. Create non-root user
adduser botuser
usermod -aG sudo botuser
su - botuser

# 3. Update system
sudo apt update && sudo apt upgrade -y

# 4. Install dependencies
sudo apt install -y python3.11 python3.11-venv python3-pip git

# 5. Install Redis (optional, for state)
sudo apt install -y redis-server
sudo systemctl enable redis-server

# 6. Setup firewall
sudo ufw allow ssh
sudo ufw enable
```

### Deploy Bot

```bash
# 1. Clone repository
cd ~
git clone https://github.com/your-username/polymarket-bot.git
cd polymarket-bot

# 2. Setup environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Create .env (secure method)
nano .env
# Paste your configuration
# Ctrl+X to save

# 4. Secure .env file
chmod 600 .env

# 5. Test run
python main.py --mode=paper
```

### Systemd Service

Create service file:

```bash
sudo nano /etc/systemd/system/polymarket-bot.service
```

Content:

```ini
[Unit]
Description=Polymarket Trading Bot
After=network.target redis.service

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/polymarket-bot
Environment=PATH=/home/botuser/polymarket-bot/venv/bin
ExecStart=/home/botuser/polymarket-bot/venv/bin/python main.py
Restart=always
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true

# Logging
StandardOutput=append:/home/botuser/polymarket-bot/logs/bot.log
StandardError=append:/home/botuser/polymarket-bot/logs/error.log

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start
sudo systemctl enable polymarket-bot

# Start the service
sudo systemctl start polymarket-bot

# Check status
sudo systemctl status polymarket-bot

# View logs
journalctl -u polymarket-bot -f
```

### Service Management

```bash
# Stop bot
sudo systemctl stop polymarket-bot

# Restart bot
sudo systemctl restart polymarket-bot

# View recent logs
sudo journalctl -u polymarket-bot -n 100

# Follow logs
sudo journalctl -u polymarket-bot -f
```

---

## Phase 4: Production Hardening

### Log Rotation

```bash
sudo nano /etc/logrotate.d/polymarket-bot
```

Content:

```
/home/botuser/polymarket-bot/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 644 botuser botuser
}
```

### Automatic Updates

Create update script:

```bash
nano ~/polymarket-bot/scripts/update.sh
```

Content:

```bash
#!/bin/bash
cd /home/botuser/polymarket-bot

# Stop service
sudo systemctl stop polymarket-bot

# Backup current version
cp -r . ../polymarket-bot-backup-$(date +%Y%m%d)

# Pull latest
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart service
sudo systemctl start polymarket-bot

echo "Update complete"
```

### Health Monitoring

Create health check script:

```bash
nano ~/polymarket-bot/scripts/health_check.sh
```

Content:

```bash
#!/bin/bash

# Check if service is running
if ! systemctl is-active --quiet polymarket-bot; then
    echo "Bot service not running!"

    # Send alert
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=🚨 Bot service is DOWN!"

    # Attempt restart
    sudo systemctl restart polymarket-bot
fi

# Check memory usage
MEM_USAGE=$(free | grep Mem | awk '{print ($3/$2) * 100}')
if (( $(echo "$MEM_USAGE > 90" | bc -l) )); then
    echo "High memory usage: $MEM_USAGE%"
    # Alert
fi

# Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "Low disk space: $DISK_USAGE%"
    # Alert
fi
```

Add to crontab:

```bash
crontab -e

# Add line:
*/5 * * * * /home/botuser/polymarket-bot/scripts/health_check.sh
```

### Backup Strategy

```bash
# Daily database backup
nano ~/polymarket-bot/scripts/backup.sh
```

Content:

```bash
#!/bin/bash
BACKUP_DIR=/home/botuser/backups
DATE=$(date +%Y%m%d)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
cp /home/botuser/polymarket-bot/data/trades.db $BACKUP_DIR/trades_$DATE.db

# Backup config (without secrets)
cp /home/botuser/polymarket-bot/config/*.json $BACKUP_DIR/

# Keep only last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete

# Optional: Upload to cloud
# aws s3 cp $BACKUP_DIR/trades_$DATE.db s3://your-bucket/backups/
```

Add to crontab:

```bash
# Daily at 2 AM
0 2 * * * /home/botuser/polymarket-bot/scripts/backup.sh
```

---

## Monitoring Setup

### Telegram Bot for Monitoring

1. Create bot via @BotFather
2. Get bot token
3. Get your chat ID
4. Configure in .env

### Daily Summary Cron

```bash
# Add to crontab
0 0 * * * cd /home/botuser/polymarket-bot && source venv/bin/activate && python scripts/send_daily_summary.py
```

### Monitoring Dashboard (Optional)

For more advanced monitoring, consider:

- **Grafana + InfluxDB:** Full metrics dashboard
- **Uptime Robot:** External availability monitoring
- **Papertrail/Logtail:** Log aggregation

---

## Cost Summary

### Monthly Operating Costs

| Item | Cost | Notes |
|------|------|-------|
| VPS (Hetzner CX11) | $4 | Minimum viable |
| RPC (Alchemy free) | $0 | Free tier sufficient |
| Domain (optional) | $1 | For monitoring |
| **Total** | **$5** | Minimum setup |

### With Premium Services

| Item | Cost | Notes |
|------|------|-------|
| VPS (DigitalOcean) | $6 | Better support |
| RPC (Alchemy Growth) | $49 | Higher limits |
| Monitoring | $5 | Uptime Robot Pro |
| **Total** | **$60** | Premium setup |

---

## Troubleshooting

### Common Issues

**Bot won't start:**
```bash
# Check logs
journalctl -u polymarket-bot -n 50

# Verify environment
source venv/bin/activate
python -c "import dotenv; dotenv.load_dotenv(); print('OK')"
```

**WebSocket disconnections:**
```bash
# Check internet
ping polygon-mainnet.g.alchemy.com

# Check RPC status
curl https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","id":1}'
```

**High memory usage:**
```bash
# Check memory
free -h

# Find memory hogs
ps aux --sort=-%mem | head

# Restart if needed
sudo systemctl restart polymarket-bot
```

**Service keeps restarting:**
```bash
# Check for crash loops
journalctl -u polymarket-bot | grep -i error

# Check exit codes
systemctl status polymarket-bot
```

---

## Security Checklist

- [ ] SSH key authentication (no passwords)
- [ ] Firewall enabled (ufw)
- [ ] Non-root user for bot
- [ ] .env file secured (chmod 600)
- [ ] Private key is fresh/dedicated wallet
- [ ] Fail2ban installed (optional)
- [ ] Regular system updates
- [ ] Backup strategy implemented

---

## Quick Reference

### Essential Commands

```bash
# Start bot
sudo systemctl start polymarket-bot

# Stop bot
sudo systemctl stop polymarket-bot

# Restart bot
sudo systemctl restart polymarket-bot

# View status
sudo systemctl status polymarket-bot

# Follow logs
journalctl -u polymarket-bot -f

# Manual run (for debugging)
cd ~/polymarket-bot && source venv/bin/activate && python main.py
```

### Emergency Procedures

```bash
# STOP ALL TRADING IMMEDIATELY
sudo systemctl stop polymarket-bot

# Check for any open positions
source venv/bin/activate
python scripts/list_positions.py

# Manual position close if needed
python scripts/emergency_close.py
```

---

*Last updated: 2026-02-03*
