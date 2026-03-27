# SDD Command: Tasks

## Purpose

The `tasks` command decomposes a technical plan into discrete, implementable tasks. Each task represents a unit of work that can be independently developed, tested, and reviewed. This command guides the Planner (or a dedicated Task Manager) in breaking down architectural designs into actionable implementation steps.

## Invocation Pattern

**When to use:**
- Technical plan has been created and approved
- Ready to begin implementation
- Need to distribute work across developers
- Want to track granular progress

**Who invokes:**
- Technical Lead
- Planner role (continuing from plan phase)
- Engineering Manager
- Senior Developer

**Command:**
```
I need to decompose this technical plan into implementation tasks.

Specification: [Path to spec]
Technical Plan: [Path to plan]

Please guide me through creating a task list using the SDD process.
```

## Inputs Required

### 1. Approved Specification

**From:** `.sdd/specs/[feature-name].md`

**What's needed:**
- User requirements and acceptance criteria
- Success metrics
- Scope boundaries
- User journeys

**Why:** Tasks must directly address spec requirements

**Example:**
```markdown
Specification: multi-region-query.md

Key Requirements:
- Query all regional controllers simultaneously
- Merge results into unified view
- Timeout protection (30s default)
- Handle partial failures gracefully

Acceptance Criteria:
- User can query across all regions with single API call
- Results return within 30 seconds or timeout
- Failed regions don't block successful results
```

### 2. Approved Technical Plan

**From:** `.sdd/plans/[feature-name].md`

**What's needed:**
- Architecture decisions
- Component design
- Integration points
- Technology choices
- Data flow diagrams

**Why:** Tasks implement the planned architecture

**Example:**
```markdown
Technical Plan: multi-region-query.md

Components:
1. QueryCoordinator (src/maasserver/services/query_coordinator.py)
2. RegionalQueryClient (src/maasserver/clients/regional_client.py)
3. ResultMerger (src/maasserver/utils/result_merger.py)
4. API Endpoint (src/maasserver/api/multi_region.py)
5. UI Component (src/maasui/src/app/machines/MultiRegionSearch.tsx)

Architecture:
- QueryCoordinator orchestrates parallel regional queries
- Uses Twisted DeferredList for async coordination
- ResultMerger handles deduplication and sorting
- API exposes /api/2.0/regions/query endpoint
```

### 3. Team Context

**Information needed:**
- Available developers and skill sets
- Sprint capacity (story points or hours)
- Parallel work constraints
- Timeline expectations

**Example:**
```
Team: 3 developers
Sprint: 2 weeks (80 hours total capacity)
Skills: 
  - 2 backend developers (Python/Twisted)
  - 1 full-stack developer (Python + React)

Constraints:
- API must be completed before UI can start
- Database changes need migration review (2 days lead time)
```

### 4. Dependency Constraints

**Identify:**
- External dependencies (other teams, systems)
- Internal prerequisites (existing features)
- Sequential dependencies (task A before task B)
- Blocking issues

**Example:**
```
Dependencies:
- Regional API clients already exist (can reuse)
- Event bus implementation available (can leverage)
- React component library v2.0 must be released first

Blockers:
- None identified
```

## Outputs Produced

### Task List Document

**Location:** `.sdd/tasks/[feature-name].md`

