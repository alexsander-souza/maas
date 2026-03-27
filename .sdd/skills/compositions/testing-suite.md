# Testing Suite Composition

## Purpose

Guide for implementing complete testing coverage for MAAS features, combining unit tests, integration tests, fixtures, mocking, and quality practices across Python and Go.

## When to Use

- Setting up tests for a new feature
- Adding comprehensive test coverage to existing code
- Reviewing test suite completeness
- Establishing testing standards for a module

## Composition Overview

This guide combines:
- **Python Testing**: pytest patterns, fixtures, async tests
- **Go Testing**: table-driven tests, testify assertions
- **Test Code Quality**: Clean tests without verbosity
- **SQLAlchemy/Django**: Testing repository and ORM code
- **Security**: Testing input validation and authorization

## Complete Testing Workflow

### 1. Test Structure Setup

**Python - Test File Organization**:

```python
# tests/maasservicelayer/test_machine_service.py
import pytest
from maasservicelayer.services.machines import MachineService
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.exceptions import MachineNotFound

# Fixtures at module level or in conftest.py
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
        "cpu_count": 4,
    })
```

**Go - Test File Organization**:

```go
// internal/machine/service_test.go
package machine

import (
    "testing"
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

func TestMachineService(t *testing.T) {
    // Shared setup
    repo := NewInMemoryRepository()
    service := NewMachineService(repo)
    
    t.Run("CreateMachine", func(t *testing.T) {
        // Test implementation
    })
    
    t.Run("GetMachine", func(t *testing.T) {
        // Test implementation
    })
}
```

### 2. Unit Tests (Business Logic)

**Python - Service Layer Tests**:

```python
class TestMachineService:
    """Test machine service business logic."""
    
    def test_create_machine_returns_instance_with_id(self, machine_service):
        request = MachineRequest(hostname="test", zone_id=1)
        
        machine = machine_service.create(request)
        
        assert machine.id is not None
        assert machine.hostname == "test"
        assert machine.status == "new"
    
    def test_create_machine_validates_hostname_format(self, machine_service):
        request = MachineRequest(hostname="invalid_name", zone_id=1)
        
        with pytest.raises(ValidationError, match="hostname"):
            machine_service.create(request)
    
    def test_get_machine_raises_not_found_for_invalid_id(self, machine_service):
        with pytest.raises(MachineNotFound):
            machine_service.get_by_id(99999)
    
    def test_list_machines_filters_by_zone(self, machine_service, sample_machine):
        machines = machine_service.list(zone_id=sample_machine.zone_id)
        
        assert len(machines) > 0
        assert all(m.zone_id == sample_machine.zone_id for m in machines)
```

**Go - Service Unit Tests**:

```go
func TestMachineService_CreateMachine(t *testing.T) {
    tests := []struct {
        name     string
        hostname string
        zoneID   int
        wantErr  bool
    }{
        {"valid machine", "test-node", 1, false},
        {"empty hostname", "", 1, true},
        {"invalid zone", "test", -1, true},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            service := NewMachineService(NewInMemoryRepository())
            
            machine, err := service.CreateMachine(tt.hostname, tt.zoneID)
            
            if tt.wantErr {
                assert.Error(t, err)
                assert.Nil(t, machine)
            } else {
                require.NoError(t, err)
                assert.NotZero(t, machine.ID)
                assert.Equal(t, tt.hostname, machine.Hostname)
            }
        })
    }
}
```

### 3. Integration Tests (Database)

**Python - Repository Integration Tests**:

```python
@pytest.mark.integration
class TestMachineRepository:
    """Test repository database operations."""
    
    async def test_create_persists_to_database(self, machine_repository):
        machine_data = {
            "hostname": "db-test",
            "zone_id": 1,
            "cpu_count": 8,
        }
        
        created = await machine_repository.create(machine_data)
        retrieved = await machine_repository.get_by_id(created.id)
        
        assert retrieved is not None
        assert retrieved.hostname == "db-test"
        assert retrieved.cpu_count == 8
    
    async def test_list_with_query_spec_filters_correctly(self, machine_repository):
        await machine_repository.create({"hostname": "zone1", "zone_id": 1})
        await machine_repository.create({"hostname": "zone2", "zone_id": 2})
        
        query = QuerySpec(where=MachineClauseFactory.with_zone_id(1))
        machines = await machine_repository.list(query)
        
        assert len(machines) == 1
        assert machines[0].zone_id == 1
    
    async def test_update_modifies_existing_record(self, machine_repository, sample_machine):
        update_data = {"cpu_count": 16}
        
        updated = await machine_repository.update(sample_machine.id, update_data)
        
        assert updated.cpu_count == 16
        assert updated.id == sample_machine.id
```

