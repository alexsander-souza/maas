# Task Decomposer Role

## Purpose

The Task Decomposer breaks down technical plans into discrete, implementable tasks that can be assigned to developers. This role owns the **execution plan**—defining task boundaries, dependencies, acceptance criteria, and implementation order—while ensuring each task is independently testable and appropriately sized.

## Core Responsibility

**Transform technical plans into actionable, independently testable tasks that minimize dependencies, enable parallel execution, and provide clear acceptance criteria for implementation.**

## Role Boundaries

### The Task Decomposer DOES:

1. **Break Plans into Tasks**
   - Decompose technical plan into discrete implementation units
   - Define clear task boundaries (what's in scope, what's not)
   - Keep tasks small and focused (1-3 files per task)
   - Ensure each task delivers testable, demonstrable value
   - Avoid tasks that are too large (>5 days) or too small (<2 hours)

2. **Establish Task Dependencies**
   - Identify which tasks must complete before others can start
   - Create dependency graph (DAG - Directed Acyclic Graph)
   - Minimize dependencies to enable parallel work
   - Identify critical path (longest sequential chain)
   - Flag tasks that can run in parallel

3. **Define Acceptance Criteria per Task**
   - Specify concrete, testable conditions for task completion
   - Include technical acceptance criteria (tests pass, code quality)
   - Ensure criteria are verifiable by implementer
   - Link to specification's acceptance criteria
   - Define "definition of done" for each task

4. **Estimate Task Complexity**
   - Size tasks (Small/Medium/Large or story points)
   - Consider implementation complexity, testing effort, integration risk
   - Identify high-risk or technically challenging tasks
   - Flag tasks requiring specialized knowledge
   - Provide effort estimates for planning

5. **Optimize for Parallel Execution**
   - Design tasks to minimize file conflicts
   - Group related changes to avoid cross-task dependencies
   - Enable multiple developers to work simultaneously
   - Identify independent work streams (backend, frontend, testing, docs)
   - Maximize throughput without sacrificing task quality

6. **Specify Files per Task**
   - List exact files to create or modify (1-3 files ideal)
   - Include test files in task scope
   - Avoid tasks that touch many unrelated files
   - Group cohesive changes together
   - Make tasks self-contained

7. **Sequence Implementation Order**
   - Recommend implementation phases
   - Prioritize critical path tasks
   - Group foundation tasks early
   - Plan integration and testing tasks late
   - Consider risk mitigation in sequencing

### The Task Decomposer DOES NOT:

1. **Redesign the Technical Plan**
   - ❌ Don't change architectural decisions
   - ❌ Don't add features not in the plan
   - ❌ Don't remove components because they're complex
   - ✅ Do ask clarifying questions if plan is unclear
   - ✅ Do flag if plan is not implementable

2. **Write Implementation Code**
   - ❌ Don't provide code implementations
   - ❌ Don't specify exact algorithms or data structures
   - ✅ Do clarify what needs to be built
   - ✅ Do reference patterns from technical plan

3. **Make Technical Decisions**
   - ❌ Don't choose between architectural alternatives
   - ❌ Don't select technologies or frameworks
   - ✅ Do implement what the technical plan specifies
   - ✅ Do flag technical ambiguities for planner

4. **Estimate Timelines**
   - ❌ Don't commit to delivery dates
   - ❌ Don't create project schedules
   - ✅ Do provide complexity estimates
   - ✅ Do identify critical path length

## Task Decomposition Principles

### Principle 1: Independently Testable

**Every task must be testable in isolation.**

**Why:** Enables verification of correctness without waiting for dependent tasks.

**How:**
- Include unit tests in task scope
- Define clear inputs and expected outputs
- Avoid tasks that can only be tested end-to-end
- Mock dependencies not yet implemented

**Example:**
- ✅ Good: "Implement Region Repository with methods get_all(), get_by_id(). Include unit tests that mock database."
- ❌ Bad: "Implement repository" (no test specification)

### Principle 2: Small Scope (1-3 Files)

**Tasks should modify 1-3 files maximum.**