**Format:**
```markdown
# Tasks: [Feature Name]

**Specification:** [Link to spec]
**Technical Plan:** [Link to plan]
**Status:** Draft | Approved | In Progress | Complete
**Total Estimated Effort:** [Story points or hours]

---

## Task Breakdown

### Task 1: [Component/Feature Name]

**ID:** TASK-001
**Title:** [Clear, actionable title]
**Component:** [File/module path]
**Estimated Effort:** [Size: Small (1-2 days) | Medium (2-4 days) | Large (3-5 days)]
**Dependencies:** [List of task IDs this depends on, or "None"]
**Assigned To:** [Developer name or "Unassigned"]

**Description:**
[What needs to be built/changed]

**Acceptance Criteria:**
- [ ] Criterion 1 (testable, specific)
- [ ] Criterion 2
- [ ] Criterion 3

**Files to Modify/Create:**
- `path/to/file1.py` (create/modify)
- `path/to/file2.py` (create/modify)
- `path/to/test_file1.py` (create)

**Testing Requirements:**
- Unit tests for [specific functionality]
- Integration tests for [integration points]
- [Any special testing needs]

**Notes:**
[Any additional context, risks, or considerations]

---

### Task 2: [Next Component/Feature]
[Same structure as Task 1]

---

## Task Dependencies

```
[ASCII diagram showing task relationships]

TASK-001 (Foundation)
    ├─> TASK-002 (Service Layer)
    └─> TASK-003 (Repository)

TASK-002 + TASK-003
    └─> TASK-004 (API Endpoint)

TASK-004
    └─> TASK-005 (UI Component)
```

---

## Sprint Allocation (Optional)

**Sprint 1 (Week 1-2):**
- TASK-001: Foundation (Dev A)
- TASK-002: Service Layer (Dev B)
- TASK-003: Repository (Dev A)

**Sprint 2 (Week 3-4):**
- TASK-004: API Endpoint (Dev B)
- TASK-005: UI Component (Dev C)

---

## Risk Assessment

**High Risk Tasks:** [Tasks with significant unknowns]
**Mitigation:** [Strategies to reduce risk]

**Critical Path:** [Tasks that cannot be delayed]
```

## Validation Criteria

### Task Quality Checklist

Each task must meet these criteria:

- [ ] **Properly Sized**: 1-5 days effort (1-3 files modified)
- [ ] **Clear Scope**: Obvious what's in and out
- [ ] **Independently Testable**: Can write tests without other tasks
- [ ] **Acceptance Criteria**: 3-7 specific, testable criteria
- [ ] **File Listing**: Exact files to create/modify specified
- [ ] **Dependencies Identified**: Clear what must be done first
- [ ] **Maps to Plan**: Implements specific component from technical plan
- [ ] **Addresses Spec**: Contributes to specification requirements

### Task List Quality Checklist

Overall task list must meet:

- [ ] **Complete Coverage**: All plan components have tasks
- [ ] **No Gaps**: Every spec requirement addressed by at least one task
- [ ] **Realistic Estimates**: Total effort matches team capacity
- [ ] **Parallelizable**: Multiple tasks can be worked simultaneously
- [ ] **Logical Ordering**: Dependencies make sense
- [ ] **Clear Ownership**: Assignment strategy defined
- [ ] **Testable Increments**: Each task delivers testable value

## Process Flow

### Step 1: Review Inputs

**Action:** Read specification and technical plan thoroughly

**Output:** Understanding of:
- What needs to be built (spec)
- How it will be built (plan)
- Why it matters (spec)

**Time:** 30-60 minutes

### Step 2: Identify Natural Boundaries

**Action:** Find logical decomposition points in the architecture

**Look for:**
- Distinct components (classes, modules)
- Layers (data, service, API, UI)
- Vertical slices (end-to-end features)
- Integration points

**Example:**
```
Technical Plan Components:
1. QueryCoordinator (service layer)
2. RegionalQueryClient (client layer)
3. ResultMerger (utility)
4. API Endpoint (HTTP layer)
5. React Component (UI layer)

Natural Task Boundaries:
- Backend foundation (database, models)
- Service layer (QueryCoordinator)
- Client layer (RegionalQueryClient)
- API layer (HTTP endpoint)
- UI layer (React component)
- Integration testing
```

**Time:** 15-30 minutes

### Step 3: Define Tasks

**Action:** Create task for each component/boundary

**For each task, specify:**
1. Clear title and description
2. Specific files to create/modify
3. Acceptance criteria (from spec + technical requirements)
4. Estimated effort
5. Dependencies on other tasks

