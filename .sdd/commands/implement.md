# SDD Command: Implement

## Purpose

The `implement` command guides developers through implementing a specific task from the task list. This command ensures code is written using test-driven development, follows minimal-change integration principles, and meets all acceptance criteria defined in the task specification.

## Invocation Pattern

**When to use:**
- Task has been assigned to you
- Dependencies (prerequisite tasks) are complete
- You're ready to write code
- Need guidance on implementation approach

**Who invokes:**
- Developer (any skill level)
- Engineer working on task
- Contributor implementing feature

**Command:**
```
I'm ready to implement a task.

Task ID: TASK-003
Task: Implement Query Coordinator Service
Specification: .sdd/specs/multi-region-query.md
Technical Plan: .sdd/plans/multi-region-query.md
Task Document: .sdd/tasks/multi-region-query.md

Please guide me through implementation using the SDD process.
```

## Inputs Required

### 1. Task Definition

**From:** `.sdd/tasks/[feature-name].md`

**What's needed:**
- Task ID and title
- Description of what to build
- Acceptance criteria (specific, testable)
- Files to create/modify
- Testing requirements
- Dependencies (completed or verified)

**Example:**
```markdown
### Task 3: Query Coordinator Service

**ID:** TASK-003
**Estimated Effort:** Large (4 days)
**Dependencies:** TASK-002 (Regional Query Client)

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
```

### 2. Specification Reference

**From:** `.sdd/specs/[feature-name].md`

**What's needed:**
- User requirements context
- Success criteria
- User journeys
- Acceptance criteria (overall feature)

**Why:** Keep user needs in mind during implementation

### 3. Technical Plan Reference

**From:** `.sdd/plans/[feature-name].md`

**What's needed:**
- Architecture decisions
- Component design
- Integration patterns
- Technology choices
- Data flow

**Why:** Understand how your component fits into overall design

### 4. Related Code Context

**Identify:**
- Existing code that will integrate with your changes
- Similar patterns in the codebase
- Interfaces to implement
- Dependencies to use

**Example:**
```
Related Code:
- src/maasserver/clients/regional_client.py (dependency)
- src/maasserver/services/base_service.py (pattern reference)
- src/maasserver/models/region.py (data model)
```

### 5. Team Standards

**Review:**
- `.sdd/context/agents.md` - Code quality guidelines
- `.sdd/skills/test-driven-implementation.md` - TDD approach
- `.sdd/skills/minimal-change-integration.md` - Integration patterns
- Project style guides (PEP 8 for Python, ESLint for JS)

## Outputs Produced

### 1. Test Files (Created First)

**Location:** As specified in task

**Content:**
- Unit tests for all functionality
- Integration tests for integration points
- Error case tests
- Edge case tests

**Example:**
```python
# src/maasserver/tests/test_query_coordinator.py
from twisted.internet import defer
from maastesting.testcase import MAASTestCase

class TestQueryCoordinator(MAASTestCase):
    
    def test_query_all_regions_returns_merged_results(self):
        """QueryCoordinator merges results from all regions."""
        # Test implementation
        pass
    
    def test_query_all_regions_handles_timeout(self):
        """QueryCoordinator enforces timeout."""
        # Test implementation
        pass
```

### 2. Implementation Files

**Location:** As specified in task

**Content:**
- Minimal code to pass tests
- Follows existing patterns
- Clean, readable, documented
- Type hints (Python) or TypeScript types

**Example:**
```python
# src/maasserver/services/query_coordinator.py
from twisted.internet import defer

class QueryCoordinator:
    """Coordinates parallel queries across regional controllers."""
    
    def __init__(self, regional_clients, timeout=30):
        """Initialize coordinator.
        
        Args:
            regional_clients: List of RegionalQueryClient instances
            timeout: Query timeout in seconds (default: 30)
        """
        self.clients = regional_clients
        self.timeout = timeout
    
    @defer.inlineCallbacks
    def query_all_regions(self, filters):
        """Query all regions in parallel.
        
        Args:
            filters: Query filter dictionary
            
        Returns:
            Deferred that fires with list of results from all regions
        """
        # Implementation
        pass
```

