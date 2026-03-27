# Dependency Mapping for MAAS

## Overview

Dependency mapping is the process of identifying and documenting relationships between tasks, creating a Directed Acyclic Graph (DAG) that shows which tasks must complete before others can start. Effective dependency mapping enables parallel execution, identifies critical paths, and prevents bottlenecks in implementation.

## Purpose

- **Enable parallel work**: Identify tasks that can run concurrently
- **Identify critical path**: Find the longest sequential chain determining project duration
- **Prevent blocking**: Ensure developers don't wait unnecessarily
- **Optimize scheduling**: Sequence work for maximum efficiency
- **Surface integration points**: Make component interactions explicit
- **Detect circular dependencies**: Find and resolve impossible task orders

## Core Concepts

### What is a Task Dependency?

**Task B depends on Task A** means:
- Task B cannot start until Task A completes
- Task A produces output that Task B requires
- Task B needs to see, use, or build upon Task A's work

### Dependency Types

**Hard Dependency (Required):**
- Task B literally cannot proceed without Task A
- Task A produces artifacts Task B consumes
- Example: Repository depends on database schema

**Soft Dependency (Beneficial):**
- Task B can proceed with mocks/stubs, but integration requires Task A
- Task B benefits from Task A being done first
- Example: API endpoint can mock service layer initially

**Ordering Dependency (Logical):**
- Makes sense to do Task A before Task B, but not strictly required
- Example: Implement core logic before optimization

### DAG Properties

**Directed:** Dependencies have direction (A → B, not B → A)

**Acyclic:** No circular dependencies (A → B → C → A is invalid)

**Graph:** Visual representation of task relationships

```
Valid DAG:
A → B → D
A → C → D
(B and C can run in parallel)

Invalid (Cyclic):
A → B → C → A
(Circular dependency)
```

## Dependency Identification Process

### Step 1: List All Tasks

Start with complete task list:
- Task ID, description
- Files modified
- Acceptance criteria

### Step 2: Identify Prerequisites for Each Task

For each task, ask:

**What must exist before this task can start?**
- Code/files from other tasks
- APIs or interfaces
- Database schemas
- Configuration
- Test infrastructure

**What inputs does this task need?**
- Data structures
- Function signatures
- API contracts
- Database tables

**What knowledge is required?**
- Understanding of other components
- Integration patterns
- Performance characteristics

### Step 3: Document Dependencies

For each dependency, record:
- **From Task**: Task that produces the artifact
- **To Task**: Task that consumes it
- **Artifact**: What's being passed
- **Type**: Hard, soft, or ordering
- **Reason**: Why this dependency exists

**Example:**
```
Dependency: TASK-002 → TASK-004
From: TASK-002 (Implement Repository)
To: TASK-004 (Implement Service)
Artifact: RegionRepository class with get_all(), get_by_id() methods
Type: Hard
Reason: Service needs repository to access database
```

### Step 4: Draw the Graph

Visualize dependencies:
- Nodes = Tasks
- Edges = Dependencies (arrows)
- Group parallel tasks visually
- Highlight critical path

### Step 5: Validate the DAG

Check for:
- Circular dependencies (none should exist)
- Missing dependencies (edges not drawn)
- Unnecessary dependencies (can be removed)
- Critical path length (optimize if too long)

## Dependency Patterns in MAAS

### Pattern 1: Layer Dependencies

**Database → Repository → Service → API → UI**

```
TASK-001: Database Schema
    ↓
TASK-002: Repository
    ↓
TASK-003: Service
    ↓
TASK-004: API Endpoint
    ↓
TASK-005: UI Component
```

**Characteristics:**
- Strict sequential ordering
- Each layer depends on the one below
- Long critical path
- Limited parallelism

**When to use:**
- Small features (few tasks)
- Tight integration required
- Learning new codebase (build layer by layer)

**When to avoid:**
- Large features (creates bottleneck)
- Multiple developers (limits concurrency)

### Pattern 2: Interface-Based Parallelism

**Define interfaces early, implement in parallel**

```
TASK-001: Define Repository Interface
    ↓
    ├─→ TASK-002: Implement Repository
    └─→ TASK-003: Implement Service (mocks repository)
    
TASK-002 + TASK-003 → TASK-004: Integration
```

**Characteristics:**
- Interface defined first
- Implementations in parallel
- Integration task at end
- Shorter critical path

**Benefits:**
- Backend and frontend can work simultaneously
- Reduces waiting
- Clear contracts between components