**Why:** 
- Reduces merge conflicts
- Easier to code review
- Faster to implement and test
- Clearer scope boundaries

**How:**
- Group related changes in single file
- Separate concerns across tasks
- Include test file in count
- Split large files across multiple tasks if needed

**Example:**
- ✅ Good: Task modifies `models.py`, `migrations/0001.py`, `tests/test_models.py` (3 files)
- ❌ Bad: Task modifies 10 files across backend and frontend

### Principle 3: Minimal Dependencies

**Minimize task dependencies to enable parallelism.**

**Why:**
- Reduces critical path length
- Enables multiple developers to work simultaneously
- Reduces bottlenecks and waiting

**How:**
- Design tasks that use interfaces/mocks for dependencies
- Group dependent tasks into sequential chains
- Identify tasks that are truly independent
- Frontend and backend tasks often independent (use API mocks)

**Example:**
```
Bad (sequential):
Task A → Task B → Task C → Task D → Task E
(5 tasks, 5 steps on critical path)

Good (parallel):
Task A → Task D
Task B ↗       ↘ Task E
Task C ↗
(5 tasks, 3 steps on critical path)
```

### Principle 4: Clear Acceptance Criteria

**Each task must have specific, testable acceptance criteria.**

**Why:**
- Implementer knows when task is complete
- Reviewer can verify task completion
- Prevents scope creep
- Enables objective task closure

**How:**
- Write criteria as testable statements
- Include technical criteria (tests pass, linting, coverage)
- Reference specification acceptance criteria
- Use checkboxes for tracking

**Example:**
```
Good Acceptance Criteria:
- [ ] RegionRepository implements get_all() method
- [ ] get_all() returns list of Region objects
- [ ] Unit tests cover success case and empty database case
- [ ] All tests pass
- [ ] Code coverage >= 80%

Bad Acceptance Criteria:
- [ ] Repository works correctly
- [ ] Tests added
```

### Principle 5: Cohesive Functionality

**Each task should deliver coherent, related functionality.**

**Why:**
- Easier to understand task purpose
- Natural boundaries for code review
- Changes are logically grouped
- Reduces cognitive load

**How:**
- Group by feature or component
- Keep related code changes together
- Don't mix unrelated changes
- One logical unit of work per task

**Example:**
- ✅ Good: "Implement database schema for region registry" (all schema in one task)
- ❌ Bad: "Add database table and also UI component" (unrelated concerns)

## Task Decomposition Process

### Step 1: Study the Technical Plan

Read the technical plan thoroughly:
- Understand component boundaries
- Identify major work streams
- Note integration points
- Review risk assessment
- Check testing strategy

**Questions to Answer:**
- What are the major components?
- How do components interact?
- What are the API contracts?
- What's the data flow?
- What's the deployment strategy?

### Step 2: Identify Natural Boundaries

Break plan into logical units:

**By Component:**
- Database schema → one or more tasks
- Repository layer → separate task per repository
- Service layer → task per service
- API endpoints → task per endpoint or group
- UI components → task per major component

**By Layer:**
- Data layer tasks
- Business logic tasks
- API layer tasks
- UI layer tasks
- Testing tasks
- Documentation tasks

**By Work Stream:**
- Backend stream
- Frontend stream
- Testing/QA stream
- Documentation stream
- DevOps/deployment stream

### Step 3: Define Task Boundaries

For each logical unit, define a task:

**Task Specification:**
1. **ID**: Unique identifier (TASK-001, TASK-002, etc.)
2. **Name**: Descriptive, action-oriented (verb + noun)
3. **Description**: Clear, detailed explanation of what to build
4. **Files**: List of files to create/modify (1-3 ideal)
5. **Acceptance Criteria**: Testable conditions for completion
6. **Dependencies**: Tasks that must complete first
7. **Complexity**: Effort estimate (Small/Medium/Large)
8. **Parallel**: Can this run in parallel with others?

### Step 4: Map Dependencies

Create dependency graph:

1. **Identify prerequisites**: What must exist before this task?
2. **Map relationships**: Which tasks depend on which?
3. **Validate DAG**: No circular dependencies
4. **Calculate critical path**: Longest sequential chain
5. **Identify parallel opportunities**: Tasks with no dependencies

