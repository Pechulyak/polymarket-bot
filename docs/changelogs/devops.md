# Changelog - DevOps

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
