# Test-Driven Implementation for MAAS

## Overview

Test-Driven Implementation (TDI) is the discipline of writing tests **before** implementation code, using tests to drive design and validate behavior. In the MAAS context, TDI ensures reliable infrastructure management software where failures can have serious operational consequences.

## Purpose

- **Design Driver**: Tests force you to think about interfaces before implementation
- **Specification**: Tests document expected behavior in executable form
- **Safety Net**: Tests catch regressions when refactoring
- **Confidence**: Tests prove code works as intended
- **Fast Feedback**: Automated tests provide immediate validation
- **Living Documentation**: Tests show how code should be used

## TDD Philosophy

### The Three Laws of TDD

1. **Don't write production code until you have a failing test**
2. **Don't write more of a test than is sufficient to fail**
3. **Don't write more production code than is sufficient to pass the test**

### Why Test First?

**Design Benefits:**
- Forces interface thinking before implementation
- Reveals complexity early
- Encourages loose coupling
- Results in testable code

**Quality Benefits:**
- 100% test coverage by default
- Tests that actually validate behavior (not just coverage)
- No "I'll test it later" technical debt
- Catches edge cases early

**Process Benefits:**
- Clear definition of "done" (tests pass)
- Small incremental steps
- Fast feedback loop
- Reduces debugging time

## The Red-Green-Refactor Cycle

### The Core Loop

```
1. RED:     Write a failing test
2. GREEN:   Make it pass (quickly, even if ugly)
3. REFACTOR: Clean up while keeping tests green
4. REPEAT:   Next test
```

### Detailed Process

#### Step 1: RED - Write a Failing Test

**Goal:** Define expected behavior in test form

**Actions:**
1. Choose next behavior to implement (smallest useful increment)
2. Write test that exercises that behavior
3. Run test and watch it fail
4. Verify failure reason is correct (not syntax error or missing import)

**Example (MAAS):**
```python
# Test: Repository should retrieve machine by system_id
def test_get_machine_by_system_id(self):
    """Repository returns machine when system_id exists."""
    # Arrange
    expected_machine = factory.make_Machine(system_id="abc123")
    repo = MachineRepository()
    
    # Act
    machine = repo.get_by_system_id("abc123")
    
    # Assert
    self.assertEqual(machine.system_id, "abc123")
    self.assertEqual(machine.id, expected_machine.id)
```

**Run test:**
```bash
$ pytest src/maasserver/tests/test_machine_repository.py::test_get_machine_by_system_id
FAILED - AttributeError: 'MachineRepository' object has no attribute 'get_by_system_id'
```

**Good failure:** Test fails because method doesn't exist (expected)

#### Step 2: GREEN - Make It Pass

**Goal:** Get to green as quickly as possible

**Actions:**
1. Write **minimal** code to pass test
2. Resist urge to make it "perfect"
3. Hard-code if needed (later tests will force generalization)
4. Run test and watch it pass

**Example:**
```python
# src/maasserver/repositories/machine_repository.py
class MachineRepository:
    def get_by_system_id(self, system_id):
        """Get machine by system_id."""
        return Machine.objects.get(system_id=system_id)
```

**Run test:**
```bash
$ pytest src/maasserver/tests/test_machine_repository.py::test_get_by_system_id
PASSED
```

**Note:** This implementation is simple and direct. No premature optimization, no error handling (yet). That's intentional.

#### Step 3: REFACTOR - Clean Up

**Goal:** Improve code quality while keeping tests green

**Actions:**
1. Look for duplication (DRY principle)
2. Improve naming
3. Extract methods
4. Simplify logic
5. Run tests after each change (must stay green)

**Example:**
```python
# Nothing to refactor yet - code is already clean
# But if we had duplication across methods, we'd extract it now
```

**Refactoring happens when:**
- Code duplication appears
- Method/variable names are unclear
- Logic is convoluted
- Responsibilities are mixed

**Refactoring doesn't happen when:**
- Tests are failing (fix them first)
- Adding new functionality (write new test first)

#### Step 4: REPEAT - Next Test

Pick next behavior to implement:
- Error cases
- Edge conditions
- Alternative paths
- Integration scenarios

