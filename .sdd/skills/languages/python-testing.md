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
    assert result.id == sample_machine.id

def test_get_machine_raises_not_found_for_invalid_id(machine_service):
    with pytest.raises(MachineNotFound):
        machine_service.get_by_id(99999)
```

### Fixture Patterns

```python
import pytest

@pytest.fixture
def machine_service(machine_repository):
    return MachineService(machine_repository)

@pytest.fixture
def sample_machine(machine_repository):
    return machine_repository.create({"hostname": "test-machine", "zone_id": 1})

# Fixture with cleanup
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "temp"})
    yield machine
    machine_repository.delete(machine.id)

# Parameterized fixture
@pytest.fixture(params=["ready", "allocated", "deployed"])
def machine_status(request):
    return request.param
```

### Database Fixtures

```python
@pytest.fixture
async def db_connection():
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test_db")
    async with engine.begin() as conn:
        yield conn
        await conn.rollback()

@pytest.fixture
def machine_repo(db_connection):
    return MachineRepository(db_connection)
```

### Mocking External Dependencies

```python
from unittest.mock import Mock, AsyncMock, patch

@pytest.fixture
def mock_temporal_client():
    client = Mock()
    client.execute_workflow = AsyncMock(return_value={"status": "success"})
    return client

def test_deploy_machine_triggers_workflow(machine_service, mock_temporal_client):
    machine_service.deploy(machine_id=1)
    mock_temporal_client.execute_workflow.assert_called_once()

def test_machine_creation_sends_notification(machine_service):
    with patch("maasservicelayer.services.notifications.send_notification") as mock_notify:
        machine_service.create({"hostname": "new-machine"})
        mock_notify.assert_called_once_with(event="machine_created", data={"hostname": "new-machine"})
```

### Testing Async Code

```python
@pytest.mark.asyncio
async def test_async_machine_creation(machine_service):
    machine = await machine_service.create_async({"hostname": "async-machine", "zone_id": 1})
    assert machine.id is not None

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
@pytest.mark.parametrize("hostname,valid", [
    ("valid-hostname", True),
    ("invalid_hostname", False),
    ("", False),
])
def test_hostname_validation(hostname, valid):
    if valid:
        Machine(hostname=hostname, zone_id=1)
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
def test_machine_request_validates_hostname():
    with pytest.raises(ValidationError) as exc_info:
        MachineRequest(hostname="", zone_id=1)
    assert any(e["loc"] == ("hostname",) for e in exc_info.value.errors())
```

### Test Organization

```python
class TestMachineCreation:
    def test_create_with_valid_data(self, machine_service):
        machine = machine_service.create({"hostname": "test", "zone_id": 1})
        assert machine.id is not None
    
    def test_create_with_duplicate_hostname_fails(self, machine_service):
        machine_service.create({"hostname": "test", "zone_id": 1})
        with pytest.raises(DuplicateHostname):
            machine_service.create({"hostname": "test", "zone_id": 1})
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
    assert hasattr(machine, "id")  # Useless - testing framework
```

### ❌ Verbose Test Docstrings

```python
# NEVER write verbose docstrings - test name should be descriptive
def test_create_machine_returns_instance_with_generated_id():
    pass
```

### ❌ Testing Multiple Things

```python
# NEVER test multiple unrelated things in one test
def test_machine_operations(machine_service):
    machine = machine_service.create({"hostname": "test"})
    machine = machine_service.update(machine.id, {"cpu_count": 8})
    machines = machine_service.list()
    machine_service.delete(machine.id)  # Split into separate tests
```

### ❌ Hardcoded Test Data

```python
# NEVER hardcode IDs - use fixtures
def test_get_machine(sample_machine):
    machine = machine_service.get_by_id(sample_machine.id)
    assert machine.id == sample_machine.id
```

### ❌ Not Cleaning Up

```python
# Use fixtures with cleanup to avoid polluting database
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "test"})
    yield machine
    machine_repository.delete(machine.id)
```

### ❌ Over-Mocking

```python
# Mock only external dependencies, not everything
def test_machine_service(machine_repository, mock_temporal_client):
    service = MachineService(machine_repository, mock_temporal_client)
```

### ❌ Catching All Exceptions

```python
# Test specific exceptions, not generic Exception
def test_create_machine_with_invalid_data(machine_service):
    with pytest.raises(ValidationError):
        machine_service.create({"invalid": "data"})
```

## Common Fixtures in MAAS

- `db_connection`: Async database connection with transaction rollback
- `services_mock`: Mock service layer dependencies
- `admin_user`: Test user with admin privileges
- `sample_machine`, `sample_zone`, etc.: Pre-created test entities

Check `src/maastesting/fixtures.py` for available fixtures in the project.