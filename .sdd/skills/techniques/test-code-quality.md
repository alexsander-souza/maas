# Test Code Quality

## Purpose

Define clean testing practices for MAAS, focusing on readable, maintainable tests without unnecessary verbosity, trivial assertions, or obvious comments.

## When to Use

- Writing new tests (Python or Go)
- Reviewing test code
- Refactoring test suites
- Creating test fixtures
- Organizing test files

## Pattern Examples

### Self-Documenting Test Names

**Python - Descriptive Test Names**:

```python
# Test name should describe what is being tested
def test_create_machine_returns_instance_with_generated_id():
    machine = machine_service.create({"hostname": "test", "zone_id": 1})
    
    assert machine.id is not None
    assert machine.hostname == "test"

def test_create_machine_raises_validation_error_for_empty_hostname():
    with pytest.raises(ValidationError):
        machine_service.create({"hostname": "", "zone_id": 1})

def test_list_machines_filters_by_zone_when_zone_id_provided():
    machines = machine_service.list(zone_id=1)
    assert all(m.zone_id == 1 for m in machines)
```

**Go - Descriptive Test Names**:

```go
func TestCreateMachineReturnsValidInstance(t *testing.T) {
    machine, err := service.CreateMachine("test-host", 1)
    
    require.NoError(t, err)
    assert.NotZero(t, machine.ID)
    assert.Equal(t, "test-host", machine.Hostname)
}

func TestGetMachineReturnsErrorForInvalidID(t *testing.T) {
    _, err := service.GetMachine(-1)
    assert.Error(t, err)
}
```

### No Verbose Docstrings

```python
# NEVER write verbose docstrings in tests
def test_machine_creation():
    """
    This test verifies that when we call the create_machine method
    with valid parameters, it successfully creates a new machine
    instance and returns it with all the fields properly populated.
    """  # Too verbose - delete this
    machine = create_machine("test", 1)
    assert machine.id is not None

# Correct: Let test name speak for itself
def test_create_machine_returns_instance_with_id():
    machine = create_machine("test", 1)
    assert machine.id is not None

# Only add docstring for complex test behavior
def test_concurrent_machine_allocation_prevents_double_booking():
    """
    Verifies that simultaneous allocation requests for the same machine
    result in only one successful allocation due to database locking.
    """
    # Complex test logic here...
```

### Self-Documenting Fixtures

**Python - Clear Fixture Names**:

```python
# Fixture name should explain what it provides
@pytest.fixture
def sample_machine():
    """Returns a basic test machine."""
    return Machine(id=1, hostname="test-node", zone_id=1)

@pytest.fixture
def allocated_machine():
    """Returns a machine in allocated state."""
    return Machine(id=2, hostname="allocated-node", status="allocated")

@pytest.fixture
def machine_with_interfaces(sample_machine):
    """Returns a machine with network interfaces attached."""
    sample_machine.interfaces = [
        Interface(name="eth0", mac="00:11:22:33:44:55"),
        Interface(name="eth1", mac="00:11:22:33:44:66"),
    ]
    return sample_machine

# No need for comments inside fixtures if structure is clear
@pytest.fixture
def machine_repository(db_connection):
    return MachineRepository(db_connection)
```

### Avoid Trivial Assertions

```python
# NEVER test obvious framework behavior
def test_model_has_fields():
    machine = Machine(id=1, hostname="test", zone_id=1)
    assert hasattr(machine, "id")  # Useless
    assert hasattr(machine, "hostname")  # Useless

# NEVER test Python/library internals
def test_list_operations():
    items = [1, 2, 3]
    assert len(items) == 3  # Testing Python, not your code
    assert items[0] == 1  # Obvious

# Correct: Test meaningful behavior
def test_machine_is_ready_returns_true_when_status_is_ready():
    machine = Machine(status="ready")
    assert machine.is_ready() is True

def test_machine_is_ready_returns_false_when_status_is_allocated():
    machine = Machine(status="allocated")
    assert machine.is_ready() is False
```

### Minimal, Focused Tests

```python
# Each test should verify one thing
def test_machine_validates_hostname_length():
    with pytest.raises(ValidationError, match="hostname"):
        Machine(hostname="", zone_id=1)

def test_machine_validates_zone_id_positive():
    with pytest.raises(ValidationError, match="zone_id"):
        Machine(hostname="test", zone_id=0)

# Don't combine unrelated assertions
def test_machine_creation():  # WRONG: Testing too much
    machine = create_machine("test", 1)
    assert machine.id is not None
    assert machine.hostname == "test"
    machine.status = "allocated"
    assert machine.status == "allocated"
    machine.delete()
    assert Machine.objects.filter(id=machine.id).count() == 0
    # Split into separate tests
```

### Clear Test Data

```python
# Use meaningful test data
def test_hostname_validation():
    # Clear: Each value has a purpose
    valid_hostnames = ["node1", "test-machine", "server.local"]
    invalid_hostnames = ["", "node_1", "UPPERCASE", "a" * 256]
    
    for hostname in valid_hostnames:
        Machine(hostname=hostname, zone_id=1)  # Should not raise
    
    for hostname in invalid_hostnames:
        with pytest.raises(ValidationError):
            Machine(hostname=hostname, zone_id=1)

# Avoid magic numbers
def test_machine_cpu_limit():
    machine = Machine(cpu_count=1024)  # Why 1024? Unclear
    
    # Better: Named constants
    MAX_CPU_COUNT = 256
    machine = Machine(cpu_count=MAX_CPU_COUNT + 1)
    with pytest.raises(ValidationError):
        machine.validate()
```