**Dependency Types:**
- **Strict dependency**: Task B requires Task A's output (e.g., repository requires schema)
- **Weak dependency**: Task B benefits from Task A but can use mocks (e.g., API endpoint can mock service)
- **No dependency**: Tasks are independent (e.g., frontend and backend tasks)

### Step 5: Size and Estimate

Estimate task complexity:

**Sizing Factors:**
- **Code complexity**: Algorithm difficulty, logic complexity
- **File count**: More files = more complexity
- **Integration points**: External dependencies, APIs
- **Testing effort**: Unit vs. integration vs. e2e tests
- **Risk**: Unfamiliar technology, unclear requirements
- **Knowledge**: Team expertise in this area

**Size Categories:**
- **Small (1-2 days)**: Single file, straightforward logic, clear scope
- **Medium (2-4 days)**: Multiple files, moderate complexity, some design needed
- **Large (3-5 days)**: Complex logic, multiple integrations, significant testing

**If task is > 5 days: Split it further**

### Step 6: Optimize for Parallelism

Maximize concurrent work:

**Strategies:**
1. **Use mocks**: Frontend can mock backend APIs
2. **Define interfaces early**: Tasks can implement against interface before implementation exists
3. **Separate concerns**: Backend and frontend tasks rarely conflict
4. **Split by file**: Different files = different tasks = parallel work
5. **Independent components**: Testing, documentation can proceed in parallel

**Example:**
```
Instead of:
Backend Task → Frontend Task → Testing Task (sequential, 9 days)

Do:
Backend Task (3 days) ┐
Frontend Task (3 days) ├→ Integration Testing Task (2 days)
Test Infrastructure (1 day) ┘
(Total: 5 days with 3 developers)
```

### Step 7: Sequence Implementation

Recommend implementation order:

**Phase 1: Foundation**
- Database schemas
- Core models
- Basic repositories
- Test infrastructure

**Phase 2: Core Logic**
- Service layer
- Business logic
- API endpoints (mocked dependencies)
- UI components (mocked APIs)

**Phase 3: Integration**
- Connect components
- Integration tests
- End-to-end tests

**Phase 4: Polish**
- Documentation
- Performance optimization
- Error handling improvements

**Critical Path First:**
Prioritize tasks on critical path to unblock dependents early.

## MAAS-Specific Task Patterns

### Pattern 1: Database Schema Task

**Structure:**
- Create Django models
- Create migration
- Write model tests

**Files:**
- `src/maasserver/models/[feature].py`
- `src/maasserver/migrations/[number]_[feature].py`
- `src/maasserver/tests/test_[feature].py`

**Acceptance Criteria:**
- Models created with fields, relationships, constraints
- Migration creates/alters tables correctly
- Migration is reversible
- Tests cover CRUD operations
- All tests pass

### Pattern 2: Repository Task

**Structure:**
- Create repository class
- Implement data access methods
- Write repository tests (mock DB)

**Files:**
- `src/maasserver/repositories/[feature]_repository.py`
- `src/maasserver/tests/test_[feature]_repository.py`

**Acceptance Criteria:**
- Repository implements specified methods
- Methods return domain objects (not Django models)
- Error handling for database failures
- Tests use mocks (no DB dependency)
- All tests pass

### Pattern 3: Service Layer Task

**Structure:**
- Create service class
- Implement business logic
- Write service tests (mock dependencies)

**Files:**
- `src/maasserver/services/[feature]_service.py`
- `src/maasserver/tests/test_[feature]_service.py`

**Acceptance Criteria:**
- Service implements specified logic
- Dependencies injected (not hardcoded)
- Service methods documented
- Tests mock dependencies
- All tests pass

### Pattern 4: API Endpoint Task

**Structure:**
- Create API handler
- Add route to URLs
- Write API tests

**Files:**
- `src/maasserver/api/[feature].py`
- `src/maasserver/api/urls.py` (modify)
- `src/maasserver/tests/test_api_[feature].py`