### Pattern 3: Parallel Streams

**Independent work streams with minimal dependencies**

```
Stream 1 (Backend):
TASK-001 → TASK-002 → TASK-003

Stream 2 (Frontend):
TASK-004 → TASK-005 → TASK-006

Stream 3 (Testing):
TASK-007 → TASK-008

(All streams merge at)
    ↓
TASK-009: Integration Test
```

**Characteristics:**
- Multiple independent chains
- Parallel execution
- Final integration task
- Short critical path

**Benefits:**
- Maximum parallelism
- Fast overall completion
- Good for distributed teams

### Pattern 4: Foundation + Parallel Build

**Common foundation, then parallel specialization**

```
TASK-001: Database Schema
    ↓
    ├─→ TASK-002: Read API
    ├─→ TASK-003: Write API
    └─→ TASK-004: Health Check
    
All → TASK-005: Integration
```

**Characteristics:**
- Shared foundation task
- Multiple dependent tasks in parallel
- Integration at end

**Benefits:**
- Establishes common ground
- Then maximizes parallelism
- Balanced approach

## Techniques for Minimizing Dependencies

### Technique 1: Mock Dependencies

**Instead of waiting for Task A, mock it in Task B**

**Before:**
```
TASK-001: Implement Service
    ↓
TASK-002: Implement API Endpoint
(API must wait for Service)
```

**After:**
```
TASK-001: Implement Service
TASK-002: Implement API Endpoint (mock Service)
    ↓
TASK-003: Integration (connect real Service)
```

**Benefits:**
- Tasks run in parallel
- Earlier testing of API layer
- Clear integration point

**Cost:**
- Additional integration task
- Mock maintenance

### Technique 2: Interface Definition Tasks

**Create explicit interface definition tasks**

**Before:**
```
TASK-001: Implement entire Repository
    ↓
TASK-002: Implement Service using Repository
```

**After:**
```
TASK-001: Define Repository interface (signatures, docstrings)
    ↓
    ├─→ TASK-002: Implement Repository
    └─→ TASK-003: Implement Service (code to interface)
```

**Benefits:**
- Contract established early
- Parallel implementation
- Clear expectations

### Technique 3: Split by Layer

**Separate data, logic, and presentation**

**Before:**
```
TASK-001: Build entire feature (database + API + UI)
(One large task, no parallelism)
```

**After:**
```
TASK-001: Database schema
    ↓
TASK-002: Backend API
    ↓
TASK-003: Frontend UI (can mock API from start)
```

**Benefits:**
- Each layer can have different owner
- Frontend starts earlier with mocks
- Smaller, testable tasks

### Technique 4: Separate Read and Write Paths

**Split CRUD operations into independent tasks**

**Before:**
```
TASK-001: Implement all CRUD operations
```

**After:**
```
TASK-001: Database schema
    ↓
    ├─→ TASK-002: Implement read operations
    └─→ TASK-003: Implement write operations
(Tasks 2 and 3 can run in parallel)
```

**Benefits:**
- Reads and writes often independent
- Different complexity levels
- Parallel development

### Technique 5: Defer Optimization

**Separate core functionality from optimization**

**Before:**
```
TASK-001: Implement query with caching, optimization, monitoring
(Large, complex task)
```

**After:**
```
TASK-001: Implement basic query
TASK-002: Add caching (depends on TASK-001)
TASK-003: Performance optimization (depends on TASK-001)
TASK-004: Add monitoring (depends on TASK-001)
(Tasks 2, 3, 4 can run in parallel after 1)
```

**Benefits:**
- Core functionality delivered early
- Enhancements in parallel
- Easier to prioritize

## Critical Path Analysis

### What is the Critical Path?

**The longest sequential chain of tasks that determines minimum project duration.**

Example:
```
Path 1: A → B → C = 6 days
Path 2: A → D → E → F = 8 days (CRITICAL PATH)
Path 3: G → H = 3 days

Project duration: 8 days (determined by Path 2)
```

### Identifying the Critical Path

**Algorithm:**
1. List all possible paths from start to finish
2. Calculate duration of each path (sum of task estimates)
3. Longest path is the critical path

**Example:**
```
Graph:
TASK-001 (2d) → TASK-002 (3d) → TASK-005 (2d)
TASK-001 (2d) → TASK-003 (1d) → TASK-004 (2d) → TASK-005 (2d)

Paths:
Path A: 1 → 2 → 5 = 2+3+2 = 7 days
Path B: 1 → 3 → 4 → 5 = 2+1+2+2 = 7 days

Both are critical paths (tied at 7 days)
```