**Next test (error case):**
```python
def test_get_machine_by_system_id_not_found(self):
    """Repository raises MachineNotFoundError when system_id doesn't exist."""
    repo = MachineRepository()
    
    with self.assertRaises(MachineNotFoundError):
        repo.get_by_system_id("nonexistent")
```

**This test fails (GREEN needed):**
```python
class MachineRepository:
    def get_by_system_id(self, system_id):
        """Get machine by system_id."""
        try:
            return Machine.objects.get(system_id=system_id)
        except Machine.DoesNotExist:
            raise MachineNotFoundError(f"Machine {system_id} not found")
```

**Cycle continues...**

## Test Structure

### Arrange-Act-Assert (AAA) Pattern

**Standard test structure for clarity:**

```python
def test_behavior_description(self):
    """What this test validates."""
    # Arrange: Set up test data and dependencies
    machine = factory.make_Machine(hostname="test-machine")
    repo = MachineRepository()
    
    # Act: Execute the behavior being tested
    result = repo.get_by_hostname("test-machine")
    
    # Assert: Verify expected outcomes
    self.assertEqual(result.hostname, "test-machine")
```

### Given-When-Then (BDD Style)

**Alternative structure for complex scenarios:**

```python
def test_query_coordinator_aggregates_regional_results(self):
    """Query coordinator merges results from multiple regions."""
    # Given: Multiple regions with machines
    region1 = factory.make_Region(name="us-east")
    region2 = factory.make_Region(name="us-west")
    factory.make_Machine(region=region1, hostname="east-1")
    factory.make_Machine(region=region2, hostname="west-1")
    coordinator = QueryCoordinator()
    
    # When: Querying all regions
    results = coordinator.query_all_regions("hostname__contains=1")
    
    # Then: Results from both regions are present
    self.assertEqual(len(results), 2)
    hostnames = {m.hostname for m in results}
    self.assertIn("east-1", hostnames)
    self.assertIn("west-1", hostnames)
```

### Test Naming

**Pattern:** `test_<what>_<condition>_<expected_result>`

**Good names:**
- `test_get_machine_returns_machine_when_exists`
- `test_get_machine_raises_error_when_not_found`
- `test_query_all_regions_merges_results`
- `test_api_endpoint_returns_401_when_unauthorized`

**Bad names:**
- `test_get_machine` (what behavior?)
- `test_1` (meaningless)
- `test_the_thing_works` (vague)

## MAAS-Specific Testing Approaches

### Django Model Tests

**Test model behavior, not Django itself:**

```python
# ✓ Good: Test business logic
def test_machine_status_transitions_to_deployed_after_allocation(self):
    """Machine status changes to DEPLOYED after successful allocation."""
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    
    machine.allocate_to_user(user=factory.make_User())
    machine.deploy()
    
    self.assertEqual(machine.status, NODE_STATUS.DEPLOYED)

# ✗ Bad: Testing Django framework
def test_machine_has_hostname_field(self):
    """Machine model has hostname field."""
    machine = factory.make_Machine()
    self.assertTrue(hasattr(machine, 'hostname'))  # Don't test framework
```

### Repository Tests

**Test data access patterns:**

```python
def test_list_machines_filters_by_status(self):
    """Repository returns only machines with specified status."""
    # Arrange
    factory.make_Machine(status=NODE_STATUS.READY)
    factory.make_Machine(status=NODE_STATUS.READY)
    factory.make_Machine(status=NODE_STATUS.DEPLOYED)
    repo = MachineRepository()
    
    # Act
    ready_machines = repo.list_by_status(NODE_STATUS.READY)
    
    # Assert
    self.assertEqual(len(ready_machines), 2)
    for machine in ready_machines:
        self.assertEqual(machine.status, NODE_STATUS.READY)
```

### Service Tests (with Mocks)

**Test orchestration logic, mock dependencies:**

```python
def test_machine_service_allocates_machine_and_records_event(self):
    """Machine service allocates machine and publishes allocation event."""
    # Arrange
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    mock_event_bus = Mock(spec=EventBus)
    service = MachineService(event_bus=mock_event_bus)
    user = factory.make_User()
    
    # Act
    allocated_machine = service.allocate_machine(machine.system_id, user)
    
    # Assert
    self.assertEqual(allocated_machine.status, NODE_STATUS.ALLOCATED)
    mock_event_bus.publish.assert_called_once()
    event = mock_event_bus.publish.call_args[0][0]
    self.assertEqual(event.type, "MACHINE_ALLOCATED")
    self.assertEqual(event.machine_id, machine.system_id)
```