**Task Template:**
```markdown
### Task [N]: [Component Name]

**ID:** TASK-00[N]
**Title:** Implement [specific component]
**Component:** [File path]
**Estimated Effort:** [Small/Medium/Large]
**Dependencies:** [Task IDs or "None"]

**Description:**
Implement [component] that [does what]. This component [responsibility].

**Acceptance Criteria:**
- [ ] [Specific testable criterion 1]
- [ ] [Specific testable criterion 2]
- [ ] [Specific testable criterion 3]

**Files to Modify/Create:**
- `path/to/implementation.py` (create)
- `path/to/tests/test_implementation.py` (create)

**Testing Requirements:**
- Unit tests with mocked dependencies
- [Any integration tests needed]
```

**Time:** 2-4 hours

### Step 4: Map Dependencies

**Action:** Identify which tasks must happen before others

**Create dependency graph:**
- Foundation tasks (no dependencies)
- Layer 2 tasks (depend on foundation)
- Layer 3 tasks (depend on layer 2)
- Integration tasks (depend on multiple components)

**Example:**
```
TASK-001: Database schema (no dependencies)
    └─> TASK-002: Repository (depends on schema)
            └─> TASK-003: Service (depends on repository)
                    └─> TASK-004: API (depends on service)
                            └─> TASK-005: UI (depends on API)

Parallel tracks:
TASK-001 (Database)
    ├─> TASK-002 (Repository)
    └─> TASK-006 (Client library)

TASK-002 + TASK-006
    └─> TASK-003 (Service)
```

**Time:** 30-60 minutes

### Step 5: Validate Against Spec

**Action:** Ensure all spec requirements are covered by tasks

**Check:**
- Each acceptance criterion addressed by at least one task
- User journeys have corresponding implementation tasks
- Success metrics are measurable after tasks complete
- Out-of-scope items are not included

**Example:**
```
Spec Requirement: "Query all regions simultaneously"
Covered by: TASK-003 (QueryCoordinator with parallel execution)

Spec Requirement: "Timeout protection (30s)"
Covered by: TASK-003 (QueryCoordinator timeout handling)

Spec Requirement: "Graceful partial failure handling"
Covered by: TASK-004 (API error response formatting)
```

**Time:** 30 minutes

### Step 6: Size and Estimate

**Action:** Estimate effort for each task using sizing guidelines

**Apply sizing factors:**
- Code complexity
- File count (1-3 files = good task size)
- Testing effort
- Integration points
- Risk/unknowns

**Guidelines:**
- Small: 1-2 days (1-2 files, simple logic)
- Medium: 2-4 days (2-3 files, moderate complexity)
- Large: 3-5 days (3-5 files, complex logic)
- If > 5 days: Split the task

**Example:**
```
TASK-001: Database Migration
- 1 file (migration)
- Simple schema change
- Standard Django migration
Estimate: Small (0.5 days)

TASK-003: QueryCoordinator Service
- 2 files (service + tests)
- Complex async logic (Twisted Deferreds)
- Multiple integration points
- Timeout handling
Estimate: Large (4 days)
```

**Time:** 30-60 minutes

### Step 7: Review and Refine

**Action:** Check for issues and optimize task breakdown

**Look for:**
- Tasks that are too large (split them)
- Tasks that are too small (combine them)
- Missing dependencies
- Unrealistic estimates
- Opportunities for parallelization

**Adjust as needed**

**Time:** 30 minutes

## MAAS-Specific Examples

### Example 1: Multi-Region Query Feature

**Context:**
- Spec: Multi-region machine query capability
- Plan: QueryCoordinator service with parallel regional API calls

**Task Breakdown:**