### Optimizing the Critical Path

**Strategies to shorten:**

1. **Split large tasks on critical path**
   - Large task (5d) → Two smaller tasks (2d + 2d with second in parallel)

2. **Remove unnecessary dependencies**
   - If Task B doesn't really need Task A, remove dependency

3. **Add resources to critical tasks**
   - Pair programming on critical path tasks
   - Assign best developers to critical tasks

4. **Move tasks off critical path**
   - Reorder if possible
   - Start earlier if dependencies allow

5. **Parallelize sequential tasks**
   - Use mocking to enable parallel work

**Example:**
```
Before (Critical Path = 8 days):
A (2d) → B (3d) → C (3d)

After (Critical Path = 5 days):
A (2d) → B (2d) → D (1d)
     → C (2d) ↗

(B and C now parallel, B split into B+D)
```

## Circular Dependency Detection and Resolution

### Detecting Circular Dependencies

**Signs of circular dependencies:**
- Task A depends on Task B, Task B depends on Task A
- Longer cycles: A → B → C → D → A
- Cannot determine which task to do first

**Detection Method:**
1. Start at any task
2. Follow dependencies
3. If you return to starting task, cycle exists

**Example:**
```
Circular:
TASK-001: API Endpoint (needs Service)
    ↓
TASK-002: Service (needs API Endpoint for callback)
    ↓
TASK-001: (cycle detected!)
```

### Resolving Circular Dependencies

**Strategy 1: Break the Cycle with Interface**

**Before:**
```
A needs B's output
B needs A's output
(Circular)
```

**After:**
```
TASK-000: Define interface
    ↓
    ├─→ TASK-A: Implements interface
    └─→ TASK-B: Implements interface
Both → TASK-C: Connect implementations
```

**Strategy 2: Reorder Operations**

**Before:**
```
Initialize A (needs config from B)
Initialize B (needs data from A)
```

**After:**
```
Load configuration
Initialize A
Initialize B
Connect A and B
```

**Strategy 3: Use Dependency Injection**

**Before:**
```
Service creates Repository (needs database connection)
Repository needs Service for callbacks
```

**After:**
```
Create Repository
Create Service with Repository injected
Register callbacks
```

**Strategy 4: Extract Common Dependency**

**Before:**
```
A depends on B
B depends on A
```

**After:**
```
Extract shared component C
A depends on C
B depends on C
(No cycle)
```

## Dependency Matrix

### Creating a Dependency Matrix

**Table showing which tasks depend on which:**

|        | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|--------|----------|----------|----------|----------|
| TASK-001 |    -     |          |          |          |
| TASK-002 |    X     |    -     |          |          |
| TASK-003 |    X     |          |    -     |          |
| TASK-004 |          |    X     |    X     |    -     |

**Read as:** "TASK-002 depends on TASK-001" (X in row 2, column 1)

**Benefits:**
- Easy to spot circular dependencies (X above and below diagonal)
- See all dependencies for a task (read across row)
- See which tasks depend on a task (read down column)

### Analyzing the Matrix

**Column totals:** How many tasks depend on this task
- High count = critical bottleneck
- Should complete this task early

**Row totals:** How many dependencies this task has
- High count = can only start late
- Consider splitting or removing dependencies

## Visualization Techniques

### ASCII Graph

```
TASK-001: Database Schema
    ↓
    ├─→ TASK-002: Repository
    │       ↓
    │   TASK-004: Service
    │       ↓
    │   TASK-006: API Endpoint
    │
    └─→ TASK-003: Health Monitor

TASK-005: UI Component (independent)
    ↓
TASK-007: UI Integration

TASK-006 + TASK-007 → TASK-008: E2E Test
```

### Gantt-Style Dependency View

```
Week 1          Week 2          Week 3
|---------------|---------------|---------------|
TASK-001 ███
         TASK-002 ████
                  TASK-004 ████
         TASK-003 ████████████
                          TASK-006 ███
TASK-005 ███████
                  TASK-007 ███
                              TASK-008 ████
```

### Layer Diagram

