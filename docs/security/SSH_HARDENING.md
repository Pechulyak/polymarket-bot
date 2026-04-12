# SSH Hardening — SEC-501

**Дата:** 2026-04-12  
**Статус:** COMPLETED

---

## Что изменено

| Параметр | До | После |
|----------|-----|-------|
| `PasswordAuthentication` | yes | **no** |
| `PermitRootLogin` | yes | **prohibit-password** |
| `PubkeyAuthentication` | yes | yes (без изменений) |
| `MaxAuthTries` | 3 | 3 (уже было) |
| `LoginGraceTime` | 120 | 30 |
| fail2ban | не установлен | **installed + enabled** |

### fail2ban config (`/etc/fail2ban/jail.local`)

```ini
[DEFAULT]
ignoreip = 127.0.0.1/8 62.60.233.100 83.139.133.100

[sshd]
enabled = true
port = 22
maxretry = 5
bantime = 3600
findtime = 600
```

---

## Rollback инструкция

```bash
# Восстановить sshd_config из backup
sudo cp /etc/ssh/sshd_config.backup /etc/ssh/sshd_config
sudo systemctl reload sshd

# Остановить fail2ban (опционально)
sudo systemctl stop fail2ban
sudo systemctl disable fail2ban

# Удалить jail.local (опционально)
sudo rm /etc/fail2ban/jail.local
```

---

## Verification

```bash
# SSH config
sudo sshd -T | grep -iE "password|permitroot"
# Ожидаем: passwordauthentication no, permitrootlogin prohibit-password

# fail2ban status
sudo fail2ban-client status sshd
# Ожидаем: enabled, some banned IPs

# fail2ban systemd
sudo systemctl status fail2ban --no-pager
# Ожидаем: active (running), enabled
```

---

## Incidents checked

- **006.1** (2026-04-10 08:51–09:11 UTC): подозрительной активности не обнаружено