### 3. Documentation Updates

**Update as needed:**
- Docstrings in code
- API documentation
- README if public interface changed
- Migration guides if breaking change

### 4. Task Completion Checklist

**Document:** Progress against acceptance criteria

```markdown
## Task 3: Query Coordinator Service

**Status:** In Progress / Complete
**Developer:** [Your Name]
**Date Started:** YYYY-MM-DD
**Date Completed:** YYYY-MM-DD

**Acceptance Criteria Progress:**
- [x] Queries all registered regions in parallel using DeferredList
- [x] Applies consistent timeout (30s default, configurable)
- [x] Continues even if some regions fail
- [x] Returns results from successful regions
- [x] Logs failures for debugging
- [x] Unit tests with mocked clients
- [x] Integration tests with real database

**Files Created:**
- src/maasserver/services/query_coordinator.py (152 lines)
- src/maasserver/tests/test_query_coordinator.py (287 lines)
- src/maasserver/tests/integration/test_query_coordinator_integration.py (94 lines)

**Code Review:** [PR link]
**Merged:** YYYY-MM-DD
```

## Validation Against Acceptance Criteria

Before marking task complete, verify:

- [ ] **All acceptance criteria met** - Every criterion has passing test
- [ ] **Tests written first** - TDD approach followed
- [ ] **Tests pass** - All new and existing tests green
- [ ] **Code reviewed** - At least one peer review
- [ ] **Documentation complete** - Docstrings, comments, README updates
- [ ] **No regressions** - Existing functionality still works
- [ ] **Style compliance** - Linter passes, style guide followed
- [ ] **Integration verified** - Component works with dependencies
- [ ] **Task boundaries respected** - Only changed what task specified
- [ ] **AGENTS.md compliance** - Follows code quality standards

## Process Flow

### Step 1: Understand the Task (15-30 minutes)

**Actions:**
1. Read task description thoroughly
2. Review acceptance criteria
3. Understand what "done" looks like
4. Identify files to modify/create
5. Review specification for user context
6. Review technical plan for architecture
7. Scan related existing code

**Output:** Clear mental model of what to build

**Questions to answer:**
- What is this component's responsibility?
- How does it integrate with existing code?
- What are the inputs and outputs?
- What edge cases need handling?
- What testing strategy is appropriate?

### Step 2: Set Up Development Environment (5-10 minutes)

**Actions:**
1. Pull latest code from main branch
2. Create feature branch: `feature/TASK-00X-short-description`
3. Verify dependencies are installed
4. Run existing tests to ensure clean baseline
5. Set up test database if needed

**Commands:**
```bash
git checkout main
git pull origin main
git checkout -b feature/TASK-003-query-coordinator
make test  # Verify clean baseline
```

### Step 3: Write First Test (RED) (30-60 minutes)

**Actions:**
1. Create test file if it doesn't exist
2. Write simplest test for core behavior
3. Use Arrange-Act-Assert pattern
4. Mock external dependencies
5. Make test specific and focused
6. Run test and watch it fail

**Example:**
```python
# src/maasserver/tests/test_query_coordinator.py
from unittest.mock import Mock
from twisted.internet import defer
from maastesting.testcase import MAASTestCase
from maasserver.services.query_coordinator import QueryCoordinator

class TestQueryCoordinator(MAASTestCase):
    
    @defer.inlineCallbacks
    def test_query_all_regions_returns_results_from_all_clients(self):
        """QueryCoordinator queries all regional clients and merges results."""
        # Arrange: Create mock clients that return test data
        client1 = Mock()
        client1.query.return_value = defer.succeed([
            {'system_id': 'm1', 'hostname': 'machine-1'}
        ])
        
        client2 = Mock()
        client2.query.return_value = defer.succeed([
            {'system_id': 'm2', 'hostname': 'machine-2'}
        ])
        
        coordinator = QueryCoordinator(clients=[client1, client2])
        
        # Act: Query all regions
        results = yield coordinator.query_all_regions({'status': 'ready'})
        
        # Assert: Results from both clients are present
        self.assertEqual(len(results), 2)
        system_ids = {r['system_id'] for r in results}
        self.assertIn('m1', system_ids)
        self.assertIn('m2', system_ids)
```