```markdown
# Tasks: Multi-Region Query

**Total Estimated Effort:** 18 days (across 3 developers)

---

### Task 1: Database Schema for Region Tracking

**ID:** TASK-001
**Estimated Effort:** Small (1 day)
**Dependencies:** None

**Description:**
Add database fields to track regional controller endpoints and credentials.

**Acceptance Criteria:**
- [ ] Region model has endpoint URL field
- [ ] Region model has authentication credentials (encrypted)
- [ ] Migration created and tested
- [ ] Factory fixtures updated for tests

**Files to Modify/Create:**
- `src/maasserver/models/region.py` (modify)
- `src/maasserver/migrations/0234_add_region_endpoint.py` (create)
- `src/maasserver/tests/test_models_region.py` (modify)

---

### Task 2: Regional Query Client

**ID:** TASK-002
**Estimated Effort:** Medium (3 days)
**Dependencies:** TASK-001

**Description:**
Implement HTTP client for querying individual regional controllers.

**Acceptance Criteria:**
- [ ] Client can authenticate with regional controller
- [ ] Client can execute machine queries against regional API
- [ ] Client handles connection failures gracefully
- [ ] Client respects timeout configuration
- [ ] Full unit test coverage with mocked HTTP

**Files to Modify/Create:**
- `src/maasserver/clients/regional_client.py` (create)
- `src/maasserver/tests/test_regional_client.py` (create)

---

### Task 3: Query Coordinator Service

**ID:** TASK-003
**Estimated Effort:** Large (4 days)
**Dependencies:** TASK-002

**Description:**
Implement service that coordinates parallel queries across all regions.

**Acceptance Criteria:**
- [ ] Queries all registered regions in parallel using DeferredList
- [ ] Applies consistent timeout (30s default, configurable)
- [ ] Continues even if some regions fail
- [ ] Returns results from successful regions
- [ ] Logs failures for debugging
- [ ] Unit tests with mocked clients
- [ ] Integration tests with real database

**Files to Modify/Create:**
- `src/maasserver/services/query_coordinator.py` (create)
- `src/maasserver/tests/test_query_coordinator.py` (create)
- `src/maasserver/tests/integration/test_query_coordinator_integration.py` (create)

---

### Task 4: Result Merger Utility

**ID:** TASK-004
**Estimated Effort:** Medium (2 days)
**Dependencies:** TASK-003

**Description:**
Implement utility to merge, deduplicate, and sort results from multiple regions.

**Acceptance Criteria:**
- [ ] Merges results from multiple regions into single list
- [ ] Removes duplicate machines (by system_id)
- [ ] Sorts by configurable field (default: hostname)
- [ ] Preserves region information for each result
- [ ] Handles empty result sets
- [ ] Full unit test coverage

**Files to Modify/Create:**
- `src/maasserver/utils/result_merger.py` (create)
- `src/maasserver/tests/test_result_merger.py` (create)

---

### Task 5: Multi-Region API Endpoint

**ID:** TASK-005
**Estimated Effort:** Medium (3 days)
**Dependencies:** TASK-003, TASK-004

**Description:**
Expose multi-region query capability via REST API.

**Acceptance Criteria:**
- [ ] GET /api/2.0/regions/machines endpoint created
- [ ] Accepts query filters (status, zone, tags)
- [ ] Returns merged results from all regions
- [ ] Returns 200 with results on success
- [ ] Returns 400 on invalid filters
- [ ] Returns 500 on complete failure
- [ ] Returns 207 (Multi-Status) on partial failure
- [ ] API tests cover success and error cases

**Files to Modify/Create:**
- `src/maasserver/api/multi_region.py` (create)
- `src/maasserver/tests/test_api_multi_region.py` (create)
- `src/maasserver/urls.py` (modify - add route)

---

### Task 6: React Multi-Region Search Component

**ID:** TASK-006
**Estimated Effort:** Large (4 days)
**Dependencies:** TASK-005

**Description:**
Create React component for multi-region machine search UI.

**Acceptance Criteria:**
- [ ] Search input with filters (status, zone, tags)
- [ ] Results table shows machines from all regions
- [ ] Region column indicates source region
- [ ] Loading state during query
- [ ] Error message on complete failure
- [ ] Warning banner on partial failure
- [ ] Component tests using React Testing Library
- [ ] Accessibility: keyboard navigation, ARIA labels

**Files to Modify/Create:**
- `src/maasui/src/app/machines/MultiRegionSearch.tsx` (create)
- `src/maasui/src/app/machines/MultiRegionSearch.test.tsx` (create)
- `src/maasui/src/app/machines/components/RegionBadge.tsx` (create)

---

### Task 7: End-to-End Integration Testing

**ID:** TASK-007
**Estimated Effort:** Small (1 day)
**Dependencies:** TASK-005, TASK-006

**Description:**
Create end-to-end tests validating complete workflow.

**Acceptance Criteria:**
- [ ] Test setup creates multi-region environment
- [ ] Test validates API query returns results from all regions
- [ ] Test validates partial failure handling
- [ ] Test validates timeout behavior
- [ ] Tests run in CI/CD pipeline

**Files to Modify/Create:**
- `src/maasserver/tests/e2e/test_multi_region_query.py` (create)

---

## Task Dependencies

```
TASK-001 (Database Schema)
    └─> TASK-002 (Regional Client)
            └─> TASK-003 (Query Coordinator)
                    ├─> TASK-004 (Result Merger)
                    └─> TASK-005 (API Endpoint)
                            └─> TASK-006 (React UI)

