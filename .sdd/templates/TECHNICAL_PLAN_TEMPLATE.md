# Technical Plan: [Feature Name]

**Date:** YYYY-MM-DD  
**Planner:** [Your Name]  
**Status:** Draft | Review | Approved  
**Specification:** [Link to corresponding specification document]

---

## Executive Summary

[2-3 paragraph overview of the technical approach]

**What we're building:** [Brief description of the solution]

**Why this approach:** [Key reasons for the chosen technical direction]

**Key risks:** [Top 2-3 technical risks and mitigation strategies]

**Example:**
We're building a federated query system that allows operators to search for machines across multiple MAAS regional controllers from a unified interface. The approach uses a lightweight aggregation service that queries regional APIs in parallel and merges results client-side. This design maintains regional autonomy (no central database) while providing the cross-region visibility users need. Key risks include handling network failures gracefully and ensuring query performance at scale; we mitigate these through timeout management, result streaming, and caching strategies.

---

## Architectural Approach

### High-Level Architecture

[Describe the overall architectural pattern and how components interact]

**Example:**
```
┌─────────────────────────────────────────────────────┐
│  MAAS Web UI (React)                                │
│  ┌─────────────────────────────────────────────┐   │
│  │  Cross-Region Search Component              │   │
│  │  - Search input & filters                   │   │
│  │  - Result aggregation & display             │   │
│  └─────────────────────────────────────────────┘   │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP/REST
                   ▼
┌─────────────────────────────────────────────────────┐
│  MAAS Aggregation Service (Python/Twisted)          │
│  - Region registry                                  │
│  - Parallel query coordinator                       │
│  - Result merger                                    │
└──────────┬──────────────┬───────────────────────────┘
           │              │
           │ REST API     │ REST API
           ▼              ▼
  ┌───────────────┐  ┌───────────────┐
  │ Regional      │  │ Regional      │
  │ Controller 1  │  │ Controller 2  │
  │ (MAAS API)    │  │ (MAAS API)    │
  └───────────────┘  └───────────────┘
```

**Architecture Pattern:** Hub-and-spoke with federated queries

**Rationale:**
- **Regional autonomy preserved:** Each regional controller remains independent; no schema changes required
- **Horizontal scalability:** New regions can be added without central database migration
- **Failure isolation:** One region's unavailability doesn't block queries to others
- **Performance:** Parallel queries minimize total latency

**Alternatives Considered:**
1. **Central database with replication:** Rejected due to operational complexity and synchronization delays
2. **Client-side only (browser queries regions):** Rejected due to CORS issues and authentication complexity
3. **Message queue-based:** Rejected as overkill for synchronous query use case

### Component Overview

[List major components and their responsibilities]

| Component | Responsibility | Technology | Rationale |
|-----------|---------------|------------|-----------|
| Regional Registry Service | Store list of configured regions, credentials, health status | PostgreSQL (existing MAAS DB) | Leverage existing infrastructure, ensure credentials are stored securely |
| Query Coordinator | Accept search requests, dispatch to regions in parallel, handle timeouts | Python/Twisted (async) | Match MAAS stack, async model fits parallel I/O pattern |
| Result Merger | Combine results from multiple regions, apply filters, sort | Python | Simple data processing, no heavy lifting required |
| Search UI Component | User input, filter controls, result display | React | Consistent with MAAS 3.x UI framework |
| Region Health Monitor | Periodic health checks, mark regions online/offline | Python/Twisted (cron job) | Detect unavailable regions before queries fail |

### Data Flow

[Describe how data moves through the system for key scenarios]

**Scenario 1: Cross-Region Machine Search**