**Run test:**
```bash
pytest src/maasserver/tests/test_query_coordinator.py::TestQueryCoordinator::test_query_all_regions_returns_results_from_all_clients -v
```

**Expected:** Test fails (RED) because QueryCoordinator doesn't exist yet

### Step 4: Write Minimal Implementation (GREEN) (30-90 minutes)

**Actions:**
1. Create implementation file
2. Write minimal code to pass the test
3. Don't worry about edge cases yet
4. Don't optimize prematurely
5. Focus on getting to green
6. Run test and watch it pass

**Example:**
```python
# src/maasserver/services/query_coordinator.py
from twisted.internet import defer

class QueryCoordinator:
    """Coordinates parallel queries across regional controllers."""
    
    def __init__(self, clients, timeout=30):
        self.clients = clients
        self.timeout = timeout
    
    @defer.inlineCallbacks
    def query_all_regions(self, filters):
        """Query all regions in parallel."""
        # Minimal implementation: query each client and collect results
        all_results = []
        
        for client in self.clients:
            results = yield client.query(filters)
            all_results.extend(results)
        
        defer.returnValue(all_results)
```

**Run test:**
```bash
pytest src/maasserver/tests/test_query_coordinator.py::TestQueryCoordinator::test_query_all_regions_returns_results_from_all_clients -v
```

**Expected:** Test passes (GREEN)

### Step 5: Refactor (REFACTOR) (15-30 minutes)

**Actions:**
1. Look for duplication
2. Improve naming
3. Extract helper methods
4. Add docstrings
5. Add type hints
6. Run tests after each change (must stay green)

**Example:**
```python
# src/maasserver/services/query_coordinator.py
from typing import List, Dict, Any
from twisted.internet import defer

class QueryCoordinator:
    """Coordinates parallel queries across regional controllers.
    
    This service queries multiple regional controllers in parallel and
    merges their results into a unified view.
    """
    
    def __init__(self, clients: List, timeout: int = 30):
        """Initialize query coordinator.
        
        Args:
            clients: List of RegionalQueryClient instances
            timeout: Query timeout in seconds (default: 30)
        """
        self.clients = clients
        self.timeout = timeout
    
    @defer.inlineCallbacks
    def query_all_regions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Query all regions in parallel and merge results.
        
        Args:
            filters: Query filter dictionary
            
        Returns:
            List of machine dictionaries from all regions
        """
        all_results = []
        
        for client in self.clients:
            results = yield client.query(filters)
            all_results.extend(results)
        
        defer.returnValue(all_results)
```

**Run tests:**
```bash
pytest src/maasserver/tests/test_query_coordinator.py -v
```

**Expected:** All tests still pass (GREEN maintained)

### Step 6: Add More Tests (Repeat RED-GREEN-REFACTOR) (2-4 hours)

**For each acceptance criterion:**
1. Write test (RED)
2. Implement (GREEN)
3. Refactor (REFACTOR)

**Example - Add timeout handling:**