TASK-005 + TASK-006
    └─> TASK-007 (E2E Tests)
```

---

## Sprint Allocation

**Sprint 1 (Weeks 1-2): Backend Foundation**
- TASK-001: Database Schema (Dev A, 1 day)
- TASK-002: Regional Client (Dev A, 3 days)
- TASK-003: Query Coordinator (Dev B, 4 days)
- TASK-004: Result Merger (Dev A, 2 days)

**Sprint 2 (Weeks 3-4): API & UI**
- TASK-005: API Endpoint (Dev B, 3 days)
- TASK-006: React Component (Dev C, 4 days)
- TASK-007: E2E Tests (Dev A, 1 day)

**Total: 18 developer-days across 3 developers = 2.5 weeks**
```

### Example 2: BMC Power Control Refactoring

**Context:**
- Spec: Modernize BMC power control to support new protocols
- Plan: Adapter pattern with protocol-specific implementations

**Task Breakdown:**

```markdown
# Tasks: BMC Power Control Refactoring

---

### Task 1: Define PowerControl Interface

**ID:** TASK-001
**Estimated Effort:** Small (1 day)
**Dependencies:** None

**Description:**
Create abstract base class defining power control interface.

**Acceptance Criteria:**
- [ ] Abstract class with power_on, power_off, power_status methods
- [ ] Type hints for all methods
- [ ] Docstrings documenting expected behavior
- [ ] Raises NotImplementedError for unimplemented methods

**Files to Create:**
- `src/maasserver/power/base.py` (create)
- `src/maasserver/tests/test_power_base.py` (create)

---

### Task 2: Implement IPMI Adapter

**ID:** TASK-002
**Estimated Effort:** Medium (2 days)
**Dependencies:** TASK-001

**Description:**
Implement power control adapter for IPMI protocol.

**Acceptance Criteria:**
- [ ] Implements PowerControl interface
- [ ] Uses existing IPMI library
- [ ] Handles authentication errors
- [ ] Handles timeout errors
- [ ] Full unit test coverage with mocked IPMI calls

**Files to Create:**
- `src/maasserver/power/ipmi.py` (create)
- `src/maasserver/tests/test_power_ipmi.py` (create)

---

### Task 3: Implement Redfish Adapter

**ID:** TASK-003
**Estimated Effort:** Medium (3 days)
**Dependencies:** TASK-001

**Description:**
Implement power control adapter for Redfish protocol.

[Similar structure to TASK-002]

---

### Task 4: Power Control Factory

**ID:** TASK-004
**Estimated Effort:** Small (1 day)
**Dependencies:** TASK-002, TASK-003

**Description:**
Create factory to instantiate correct adapter based on BMC type.

[Detailed acceptance criteria]

---

[More tasks...]
```

