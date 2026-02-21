# GitHub Secrets Setup

## Required Secrets

Go to **Repository Settings → Secrets and variables → Actions** and add:

### Server Access
| Secret | Description | Example |
|--------|-------------|---------|
| `SERVER_HOST` | Server IP or hostname | `192.168.1.100` |
| `SERVER_USER` | SSH username | `deploy` |
| `SSH_PRIVATE_KEY` | Private SSH key | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` |

### Telegram (optional - for failure notifications)
| Secret | Description | Example |
|--------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Your chat ID | `946830266` |

## Generating SSH Key

On your local machine:

```bash
# Generate new SSH key (no passphrase)
ssh-keygen -t ed25519 -C "deploy@polymarket-bot" -f ~/.ssh/polymarket_deploy

# Copy public key to server
ssh-copy-id -i ~/.ssh/polymarket_deploy.pub deploy@SERVER_IP

# Test connection
ssh -i ~/.ssh/polymarket_deploy deploy@SERVER_IP

# Copy private key content
cat ~/.ssh/polymarket_deploy
```

Add the **private key** content to `SSH_PRIVATE_KEY` secret.

## Server Setup

On your server:

```bash
# Create deploy user (optional)
sudo adduser deploy
sudo usermod -aG docker deploy

# Setup directory
sudo mkdir -p /opt/polymarket-bot
sudo chown deploy:deploy /opt/polymarket-bot
```

## Repository Variables

Go to **Repository Settings → Secrets and variables → Actions → Variables**:

| Variable | Value |
|----------|-------|
| `DOCKER_REGISTRY` | `docker.io` (or your registry) |
| `IMAGE_NAME` | `polymarket-bot` |