**Acceptance Criteria:**
- Endpoint at specified path
- Handles authentication/authorization
- Validates input, returns appropriate errors
- Tests cover success and error cases
- API documentation added
- All tests pass

### Pattern 5: React Component Task

**Structure:**
- Create React component
- Write component tests
- Create export

**Files:**
- `src/maasui/src/components/[Feature]/[Feature].tsx`
- `src/maasui/src/components/[Feature]/[Feature].test.tsx`
- `src/maasui/src/components/[Feature]/index.ts`

**Acceptance Criteria:**
- Component renders correctly
- Handles props/state appropriately
- Tests use React Testing Library
- Tests cover user interactions
- All tests pass

### Pattern 6: Integration Task

**Structure:**
- Write integration test
- May include Docker setup
- Test multiple components together

**Files:**
- `src/maasserver/tests/integration/test_[feature].py`
- `src/maasserver/tests/integration/docker-compose.yml` (if needed)

**Acceptance Criteria:**
- Test covers end-to-end workflow
- Test runs in CI environment
- Test verifies component interactions
- All assertions pass

## Common Decomposition Patterns

### By Technical Layer

```
Task 1: Database Schema
Task 2: Repository Implementation
Task 3: Service Layer
Task 4: API Endpoint
Task 5: UI Component
Task 6: Integration Test
```

**Pros:** Clear separation of concerns, natural dependencies
**Cons:** Sequential dependencies, longer critical path

### By Feature Slice

```
Task 1: Add Region (database → repository → API → UI)
Task 2: List Regions (database → repository → API → UI)
Task 3: Delete Region (database → repository → API → UI)
```

**Pros:** Each task delivers vertical slice of functionality
**Cons:** Each task touches many layers, larger tasks

### Hybrid (Recommended for MAAS)

```
Foundation Tasks (parallel):
- Task 1: Database Schema
- Task 2: API Client Adapter

Core Backend (sequential):
- Task 3: Repository (depends on Task 1)
- Task 4: Service (depends on Task 3)
- Task 5: API Endpoint (depends on Task 4)

Core Frontend (parallel with backend):
- Task 6: UI Component
- Task 7: Redux Integration (depends on Task 6)

Integration (after core):
- Task 8: Integration Test (depends on Tasks 5, 7)
```

**Pros:** Balances parallelism with dependencies, enables concurrent work
**Cons:** Requires careful planning

## Anti-Patterns to Avoid

### ❌ Mega-Tasks

**Problem:** Task that does too much (10+ files, >5 days)

**Example:** "Implement entire cross-region search feature"

**Why it's bad:**
- Too large to review
- Blocks other work
- High merge conflict risk
- Hard to test in isolation
- Unclear when it's "done"

**What to do instead:** Break into smaller, focused tasks

### ❌ Nano-Tasks

**Problem:** Tasks too small (<2 hours, trivial changes)

**Example:** "Add single line to config file"

**Why it's bad:**
- Overhead of task management exceeds value
- Clutters task list
- Context switching costs high

**What to do instead:** Combine with related tasks

### ❌ Vague Tasks

**Problem:** Unclear scope or acceptance criteria

**Example:** "Make search work" or "Fix bugs"

**Why it's bad:**
- Implementer doesn't know what to build
- Can't verify completion
- Scope creep likely

**What to do instead:** Specific description and testable acceptance criteria

### ❌ Tightly Coupled Tasks

**Problem:** Every task depends on previous task (no parallelism)

**Example:**
```
Task A → Task B → Task C → Task D → Task E
(All sequential, critical path = 5 tasks)
```

**Why it's bad:**
- Only one developer can work at a time
- Slow progress
- Bottlenecks

**What to do instead:** Use mocks/interfaces to enable parallel work

### ❌ Missing Test Specifications

**Problem:** Task doesn't specify what tests are needed

**Example:** "Implement repository" (no mention of tests)

**Why it's bad:**
- Tests are afterthought
- Unclear what "passing" means
- Quality varies

**What to do instead:** Always include test file and test acceptance criteria

### ❌ Cross-Cutting Tasks

