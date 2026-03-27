# Task List: [Feature Name]

**Date:** YYYY-MM-DD  
**Task Decomposer:** [Your Name]  
**Technical Plan:** [Link to corresponding technical plan]  
**Status:** Draft | Review | Approved

---

## Overview

**Feature Summary:** [Brief description of what's being built]

**Total Tasks:** [Number]  
**Estimated Complexity:** [Total story points or effort estimate]  
**Critical Path Length:** [Number of sequential tasks on longest path]  
**Parallel Streams:** [Number of independent work streams]

---

## Task Format

Each task follows this structure:

- **ID**: Unique identifier (e.g., TASK-001)
- **Description**: Clear, actionable description of what to implement
- **Files**: List of files to create/modify (1-3 files per task)
- **Acceptance Criteria**: Testable conditions for task completion
- **Dependencies**: Tasks that must complete before this one
- **Complexity**: Effort estimate (Small/Medium/Large or story points)
- **Parallel**: Can this be done in parallel with other tasks? (Yes/No)
- **Risk**: Any known risks or challenges (Optional)

---

## Task List

### TASK-001: [Task Name]

**Description:**
[Clear, actionable description of what needs to be implemented. Should be specific enough that an implementer knows exactly what to build.]

**Files:**
- `path/to/file1.py` - [What changes to this file]
- `path/to/file2.py` - [What changes to this file]
- `path/to/test_file.py` - [Tests for this task]

**Acceptance Criteria:**
- [ ] AC1: [Specific, testable criterion]
- [ ] AC2: [Specific, testable criterion]
- [ ] AC3: [Specific, testable criterion]
- [ ] All unit tests pass
- [ ] Code passes linting (flake8, black)
- [ ] Documentation updated (if applicable)

**Dependencies:**
- None (or list task IDs: TASK-XXX, TASK-YYY)

**Complexity:** Small | Medium | Large

**Parallel:** Yes | No

**Risk:** [Optional: Any known challenges or unknowns]

---

### TASK-002: [Task Name]

**Description:**
[Description]

**Files:**
- `path/to/file.py`

**Acceptance Criteria:**
- [ ] Criterion 1
- [ ] Criterion 2

**Dependencies:**
- TASK-001

**Complexity:** Medium

**Parallel:** No

---

## Example: Cross-Region Machine Search

### Foundation Tasks (Can Run in Parallel)

---

### TASK-001: Create Region Registry Database Schema

**Description:**
Create PostgreSQL database tables to store regional controller configurations. Implement Django models and migrations for `RegionRegistry` and `RegionHealth` tables. This provides the foundation for storing and querying configured regions.

**Files:**
- `src/maasserver/models/region_registry.py` - New Django models for region configuration
- `src/maasserver/migrations/0234_region_registry.py` - Database migration
- `src/maasserver/tests/test_region_registry.py` - Model tests

**Acceptance Criteria:**
- [ ] `RegionRegistry` model created with fields: name, api_url, encrypted credentials, is_active
- [ ] `RegionHealth` model created with fields: region_id (FK), checked_at, is_online, response_time_ms, error_message
- [ ] Migration creates tables with appropriate indexes
- [ ] Migration is reversible (down migration implemented)
- [ ] Credentials are encrypted using django-fernet-fields
- [ ] Model tests cover create, read, update, delete operations
- [ ] Tests verify credential encryption/decryption
- [ ] All tests pass

**Dependencies:**
- None

**Complexity:** Small

**Parallel:** Yes

---

### TASK-002: Implement Region Repository

**Description:**
Create repository class to abstract database access for region registry. Implement methods to retrieve regions, update health status, and query active regions. Use repository pattern for testability and separation of concerns.

**Files:**
- `src/maasserver/repositories/region_repository.py` - Repository implementation
- `src/maasserver/tests/test_region_repository.py` - Repository tests

**Acceptance Criteria:**
- [ ] `RegionRepository` class implements: `get_all()`, `get_active()`, `get_by_id()`, `update_health()`
- [ ] Repository methods return domain objects, not Django models
- [ ] All methods have error handling for database failures
- [ ] Tests use mocked database (no real DB hits in unit tests)
- [ ] Tests cover success and failure cases
- [ ] Repository methods are documented with docstrings
- [ ] All tests pass

**Dependencies:**
- TASK-001

**Complexity:** Small

**Parallel:** Yes (after TASK-001)

---

### TASK-003: Create Regional API Client Adapter

**Description:**
Implement adapter class for communicating with MAAS regional controller APIs. Handle OAuth 1.0 authentication, connection timeouts, error handling, and response normalization. Support different MAAS API versions gracefully.

**Files:**
- `src/maasserver/api/regional_client.py` - API client adapter
- `src/maasserver/tests/test_regional_client.py` - Client tests with mocked HTTP

**Acceptance Criteria:**
- [ ] `RegionalAPIClient` class accepts region config and credentials
- [ ] Implements method: `query_machines(filters, timeout)` returning normalized machine data
- [ ] Uses treq (Twisted HTTP client) for async requests
- [ ] Handles OAuth 1.0 authentication automatically
- [ ] Enforces configurable timeout (default 5 seconds)
- [ ] Normalizes responses from different MAAS versions (3.2, 3.3, 3.4)
- [ ] Returns structured errors on failure (timeout, auth failure, connection refused)
- [ ] Tests mock HTTP responses, verify correct API calls made
- [ ] Tests cover success, timeout, auth failure, and network error cases
- [ ] All tests pass

**Dependencies:**
- None

**Complexity:** Medium

**Parallel:** Yes

---

### Core Query Logic Tasks (Sequential)

---

### TASK-004: Implement Query Coordinator Service

**Description:**
Build service that coordinates parallel queries to multiple regional controllers. Accept search request, retrieve active regions from repository, query each region in parallel using Twisted DeferredList, and collect results. Handle timeouts and partial failures gracefully.

**Files:**
- `src/maasserver/services/query_coordinator.py` - Query coordination logic
- `src/maasserver/tests/test_query_coordinator.py` - Coordinator tests

**Acceptance Criteria:**
- [ ] `QueryCoordinator` class implements: `search_machines(query, filters, timeout)`
- [ ] Queries all active regions in parallel (not sequential)
- [ ] Uses Twisted `DeferredList` for parallel async operations
- [ ] Enforces per-region timeout (5 seconds default)
- [ ] Continues with partial results if some regions fail/timeout
- [ ] Returns tuple: (results, successful_regions, failed_regions)
- [ ] Logs failures with region name, error type, and timestamp
- [ ] Tests mock `RegionRepository` and `RegionalAPIClient`
- [ ] Tests verify parallel execution (not sequential)
- [ ] Tests cover all regions succeed, partial failure, all regions fail
- [ ] All tests pass

**Dependencies:**
- TASK-002 (Region Repository)
- TASK-003 (Regional API Client)

**Complexity:** Large

**Parallel:** No

---

### TASK-005: Implement Result Merger

**Description:**
Create component that merges machine results from multiple regions, adds region metadata, applies client-side filters, and sorts results. Handle duplicate system_ids (shouldn't happen, but defensive), and ensure consistent output format.

**Files:**
- `src/maasserver/services/result_merger.py` - Result merging logic
- `src/maasserver/tests/test_result_merger.py` - Merger tests

**Acceptance Criteria:**
- [ ] `ResultMerger` class implements: `merge(results_by_region, filters, sort_by)`
- [ ] Adds `region` field to each machine result
- [ ] Applies client-side filters if specified
- [ ] Sorts by configurable field (default: region, then hostname)
- [ ] Handles empty results from some regions
- [ ] Detects and logs duplicate system_ids across regions
- [ ] Returns list of normalized machine dictionaries
- [ ] Tests cover merging 0, 1, 2, and 5 regions
- [ ] Tests verify filtering and sorting work correctly
- [ ] Tests check duplicate detection
- [ ] All tests pass

**Dependencies:**
- TASK-004 (need output format from coordinator)

**Complexity:** Small

**Parallel:** No

---

### API Endpoint Tasks

---

### TASK-006: Create Cross-Region Search API Endpoint

**Description:**
Implement new REST API endpoint `/api/2.0/machines/search/` that accepts search requests, calls query coordinator, merges results, and returns JSON response. Handle authentication, authorization, rate limiting, and error responses.

**Files:**
- `src/maasserver/api/machines_search.py` - API endpoint handler
- `src/maasserver/api/urls.py` - Add route to URL configuration
- `src/maasserver/tests/test_api_machines_search.py` - API endpoint tests

**Acceptance Criteria:**
- [ ] POST endpoint at `/api/2.0/machines/search/` accepts JSON request body
- [ ] Request format: `{"query": "...", "filters": {...}, "regions": [...]}`
- [ ] Validates request parameters, returns 400 for invalid input
- [ ] Requires authentication (OAuth 1.0)
- [ ] Calls `QueryCoordinator.search_machines()`
- [ ] Returns 200 with results or 207 (Multi-Status) if partial failure
- [ ] Response includes: results, regions_queried, regions_failed, total_count, query_time_ms
- [ ] Rate limiting: 10 requests/minute per user
- [ ] Tests mock coordinator and verify correct API responses
- [ ] Tests cover success, partial failure, authentication failure, invalid input
- [ ] API documentation added (OpenAPI/Swagger)
- [ ] All tests pass

**Dependencies:**
- TASK-004 (Query Coordinator)
- TASK-005 (Result Merger)

**Complexity:** Medium

**Parallel:** No

---

### UI Component Tasks (Can Run in Parallel with Backend)

---

### TASK-007: Create Cross-Region Search UI Component

**Description:**
Build React component for cross-region machine search. Implement search input, filter controls (status, tags, region selection), and results table. Display region badges, loading states, and error messages for offline regions.

**Files:**
- `src/maasui/src/components/CrossRegionSearch/CrossRegionSearch.tsx` - Main component
- `src/maasui/src/components/CrossRegionSearch/CrossRegionSearch.test.tsx` - Component tests
- `src/maasui/src/components/CrossRegionSearch/index.ts` - Export

**Acceptance Criteria:**
- [ ] Search input with debounced query (300ms)
- [ ] Filter controls: status dropdown, tag multiselect, region checkboxes
- [ ] Results table using existing `MachineTable` component
- [ ] Region badge displayed for each machine
- [ ] Loading spinner during query
- [ ] Warning banner for offline/failed regions
- [ ] Empty state message when no results
- [ ] Click machine row navigates to machine detail page
- [ ] Component tests using React Testing Library
- [ ] Tests cover loading, success, partial failure, empty results
- [ ] All tests pass

**Dependencies:**
- None (can mock API)

**Complexity:** Medium

**Parallel:** Yes (independent of backend tasks)

---

### TASK-008: Integrate Search Component with Redux Store

**Description:**
Create Redux slice for cross-region search state management. Implement actions and reducers for search requests, results, loading states, and errors. Connect search component to Redux store.

**Files:**
- `src/maasui/src/store/crossRegionSearch/slice.ts` - Redux slice
- `src/maasui/src/store/crossRegionSearch/slice.test.ts` - Slice tests
- `src/maasui/src/components/CrossRegionSearch/CrossRegionSearchContainer.tsx` - Connected component

**Acceptance Criteria:**
- [ ] Redux slice with state: query, filters, results, loading, errors
- [ ] Actions: searchMachines, searchSuccess, searchFailure, clearResults
- [ ] Async thunk for API calls using axios
- [ ] Reducers handle all actions correctly
- [ ] Connected component uses Redux hooks (useSelector, useDispatch)
- [ ] Tests verify reducers update state correctly
- [ ] Tests verify async thunk dispatches correct actions
- [ ] All tests pass

**Dependencies:**
- TASK-007 (UI Component)

**Complexity:** Small

**Parallel:** No (depends on TASK-007)

---

### TASK-009: Add Search Route to Web UI

**Description:**
Add new route `/machines/search-multi-region` to MAAS web UI. Update navigation menu to include link to cross-region search. Ensure route is protected (requires authentication).

**Files:**
- `src/maasui/src/routes.tsx` - Add route
- `src/maasui/src/components/Navigation/Navigation.tsx` - Add menu item

**Acceptance Criteria:**
- [ ] Route `/machines/search-multi-region` renders `CrossRegionSearchContainer`
- [ ] Route requires authentication (redirects to login if not authenticated)
- [ ] Navigation menu item "Search Across Regions" added under Machines section
- [ ] Menu item only visible to users with appropriate permissions
- [ ] Tests verify route renders correct component
- [ ] Tests verify authentication requirement
- [ ] All tests pass

**Dependencies:**
- TASK-008 (Redux Integration)

**Complexity:** Small

**Parallel:** No

---

### Supporting Tasks

---

### TASK-010: Implement Region Health Monitor

**Description:**
Create background task that periodically checks health of registered regions. Query each region's `/api/2.0/version/` endpoint, measure response time, update health status in database. Run every 60 seconds via Twisted LoopingCall.

**Files:**
- `src/maasserver/services/region_health_monitor.py` - Health check service
- `src/maasserver/tests/test_region_health_monitor.py` - Monitor tests

**Acceptance Criteria:**
- [ ] `RegionHealthMonitor` class with method: `check_all_regions()`
- [ ] Queries each active region's version endpoint
- [ ] Measures response time in milliseconds
- [ ] Updates `RegionHealth` table with results
- [ ] Marks region offline after 3 consecutive failures (circuit breaker)
- [ ] Runs as Twisted LoopingCall (60-second interval)
- [ ] Logs health check results at INFO level
- [ ] Tests mock API calls and verify health status updates
- [ ] Tests verify circuit breaker behavior
- [ ] All tests pass

**Dependencies:**
- TASK-002 (Region Repository)
- TASK-003 (Regional API Client)

**Complexity:** Medium

**Parallel:** Yes (independent work stream)

---

### TASK-011: Add Region Management API Endpoints

**Description:**
Create API endpoints for managing regional controller registry: add region, update region, delete region, list regions. Require superuser permissions. Validate API URLs and credentials before saving.

**Files:**
- `src/maasserver/api/regions.py` - Region management endpoints
- `src/maasserver/tests/test_api_regions.py` - API tests

**Acceptance Criteria:**
- [ ] POST `/api/2.0/regions/` - Add new region
- [ ] PUT `/api/2.0/regions/{id}/` - Update region
- [ ] DELETE `/api/2.0/regions/{id}/` - Delete region
- [ ] GET `/api/2.0/regions/` - List all regions with health status
- [ ] All endpoints require superuser authentication
- [ ] Validate API URL is HTTPS
- [ ] Test connectivity before saving new region
- [ ] Returns 403 for non-superusers
- [ ] Tests cover CRUD operations
- [ ] Tests verify permission checks
- [ ] API documentation added
- [ ] All tests pass

**Dependencies:**
- TASK-002 (Region Repository)

**Complexity:** Medium

**Parallel:** Yes (independent work stream)

---

### Integration and Documentation Tasks

---

### TASK-012: End-to-End Integration Test

**Description:**
Create end-to-end test that simulates complete cross-region search workflow. Use Docker containers to run 2 mock MAAS regional controllers, perform search via API and UI, verify results.

**Files:**
- `src/maasserver/tests/integration/test_cross_region_search.py` - Integration test
- `src/maasserver/tests/integration/docker-compose.yml` - Docker environment

**Acceptance Criteria:**
- [ ] Docker Compose file defines 2 mock MAAS regions
- [ ] Test registers regions via API
- [ ] Test performs cross-region search via API, verifies results contain machines from both regions
- [ ] Test uses Playwright to navigate UI, enter search, verify results displayed
- [ ] Test simulates one region offline, verifies partial results with warning
- [ ] Test runs in CI environment
- [ ] All assertions pass

**Dependencies:**
- TASK-006 (API Endpoint)
- TASK-009 (UI Route)
- TASK-011 (Region Management API)

**Complexity:** Large

**Parallel:** No (requires completed feature)

---

### TASK-013: Performance Testing

**Description:**
Create performance test suite using Locust. Simulate 10, 25, and 50 concurrent users performing cross-region searches. Measure p95 latency, throughput, and error rate. Verify performance meets specification (<3 seconds for 1,000 machines/region).

**Files:**
- `src/maasserver/tests/performance/locustfile.py` - Locust test scenarios
- `src/maasserver/tests/performance/README.md` - Instructions for running tests

**Acceptance Criteria:**
- [ ] Locust scenario: 10 users, 2 regions, 1,000 machines/region
- [ ] Locust scenario: 50 users, 5 regions, 1,000 machines/region
- [ ] Locust scenario: 25 users, 3 regions, 5,000 machines/region
- [ ] Measure p50, p95, p99 latency
- [ ] Measure requests per second
- [ ] Measure error rate
- [ ] Generate report with graphs
- [ ] Verify p95 latency < 3 seconds for baseline scenario
- [ ] Document results in report
- [ ] Tests can run in CI or manually

**Dependencies:**
- TASK-006 (API Endpoint)

**Complexity:** Medium

**Parallel:** No (requires completed API)

---

### TASK-014: User Documentation

**Description:**
Write user-facing documentation for cross-region search feature. Include setup guide for configuring regions, usage guide for searching, troubleshooting common issues, and FAQ.

**Files:**
- `docs/user/cross-region-search.md` - User documentation
- `docs/admin/region-configuration.md` - Admin documentation

**Acceptance Criteria:**
- [ ] User documentation covers: how to access search, filter options, interpreting results
- [ ] Admin documentation covers: how to add/remove regions, credentials setup, troubleshooting connectivity
- [ ] Includes screenshots of UI
- [ ] FAQ covers: What if region is offline? How often is health checked? What are performance limits?
- [ ] Troubleshooting section covers common errors and solutions
- [ ] Documentation reviewed for clarity and accuracy
- [ ] Links added to main documentation index

**Dependencies:**
- TASK-009 (UI Route)
- TASK-011 (Region Management API)

**Complexity:** Small

**Parallel:** Yes (can start once UI/API are defined)

---

### TASK-015: Developer Documentation

**Description:**
Write developer documentation for cross-region search architecture. Include component diagram, data flow, API contracts, extension points, and testing guide.

**Files:**
- `docs/developer/cross-region-search-architecture.md` - Architecture documentation
- `docs/developer/api-reference.md` - Update API reference

**Acceptance Criteria:**
- [ ] Architecture document includes: component diagram, data flow diagram, key design decisions
- [ ] Documents the scatter-gather pattern implementation
- [ ] API contract documented with request/response examples
- [ ] Extension points documented (how to add new query types, filters)
- [ ] Testing guide explains how to run unit, integration, and performance tests
- [ ] Code examples for common tasks
- [ ] Linked from developer documentation index

**Dependencies:**
- TASK-012 (Integration Test)

**Complexity:** Small

**Parallel:** Yes (can write as implementation progresses)

---

## Task Dependencies (Graph)

```
TASK-001 (Database Schema)
    ↓
TASK-002 (Repository) ────────────────┐
    ↓                                  ↓
TASK-004 (Query Coordinator)      TASK-010 (Health Monitor)
    ↓                 
TASK-005 (Result Merger)
    ↓
TASK-006 (API Endpoint) ──→ TASK-013 (Performance Testing)
    ↓
    ├──→ TASK-012 (Integration Test)
    └──→ TASK-015 (Developer Docs)

TASK-003 (API Client) ────────────────→ TASK-004, TASK-010

TASK-007 (UI Component)
    ↓
TASK-008 (Redux Integration)
    ↓
TASK-009 (UI Route) ──→ TASK-012 (Integration Test)
                    └──→ TASK-014 (User Docs)

TASK-002 (Repository) ──→ TASK-011 (Region Management API)
```

**Critical Path:** TASK-001 → TASK-002 → TASK-004 → TASK-005 → TASK-006 → TASK-012
**Length:** 6 sequential tasks

**Parallel Streams:**
- Stream 1 (Backend): TASK-001 → 002 → 004 → 005 → 006
- Stream 2 (Frontend): TASK-007 → 008 → 009
- Stream 3 (Management): TASK-001 → 002 → 011
- Stream 4 (Monitoring): TASK-001 → 002 + 003 → 010

---

## Complexity Summary

| Complexity | Count | Tasks |
|------------|-------|-------|
| Small | 6 | TASK-001, 002, 005, 008, 009, 014, 015 |
| Medium | 6 | TASK-003, 006, 007, 010, 011, 013 |
| Large | 2 | TASK-004, 012 |

**Total Effort Estimate:** ~15-20 developer-days (assuming Small=1d, Medium=2d, Large=3d)

---

## Implementation Order

### Phase 1: Foundation (Parallel)
- TASK-001, TASK-003 (can start simultaneously)

### Phase 2: Core Backend (Sequential)
- TASK-002 → TASK-004 → TASK-005 → TASK-006

### Phase 3: Frontend (Parallel with Backend Phase 2)
- TASK-007 → TASK-008 → TASK-009

### Phase 4: Supporting Features (Parallel)
- TASK-010 (Health Monitor)
- TASK-011 (Region Management)
- TASK-014 (User Docs)

### Phase 5: Integration and Validation (Sequential)
- TASK-012 (Integration Test)
- TASK-013 (Performance Test)
- TASK-015 (Developer Docs)

---

## Notes

**Task Sizing Guidelines:**
- **Small (1-2 days)**: Single file or simple changes, straightforward logic, well-defined scope
- **Medium (2-4 days)**: Multiple files, moderate complexity, requires some design decisions
- **Large (3-5 days)**: Complex logic, multiple integration points, significant testing required

**Parallel Execution:**
- Tasks marked "Parallel: Yes" can be worked on simultaneously by different developers
- Tasks with different file paths rarely conflict (merge conflicts minimal)
- UI tasks can progress independently of backend tasks using mocked APIs

**Testing Requirements:**
- Every task must include unit tests
- Tests must pass before task is considered complete
- Code coverage target: 80%+ for new code
- Integration tests verify component interactions
- Performance tests validate specification requirements

**Definition of Done (for each task):**
1. Code written and passes all acceptance criteria
2. Unit tests written and passing
3. Code reviewed and approved
4. Linting passes (flake8, black, prettier)
5. Documentation updated (docstrings, comments)
6. Changes merged to main branch

---

## Risk Register

| Task | Risk | Mitigation |
|------|------|-----------|
| TASK-004 | Twisted DeferredList complexity | Early prototype, pair programming |
| TASK-006 | API design requires review | Get API contract approved before implementation |
| TASK-012 | Docker environment flaky in CI | Add retry logic, ensure cleanup |
| TASK-013 | Performance targets not met | Profile and optimize critical path, may need caching |

---

## Sign-off

**Task Decomposer:** [Name, Date]  
**Reviewed by:** [Tech Lead, Date]  
**Approved by:** [Project Manager, Date]