```
1. User enters search query "gpu" with filter "status=ready"
   ↓
2. UI sends request to /api/2.0/machines/search/
   {
     "query": "gpu",
     "filters": {"status": "ready"},
     "regions": ["region-1", "region-2", "region-3"]
   }
   ↓
3. Query Coordinator retrieves region configs from registry
   - region-1: https://maas-region1.example.com/MAAS/api/2.0/
   - region-2: https://maas-region2.example.com/MAAS/api/2.0/
   - region-3: https://maas-region3.example.com/MAAS/api/2.0/ (offline)
   ↓
4. Parallel API calls to available regions (timeout: 5s each)
   - region-1: GET /MAAS/api/2.0/machines/?hostname=gpu&status=4
   - region-2: GET /MAAS/api/2.0/machines/?hostname=gpu&status=4
   - region-3: SKIPPED (offline)
   ↓
5. Results received (after 1.2s max latency)
   - region-1: [machine-1, machine-2, machine-3] (3 results)
   - region-2: [machine-10, machine-11] (2 results)
   ↓
6. Result Merger combines and enriches
   - Add "region" field to each result
   - Apply any additional client-side filters
   - Sort by region, then hostname
   ↓
7. Response returned to UI
   {
     "results": [
       {"hostname": "machine-1", "region": "region-1", "status": "ready", ...},
       {"hostname": "machine-2", "region": "region-1", "status": "ready", ...},
       ...
     ],
     "regions_queried": ["region-1", "region-2"],
     "regions_offline": ["region-3"],
     "total_count": 5,
     "query_time_ms": 1247
   }
   ↓
8. UI displays results with region badges, shows warning for offline regions
```

**Scenario 2: Region Goes Offline During Query**

```
1. Query initiated to 3 regions
2. region-2 times out after 5 seconds
3. Results from region-1 and region-3 are returned
4. Response includes partial results + error details:
   {
     "results": [...],
     "regions_queried": ["region-1", "region-3"],
     "regions_failed": [{"region": "region-2", "error": "timeout"}]
   }
5. UI shows results with warning banner: "Results incomplete: region-2 unavailable"
```

### Integration Points

[Identify how this solution connects with existing systems]

**External Systems:**

1. **MAAS Regional Controller APIs**
   - **Endpoints Used:** `/MAAS/api/2.0/machines/`, `/MAAS/api/2.0/version/`
   - **Authentication:** OAuth 1.0 (existing MAAS tokens)
   - **Dependency:** Regional APIs must be accessible over HTTPS
   - **Version Compatibility:** MAAS 3.2+ required for batch query support

2. **MAAS Authentication Service**
   - **Integration:** Reuse existing user session tokens
   - **Authorization:** User must have read permissions for each region
   - **Constraint:** Cross-region token validation needed (dependency on auth service upgrade)

3. **PostgreSQL Database (MAAS Central)**
   - **Schema Changes:** 
     - New table: `maas_region_registry` (stores region configs)
     - New table: `maas_region_health` (stores health check results)
   - **Migration:** Django migration to create tables
   - **Backwards Compatibility:** No changes to existing tables

**Internal MAAS Components:**

1. **Web UI (React)**
   - **New Component:** `CrossRegionSearch.jsx`
   - **Shared Components:** Reuse `MachineTable`, `StatusBadge`, `FilterBar`
   - **Routing:** New route `/machines/search-multi-region`

2. **API Layer (Python/Twisted)**
   - **New Endpoint:** `/api/2.0/machines/search/` (POST)
   - **Existing Endpoints Modified:** None
   - **Middleware:** Reuse authentication, rate limiting

### Technology Stack

[Specify technologies, versions, and justification]

| Layer | Technology | Version | Justification |
|-------|-----------|---------|---------------|
| **Backend** | Python | 3.10+ | MAAS standard, existing codebase |
| **Web Framework** | Twisted | 22.10+ | MAAS standard for async API servers |
| **Database** | PostgreSQL | 12+ | MAAS standard, already deployed |
| **Frontend Framework** | React | 18.x | MAAS web UI standard (recent upgrade) |
| **State Management** | Redux Toolkit | 1.9+ | MAAS UI standard for complex state |
| **HTTP Client (Backend)** | treq | 22.x | Twisted-native async HTTP, avoids blocking |
| **HTTP Client (Frontend)** | axios | 1.x | Already used in MAAS UI |