### Async/Twisted Tests

**Test Twisted Deferreds properly:**

```python
from twisted.internet import defer
from maastesting.testcase import MAASTestCase

class TestAsyncQueryCoordinator(MAASTestCase):
    
    @defer.inlineCallbacks
    def test_query_all_regions_makes_parallel_calls(self):
        """QueryCoordinator queries all regions in parallel."""
        # Arrange
        mock_client1 = Mock()
        mock_client1.query.return_value = defer.succeed([{"id": "1"}])
        mock_client2 = Mock()
        mock_client2.query.return_value = defer.succeed([{"id": "2"}])
        
        coordinator = QueryCoordinator(clients=[mock_client1, mock_client2])
        
        # Act
        results = yield coordinator.query_all_regions("status=ready")
        
        # Assert
        self.assertEqual(len(results), 2)
        mock_client1.query.assert_called_once_with("status=ready")
        mock_client2.query.assert_called_once_with("status=ready")
```

### API Endpoint Tests

**Test HTTP interface:**

```python
class TestMachineAPIEndpoint(APITestCase):
    
    def test_get_machine_returns_200_with_machine_data(self):
        """GET /api/machines/{system_id} returns machine JSON."""
        # Arrange
        machine = factory.make_Machine(
            hostname="test-machine",
            status=NODE_STATUS.READY
        )
        self.client.login(user=factory.make_admin())
        
        # Act
        response = self.client.get(f"/api/2.0/machines/{machine.system_id}/")
        
        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["hostname"], "test-machine")
        self.assertEqual(data["status"], NODE_STATUS.READY)
    
    def test_get_machine_returns_404_when_not_found(self):
        """GET /api/machines/{system_id} returns 404 for nonexistent machine."""
        # Arrange
        self.client.login(user=factory.make_admin())
        
        # Act
        response = self.client.get("/api/2.0/machines/nonexistent/")
        
        # Assert
        self.assertEqual(response.status_code, 404)
```

### React Component Tests

**Test component behavior:**

```javascript
// test_machine_list.spec.js
import { render, screen, fireEvent } from '@testing-library/react';
import MachineList from './MachineList';

describe('MachineList', () => {
  test('renders machine hostnames', () => {
    // Arrange
    const machines = [
      { system_id: '1', hostname: 'machine-1' },
      { system_id: '2', hostname: 'machine-2' }
    ];
    
    // Act
    render(<MachineList machines={machines} />);
    
    // Assert
    expect(screen.getByText('machine-1')).toBeInTheDocument();
    expect(screen.getByText('machine-2')).toBeInTheDocument();
  });
  
  test('calls onSelect when machine clicked', () => {
    // Arrange
    const machines = [{ system_id: '1', hostname: 'machine-1' }];
    const handleSelect = jest.fn();
    render(<MachineList machines={machines} onSelect={handleSelect} />);
    
    // Act
    fireEvent.click(screen.getByText('machine-1'));
    
    // Assert
    expect(handleSelect).toHaveBeenCalledWith('1');
  });
});
```

## Test Organization

### File Structure

**Mirror production structure:**

```
src/maasserver/
  repositories/
    machine_repository.py
  tests/
    repositories/
      test_machine_repository.py
```

### Test Categories

**Unit Tests:** Test single component in isolation
```python
# Fast, isolated, mocked dependencies
def test_repository_get_by_id(self):
    # Tests repository logic only
```

**Integration Tests:** Test component interactions
```python
# Tests repository + database
def test_repository_saves_to_database(self):
    # Actually writes to test database
```

**End-to-End Tests:** Test complete workflows
```python
# Tests API + service + repository + database
def test_full_machine_allocation_workflow(self):
    # Complete user journey
```

### Test Fixtures

**Use factories for test data:**

```python
# Good: Use factory
machine = factory.make_Machine(hostname="test")

# Bad: Manual creation
machine = Machine(
    hostname="test",
    system_id=generate_system_id(),
    architecture="amd64/generic",
    status=NODE_STATUS.READY,
    # ...50 more fields
)
```

