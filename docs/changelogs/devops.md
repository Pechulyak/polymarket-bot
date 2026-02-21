# Changelog - DevOps

## [2026-02-21] - CI/CD Setup

### Added
- `.github/workflows/deploy.yml` - GitHub Actions workflow for automatic deployment:
  - Runs on push to main branch
  - Test job: linting (ruff) + pytest
  - Build job: Docker image build
  - Deploy job: SSH to server, docker-compose up
  - Telegram notification on failure
- `scripts/deploy.sh` - Deployment script with:
  - Health checks for PostgreSQL, Redis, Bot
  - Backup before deployment
  - Logging to logs/deploy_*.log
  - Cleanup old Docker images
- `docs/CI_CD_SETUP.md` - Documentation for GitHub secrets setup

### Infrastructure
- **GitHub Actions** for CI/CD
- **SSH deployment** to production server
- **Automatic health checks** after deployment

### Configuration
- Required GitHub Secrets:
  - `SERVER_HOST` - Server IP
  - `SERVER_USER` - SSH username
  - `SSH_PRIVATE_KEY` - Deploy key
  - `TELEGRAM_BOT_TOKEN` (optional)
  - `TELEGRAM_CHAT_ID` (optional)

### Breaking Changes
- None

## [2026-02-20] - Production Monitoring & Docker

### Added
- `docker-compose.yml` - Added `bot` service for production deployment with health checks
- `src/monitoring/telegram_alerts.py` - Telegram alerts integration for:
  - Bot start/stop notifications
  - Trade execution alerts
  - Whale signal notifications
  - PnL updates
  - Risk events
  - Kill switch activation
- `src/monitoring/metrics.py` - Prometheus metrics collection:
  - Balance gauge
  - Trade counters (by side and status)
  - PnL gauges (daily and total)
  - Win rate gauge
  - Error counters
  - Whale signal counters
  - Open positions gauge
  - Execution time histogram
  - API latency histogram
- `.env.production.template` - Production environment template with all required variables

### Changed
- `docker-compose.yml` - Added bot service with:
  - Build from docker/Dockerfile
  - Environment variable configuration for DATABASE_URL and REDIS_URL
  - Volume mount for logs (/app/logs)
  - Health checks
  - Resource limits (1 CPU, 1GB RAM)
  - Restart policy (unless-stopped)
- `src/monitoring/logger.py` - Enhanced logging:
  - File output to logs/bot.log
  - Error log to logs/error.log
  - Console output in JSON format
  - Configurable log level via LOG_LEVEL env var
- `src/config/settings.py` - Added metrics configuration:
  - `metrics_enabled` (default: true)
  - `metrics_port` (default: 9090)
- `src/execution/copy_trading_engine.py` - Integrated Telegram alerts:
  - Trade execution notifications
  - Whale signal alerts
  - Position close with PnL

### Infrastructure
- **Docker Services**:
  - PostgreSQL 15 (port 5433)
  - Redis 7 (port 6379)
  - Bot service (production mode)

### Configuration
- Production `.env` template with clear sections for:
  - API Keys
  - Database (Docker internal networking)
  - Trading parameters
  - Risk management
  - Monitoring (Telegram, Sentry)
  - Production settings

### Monitoring
- **Telegram Alerts**: Bot token and chat ID configuration
- **Prometheus Metrics**: HTTP server on port 9090
- **Logging**: Structured JSON to stdout + file output

### Security
- `.env.production.template` does not contain real secrets
- Clear documentation for production deployment

### Breaking Changes
- None

### Verified
- Telegram alerts tested and working (2026-02-21)
  - Bot token: 7713075797:AAGkXEt6FpaPEIT3Gg-...
  - Chat ID: 946830266
  - All message types sent successfully

## [2026-02-06] - Setup Local Infrastructure

### Added
- `docker-compose.yml` - Docker Compose configuration for PostgreSQL + Redis
- `.env` - Local environment configuration (not in git, created from .env.example)
- `scripts/test_infrastructure.py` - Infrastructure test script for PostgreSQL and Redis connectivity

### Changed
- `docker-compose.yml` - Improved configuration with resource limits, health checks, and restart policies
- Removed `trading_bot` service from docker-compose.yml (will be run separately for development)

### Infrastructure
- **PostgreSQL 15** with persistent volume (`postgres_data`)
  - Port: 5433 (changed from 5432 due to port conflict)
  - Health checks configured
  - Resource limits: 1 CPU, 512MB RAM
  - Auto-restart on failure
  
- **Redis 7** with persistent volume (`redis_data`)
  - Port: 6379
  - AOF persistence enabled
  - Memory limit: 256MB with LRU eviction
  - Health checks configured
  - Resource limits: 0.5 CPU, 256MB RAM

- **Docker Network**: `polymarket_network` (bridge driver)

### Configuration
- Environment variables from `.env` file
- PostgreSQL: `postgresql://postgres:password@localhost:5433/polymarket`
- Redis: `redis://localhost:6379/0`

### Security
- Development passwords only (localhost access)
- No secrets committed to git (`.env` in `.gitignore`)
- Resource limits prevent container resource exhaustion

### Testing
- Infrastructure test script validates:
  - PostgreSQL connection and version
  - All required database tables exist
  - Bankroll initial data present
  - Redis connection and version
  - Redis SET/GET/DELETE operations
  - Redis persistence (AOF) status

### Breaking Changes
- None

## [YYYY-MM-DD] - [DevOps Task]

### Added
- `[file path]` - [infrastructure component]

### Changed
- `[file path]` - [configuration changes]

### Deployment
- [deployment scripts]
- [automation changes]

### Infrastructure
- [Docker changes]
- [CI/CD updates]
- [Monitoring setup]

### Configuration
- [environment changes]
- [secrets management]

### Performance
- [optimization changes]
- [resource adjustments]

### Security
- [security updates]
- [access control changes]

### Monitoring
- [alerts setup]
- [dashboards created]

### Breaking Changes
- [deployment impacts]
