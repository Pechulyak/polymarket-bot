# Security Audit Report
**Date:** 2026-03-13  
**Auditor:** SEC-401  
**Server IP:** 212.192.11.92

---

## 1. Open Ports

| Port | Service | Binding | Risk Level | Notes |
|------|---------|---------|------------|-------|
| 22 | SSH | 0.0.0.0:22 | **HIGH** | Open to all - recommend IP restriction |
| 6333 | qdrant | 0.0.0.0:6333 | **CRITICAL** | Vector DB exposed publicly |
| 42248 | amnezia-awg | 0.0.0.0:42248/udp | **HIGH** | VPN service - open UDP |
| 6379 | redis | Docker network only | **MEDIUM** | In container network, not exposed |
| 5433 | postgres | 127.0.0.1:5433 | **LOW** | Correctly bound to localhost |

### Assessment:
- ❌ **CRITICAL:** qdrant (port 6333) is exposed on 0.0.0.0 - vector database accessible from internet
- ❌ **HIGH:** SSH (port 22) open to all - recommended IP whitelist
- ❌ **HIGH:** amnezia-awg (VPN) port 42248/UDP open to all

---

## 2. Docker Ports

| Container | Exposed Ports | Binding | Status |
|-----------|--------------|---------|--------|
| polymarket_postgres | 5432/tcp | 127.0.0.1:5433->5432 | ✅ SECURE |
| polymarket_redis | 6379/tcp | Internal only | ✅ SECURE |
| polymarket_bot | - | Internal only | ✅ SECURE |
| polymarket_paper_settlement | - | Internal only | ✅ SECURE |
| polymarket_whale_detector | - | Internal only | ✅ SECURE |
| qdrant | 6333/tcp | 0.0.0.0:6333->6333 | ❌ **EXPOSED** |
| amnezia-awg | 42248/udp | 0.0.0.0:42248 | ❌ **EXPOSED** |

### Issues:
- **qdrant** container exposes port 6333 to all interfaces (0.0.0.0)
- **amnezia-awg** VPN service exposes UDP port 42248 to all

---

## 3. Firewall (UFW)

```
Status: active
Default: deny (incoming), allow (outgoing)
```

| Port | Action | From | Status |
|------|--------|------|--------|
| 22/tcp | ALLOW | Anywhere | ⚠️ Open to all |
| 8000 | DENY | Anywhere | ✅ Blocked |
| 2096 | ALLOW | Specific IPs only | ✅ Restricted |
| 42240 | ALLOW | Specific IPs only | ✅ Restricted |

### Issues:
- SSH (22) should be restricted to known IPs
- No specific rule for qdrant (6333) - exposed at Docker level

---

## 4. Secrets (.env)

| Check | Status |
|-------|--------|
| File exists | ✅ Yes |
| Permissions | ✅ 600 (-rw-------) |
| In .gitignore | ✅ Yes |

---

## 5. Git Configuration

| File/Directory | In .gitignore |
|----------------|---------------|
| .env | ✅ |
| .env.local | ✅ |
| .env.*.local | ✅ |
| logs/ | ✅ |
| *.log | ✅ |

---

## 6. Web Server

| Service | Status |
|---------|--------|
| nginx | ❌ Not installed |
| http.server | ❌ Not running |
| node dev server | ❌ Not running |

---

## 7. Public Services Running

| Process | Status |
|---------|--------|
| http.server | ✅ Not running |
| file browser | ✅ Not running |
| npm serve | ✅ Not running |

---

## 8. Docker Volumes

| Volume | Status |
|--------|--------|
| polymarket-bot_postgres_data | ✅ Isolated |
| polymarket-bot_redis_data | ✅ Isolated |
| qdrant_data | ✅ Isolated |

---

## Critical Findings Summary

### 🚨 CRITICAL (Immediate Action Required)
1. **qdrant (port 6333)** - Exposed publicly via 0.0.0.0
   - Vector database accessible from internet
   - Potential data exposure risk

### ⚠️ HIGH (Recommended Fix)
2. **SSH (port 22)** - Open to all IP addresses
   - Brute force attack surface
   - Recommend: `ufw allow from <trusted_ip> to any port 22`

3. **amnezia-awg (port 42248/UDP)** - VPN exposed to all
   - If intentional VPN access, limit to specific IPs
   - If not needed externally, block

---

## Security Rating

```
┌─────────────────────────────────────────────────┐
│  OVERALL STATUS: ⚠️ VULNERABLE                  │
│                                                 │
│  Critical:   1                                 │
│  High:       2                                 │
│  Medium:    1                                 │
│  Low:        2                                 │
│  Secure:    6                                 │
└─────────────────────────────────────────────────┘
```

---

## Recommendations

### Immediate Actions (Today)
1. **Block qdrant external access:**
   ```bash
   # Option A: Bind to localhost only
   # Modify docker-compose.yml for qdrant:
   ports:
     - "127.0.0.1:6333:6333"
   
   # Option B: Add UFW rule
   ufw deny 6333
   ```

2. **Restrict SSH access:**
   ```bash
   ufw allow from <your_ip> to any port 22
   ufw delete allow 22/tcp
   ```

### Short-term (This Week)
- Review amnezia-awg VPN necessity
- Implement fail2ban for SSH
- Add monitoring for port scanning

---

## Conclusion

The system has **1 CRITICAL vulnerability** (qdrant exposed) and **2 HIGH risk items** (SSH and VPN ports). While the project-specific services (postgres, redis, bot) are properly secured, external services pose significant risk.

**.env file is properly secured** - not exposed.

**Action Required:** Address qdrant exposure before any other security work.