```
┌─────────────────────────────────────┐
│ Layer 5: Integration                │
│ TASK-008: E2E Test                  │
└─────────────────────────────────────┘
           ↑
┌─────────────────────────────────────┐
│ Layer 4: Presentation               │
│ TASK-006: API     TASK-007: UI      │
└─────────────────────────────────────┘
           ↑
┌─────────────────────────────────────┐
│ Layer 3: Business Logic             │
│ TASK-004: Service                   │
└─────────────────────────────────────┐
           ↑
┌─────────────────────────────────────┐
│ Layer 2: Data Access                │
│ TASK-002: Repository                │
└─────────────────────────────────────┘
           ↑
┌─────────────────────────────────────┐
│ Layer 1: Data Storage               │
│ TASK-001: Database Schema           │
└─────────────────────────────────────┘
```

## MAAS-Specific Dependency Patterns

### Pattern: Database-First

```
TASK-001: Database schema/migration
    ↓
    ├─→ TASK-002: Django models
    │       ↓
    │   TASK-003: Repository
    │       ↓
    │   TASK-004: Service
    │       ↓
    │   TASK-005: API
    │
    └─→ TASK-006: Admin interface (can be parallel)
```

**Critical Path:** 1 → 2 → 3 → 4 → 5 (5 sequential tasks)

### Pattern: API-First (Frontend Parallel)

```
Backend Stream:
TASK-001: API contract definition
    ↓
    ├─→ TASK-002: Backend implementation
    │
    └─→ TASK-003: Frontend (mock API)

TASK-002 + TASK-003 → TASK-004: Integration
```

**Critical Path:** 1 → 2 → 4 (3 sequential tasks)
**Parallel:** Task 2 and 3 run simultaneously

### Pattern: Test Infrastructure Early

```
TASK-001: Test infrastructure setup
    ↓
    ├─→ TASK-002: Component A + Tests
    ├─→ TASK-003: Component B + Tests
    └─→ TASK-004: Component C + Tests

All → TASK-005: Integration Tests
```

**Benefits:**
- Testing patterns established early
- All developers use consistent test approach
- Parallel component development

## Dependency Checklist

When analyzing task dependencies, verify:

- [ ] **All prerequisites identified**: Each task lists what it needs
- [ ] **Dependencies are justified**: Each dependency has clear reason
- [ ] **No circular dependencies**: DAG is valid (acyclic)
- [ ] **Critical path identified**: Longest chain documented
- [ ] **Parallel opportunities maximized**: Independent tasks flagged
- [ ] **Hard vs soft dependencies distinguished**: Mock opportunities identified
- [ ] **Interface tasks added**: Enables parallel work
- [ ] **Integration tasks included**: Dependencies connected at end
- [ ] **Dependencies in task description**: Clearly documented
- [ ] **Graph is visualized**: Team can see structure

## Common Mistakes

### ❌ Over-Dependency

**Problem:** Creating unnecessary dependencies

**Example:**
```
"TASK-003 depends on TASK-002 because we should do them in order"
(But TASK-003 doesn't actually use TASK-002's output)
```

**Fix:** Only create dependencies when truly required

### ❌ Under-Specification

**Problem:** Not documenting dependencies

**Example:**
```
Task list has no dependencies marked
(Team discovers dependencies during implementation)
```

**Fix:** Explicitly analyze and document all dependencies

### ❌ Integration Forgotten

**Problem:** Parallel tasks with no integration task

**Example:**
```
Backend (mocked) ✓
Frontend (mocked) ✓
Integration task? ✗
```

**Fix:** Always add integration task when using mocks

### ❌ Assuming Sequential

**Problem:** Making all tasks sequential by default

**Example:**
```
TASK-001 → TASK-002 → TASK-003 → TASK-004
(When 2 and 3 could be parallel)
```

**Fix:** Identify truly independent tasks

### ❌ Giant Integration Task

**Problem:** All parallel tasks depend on one huge integration task

**Example:**
```
10 parallel tasks → 1 mega-integration task (10 days)
(Critical path includes massive integration)
```

**Fix:** Break integration into smaller, incremental tasks

## Summary

Effective dependency mapping requires:

1. **Identify all dependencies systematically**: What does each task need?
2. **Distinguish dependency types**: Hard, soft, ordering
3. **Create valid DAG**: No circular dependencies
4. **Optimize critical path**: Minimize longest sequential chain
5. **Maximize parallelism**: Use mocks, interfaces, separate streams
6. **Visualize clearly**: Graph, matrix, or timeline
7. **Document explicitly**: Dependencies in task specs
8. **Validate with team**: Review for accuracy
9. **Update as needed**: Dependencies may change during implementation

A well-mapped dependency graph enables efficient parallel execution, prevents bottlenecks, and provides clear visibility into project structure and timeline. The goal is maximum parallelism while respecting true technical dependencies.