**New Dependencies:**

- **None for backend** (uses existing MAAS stack)
- **None for frontend** (uses existing MAAS UI stack)

**Rationale for Stack Choices:**
- Stick to MAAS existing technologies to minimize operational overhead
- Twisted's async model is perfect for parallel I/O-bound operations
- React 18 is already deployed; no framework migration needed
- No new languages or major frameworks to maintain

### Design Patterns

[Key patterns used and where]

1. **Scatter-Gather Pattern**
   - **Where:** Query Coordinator
   - **Why:** Need to query multiple independent sources and combine results
   - **Implementation:** Use `DeferredList` (Twisted) to manage parallel async calls

2. **Circuit Breaker Pattern**
   - **Where:** Regional API calls
   - **Why:** Prevent cascading failures when a region is persistently down
   - **Implementation:** After 3 consecutive failures, mark region offline for 60s before retrying

3. **Repository Pattern**
   - **Where:** Region registry access
   - **Why:** Abstract database operations, enable testing with mocks
   - **Implementation:** `RegionRepository` class with methods `get_all()`, `get_by_id()`, `health_check()`

4. **Adapter Pattern**
   - **Where:** Regional API client
   - **Why:** Different MAAS versions may have slight API variations
   - **Implementation:** `RegionalAPIAdapter` normalizes responses from different MAAS versions

---

## Security Considerations

### Authentication & Authorization

**Current State:**
- MAAS uses OAuth 1.0 for API authentication
- Users have per-region API keys
- Web UI uses session-based auth

**New Requirements:**
- Aggregation service must authenticate to multiple regions
- User permissions must be respected per region
- Credentials must be stored securely

**Solution:**

1. **Region Credential Storage**
   - Store regional API credentials in `maas_region_registry` table
   - Encrypt credentials at rest using `django-fernet-fields`
   - Access restricted to superusers via MAAS API

