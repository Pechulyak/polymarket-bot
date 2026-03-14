# Qdrant Audit Report
**Date:** 2026-03-13
**Task ID:** SEC-402

---

## 1. Container Configuration

| Parameter | Value |
|-----------|-------|
| Container ID | 4be62303377b |
| Image | qdrant/qdrant:v1.17.0 |
| Status | Running (Up 7 days) |
| Created | 2026-03-05 16:13:05 |
| Restart Policy | unless-stopped |
| PID | 1362200 |

**Ports:**
- `0.0.0.0:6333->6333/tcp` (REST API)
- `[::]:6333->6333/tcp` (REST API IPv6)
- `6334/tcp` (gRPC)

**Volumes:**
- `qdrant_data` → `/qdrant/storage` inside container

**Network:**
- Container IP: 172.17.0.3
- Network: default bridge (docker0)
- Connected to polymarket-bot network: **NO**

---

## 2. Port Binding

| Interface | Address | Status |
|-----------|---------|--------|
| IPv4 | 0.0.0.0:6333 | LISTEN |
| IPv6 | [::]:6333 | LISTEN |

**Bind Address:** 0.0.0.0 (all interfaces)

---

## 3. Active Connections

```
COMMAND   PID    USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
docker-pr 1362216 root   8u  IPv4 31423152 0t0 TCP *:6333 (LISTEN)
docker-pr 1362226 root   8u  IPv6 31423153 0t0 TCP *:6333 (LISTEN)
```

**Result:** No active client connections detected. Only listening docker-proxy processes.

---

## 4. Project Usage

| Check | Result |
|-------|--------|
| Python code (*.py) | ❌ Not found |
| Requirements (*.txt) | ❌ Not found |
| Docker Compose (*.yml) | ❌ Not found |
| Documentation (*.md) | ⚠️ Referenced in SECURITY_AUDIT_20260313.md |

**Conclusion:** Qdrant is **NOT integrated** into polymarket-bot codebase.

---

## 5. Collections

```json
{
  "result": {
    "collections": [
      {
        "name": "ws-5fe07fc827daaa7e"
      }
    ]
  },
  "status": "ok"
}
```

**Total Collections:** 1
**Collection Name:** `ws-5fe07fc827daaa7e` (likely WebSocket-related)

---

## 6. Data Size

| Volume | Driver | Mountpoint |
|--------|--------|------------|
| qdrant_data | local | /var/lib/docker/volumes/qdrant_data/_data |

**Volume exists:** Yes
**Created:** 2026-03-05

---

## 7. External Accessibility

| Test | Result |
|------|--------|
| localhost:6333 | ✅ Responds |
| 0.0.0.0:6333 binding | ✅ Exposed |

**Status:** **PUBLIC** - Qdrant REST API is accessible on all network interfaces (0.0.0.0)

---

## 8. Outgoing Connections

Qdrant (as a vector database) does not typically make outgoing connections to external services. No outbound connections detected.

---

## 9. Exposure Assessment

| Category | Assessment |
|----------|------------|
| Port Binding | 0.0.0.0:6333 |
| Network Isolation | Isolated from polymarket-bot network |
| Client Usage | No active connections |
| Code Integration | Not integrated |
| Container Management | Manual (outside docker-compose) |

**Final Exposure:** **PUBLIC** ( port exposed to all interfaces)

---

## Summary

### Key Findings:

1. ✅ Qdrant container is running (7 days)
2. ✅ API responds normally
3. ✅ Volume mounted correctly
4. ❌ **PORT EXPOSED on 0.0.0.0** - accessible from internet
5. ❌ **NOT integrated** into polymarket-bot code
6. ✅ **Isolated** from project network
7. ✅ Running standalone (outside docker-compose)

### Recommendations:

1. **IMMEDIATE:** If Qdrant is not actively used, consider removing the container
2. **If needed:** Bind to 127.0.0.1 only (localhost) to prevent external access
3. **Security:** Add firewall rules to restrict port 6333 if Qdrant is required

### Conclusion:

Qdrant is **NOT used by polymarket-bot** but is exposed publicly on port 6333. The single collection `ws-5fe07fc827daaa7e` suggests it was used for testing or experimental purposes (likely WebSocket-related indexing).

**Action Required:** Decide whether to keep Qdrant or remove it. If keeping, restrict port binding to localhost.