### Go - Table-Driven Test Quality

```go
func TestValidateHostname(t *testing.T) {
    tests := []struct {
        name     string
        hostname string
        wantErr  bool
    }{
        {"valid simple", "node1", false},
        {"valid with dash", "test-node", false},
        {"empty fails", "", true},
        {"underscore fails", "test_node", true},
        {"too long fails", string(make([]byte, 256)), true},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := ValidateHostname(tt.hostname)
            if (err != nil) != tt.wantErr {
                t.Errorf("error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}

// NEVER write redundant comments
func TestCreateMachine(t *testing.T) {
    // Create a new machine  // WRONG: Obvious from code
    machine := NewMachine("test", 1)
    
    // Check that ID is not zero  // WRONG: Obvious from assertion
    assert.NotZero(t, machine.ID)
    
    // Just write the test
    machine := NewMachine("test", 1)
    assert.NotZero(t, machine.ID)
}
```

### Organize Tests Logically

```python
# Group related tests in classes
class TestMachineCreation:
    def test_create_with_valid_data_returns_machine(self, service):
        machine = service.create({"hostname": "test", "zone_id": 1})
        assert machine.id is not None
    
    def test_create_with_duplicate_hostname_raises_error(self, service):
        service.create({"hostname": "test", "zone_id": 1})
        with pytest.raises(DuplicateHostname):
            service.create({"hostname": "test", "zone_id": 1})

class TestMachineRetrieval:
    def test_get_by_id_returns_existing_machine(self, service, sample_machine):
        result = service.get_by_id(sample_machine.id)
        assert result.id == sample_machine.id
    
    def test_get_by_id_raises_not_found_for_invalid_id(self, service):
        with pytest.raises(MachineNotFound):
            service.get_by_id(99999)
```

### Cleanup Without Comments

```python
# Cleanup is self-explanatory
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "temp"})
    yield machine
    machine_repository.delete(machine.id)

# Setup/teardown without comments
@pytest.fixture
def test_database():
    db = create_test_db()
    run_migrations(db)
    yield db
    db.close()
```

## Anti-patterns

### ❌ Verbose Docstrings

```python
# NEVER write obvious docstrings
def test_get_machine():
    """
    Test the get_machine function.
    
    This test creates a machine and then retrieves it to verify
    that the get_machine function works correctly.
    """  # Delete all of this
```

### ❌ Obvious Comments

```python
# NEVER comment obvious test code
def test_machine_status():
    # Create a machine  # WRONG
    machine = Machine(status="ready")
    
    # Check if it's ready  # WRONG
    assert machine.is_ready()
    
    # Change status to allocated  # WRONG
    machine.status = "allocated"
    
    # Verify it's not ready anymore  # WRONG
    assert not machine.is_ready()
```

### ❌ Testing Multiple Things

```python
# NEVER combine unrelated tests
def test_machine_crud_operations():  # WRONG
    # Create
    machine = create_machine("test", 1)
    # Update
    update_machine(machine.id, {"cpu_count": 8})
    # List
    machines = list_machines()
    # Delete
    delete_machine(machine.id)
    # Split into 4 separate tests
```

### ❌ Redundant Assertions

```python
# NEVER assert the obvious
def test_pydantic_validation():
    request = MachineRequest(hostname="test", zone_id=1)
    assert request.hostname == "test"  # Obvious
    assert isinstance(request, MachineRequest)  # Useless
    assert hasattr(request, "hostname")  # Framework behavior
```

### ❌ Hardcoded IDs

```python
# NEVER hardcode test IDs
def test_get_machine():
    machine = get_machine(42)  # What if ID 42 doesn't exist?
    assert machine is not None

# Correct: Create test data
def test_get_machine(sample_machine):
    machine = get_machine(sample_machine.id)
    assert machine.id == sample_machine.id
```

## Related Skills

- **Python Testing**: [../languages/python-testing.md](../languages/python-testing.md) - pytest patterns
- **Go Testing**: [../languages/go-testing.md](../languages/go-testing.md) - Go test patterns  
- **Code Clarity**: [code-clarity.md](code-clarity.md) - Readable code principles
- **Naming Conventions**: [naming-conventions.md](naming-conventions.md) - Naming tests and fixtures
- **Minimal Comments**: [minimal-comments.md](minimal-comments.md) - When to comment

## Test Quality Principles

1. **Self-Documenting**: Test names explain what is being tested
2. **Minimal**: Test only meaningful behavior, not framework internals
3. **Focused**: One test, one concern
4. **Clear Data**: Use meaningful test values, not magic numbers
5. **No Verbosity**: Avoid docstrings unless test is complex
6. **No Obvious Comments**: Code should speak for itself
7. **Clean Fixtures**: Fixture names explain what they provide
8. **Organized**: Group related tests logically

## When Comments Are Acceptable

```python
# Comment is acceptable here - explains WHY
def test_concurrent_allocation_uses_database_locking():
    """
    Verifies SELECT FOR UPDATE prevents race conditions.
    
    Without proper locking, concurrent allocations could assign
    the same machine twice. This test spawns multiple threads
    to verify the database lock prevents this.
    """
    # Complex test implementation
```

## Test File Organization

```
tests/
├── test_machines.py           # Tests for machine operations
├── test_zones.py              # Tests for zone operations
├── conftest.py                # Shared fixtures
└── factories.py               # Test data factories (not fixtures)
```