```python
# Test (RED)
@defer.inlineCallbacks
def test_query_all_regions_enforces_timeout(self):
    """QueryCoordinator applies timeout to prevent hanging."""
    # Arrange: Client that delays beyond timeout
    slow_client = Mock()
    slow_client.query.return_value = defer.Deferred()  # Never resolves
    
    coordinator = QueryCoordinator(clients=[slow_client], timeout=1)
    
    # Act & Assert: Should timeout
    with self.assertRaises(defer.TimeoutError):
        yield coordinator.query_all_regions({'status': 'ready'})

# Implementation (GREEN)
from twisted.internet import defer, reactor

@defer.inlineCallbacks
def query_all_regions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query all regions in parallel with timeout."""
    all_results = []
    
    for client in self.clients:
        # Add timeout wrapper
        query_deferred = client.query(filters)
        timeout_deferred = defer.Deferred()
        reactor.callLater(self.timeout, timeout_deferred.callback, None)
        
        try:
            results = yield defer.race([query_deferred, timeout_deferred])
            if results is not None:
                all_results.extend(results)
        except defer.TimeoutError:
            # Log and continue
            pass
    
    defer.returnValue(all_results)

# Refactor: Extract timeout logic
def _query_with_timeout(self, client, filters):
    """Query client with timeout protection."""
    query_deferred = client.query(filters)
    return defer.timeoutDeferred(query_deferred, self.timeout, reactor)

@defer.inlineCallbacks
def query_all_regions(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query all regions in parallel with timeout."""
    all_results = []
    
    for client in self.clients:
        try:
            results = yield self._query_with_timeout(client, filters)
            all_results.extend(results)
        except defer.TimeoutError:
            logger.warning(f"Query to region timed out after {self.timeout}s")
    
    defer.returnValue(all_results)
```

**Continue until all acceptance criteria have tests and implementation**

### Step 7: Add Integration Tests (1-2 hours)

**Actions:**
1. Create integration test file
2. Test component with real dependencies (database, etc.)
3. Verify end-to-end behavior
4. Test with realistic data volumes

**Example:**
```python
# src/maasserver/tests/integration/test_query_coordinator_integration.py
from maastesting.testcase import MAASTestCase
from maasserver.services.query_coordinator import QueryCoordinator
from maasserver.clients.regional_client import RegionalQueryClient
from maasserver.models import Region
from maasserver.testing import factory

class TestQueryCoordinatorIntegration(MAASTestCase):
    
    def test_query_coordinator_with_real_clients_and_database(self):
        """QueryCoordinator works with real RegionalQueryClient and database."""
        # Setup: Create regions and machines in database
        region1 = factory.make_Region(name="us-east")
        region2 = factory.make_Region(name="us-west")
        factory.make_Machine(region=region1, hostname="east-1", status=NODE_STATUS.READY)
        factory.make_Machine(region=region2, hostname="west-1", status=NODE_STATUS.READY)
        
        # Create real clients (might need to mock HTTP layer)
        client1 = RegionalQueryClient(region1)
        client2 = RegionalQueryClient(region2)
        
        coordinator = QueryCoordinator(clients=[client1, client2])
        
        # Act: Query for ready machines
        results = coordinator.query_all_regions({'status': NODE_STATUS.READY})
        
        # Assert: Results from both regions present
        self.assertEqual(len(results), 2)
        hostnames = {m['hostname'] for m in results}
        self.assertEqual(hostnames, {'east-1', 'west-1'})
```

### Step 8: Verify All Acceptance Criteria (30 minutes)

**Actions:**
1. Review task acceptance criteria list
2. Verify each has passing test
3. Check for edge cases not covered
4. Add missing tests
5. Update task document with checkmarks

**Example checklist:**
```markdown
**Acceptance Criteria Progress:**
- [x] Queries all registered regions in parallel using DeferredList ✓ (test_query_all_regions_parallel)
- [x] Applies consistent timeout (30s default, configurable) ✓ (test_timeout_default, test_timeout_configurable)
- [x] Continues even if some regions fail ✓ (test_partial_failure_continues)
- [x] Returns results from successful regions ✓ (test_partial_failure_returns_successful)
- [x] Logs failures for debugging ✓ (test_logs_failures, verified log output)
- [x] Unit tests with mocked clients ✓ (13 unit tests, all passing)
- [x] Integration tests with real database ✓ (3 integration tests, all passing)
```