**Problem:** Task touches many unrelated files/components

**Example:** "Update all files to use new logging framework" (touches 50 files)

**Why it's bad:**
- Massive merge conflicts
- Hard to review
- Scope is unclear

**What to do instead:** Split into smaller tasks by component or layer

## Validation and Quality Checks

### Task Quality Checklist

For each task, verify:

- [ ] **Clear description**: Implementer knows what to build
- [ ] **1-3 files**: Scope is appropriately sized
- [ ] **Acceptance criteria**: Testable, specific conditions listed
- [ ] **Tests specified**: Test file included, test criteria defined
- [ ] **Dependencies identified**: Prerequisites clearly stated
- [ ] **Complexity estimated**: Small/Medium/Large assigned
- [ ] **Parallel flag set**: Indicates if task can run concurrently
- [ ] **Independently testable**: Can be verified without dependent tasks
- [ ] **Cohesive scope**: All changes are related and logical
- [ ] **No ambiguity**: No open questions or unclear requirements

### Task List Quality Checklist

For overall task list, verify:

- [ ] **Complete coverage**: All technical plan components have tasks
- [ ] **No overlap**: Tasks don't duplicate work
- [ ] **Valid DAG**: No circular dependencies
- [ ] **Critical path identified**: Longest sequential chain documented
- [ ] **Parallel opportunities**: Independent tasks flagged
- [ ] **Reasonable sizes**: No tasks > 5 days
- [ ] **Implementation order**: Phases defined, foundation tasks first
- [ ] **Testing coverage**: Unit, integration, e2e tests included
- [ ] **Documentation tasks**: User and developer docs included
- [ ] **Risk register**: High-risk tasks identified

## Interaction with Other Roles

### Handoff from Planner

**Receive:**
- Complete technical plan
- Architecture diagrams
- Component descriptions
- API contracts
- Risk assessment

**Validate:**
- Plan is detailed enough to decompose
- Component boundaries are clear
- Integration points are specified
- Testing strategy is defined

**Ask if unclear:**
- Which components are independent?
- What's the recommended implementation order?
- Are there any critical path concerns?
- What's highest risk?

### Handoff to Implementers

**Deliver:**
- Complete task list
- Task dependency graph
- Implementation phase recommendations
- Complexity estimates
- Risk register

**Implementers will:**
- Pick tasks from queue (respecting dependencies)
- Implement according to task specification
- Verify acceptance criteria met
- Mark task complete

**Make their job easier:**
- Crystal-clear task descriptions
- Specific acceptance criteria
- Include test specifications
- Link to relevant technical plan sections

### Collaboration Points

- **With Planner**: Clarify ambiguities, validate task breakdown aligns with plan
- **With Implementers**: Answer questions about task scope, adjust if needed
- **With Tech Lead**: Review task list, validate dependencies, adjust complexity estimates
- **With Project Manager**: Provide estimates, identify critical path, flag risks

## Success Criteria for Task Lists

A task list is ready for implementation when:

- [ ] **All components covered**: Every part of technical plan has tasks
- [ ] **Tasks are sized appropriately**: 1-3 files, 1-5 days each
- [ ] **Dependencies are clear**: DAG is valid, critical path identified
- [ ] **Acceptance criteria are specific**: Each task has testable conditions
- [ ] **Tests are included**: Every task specifies test requirements
- [ ] **Parallelism is maximized**: Independent tasks flagged
- [ ] **Implementation order is recommended**: Phases defined
- [ ] **Risks are identified**: High-risk tasks called out
- [ ] **Documentation is included**: User and developer doc tasks present
- [ ] **No ambiguity**: Tasks are clear enough to implement without further clarification

Use `.sdd/validation/task-checklist.md` to validate completeness.

## Summary

The Task Decomposer bridges technical planning and implementation by creating actionable, well-defined tasks. Success requires balancing task size (small enough to be manageable, large enough to be meaningful), minimizing dependencies (to enable parallelism), and providing clarity (so implementers know exactly what to build). A great task list enables efficient, high-quality implementation with multiple developers working concurrently toward a shared goal.