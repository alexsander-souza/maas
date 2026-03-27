# Python Testing

## Purpose

Define testing patterns for MAAS Python code using pytest, including fixture usage, test organization, mocking strategies, and meaningful test design.

## When to Use

- Writing tests for new Python code (v3 API, service layer, repositories)
- Creating fixtures for test data and dependencies
- Mocking external dependencies
- Testing async code
- Organizing test suites

## Pattern Examples

### Basic Pytest Structure

```python
# tests/test_machines.py
import pytest
from maasservicelayer.services.machines import MachineService
from maasservicelayer.models.machines import Machine

def test_get_machine_returns_existing_machine(machine_service, sample_machine):
    result = machine_service.get_by_id(sample_machine.id)
    
    assert result is not None
    assert result.id == sample_machine.id
    assert result.hostname == sample_machine.hostname

def test_get_machine_raises_not_found_for_invalid_id(machine_service):
    with pytest.raises(MachineNotFound):
        machine_service.get_by_id(99999)
```

### Fixture Patterns

**Simple Fixtures**:

```python
import pytest
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.services.machines import MachineService

@pytest.fixture
def machine_repository(db_connection):
    return MachineRepository(db_connection)

@pytest.fixture
def machine_service(machine_repository):
    return MachineService(machine_repository)

@pytest.fixture
def sample_machine(machine_repository):
    return machine_repository.create({
        "hostname": "test-machine",
        "zone_id": 1,
    })
```

**Fixtures with Cleanup**:

```python
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "temp"})
    yield machine
    # Cleanup after test
    machine_repository.delete(machine.id)
```

**Parameterized Fixtures**:

```python
@pytest.fixture(params=["ready", "allocated", "deployed"])
def machine_status(request):
    return request.param

def test_machine_filtering_by_status(machine_service, machine_status):
    machines = machine_service.list_by_status(machine_status)
    assert all(m.status == machine_status for m in machines)
```

### Database Fixtures

**Connection Fixture**:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

@pytest.fixture
async def db_connection():
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test_db")
    async with engine.begin() as conn:
        yield conn
        await conn.rollback()  # Rollback after each test
```

**Repository Fixtures**:

```python
@pytest.fixture
def machine_repo(db_connection):
    return MachineRepository(db_connection)

@pytest.fixture
def zone_repo(db_connection):
    return ZoneRepository(db_connection)
```

### Mocking External Dependencies

**Mock Services**:

```python
from unittest.mock import Mock, AsyncMock
import pytest

@pytest.fixture
def mock_temporal_client():
    client = Mock()
    client.execute_workflow = AsyncMock(return_value={"status": "success"})
    return client

@pytest.fixture
def machine_service(machine_repository, mock_temporal_client):
    return MachineService(
        repository=machine_repository,
        temporal_client=mock_temporal_client,
    )

def test_deploy_machine_triggers_workflow(machine_service, mock_temporal_client):
    machine_service.deploy(machine_id=1)
    
    mock_temporal_client.execute_workflow.assert_called_once()
```

**Patch External Calls**:

```python
from unittest.mock import patch

def test_machine_creation_sends_notification(machine_service):
    with patch("maasservicelayer.services.notifications.send_notification") as mock_notify:
        machine_service.create({"hostname": "new-machine"})
        
        mock_notify.assert_called_once_with(
            event="machine_created",
            data={"hostname": "new-machine"}
        )
```

### Testing Async Code

```python
import pytest

@pytest.mark.asyncio
async def test_async_machine_creation(machine_service):
    machine = await machine_service.create_async({
        "hostname": "async-machine",
        "zone_id": 1,
    })
    
    assert machine.id is not None
    assert machine.hostname == "async-machine"

@pytest.mark.asyncio
async def test_concurrent_operations(machine_service):
    import asyncio
    
    results = await asyncio.gather(
        machine_service.get_by_id(1),
        machine_service.get_by_id(2),
        machine_service.get_by_id(3),
    )
    
    assert len(results) == 3
```

### Parametrized Tests

```python
@pytest.mark.parametrize("hostname,expected_valid", [
    ("valid-hostname", True),
    ("valid.hostname", True),
    ("invalid_hostname", False),
    ("", False),
    ("a" * 256, False),
])
def test_hostname_validation(hostname, expected_valid):
    if expected_valid:
        Machine(hostname=hostname, zone_id=1)  # Should not raise
    else:
        with pytest.raises(ValueError):
            Machine(hostname=hostname, zone_id=1)
```

### Testing Exceptions

```python
def test_get_nonexistent_machine_raises_not_found(machine_service):
    with pytest.raises(MachineNotFound) as exc_info:
        machine_service.get_by_id(99999)
    
    assert exc_info.value.machine_id == 99999

def test_invalid_status_raises_validation_error(machine_service):
    with pytest.raises(ValueError, match="Invalid status"):
        machine_service.update_status(1, "invalid_status")
```

### Testing Validators (Pydantic)

```python
from pydantic import ValidationError

def test_machine_request_validates_hostname():
    with pytest.raises(ValidationError) as exc_info:
        MachineRequest(hostname="", zone_id=1)
    
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("hostname",) for e in errors)

def test_machine_request_normalizes_hostname():
    request = MachineRequest(hostname="  TEST-Machine  ", zone_id=1)
    assert request.hostname == "test-machine"