**Create reusable fixtures:**

```python
@pytest.fixture
def machine_with_interfaces():
    """Machine with multiple network interfaces."""
    machine = factory.make_Machine()
    factory.make_Interface(node=machine, name="eth0")
    factory.make_Interface(node=machine, name="eth1")
    return machine

def test_machine_has_interfaces(machine_with_interfaces):
    assert len(machine_with_interfaces.interfaces.all()) == 2
```

## TDD Best Practices

### Start with Simplest Test

**Build complexity gradually:**

```python
# 1. Start simple
def test_list_machines_returns_empty_list_when_no_machines():
    repo = MachineRepository()
    machines = repo.list_all()
    self.assertEqual(machines, [])

# 2. Add data
def test_list_machines_returns_all_machines():
    factory.make_Machine()
    factory.make_Machine()
    repo = MachineRepository()
    machines = repo.list_all()
    self.assertEqual(len(machines), 2)

# 3. Add filtering
def test_list_machines_filters_by_status():
    # ...

# 4. Add sorting
def test_list_machines_sorts_by_hostname():
    # ...
```

### One Assert per Test (Guideline)

**Each test should verify one behavior:**

```python
# ✓ Good: Focused test
def test_machine_allocation_changes_status(self):
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    machine.allocate()
    self.assertEqual(machine.status, NODE_STATUS.ALLOCATED)

def test_machine_allocation_records_timestamp(self):
    machine = factory.make_Machine()
    machine.allocate()
    self.assertIsNotNone(machine.allocated_at)

# ✗ Bad: Testing multiple behaviors
def test_machine_allocation(self):
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    machine.allocate()
    self.assertEqual(machine.status, NODE_STATUS.ALLOCATED)  # Behavior 1
    self.assertIsNotNone(machine.allocated_at)               # Behavior 2
    self.assertIsNotNone(machine.allocated_by)               # Behavior 3
```

**Exception:** Multiple asserts are OK when verifying single concept:

```python
# OK: All asserts verify "returns correct machine data"
def test_get_machine_returns_complete_data(self):
    machine = factory.make_Machine(hostname="test", status=NODE_STATUS.READY)
    result = repo.get_machine(machine.system_id)
    
    self.assertEqual(result.hostname, "test")
    self.assertEqual(result.status, NODE_STATUS.READY)
    self.assertEqual(result.system_id, machine.system_id)
```

### Test Behavior, Not Implementation

**Focus on "what," not "how":**

```python
# ✓ Good: Tests observable behavior
def test_machine_service_allocates_machine(self):
    service = MachineService()
    machine = factory.make_Machine(status=NODE_STATUS.READY)
    
    result = service.allocate_machine(machine.system_id, user)
    
    self.assertEqual(result.status, NODE_STATUS.ALLOCATED)

# ✗ Bad: Tests internal implementation
def test_machine_service_calls_repository_get_method(self):
    mock_repo = Mock()
    service = MachineService(repo=mock_repo)
    
    service.allocate_machine("abc123", user)
    
    mock_repo.get_machine.assert_called_once()  # Testing implementation detail
```

### Keep Tests Independent

**Tests should not depend on each other:**

```python
# ✗ Bad: Tests depend on execution order
def test_1_create_machine(self):
    self.machine = factory.make_Machine()  # State stored

def test_2_update_machine(self):
    self.machine.hostname = "updated"  # Depends on test_1
    self.machine.save()

# ✓ Good: Each test is independent
def test_create_machine(self):
    machine = factory.make_Machine()
    self.assertIsNotNone(machine.system_id)

def test_update_machine(self):
    machine = factory.make_Machine()  # Create fresh
    machine.hostname = "updated"
    machine.save()
    self.assertEqual(machine.hostname, "updated")
```

### Test Error Cases

**Don't just test happy path:**

```python
def test_allocate_machine_raises_error_when_already_allocated(self):
    machine = factory.make_Machine(status=NODE_STATUS.ALLOCATED)
    
    with self.assertRaises(MachineAlreadyAllocatedError):
        machine.allocate()

def test_api_returns_400_when_invalid_status_filter(self):
    response = self.client.get("/api/machines/?status=INVALID")
    self.assertEqual(response.status_code, 400)
```