## Common Pitfalls

### ❌ Tasks Too Large

**Problem:** Task estimated at 2 weeks of work

```markdown
### Task 1: Implement Complete Multi-Region Feature

**Estimated Effort:** 10 days
**Files:** 15+ files across backend, API, and UI
```

**Solution:** Split into smaller tasks (1-5 days each)

```markdown
### Task 1: Backend Service
**Estimated Effort:** 3 days

### Task 2: API Endpoint
**Estimated Effort:** 2 days

### Task 3: UI Component
**Estimated Effort:** 3 days
```

### ❌ Tasks Too Small

**Problem:** Task is just 2 hours of work

```markdown
### Task 1: Add Import Statement
**Estimated Effort:** 0.25 days
```

**Solution:** Combine with related work

```markdown
### Task 1: Implement Result Merger
- Includes all necessary imports, utilities, and tests
**Estimated Effort:** 2 days
```

### ❌ Vague Acceptance Criteria

**Problem:** Can't determine when task is done

```markdown
**Acceptance Criteria:**
- [ ] Code works well
- [ ] Tests pass
- [ ] No bugs
```

**Solution:** Specific, testable criteria

```markdown
**Acceptance Criteria:**
- [ ] QueryCoordinator.query_all() returns results from all 3 regions
- [ ] Timeout of 30s is enforced (test with delayed mock)
- [ ] Partial failures return 207 status with successful results
- [ ] Unit test coverage > 90%
```

### ❌ Missing Dependencies

**Problem:** Can't start task because prerequisite not identified

```markdown
### Task 5: API Endpoint
**Dependencies:** None

[But actually needs service layer from Task 3]
```

**Solution:** Explicit dependency mapping

```markdown
### Task 5: API Endpoint
**Dependencies:** TASK-003 (QueryCoordinator Service)
```

### ❌ No Test Requirements

**Problem:** Tests forgotten or vague

```markdown
**Testing Requirements:** Add tests
```

**Solution:** Specific test requirements

```markdown
**Testing Requirements:**
- Unit tests with mocked RegionalClient (100% coverage)
- Integration tests with test database
- Error case tests (timeout, connection failure, auth failure)
```

## Resources

**Reference:**
- `.sdd/skills/task-sizing.md` - Detailed sizing guidelines
- `.sdd/validation/task-checklist.md` - Task quality validation
- `.sdd/templates/task-template.md` - Blank task template

**Tools:**
- GitHub Issues / Jira for task tracking
- Dependency graphing tools (Graphviz, Mermaid)
- Estimation poker for team sizing

## Next Steps

**After task decomposition:**

1. **Review with team** - Validate estimates and dependencies
2. **Get approval** - Technical lead or manager signs off
3. **Assign tasks** - Distribute based on skills and capacity
4. **Begin implementation** - Use `.sdd/commands/implement.md`
5. **Track progress** - Update task status as work progresses

**Invoke implementation command:**
```
I'm ready to implement a task.

Task: TASK-003 (Query Coordinator Service)
Specification: .sdd/specs/multi-region-query.md
Technical Plan: .sdd/plans/multi-region-query.md

Please guide me through implementation using the SDD process.
```

## Summary

Effective task decomposition:

1. **Reviews spec and plan** to understand requirements and architecture
2. **Identifies natural boundaries** for logical task separation
3. **Defines clear tasks** with specific acceptance criteria and file lists
4. **Maps dependencies** to enable parallel work
5. **Validates coverage** ensuring all requirements addressed
6. **Sizes appropriately** for 1-5 day implementation windows
7. **Enables tracking** with measurable progress indicators

Good task decomposition enables efficient parallel development, clear progress tracking, and successful feature delivery.