# Test Code Quality

## Purpose

Define clean testing practices for MAAS: readable, maintainable tests without unnecessary verbosity, trivial assertions, or obvious comments.

## When to Use

- Writing or reviewing tests (Python or Go)
- Creating test fixtures
- Organizing test suites

**For detailed patterns and examples**, see:
- **[Python Testing](../languages/python-testing.md)** - pytest, fixtures, mocking, async patterns
- **[Go Testing](../languages/go-testing.md)** - table-driven tests, testify, benchmarks

## Test Quality Principles

1. **Self-Documenting**: Test names explain what is being tested
2. **Minimal**: Test only meaningful behavior, not framework internals
3. **Focused**: One test, one concern
4. **Clear Data**: Use meaningful test values, not magic numbers
5. **No Verbosity**: Avoid docstrings unless test is complex
6. **No Obvious Comments**: Code should speak for itself
7. **Clean Fixtures**: Fixture names explain what they provide
8. **Organized**: Group related tests logically

## What NOT to Test

- Framework behavior (Pydantic validation, Django ORM basics)
- Language features (list operations, dict access)
- Third-party library internals
- Obvious getters/setters
- Trivial assertions (`assert x is not None` when x is always set)

## Test Naming

### Python
```python
# Good: Describes behavior and outcome
def test_create_machine_returns_instance_with_generated_id()
def test_create_machine_raises_validation_error_for_empty_hostname()
def test_list_machines_filters_by_zone_when_zone_id_provided()

# Bad: Vague or obvious
def test_create_machine()
def test_machine()
```

### Go
```go
// Good: Describes behavior and outcome
func TestCreateMachineReturnsValidInstance(t *testing.T)
func TestGetMachineReturnsErrorForInvalidID(t *testing.T)

// Bad: Vague
func TestMachine(t *testing.T)
func TestCreate(t *testing.T)
```

## When Comments Are Acceptable

Comments are acceptable when explaining **complex test behavior** or **non-obvious setup**:

```python
def test_concurrent_allocation_uses_database_locking():
    """
    Verifies SELECT FOR UPDATE prevents race conditions.
    
    Without proper locking, concurrent allocations could assign
    the same machine twice. This test spawns multiple threads
    to verify the database lock prevents this.
    """
    # Complex test implementation
```

**Never comment obvious test code**:
```python
# Bad
def test_machine_status():
    # Create a machine  # OBVIOUS
    machine = Machine(status="ready")
    
    # Check if it's ready  # OBVIOUS
    assert machine.is_ready()
```

## Common Anti-Patterns

### ❌ Verbose Docstrings
```python
# Don't write essays
def test_get_machine():
    """
    This test verifies that when we call the get_machine method
    with valid parameters, it successfully retrieves...
    """  # DELETE THIS
```

### ❌ Testing Multiple Things
```python
# Split into separate tests
def test_machine_crud_operations():  # BAD
    machine = create_machine("test", 1)
    machine = update_machine(machine.id, {"cpu_count": 8})
    machines = list_machines()
    delete_machine(machine.id)
```

### ❌ Hardcoded IDs
```python
# Use fixtures instead
def test_get_machine():
    machine = get_machine(42)  # What if ID 42 doesn't exist?
```

### ❌ Over-Mocking
```python
# Mock only external dependencies
def test_machine_service(mock_repo, mock_temporal, mock_notifications, mock_cache):
    # Too many mocks - not testing real behavior
```

## Test Organization

### Python
```
tests/
├── test_machines.py           # Tests for machine operations
├── test_zones.py              # Tests for zone operations
├── conftest.py                # Shared fixtures
└── factories.py               # Test data factories
```

### Go
```
package/
├── machine.go
├── machine_test.go           # Tests for machine.go
├── repository.go
├── repository_test.go        # Tests for repository.go
└── testdata/                 # Test fixtures
    ├── valid_config.json
    └── invalid_config.json
```

## Quick Checklist

Before submitting tests, verify:

- [ ] Test names describe behavior and outcome
- [ ] No verbose docstrings (unless complex behavior)
- [ ] No obvious comments
- [ ] Testing meaningful behavior (not framework/language features)
- [ ] One concern per test
- [ ] Using fixtures (not hardcoded IDs)
- [ ] Mocking only external dependencies
- [ ] Tests are independent (can run in any order)
- [ ] Tests clean up after themselves