2. **User Authorization**
   - Pass user's session token to aggregation service
   - Service uses user's credentials (if available) for each region
   - If user lacks credentials for a region, skip that region (don't show error)
   - Log all cross-region queries for audit purposes

3. **Cross-Region Token Validation**
   - **Dependency:** Auth service must support multi-region token validation (planned Q2)
   - **Fallback:** Until available, require users to have separate credentials per region
   - **Migration Path:** Once available, switch to unified tokens transparently

**Threat Model:**

| Threat | Mitigation |
|--------|-----------|
| Credential theft from database | Encrypt at rest, restrict DB access, audit logs |
| Man-in-the-middle attacks | Require HTTPS for all regional API calls, certificate validation |
| Unauthorized cross-region access | Check user permissions per region before querying |
| Credential stuffing via search API | Rate limiting (10 req/min per user), account lockout after failures |
| Logging sensitive data | Sanitize logs, never log credentials or tokens |

### Data Privacy

**Sensitive Data:**
- Machine hostnames may reveal infrastructure topology
- IP addresses are sensitive
- Hardware details could expose vulnerabilities

**Controls:**
- All API calls over HTTPS
- Results filtered by user's regional permissions
- Audit log for cross-region queries (who, when, which regions)
- Option to redact sensitive fields in logs (configurable)

### Network Security

**Requirements:**
- Aggregation service must reach regional controllers
- Regional controllers may be in separate networks/datacenters

**Architecture:**
- Aggregation service runs on central MAAS controller
- Outbound HTTPS to regional controllers (ports 443/5240)
- No inbound connections required from regions
- Support for proxy configuration per region (if needed)

---

## Performance Requirements

### Target Metrics

[Define specific, measurable performance goals from specification]

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Query response time | < 3 seconds for 1,000 machines/region | 95th percentile, 2-5 regions |
| Query response time (large) | < 10 seconds for 10,000 machines/region | 95th percentile, 2-5 regions |
| Regional API timeout | 5 seconds per region | Configurable, fail fast |
| Concurrent users | 50 simultaneous searches | Load test with Locust |
| Memory usage | < 512 MB (aggregation service) | Steady state under load |
| Database query time | < 100ms for region registry lookups | 95th percentile |

### Performance Strategy

**Optimization Techniques:**

1. **Parallel Queries**
   - Query all regions simultaneously (not sequential)
   - Expected latency = max(region_latencies), not sum
   - Example: 3 regions at 1s each = 1s total, not 3s

2. **Streaming Results**
   - Return results as they arrive (don't wait for all regions)
   - UI updates incrementally
   - User sees partial results within 500ms

3. **Caching Strategy**
   - **Region health status:** Cache for 60s (avoid checking on every query)
   - **Region configurations:** Cache for 5 minutes (rarely change)
   - **Machine results:** NO caching (must be real-time)

4. **Query Optimization**
   - Limit results per region to 100 by default (pagination)
   - Support server-side filtering to reduce data transfer
   - Use HTTP compression for API responses

5. **Connection Pooling**
   - Maintain persistent HTTPS connections to regional APIs
   - Avoid TLS handshake overhead on every query
   - Pool size: 5 connections per region

**Scalability:**

- **Vertical:** Service is I/O-bound, not CPU-bound; modest hardware sufficient
- **Horizontal:** Can run multiple aggregation service instances behind load balancer if needed (future)
- **Bottlenecks:** Regional API response time is primary constraint (outside our control)

### Load Characteristics

**Expected Load:**
- 200 active operators across all regions
- 10% performing searches concurrently (20 users)
- Average 5 searches per user per day
- Peak: 50 concurrent searches during incident response

**Capacity Planning:**
- Single aggregation service instance can handle expected load
- Monitor query latency and regional API errors
- Alert if 95th percentile > 5s or error rate > 5%

---

## Error Handling & Resilience

### Failure Modes

[Identify what can go wrong and how to handle it]

| Failure Mode | Impact | Detection | Handling |
|--------------|--------|-----------|----------|
| Region offline | Partial results | Health check fails | Return results from available regions, show warning |
| Region timeout | Delayed response | Query exceeds 5s | Cancel query, return partial results |
| Region API error (500) | Partial results | HTTP error response | Log error, return partial results |
| Network partition | No results from subset | Connection failure | Graceful degradation, alert operator |
| Invalid credentials | Cannot query region | 401/403 response | Skip region, log warning, alert admin |
| Malformed API response | Parsing error | JSON decode fails | Skip region, log error, alert admin |
| Database unavailable | Cannot load regions | Connection failure | Return error to user, log critical alert |
| All regions offline | No results | All health checks fail | Show error message, suggest checking configurations |

### Resilience Patterns

1. **Graceful Degradation**
   - Always return best available results, even if incomplete
   - Clearly indicate which regions were queried vs. failed
   - User can proceed with partial information

2. **Timeouts and Cancellation**
   - Per-region timeout: 5 seconds
   - Total query timeout: 10 seconds
   - Cancel in-flight requests when total timeout reached

3. **Retry Logic**
   - **Don't retry** within a single query (user can resubmit)
   - Health monitor retries failed regions periodically (every 60s)
   - Circuit breaker: 3 failures → mark offline for 60s

4. **Error Context**
   - Log region name, error type, timestamp
   - Include request ID for tracing
   - Provide actionable error messages to users

**Example Error Response:**
```json
{
  "results": [...],
  "regions_queried": ["region-1"],
  "regions_failed": [
    {
      "region": "region-2",
      "error": "timeout",
      "message": "Region did not respond within 5 seconds"
    },
    {
      "region": "region-3",
      "error": "connection_refused",
      "message": "Could not connect to region API"
    }
  ],
  "warning": "Results are incomplete. 2 of 3 regions unavailable."
}
```

---

## Database Schema Changes

[Document new tables, columns, indexes, migrations]

### New Tables

**Table: `maas_region_registry`**
```sql
CREATE TABLE maas_region_registry (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    api_url VARCHAR(512) NOT NULL,
    api_key_encrypted BYTEA NOT NULL,  -- Fernet encrypted
    api_secret_encrypted BYTEA NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    
    CONSTRAINT valid_api_url CHECK (api_url LIKE 'https://%')
);

CREATE INDEX idx_region_active ON maas_region_registry(is_active);
```

**Table: `maas_region_health`**
```sql
CREATE TABLE maas_region_health (
    id SERIAL PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES maas_region_registry(id) ON DELETE CASCADE,
    checked_at TIMESTAMP DEFAULT NOW(),
    is_online BOOLEAN NOT NULL,
    response_time_ms INTEGER,
    error_message TEXT,
    maas_version VARCHAR(50),
    
    CONSTRAINT fk_region FOREIGN KEY (region_id) REFERENCES maas_region_registry(id)
);

CREATE INDEX idx_region_health_latest ON maas_region_health(region_id, checked_at DESC);
```

### Migration Strategy

1. **Migration 0001:** Create tables (backwards compatible)
2. **Migration 0002:** (Future) Add cross-region query audit log table
3. **Rollback Plan:** Drop tables if needed; no impact on existing functionality

**Data Migration:**
- No existing data to migrate
- Regions must be manually configured by admin via MAAS API
- Provide CLI tool: `maas region add <name> <url> <credentials>`

---

## Testing Strategy

### Unit Tests

**Coverage Target:** 80%+ for new code

**Key Areas:**
- Query coordinator logic (parallel execution, timeout handling)
- Result merger (combining, sorting, filtering)
- Regional API client (mocking external API calls)
- Region registry repository (database operations)
- Error handling and resilience logic

**Testing Framework:** Python `unittest` (MAAS standard)

**Example Test:**
```python
class TestQueryCoordinator(MAASTestCase):
    def test_parallel_queries_return_combined_results(self):
        # Mock two regional APIs
        region1 = self.mock_region_api(machines=[...])
        region2 = self.mock_region_api(machines=[...])
        
        coordinator = QueryCoordinator([region1, region2])
        results = coordinator.search("gpu", timeout=5)
        
        self.assertEqual(len(results), 5)
        self.assertIn("region-1", [r.region for r in results])
```

### Integration Tests

**Scenarios:**
1. Query multiple mock regional APIs, verify results merged correctly
2. One region times out, verify partial results returned
3. All regions fail, verify error message
4. Invalid credentials, verify graceful handling
5. Database unavailable, verify error propagation

**Environment:** Use Docker containers for mock MAAS regions

### End-to-End Tests

**Scenarios:**
1. User searches via UI, results appear from multiple regions
2. User clicks machine, navigates to regional detail page
3. Offline region shows warning banner
4. Filter and sort work across regions

**Framework:** Selenium/Playwright (MAAS UI test standard)

### Performance Tests

**Tools:** Locust for load testing

**Test Cases:**
1. Baseline: 10 concurrent users, 2 regions, 1000 machines/region
2. Scale: 50 concurrent users
3. Large deployment: 10,000 machines/region
4. Network delay simulation: 500ms latency to regions

**Acceptance Criteria:**
- 95th percentile < 3s for baseline
- No memory leaks over 1-hour test
- Error rate < 1%

---

## Deployment Plan

### Rollout Strategy

**Phase 1: Development & Testing (Weeks 1-3)**
- Develop in feature branch
- Unit and integration tests
- Code review

**Phase 2: Staging Deployment (Week 4)**
- Deploy to staging environment with 2 mock regions
- Internal testing with operations team
- Performance benchmarking

**Phase 3: Beta Release (Week 5)**
- Deploy to production (feature flag disabled)
- Enable for 3 pilot customers
- Gather feedback, monitor metrics

**Phase 4: General Availability (Week 6)**
- Enable feature flag for all users
- Announce in release notes
- Monitor support tickets

### Feature Flag

**Flag Name:** `cross_region_search_enabled`

**Behavior:**
- `false`: Feature hidden from UI, API endpoint returns 404
- `true`: Feature visible and functional

**Rollback:** Disable feature flag if critical issues arise

### Monitoring & Alerting

**Metrics to Track:**
- Query response time (p50, p95, p99)
- Error rate per region
- Region health status
- API endpoint usage
- Database query performance

**Alerts:**
- Critical: All regions offline
- Warning: 1+ regions offline for > 10 minutes
- Warning: p95 latency > 5 seconds
- Info: Error rate > 5% for any region

**Dashboards:**
- Grafana dashboard showing query latency trends
- Region health status overview
- Usage metrics (queries per day, active regions)

### Documentation

**Developer Documentation:**
- API endpoint specification (OpenAPI)
- Database schema documentation
- Deployment procedures

**User Documentation:**
- How to configure regions (admin guide)
- How to use cross-region search (user guide)
- Troubleshooting common issues

**Operations Documentation:**
- Monitoring and alerting setup
- Incident response procedures
- Performance tuning guide

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Regional API changes break compatibility | Medium | High | Version detection in adapter, graceful degradation, thorough testing |
| Cross-region auth not ready | High | Medium | Build with per-region credentials, switch to unified tokens later |
| Query performance worse than expected | Medium | High | Early performance testing, streaming results, timeouts |
| Database migration fails in production | Low | High | Test migration on staging DB copy, have rollback script |
| User confusion about offline regions | Medium | Low | Clear UI messaging, warnings, documentation |
| Overwhelming support tickets | Low | Medium | Beta testing with pilots, comprehensive docs, FAQ |

---

## Future Enhancements

[Explicitly out of scope for this iteration, but possible later]

1. **Cross-Region Machine Allocation** (deferred)
   - Allocate machines from multiple regions in single operation
   - Requires transaction coordination across regions

2. **Historical Search** (deferred)
   - Query past machine states, not just current
   - Requires audit log integration

3. **Advanced Query Syntax** (deferred)
   - Boolean operators, wildcards, nested filters
   - Adds complexity to query parser

4. **Result Caching** (deferred)
   - Cache results for repeat queries
   - Risk of stale data; wait for user feedback on need

5. **Mobile UI Optimization** (deferred)
   - Responsive design for mobile devices
   - Desktop/tablet support sufficient for MVP

---

## Appendix

### API Endpoint Specification

**POST /api/2.0/machines/search/**

Request:
```json
{
  "query": "string (optional)",
  "filters": {
    "status": "string (ready|allocated|deployed...)",
    "tags": ["string"],
    "region": ["string"]
  },
  "limit": "integer (default 100)",
  "sort_by": "string (hostname|status|region)"
}
```

Response:
```json
{
  "results": [
    {
      "system_id": "abc123",
      "hostname": "machine-1",
      "region": "region-1",
      "status": "ready",
      "cpu_count": 32,
      "memory": 262144,
      ...
    }
  ],
  "regions_queried": ["region-1", "region-2"],
  "regions_failed": [
    {"region": "region-3", "error": "timeout"}
  ],
  "total_count": 42,
  "query_time_ms": 1247
}
```

### Reference Architecture Diagrams

[Link to detailed diagrams in design docs]

### Related Work

- MAAS API documentation: https://maas.io/docs/api
- Twisted Deferred documentation: https://docs.twistedmatrix.com/en/stable/core/howto/defer.html
- OAuth 1.0 spec: https://tools.ietf.org/html/rfc5849

---

## Sign-off

**Planner:** [Name, Date]  
**Reviewed by:** [Architect, Date]  
**Approved by:** [Tech Lead, Date]