### Step 9: Run Full Test Suite (10-15 minutes)

**Actions:**
1. Run all project tests (not just yours)
2. Verify no regressions
3. Fix any broken tests
4. Check code coverage

**Commands:**
```bash
# Run all tests
make test

# Check coverage
pytest --cov=maasserver.services.query_coordinator \
       --cov-report=term-missing \
       src/maasserver/tests/test_query_coordinator.py

# Run linter
make lint

# Run type checker (if applicable)
mypy src/maasserver/services/query_coordinator.py
```

**Expected:** All tests pass, coverage >90%, no lint errors

### Step 10: Code Review and Documentation (30-60 minutes)

**Actions:**
1. Review your own code
2. Add/improve docstrings
3. Add inline comments for complex logic
4. Update README if needed
5. Create pull request
6. Request peer review

**Self-review checklist:**
- [ ] Code follows MAAS conventions
- [ ] Docstrings for all public methods
- [ ] Complex logic has explanatory comments
- [ ] No debug prints or commented code
- [ ] No TODOs without tickets
- [ ] Error messages are helpful
- [ ] Variable names are clear
- [ ] No magic numbers (use constants)

**Pull request template:**
```markdown
## Task: TASK-003 Query Coordinator Service

**Specification:** .sdd/specs/multi-region-query.md
**Technical Plan:** .sdd/plans/multi-region-query.md
**Task Document:** .sdd/tasks/multi-region-query.md#task-3

### Summary
Implements service to coordinate parallel queries across multiple regional controllers.

### Changes
- Created QueryCoordinator service with parallel query support
- Added timeout handling (30s default, configurable)
- Graceful handling of partial failures
- Comprehensive unit and integration tests

### Acceptance Criteria Met
- [x] All 7 acceptance criteria verified with tests

### Testing
- 13 unit tests (mocked dependencies)
- 3 integration tests (real database)
- Coverage: 96%

### Files Changed
- `src/maasserver/services/query_coordinator.py` (152 lines added)
- `src/maasserver/tests/test_query_coordinator.py` (287 lines added)
- `src/maasserver/tests/integration/test_query_coordinator_integration.py` (94 lines added)

### Reviewers
@tech-lead @senior-dev
```

### Step 11: Address Review Feedback (varies)

**Actions:**
1. Respond to reviewer comments
2. Make requested changes
3. Update tests if needed
4. Request re-review
5. Merge when approved

## MAAS-Specific Implementation Examples

### Django Model Implementation

```python
# Task: Add allocated_at timestamp to Machine model

# Test (RED)
def test_machine_tracks_allocation_timestamp(self):
    """Machine records timestamp when allocated."""
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    before_allocation = timezone.now()
    
    machine.allocate(user=factory.make_User())
    
    after_allocation = timezone.now()
    self.assertIsNotNone(machine.allocated_at)
    self.assertGreaterEqual(machine.allocated_at, before_allocation)
    self.assertLessEqual(machine.allocated_at, after_allocation)

# Implementation (GREEN)
class Machine(Model):
    # ... existing fields ...
    allocated_at = DateTimeField(null=True, blank=True)
    
    def allocate(self, user):
        """Allocate machine to user."""
        self.status = NODE_STATUS.ALLOCATED
        self.owner = user
        self.allocated_at = timezone.now()  # Added
        self.save()

# Migration
python manage.py makemigrations --name add_machine_allocated_at
```

### REST API Endpoint Implementation

```python
# Task: Add filtering endpoint for machines

# Test (RED)
class TestMachineFilterEndpoint(APITestCase):
    
    def test_filter_machines_by_status_returns_matching_machines(self):
        """GET /api/machines?status=ready returns ready machines."""
        # Arrange
        factory.make_Machine(status=NODE_STATUS.READY, hostname="ready-1")
        factory.make_Machine(status=NODE_STATUS.ALLOCATED, hostname="allocated-1")
        self.client.login(user=factory.make_admin())
        
        # Act
        response = self.client.get("/api/2.0/machines/?status=ready")
        
        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['hostname'], 'ready-1')

# Implementation (GREEN)
class MachinesHandler(OperationsHandler):
    
    def read(self, request):
        """List machines with optional filtering."""
        machines = Machine.objects.all()
        
        # Add filtering
        status = request.GET.get('status')
        if status:
            machines = machines.filter(status=status)
        
        return [self._serialize(m) for m in machines]
```