## Common TDD Anti-Patterns

### ❌ Writing Tests After Code

**Problem:** Tests become an afterthought, often with poor coverage

**Solution:** Write test first, always

### ❌ Testing Implementation Details

**Problem:** Tests break when refactoring, even if behavior unchanged

```python
# Bad: Testing internal method call
mock_validator.validate.assert_called_once()

# Good: Testing observable outcome
self.assertTrue(result.is_valid)
```

### ❌ Overly Complex Tests

**Problem:** Hard to understand, hard to maintain

```python
# Bad: Too much setup, unclear what's being tested
def test_complex_scenario(self):
    # 50 lines of setup
    # Multiple nested loops
    # Complex assertions
    
# Good: Clear and focused
def test_query_filters_by_hostname(self):
    factory.make_Machine(hostname="match")
    factory.make_Machine(hostname="other")
    results = repo.filter(hostname="match")
    self.assertEqual(len(results), 1)
```

### ❌ Testing Framework Code

**Problem:** Wasted effort testing Django/React instead of your code

```python
# Bad: Testing Django saves to database
def test_machine_saves_to_database(self):
    machine = Machine.objects.create(hostname="test")
    self.assertEqual(Machine.objects.count(), 1)

# Good: Testing your business logic
def test_machine_allocation_updates_status(self):
    # Your logic, not Django's
```

### ❌ Large Test Classes

**Problem:** Thousands of lines in one test file

**Solution:** Split by feature/behavior

```python
# Good organization
test_machine_repository_queries.py
test_machine_repository_mutations.py
test_machine_repository_filtering.py
```

## TDD Workflow Example

**Feature:** Add method to find machines by hardware specification

**Iteration 1: Basic Case**

```python
# RED
def test_find_by_cpu_count_returns_matching_machines(self):
    factory.make_Machine(cpu_count=4)
    factory.make_Machine(cpu_count=8)
    
    results = repo.find_by_hardware(cpu_count=4)
    
    self.assertEqual(len(results), 1)
    self.assertEqual(results[0].cpu_count, 4)

# GREEN
def find_by_hardware(self, cpu_count=None):
    filters = {}
    if cpu_count is not None:
        filters['cpu_count'] = cpu_count
    return Machine.objects.filter(**filters)

# REFACTOR: (none needed yet)
```

**Iteration 2: Add Memory Filter**

```python
# RED
def test_find_by_memory_returns_matching_machines(self):
    factory.make_Machine(memory=8192)
    factory.make_Machine(memory=16384)
    
    results = repo.find_by_hardware(memory=8192)
    
    self.assertEqual(len(results), 1)

# GREEN
def find_by_hardware(self, cpu_count=None, memory=None):
    filters = {}
    if cpu_count is not None:
        filters['cpu_count'] = cpu_count
    if memory is not None:
        filters['memory'] = memory
    return Machine.objects.filter(**filters)

# REFACTOR: Extract filter building
def find_by_hardware(self, **hardware_specs):
    filters = {k: v for k, v in hardware_specs.items() if v is not None}
    return Machine.objects.filter(**filters)
```

**Iteration 3: Combine Filters**

```python
# RED
def test_find_by_hardware_combines_filters(self):
    factory.make_Machine(cpu_count=4, memory=8192)
    factory.make_Machine(cpu_count=4, memory=16384)
    factory.make_Machine(cpu_count=8, memory=8192)
    
    results = repo.find_by_hardware(cpu_count=4, memory=8192)
    
    self.assertEqual(len(results), 1)

# GREEN: Already passes with refactored code!

# REFACTOR: (done in iteration 2)
```

## Summary

Test-Driven Implementation ensures:

1. **Tests are written first** - driving design and preventing gaps
2. **Red-Green-Refactor cycle** - small incremental steps with fast feedback
3. **Clear test structure** - Arrange-Act-Assert for readability
4. **MAAS-specific patterns** - appropriate testing for models, services, APIs, UI
5. **Behavior focus** - test what code does, not how it does it
6. **Independence** - tests don't depend on each other
7. **Error coverage** - test failures, not just success paths

TDD takes discipline but pays dividends in code quality, confidence, and maintainability. In MAAS, where reliability is critical, TDD is not optional—it's essential.