### 4. Mocking External Dependencies

**Python - Mock External Services**:

```python
from unittest.mock import Mock, AsyncMock, patch

@pytest.fixture
def mock_temporal_client():
    client = Mock()
    client.execute_workflow = AsyncMock(return_value={"status": "success"})
    return client

@pytest.fixture
def machine_service_with_mocks(machine_repository, mock_temporal_client):
    return MachineService(
        repository=machine_repository,
        temporal_client=mock_temporal_client,
    )

async def test_deploy_machine_triggers_workflow(
    machine_service_with_mocks,
    sample_machine,
    mock_temporal_client,
):
    await machine_service_with_mocks.deploy(sample_machine.id)
    
    mock_temporal_client.execute_workflow.assert_called_once()
    call_args = mock_temporal_client.execute_workflow.call_args
    assert call_args[0][0] == "DeployMachineWorkflow"

def test_external_api_call_with_patch(machine_service):
    with patch("maasservicelayer.external.api_client.post") as mock_post:
        mock_post.return_value = {"status": "ok"}
        
        result = machine_service.notify_external_system(machine_id=1)
        
        assert result["status"] == "ok"
        mock_post.assert_called_once()
```

**Go - Mock Interfaces**:

```go
import "github.com/stretchr/testify/mock"

type MockRepository struct {
    mock.Mock
}

func (m *MockRepository) GetByID(id int) (*Machine, error) {
    args := m.Called(id)
    if args.Get(0) == nil {
        return nil, args.Error(1)
    }
    return args.Get(0).(*Machine), args.Error(1)
}

func TestMachineService_WithMock(t *testing.T) {
    mockRepo := new(MockRepository)
    expectedMachine := &Machine{ID: 1, Hostname: "test"}
    
    mockRepo.On("GetByID", 1).Return(expectedMachine, nil)
    
    service := NewMachineService(mockRepo)
    machine, err := service.GetMachine(1)
    
    require.NoError(t, err)
    assert.Equal(t, expectedMachine, machine)
    mockRepo.AssertExpectations(t)
}
```

### 5. Testing Async Code

**Python - Async Tests**:

```python
@pytest.mark.asyncio
async def test_async_machine_creation(machine_service):
    request = MachineRequest(hostname="async-test", zone_id=1)
    
    machine = await machine_service.create_async(request)
    
    assert machine.id is not None
    assert machine.hostname == "async-test"

@pytest.mark.asyncio
async def test_concurrent_operations(machine_service):
    import asyncio
    
    requests = [
        MachineRequest(hostname=f"machine-{i}", zone_id=1)
        for i in range(10)
    ]
    
    machines = await asyncio.gather(*[
        machine_service.create_async(req) for req in requests
    ])
    
    assert len(machines) == 10
    assert all(m.id is not None for m in machines)
```

### 6. Testing Security and Validation

**Python - Input Validation Tests**:

```python
class TestMachineRequestValidation:
    """Test Pydantic validation rules."""
    
    def test_hostname_must_not_be_empty(self):
        with pytest.raises(ValidationError, match="hostname"):
            MachineRequest(hostname="", zone_id=1)
    
    def test_hostname_max_length_enforced(self):
        with pytest.raises(ValidationError, match="hostname"):
            MachineRequest(hostname="a" * 256, zone_id=1)
    
    def test_zone_id_must_be_positive(self):
        with pytest.raises(ValidationError, match="zone_id"):
            MachineRequest(hostname="test", zone_id=0)
    
    def test_hostname_normalized_to_lowercase(self):
        request = MachineRequest(hostname="TEST", zone_id=1)
        assert request.hostname == "test"
```

**Testing Authorization**:

```python
def test_delete_machine_requires_permission(authenticated_request, machine_service):
    authenticated_request.user.permissions = []  # No permissions
    
    with pytest.raises(PermissionDenied):
        machine_service.delete(authenticated_request, machine_id=1)

def test_delete_machine_allows_owner(authenticated_request, sample_machine):
    sample_machine.owner = authenticated_request.user
    
    # Should succeed - user owns machine
    machine_service.delete(authenticated_request, sample_machine.id)
```

### 7. Test Fixtures and Factories

**Python - Comprehensive Fixtures**:

```python
# conftest.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection

@pytest.fixture
async def db_connection():
    """Provide database connection with automatic rollback."""
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test_db")
    async with engine.begin() as conn:
        yield conn
        await conn.rollback()

@pytest.fixture
def machine_factory(machine_repository):
    """Factory for creating test machines with custom attributes."""
    created_machines = []
    
    def _create(**kwargs):
        defaults = {
            "hostname": f"test-machine-{len(created_machines)}",
            "zone_id": 1,
            "cpu_count": 4,
            "memory": 8192,
        }
        defaults.update(kwargs)
        machine = machine_repository.create(defaults)
        created_machines.append(machine)
        return machine
    
    yield _create
    
    # Cleanup
    for machine in created_machines:
        machine_repository.delete(machine.id)

def test_with_factory(machine_factory):
    machine1 = machine_factory(hostname="custom1", cpu_count=8)
    machine2 = machine_factory(hostname="custom2", cpu_count=16)
    
    assert machine1.cpu_count == 8
    assert machine2.cpu_count == 16
```

### 8. Parametrized Tests

**Python - Multiple Test Cases**:

```python
@pytest.mark.parametrize("hostname,valid", [
    ("valid-hostname", True),
    ("also-valid", True),
    ("", False),
    ("invalid_underscore", False),
    ("UPPERCASE", False),  # Should be normalized
    ("a" * 256, False),  # Too long
])
def test_hostname_validation(hostname, valid):
    if valid:
        request = MachineRequest(hostname=hostname, zone_id=1)
        assert request.hostname == hostname.lower()
    else:
        with pytest.raises(ValidationError):
            MachineRequest(hostname=hostname, zone_id=1)
```

### 9. Coverage and Quality Checks

**Run Tests with Coverage**:

```bash
# Python
pytest --cov=maasservicelayer --cov-report=html tests/

# Go
go test -cover ./...
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

**Quality Gates**:

```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow tests",
]
addopts = "--strict-markers --tb=short"
```

## Testing Checklist

### Unit Tests
- [ ] Service layer business logic
- [ ] Input validation (Pydantic models)
- [ ] Error conditions and exceptions
- [ ] Edge cases and boundary conditions
- [ ] Return values and state changes

### Integration Tests
- [ ] Database operations (create, read, update, delete)
- [ ] Query filtering and sorting
- [ ] Transactions and rollbacks
- [ ] Foreign key relationships

### Security Tests
- [ ] Input validation and sanitization
- [ ] Authorization checks
- [ ] SQL injection prevention (via parameterized queries)
- [ ] Path traversal prevention

### Async Tests
- [ ] Async function behavior
- [ ] Concurrent operations
- [ ] Error handling in async context

### Mocking
- [ ] External API calls
- [ ] Temporal workflows
- [ ] Third-party services
- [ ] Time-dependent code

## Anti-patterns

### ❌ Testing Framework Internals
```python
# NEVER test Pydantic or framework behavior
def test_pydantic_model():
    request = MachineRequest(hostname="test", zone_id=1)
    assert isinstance(request, MachineRequest)  # Useless
    assert hasattr(request, "hostname")  # Framework behavior
```

### ❌ Multiple Unrelated Assertions
```python
# NEVER test multiple things in one test
def test_machine_crud():  # WRONG
    machine = create_machine("test", 1)
    update_machine(machine.id, {"cpu_count": 8})
    delete_machine(machine.id)
    # Split into 3 tests
```

### ❌ No Cleanup
```python
# NEVER leave test data behind
def test_create_machine(machine_repository):
    machine = machine_repository.create({"hostname": "test"})
    # WRONG: No cleanup
    
# Correct: Use fixture with cleanup
@pytest.fixture
def temp_machine(machine_repository):
    machine = machine_repository.create({"hostname": "test"})
    yield machine
    machine_repository.delete(machine.id)
```

## Related Skills

- **Python Testing**: [../languages/python-testing.md](../languages/python-testing.md)
- **Go Testing**: [../languages/go-testing.md](../languages/go-testing.md)
- **Test Code Quality**: [../techniques/test-code-quality.md](../techniques/test-code-quality.md)
- **SQLAlchemy Patterns**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md)
- **Security Practices**: [../techniques/security-practices.md](../techniques/security-practices.md)

## Summary

A complete testing suite includes:

1. **Unit Tests**: Business logic, validation, error handling
2. **Integration Tests**: Database, external services
3. **Fixtures**: Reusable test data and setup
4. **Mocks**: Isolate external dependencies
5. **Parametrized**: Multiple cases efficiently
6. **Async**: Concurrent operations
7. **Security**: Validation, authorization
8. **Quality**: No verbosity, clear names, focused tests