### React Component Implementation

```javascript
// Task: Add machine selection checkbox

// Test (RED)
import { render, screen, fireEvent } from '@testing-library/react';
import MachineRow from './MachineRow';

describe('MachineRow', () => {
  test('calls onSelect when checkbox clicked', () => {
    // Arrange
    const machine = { system_id: 'm1', hostname: 'machine-1' };
    const handleSelect = jest.fn();
    render(<MachineRow machine={machine} onSelect={handleSelect} />);
    
    // Act
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    
    // Assert
    expect(handleSelect).toHaveBeenCalledWith('m1', true);
  });
});

// Implementation (GREEN)
const MachineRow = ({ machine, onSelect }) => {
  const handleCheckboxChange = (e) => {
    onSelect(machine.system_id, e.target.checked);
  };
  
  return (
    <tr>
      <td>
        <input 
          type="checkbox" 
          onChange={handleCheckboxChange}
        />
      </td>
      <td>{machine.hostname}</td>
    </tr>
  );
};
```

### Twisted Async Implementation

```python
# Task: Implement parallel region query with timeout

# Test (RED)
@defer.inlineCallbacks
def test_query_regions_in_parallel_using_deferred_list(self):
    """Queries execute in parallel, not sequentially."""
    # Arrange: Track call order
    call_times = []
    
    def delayed_query(delay):
        d = defer.Deferred()
        def record_and_resolve():
            call_times.append(time.time())
            d.callback([])
        reactor.callLater(delay, record_and_resolve)
        return d
    
    client1 = Mock()
    client1.query.side_effect = lambda f: delayed_query(0.1)
    client2 = Mock()
    client2.query.side_effect = lambda f: delayed_query(0.1)
    
    coordinator = QueryCoordinator([client1, client2])
    
    # Act
    start = time.time()
    yield coordinator.query_all_regions({})
    duration = time.time() - start
    
    # Assert: Should take ~0.1s (parallel), not ~0.2s (sequential)
    self.assertLess(duration, 0.15)

# Implementation (GREEN)
@defer.inlineCallbacks
def query_all_regions(self, filters):
    """Query all regions in parallel."""
    # Create list of query deferreds
    query_deferreds = [
        client.query(filters) for client in self.clients
    ]
    
    # Execute in parallel
    results_list = yield defer.DeferredList(
        query_deferreds,
        consumeErrors=True
    )
    
    # Extract successful results
    all_results = []
    for success, result in results_list:
        if success:
            all_results.extend(result)
    
    defer.returnValue(all_results)
```

## Common Pitfalls

### ❌ Skipping Tests

**Problem:** Writing implementation without tests

```python
# Wrong: No tests, just implementation
class QueryCoordinator:
    def query_all_regions(self, filters):
        # 100 lines of untested code
        pass
```

**Solution:** Always test first

```python
# Right: Test first
def test_query_all_regions_merges_results(self):
    # Test implementation
    pass

# Then implementation
class QueryCoordinator:
    def query_all_regions(self, filters):
        # Minimal code to pass test
        pass
```

### ❌ Exceeding Task Scope

**Problem:** Implementing features not in task

```python
# Task: Add status filtering

# Wrong: Added status, zone, AND tag filtering
def list_machines(status=None, zone=None, tags=None):
    # Implemented 3 features instead of 1
    pass

# Right: Just status filtering as specified
def list_machines(status=None):
    if status:
        return Machine.objects.filter(status=status)
    return Machine.objects.all()
```