```

### Test Organization

```python
# Group related tests in classes
class TestMachineCreation:
    def test_create_with_valid_data(self, machine_service):
        machine = machine_service.create({"hostname": "test", "zone_id": 1})
        assert machine.id is not None
    
    def test_create_with_duplicate_hostname_fails(self, machine_service):
        machine_service.create({"hostname": "test", "zone_id": 1})
        with pytest.raises(DuplicateHostname):
            machine_service.create({"hostname": "test", "zone_id": 1})

class TestMachineRetrieval:
    def test_get_by_id(self, machine_service, sample_machine):
        result = machine_service.get_by_id(sample_machine.id)
        assert result.id == sample_machine.id
    
    def test_list_with_filters(self, machine_service):
        machines = machine_service.list(zone_id=1)
        assert all(m.zone_id == 1 for m in machines)
```

### Fixture Factories

```python
@pytest.fixture
def machine_factory(machine_repository):
    def _create_machine(**kwargs):
        defaults = {
            "hostname": "default-machine",
            "zone_id": 1,
            "cpu_count": 4,
            "memory": 8192,
        }
        defaults.update(kwargs)
        return machine_repository.create(defaults)
    
    return _create_machine

def test_multiple_machines(machine_factory):
    machine1 = machine_factory(hostname="machine1")
    machine2 = machine_factory(hostname="machine2", cpu_count=8)
    
    assert machine1.cpu_count == 4
    assert machine2.cpu_count == 8
```

### Markers for Test Categories

```python
import pytest

@pytest.mark.unit
def test_machine_model_validation():
    # Pure unit test, no external dependencies
    pass

@pytest.mark.integration
def test_machine_repository_integration(db_connection):
    # Integration test with database
    pass

@pytest.mark.slow
def test_large_dataset_processing(machine_service):
    # Slow test that processes many records
    pass
```

## Anti-patterns

### ❌ Trivial Assertions

```python
# NEVER test obvious framework behavior
def test_model_has_id_field():
    machine = Machine(id=1, hostname="test", zone_id=1)
    assert hasattr(machine, "id")  # Useless test

# NEVER test Python/library internals
def test_list_contains_items():
    items = [1, 2, 3]
    assert len(items) == 3  # Testing Python, not your code
```

### ❌ Verbose Test Docstrings

```python
# NEVER write verbose docstrings in tests
def test_create_machine():
    """
    This test verifies that the create_machine method properly creates
    a new machine instance in the database and returns the created
    machine with all fields populated correctly.
    """  # Too verbose - test name should be descriptive enough
    pass

# Correct: Let the test name speak
def test_create_machine_returns_instance_with_generated_id():
    pass
```

### ❌ Testing Multiple Things

```python
# NEVER test multiple unrelated things in one test
def test_machine_operations(machine_service):
    # Wrong: Testing create, update, delete, and list all together
    machine = machine_service.create({"hostname": "test"})
    machine = machine_service.update(machine.id, {"cpu_count": 8})
    machines = machine_service.list()
    machine_service.delete(machine.id)
    # Split into separate tests
```

### ❌ Hardcoded Test Data

```python
# NEVER hardcode IDs or data that might change
def test_get_machine():
    machine = machine_service.get_by_id(42)  # What if ID 42 doesn't exist?
    assert machine.hostname == "specific-machine"  # Fragile

# Correct: Use fixtures or create test data
def test_get_machine(sample_machine):
    machine = machine_service.get_by_id(sample_machine.id)
    assert machine.id == sample_machine.id
```

### ❌ Not Cleaning Up

```python
# NEVER leave test data behind
def test_create_machine(machine_repository):
    machine = machine_repository.create({"hostname": "test"})
    # Wrong: No cleanup, pollutes database

# Correct: Use fixtures with cleanup
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "test"})
    yield machine
    machine_repository.delete(machine.id)
```

### ❌ Over-Mocking

```python
# NEVER mock everything
def test_machine_service(mock_repo, mock_temporal, mock_notifications, mock_cache):
    # Wrong: Too many mocks, not testing real behavior
    service = MachineService(mock_repo, mock_temporal, mock_notifications, mock_cache)
    # Test is meaningless
    
# Correct: Mock only external dependencies
def test_machine_service(machine_repository, mock_temporal_client):
    # Real repository, mock only external service
    service = MachineService(machine_repository, mock_temporal_client)
```

### ❌ Catching All Exceptions

```python
# NEVER catch generic exceptions in tests
def test_create_machine(machine_service):
    try:
        machine_service.create({"invalid": "data"})
        assert False, "Should have raised"  # Wrong: Hides actual error
    except Exception:
        pass  # Wrong: Too broad

# Correct: Test specific exceptions
def test_create_machine_with_invalid_data(machine_service):
    with pytest.raises(ValidationError):
        machine_service.create({"invalid": "data"})
```

## Related Skills

- **Python Patterns**: [python-patterns.md](python-patterns.md) - Code patterns being tested
- **Test Quality**: [../techniques/test-code-quality.md](../techniques/test-code-quality.md) - Writing clean tests
- **Testing Suite**: [../compositions/testing-suite.md](../compositions/testing-suite.md) - Complete testing workflow
- **SQLAlchemy**: [sqlalchemy-patterns.md](sqlalchemy-patterns.md) - Testing repository patterns
- **Django**: [django-patterns.md](django-patterns.md) - Testing Django code

## Common Fixtures in MAAS

- `db_connection`: Async database connection with transaction rollback
- `services_mock`: Mock service layer dependencies
- `admin_user`: Test user with admin privileges
- `sample_machine`, `sample_zone`, etc.: Pre-created test entities

Check `src/maastesting/fixtures.py` for available fixtures in the project.