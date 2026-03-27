# maastesting Subsystem

## Purpose

Testing utilities, fixtures, and helpers shared across all MAAS test suites. This subsystem provides reusable test infrastructure including database setup, factory patterns, common test base classes, pytest plugins, and mocking utilities.

**Status**: Active - critical test infrastructure for all components.

## Location

`src/maastesting`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **pytest**: Primary test framework
- **pytest-asyncio**: Async test support

### Key Libraries
- **pytest**: Modern test framework
- **factory-boy**: Test data factory pattern
- **faker**: Realistic test data generation
- **testtools**: Legacy test framework support

## Architectural Constraints

### Shared Across Components

This subsystem serves all other MAAS components:
- `maasserver` (Django tests)
- `maasapiserver` (FastAPI tests)
- `maasservicelayer` (service/repository tests)
- `maastemporalworker` (workflow tests)
- `provisioningserver` (Twisted tests)

Changes here impact all test suites - coordinate carefully.

### Minimal Dependencies

Keep dependencies minimal to avoid circular dependencies:
- No business logic dependencies
- No direct subsystem imports except for type hints
- Focus on testing infrastructure only

### Support Both Frameworks

Support legacy and modern testing approaches:
- `testtools` for legacy Django tests
- `pytest` for modern async tests
- Gradual migration path

## Key Patterns

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.
> **See**: [python-testing.md](../../skills/languages/python-testing.md) for Python testing best practices.

### Factory Pattern

Factories for creating test data with sensible defaults:

```python
from maastesting.factory import factory

class MachineFactory:
    """Factory for creating test machines."""
    
    @staticmethod
    def make_Machine(hostname=None, status=None, **kwargs):
        """Create test machine with defaults."""
        if hostname is None:
            hostname = factory.make_name('machine')
        if status is None:
            status = NODE_STATUS.READY
        
        return Machine.objects.create(
            hostname=hostname,
            status=status,
            **kwargs
        )

# Usage
def test_machine_creation():
    machine = factory.make_Machine(hostname="test-machine")
    assert machine.hostname == "test-machine"
```

### Database Fixtures

Database setup for integration tests:

```python
import pytest

@pytest.fixture(scope="session")
def db_session():
    """Set up test database for entire session."""
    db = setup_test_database()
    yield db
    teardown_test_database(db)

@pytest.fixture
async def db_connection(db_session):
    """Provide database connection with transaction rollback."""
    async with db_session.get_connection() as conn:
        trans = await conn.begin()
        yield conn
        await trans.rollback()

# Usage
@pytest.mark.asyncio
async def test_with_database(db_connection):
    repo = MachineRepository(db_connection)
    machine = await repo.create({"hostname": "test"})
    assert machine.id is not None
```

### Common Test Base Classes

Base classes for standard test patterns:

```python
from abc import ABC, abstractmethod

class RepositoryCommonTests(ABC):
    """Common tests for all repositories."""
    
    @abstractmethod
    def get_repository_class(self):
        """Return repository class to test."""
        pass
    
    @abstractmethod
    def get_create_resource(self):
        """Return resource data for create test."""
        pass
    
    @pytest.mark.asyncio
    async def test_create(self, db_connection):
        """Test creating a resource."""
        repo = self.get_repository_class()(db_connection)
        resource = self.get_create_resource()
        created = await repo.create(resource)
        assert created.id is not None
    
    @pytest.mark.asyncio
    async def test_get_by_id(self, db_connection):
        """Test retrieving by ID."""
        repo = self.get_repository_class()(db_connection)
        created = await repo.create(self.get_create_resource())
        retrieved = await repo.get_by_id(created.id)
        assert retrieved.id == created.id

# Usage
class TestMachineRepository(RepositoryCommonTests):
    def get_repository_class(self):
        return MachineRepository
    
    def get_create_resource(self):
        return {"hostname": "test", "architecture": "amd64"}
```

### Service Test Base Class

Base class for testing services:

```python
class ServiceCommonTests(ABC):
    """Common tests for all services."""
    
    @abstractmethod
    def get_service_class(self):
        """Return service class to test."""
        pass
    
    @abstractmethod
    def get_create_builder(self):
        """Return builder for create test."""
        pass
    
    @pytest.mark.asyncio
    async def test_create(self, mocker):
        """Test service create with mocked repository."""
        mock_repo = mocker.Mock()
        mock_repo.create = mocker.AsyncMock(return_value=Machine(id=1))
        
        service = self.get_service_class()(mock_repo)
        result = await service.create(self.get_create_builder())
        
        assert result.id == 1
        mock_repo.create.assert_called_once()
```

### Async Test Utilities

Utilities for async testing:

```python
import asyncio

async def wait_for_condition(condition, timeout=5.0, interval=0.1):
    """Wait for condition to become true."""
    end_time = asyncio.get_event_loop().time() + timeout
    
    while asyncio.get_event_loop().time() < end_time:
        if await condition():
            return True
        await asyncio.sleep(interval)
    
    raise TimeoutError(f"Condition not met within {timeout}s")

# Usage
async def test_deployment_completes():
    machine = await start_deployment(machine_id)
    
    async def is_deployed():
        m = await service.get_by_id(machine_id)
        return m.status == "deployed"
    
    await wait_for_condition(is_deployed, timeout=10.0)
```

### Mock Helpers

Common mocking patterns:

```python
from unittest.mock import AsyncMock, Mock

def make_mock_service(spec_class, **method_returns):
    """Create mock service with specified return values."""
    mock = Mock(spec=spec_class)
    
    for method_name, return_value in method_returns.items():
        setattr(mock, method_name, AsyncMock(return_value=return_value))
    
    return mock

# Usage
def test_with_mock_service():
    mock_service = make_mock_service(
        MachineService,
        get_by_id=Machine(id=1, hostname="test"),
        list=[]
    )
    
    result = await mock_service.get_by_id(1)
    assert result.hostname == "test"
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing guidelines.

### Test Coverage

All testing utilities must be tested:
- Factories produce valid test data
- Fixtures set up and tear down correctly
- Base classes execute all test methods
- Mock helpers create valid mocks

### Self-Testing

Testing utilities must not introduce bugs:

```python
def test_machine_factory():
    """Test that factory creates valid machines."""
    machine = factory.make_Machine()
    assert machine.hostname is not None
    assert machine.status in NODE_STATUS
    assert machine.id is not None

def test_db_fixture_isolation(db_connection):
    """Test that fixtures provide isolation."""
    repo = MachineRepository(db_connection)
    await repo.create({"hostname": "test1"})
    # Transaction rolled back after test
```

### Running Tests

```bash
# Test maastesting utilities
pytest src/maastesting/tests/

# With coverage
pytest --cov=maastesting src/maastesting/tests/
```

## Development Guidelines

### Adding New Factories

1. Inherit from or use existing factory patterns
2. Provide sensible defaults
3. Allow overrides via kwargs
4. Generate unique names/IDs
5. Document required vs optional parameters

```python
@staticmethod
def make_Machine(hostname=None, **kwargs):
    """Create test machine.
    
    Args:
        hostname: Machine hostname (auto-generated if None)
        **kwargs: Additional Machine fields
    """
    if hostname is None:
        hostname = factory.make_name('machine')
    return Machine.objects.create(hostname=hostname, **kwargs)
```

### Adding New Fixtures

1. Choose appropriate scope (function, module, session)
2. Ensure proper setup and teardown
3. Document fixture purpose and usage
4. Provide clean state for each test

### Adding Base Classes

1. Use ABC for abstract base classes
2. Define abstract methods for customization
3. Implement common test patterns
4. Document expected subclass behavior

## Integration Points

### Used By All Test Suites

All MAAS components import from maastesting:
- `maasserver.tests` - Django test suite
- `maasapiserver.tests` - FastAPI test suite
- `maasservicelayer.tests` - Service/repository tests
- `maastemporalworker.tests` - Workflow tests

### Pytest Plugins

Custom pytest plugins in `maastesting.pytest_plugin`:
- Database fixtures
- Async test support
- Factory fixtures
- Mock utilities

### Django TestCase Support

Integration with Django's test framework:
- Database setup/teardown
- Transaction management
- Fixture loading
- Test client support

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Using Factories in Production Code

❌ **Don't** use test factories in production code:
```python
# WRONG - Test factory in production
from maastesting.factory import factory

def create_machine():
    return factory.make_Machine()  # Test code only!
```

✅ **Do** use proper service layer:
```python
# Correct - Use service layer
async def create_machine():
    return await machine_service.create(builder)
```

### Sharing State Between Tests

❌ **Don't** share mutable state between tests:
```python
# WRONG - Shared state
shared_machine = None

def test_create():
    global shared_machine
    shared_machine = factory.make_Machine()

def test_update():
    shared_machine.hostname = "updated"  # Brittle!
```

✅ **Do** create fresh state per test:
```python
# Correct - Fresh state
def test_create():
    machine = factory.make_Machine()
    assert machine.id is not None

def test_update():
    machine = factory.make_Machine()
    machine.hostname = "updated"
```

### Not Cleaning Up Resources

❌ **Don't** leave resources without cleanup:
```python
# WRONG - No cleanup
def test_with_file():
    f = open("test.txt", "w")
    f.write("data")
    # Missing f.close()
```

✅ **Do** use fixtures or context managers:
```python
# Correct - Automatic cleanup
@pytest.fixture
def test_file():
    f = open("test.txt", "w")
    yield f
    f.close()

def test_with_file(test_file):
    test_file.write("data")
```

### Mocking Too Much

❌ **Don't** over-mock in integration tests:
```python
# WRONG - Mocking everything in integration test
def test_create_machine(mocker):
    mocker.patch('maasservicelayer.db.connection')
    mocker.patch('maasservicelayer.repositories')
    # Testing nothing real!
```

✅ **Do** use real components in integration tests:
```python
# Correct - Real database in integration test
async def test_create_machine(db_connection):
    repo = MachineRepository(db_connection)  # Real repo
    machine = await repo.create({"hostname": "test"})
    assert machine.id is not None
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Test Data Security

- Never use real credentials in test data
- Sanitize any production data used in tests
- Don't commit sensitive test data to repository

### Test Isolation

- Ensure tests don't leak sensitive data
- Clean up test databases completely
- Isolate test environments from production

## Performance Considerations

### Test Speed

- Use appropriate fixture scopes to minimize setup time
- Mock slow external services
- Use in-memory databases for unit tests
- Parallelize independent tests

### Database Performance

- Use transactions for test isolation (faster than full cleanup)
- Minimize database migrations in tests
- Consider using fixtures for bulk data

### Async Test Performance

- Use `pytest-xdist` for parallel execution
- Avoid unnecessary `asyncio.sleep()` calls
- Use time mocking for time-dependent tests

## Additional Resources

- **pytest Documentation**: https://docs.pytest.org/
- **factory-boy**: https://factoryboy.readthedocs.io/
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/
- **Related**: [test-code-quality.md](../../skills/techniques/test-code-quality.md), [python-testing.md](../../skills/languages/python-testing.md)