### ❌ Modifying Unrelated Code

**Problem:** "While I'm here" refactoring

```python
# Task: Add deployed count

# Wrong: Refactored entire method
def get_summary(self):
    # Completely restructured
    # Changed variable names
    # Extracted helper methods
    # Oh, and added deployed count
    pass

# Right: Minimal change
def get_summary(self):
    machines = Machine.objects.all()
    return {
        'total': machines.count(),
        'ready': machines.filter(status=NODE_STATUS.READY).count(),
        'allocated': machines.filter(status=NODE_STATUS.ALLOCATED).count(),
        'deployed': machines.filter(status=NODE_STATUS.DEPLOYED).count(),  # Added
    }
```

### ❌ Vague or Missing Tests

**Problem:** Tests don't validate behavior

```python
# Wrong: What does this test?
def test_query_coordinator(self):
    coordinator = QueryCoordinator()
    result = coordinator.query_all_regions({})
    assert result is not None  # Useless assertion

# Right: Specific, meaningful test
def test_query_coordinator_merges_results_from_all_clients(self):
    """QueryCoordinator combines results from all regional clients."""
    client1 = Mock()
    client1.query.return_value = defer.succeed([{'id': '1'}])
    client2 = Mock()
    client2.query.return_value = defer.succeed([{'id': '2'}])
    
    coordinator = QueryCoordinator([client1, client2])
    results = yield coordinator.query_all_regions({})
    
    assert len(results) == 2
    ids = {r['id'] for r in results}
    assert ids == {'1', '2'}
```

### ❌ Not Running Full Test Suite

**Problem:** Only running your tests, missing regressions

```bash
# Wrong: Only test your file
pytest src/maasserver/tests/test_query_coordinator.py

# Right: Run full suite
make test
```

### ❌ Ignoring Code Review Feedback

**Problem:** Defensive or dismissive responses

```markdown
# Wrong
> Reviewer: "This could cause a memory leak with large result sets"
> You: "Works fine in my testing"

# Right
> Reviewer: "This could cause a memory leak with large result sets"
> You: "Good catch! I'll add pagination to limit result size. Will also add a test for large data sets."
```

## Resources

**Reference:**
- `.sdd/skills/test-driven-implementation.md` - TDD patterns
- `.sdd/skills/minimal-change-integration.md` - Integration approach
- `.sdd/validation/implementation-checklist.md` - Quality validation
- `.sdd/context/agents.md` - Code quality standards

**Testing Guides:**
- MAAS Testing Guide (project-specific)
- Twisted Testing Documentation
- Django Testing Guide
- React Testing Library Docs

**Tools:**
- `pytest` - Test runner
- `coverage.py` - Code coverage
- `make test` - Run full test suite
- `make lint` - Code quality checks

## Next Steps

**After implementation complete:**

1. **Create pull request** - Submit for review
2. **Address feedback** - Make requested changes
3. **Merge** - Once approved
4. **Update task status** - Mark as complete
5. **Deploy** - Follow deployment process
6. **Monitor** - Watch for issues in production
7. **Document lessons learned** - Share knowledge

**If blocked or stuck:**
- Ask for help (don't stay blocked)
- Review technical plan again
- Pair program with teammate
- Create spike task for unknowns

**Celebrate completion:**
- ✅ Tests passing
- ✅ Code reviewed and approved
- ✅ All acceptance criteria met
- ✅ Feature working as specified
- ✅ User value delivered

## Summary

Effective implementation requires:

1. **Understanding** - Know what to build before coding
2. **TDD discipline** - Test first, always
3. **Minimal changes** - Surgical integration, preserve existing code
4. **Quality focus** - Clean, documented, well-tested code
5. **Acceptance validation** - Every criterion has passing test
6. **Team collaboration** - Code review, feedback incorporation
7. **Continuous verification** - Full test suite, no regressions

Follow this process to deliver high-quality, well-tested code that meets requirements and integrates cleanly with the MAAS codebase.