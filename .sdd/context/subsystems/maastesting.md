# maastesting Subsystem

## Purpose

Testing utilities, fixtures, and helpers shared across MAAS test suites. This subsystem provides reusable test infrastructure including database setup, factory patterns, common test base classes, pytest plugins, and mocking utilities to ensure consistent and efficient testing across all MAAS components.

**Status**: Active - critical test infrastructure for all subsystems.

## Location

`src/maastesting`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **pytest**: Primary test framework
- **testtools**: Legacy test framework support
- **pytest-asyncio**: Async test support

### Key Libraries
- **pytest**: Modern test framework and runner
- **pytest-asyncio**: Async/await test support
- **factory-boy**: Test data factory pattern
- **faker**: Realistic test data generation
- **fixtures**: Test fixture management
- **mock**: Mocking and patching utilities

## Architectural Constraints

### Shared Across Components

This subsystem serves all other subsystems:
- Used by `maasserver` (Django tests)
- Used by `maasapiserver` (FastAPI tests)
- Used by `maasservicelayer` (service/repository tests)
- Used by `provisioningserver` (Twisted tests)
- Used by other components

### Minimal Dependencies

Keep dependencies minimal to avoid circular dependencies:
- No business logic dependencies
- No direct subsystem imports
- Focus on testing infrastructure only
- Support multiple test frameworks

### Backward Compatibility

Support both legacy and modern testing approaches:
- testtools for legacy Django tests
- pytest for modern async tests
- Gradual migration path
- Both frameworks coexist

## Key Patterns

### Factory Pattern

Provide factories for creating test data:

```python
from maastesting.factory import factory

class MachineFactory:
    """Factory for creating test machines."""
    
    @staticmethod
    def make_Machine(hostname=None, status=None, **kwargs):
        """Create a test machine with sensible defaults."""
        from maasserver.models import Machine
        
        if hostname is None:
            hostname = factory.make_name('machine')
        
        if status is None:
            status = NODE_STATUS.READY
        
        return Machine.objects.create(
            hostname=hostname,
            status=status,
            **kwargs
        )
    
    @staticmethod
    def make_Machine_with_interfaces(interface_count=1):
        """Create machine with network interfaces."""
        machine = MachineFactory.make_Machine()
        
        for i in range(interface_count):
            InterfaceFactory.make_Interface(
                node=machine,
                name=f"eth{i}"
            )
        
        return machine

# Usage in tests
def test_machine_creation():
    machine = factory.make_Machine(hostname="test-machine")
    assert machine.hostname == "test-machine"
```

### Database Fixtures

Provide database setup for tests:

```python
import pytest
from maastesting.database import setup_test_database, teardown_test_database

@pytest.fixture(scope="session")
def db_session():
    """Set up test database for entire session."""
    db = setup_test_database()
    yield db
    teardown_test_database(db)

@pytest.fixture
async def db_connection(db_session):
    """Provide database connection for test."""
    async with db_session.get_connection() as conn:
        # Start transaction
        trans = await conn.begin()
        
        yield conn
        
        # Rollback transaction to clean up
        await trans.rollback()

# Usage in tests
@pytest.mark.asyncio
async def test_with_database(db_connection):
    """Test that uses database."""
    from maasservicelayer.db.repositories import MachineRepository
    
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
        """Return the repository class to test."""
        pass
    
    @abstractmethod
    def get_create_resource(self):
        """Return resource data for create test."""
        pass
    
    @pytest.mark.asyncio
    async def test_create(self, db_connection):
        """Test creating a resource."""
        repo_class = self.get_repository_class()
        repo = repo_class(db_connection)
        
        resource = self.get_create_resource()
        created = await repo.create(resource)
        
        assert created.id is not None
    
    @pytest.mark.asyncio
    async def test_get_by_id(self, db_connection):
        """Test retrieving by ID."""
        repo_class = self.get_repository_class()
        repo = repo_class(db_connection)
        
        resource = self.get_create_resource()
        created = await repo.create(resource)
        
        retrieved = await repo.get_by_id(created.id)
        assert retrieved.id == created.id
    
    @pytest.mark.asyncio
    async def test_list(self, db_connection):
        """Test listing resources."""
        repo_class = self.get_repository_class()
        repo = repo_class(db_connection)
        
        # Create multiple resources
        for i in range(3):
            await repo.create(self.get_create_resource())
        
        results = await repo.list()
        assert len(results) >= 3

# Usage
class TestMachineRepository(RepositoryCommonTests):
    """Test machine repository."""
    
    def get_repository_class(self):
        return MachineRepository
    
    def get_create_resource(self):
        return {"hostname": "test-machine", "architecture": "amd64"}
```

### Service Test Base Classes

Common tests for services:

```python
class ServiceCommonTests(ABC):
    """Common tests for all services."""
    
    @abstractmethod
    def get_service_class(self):
        """Return the service class to test."""
        pass
    
    @abstractmethod
    def get_create_builder(self):
        """Return builder for create test."""
        pass
    
    @abstractmethod
    def get_mock_repository(self, mocker):
        """Return mocked repository."""
        pass
    
    @pytest.mark.asyncio
    async def test_create(self, mocker):
        """Test create operation."""
        service_class = self.get_service_class()
        mock_repo = self.get_mock_repository(mocker)
        
        # Mock repository create
        mock_repo.create = AsyncMock(return_value=Machine(id=1))
        
        service = service_class(mock_repo)
        builder = self.get_create_builder()
        
        result = await service.create(builder)
        
        assert result.id == 1
        mock_repo.create.assert_called_once()
```

### API Test Fixtures

Fixtures for API testing:

```python
import pytest
from httpx import AsyncClient
from maasapiserver.v3.app import create_app

@pytest.fixture
async def api_client():
    """Provide API test client."""
    app = create_app()
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def mocked_api_client_user(mocker):
    """API client with mocked services and authenticated user."""
    app = create_app()
    
    # Mock authentication
    mock_user = User(id=1, username="testuser")
    mock_get_user = mocker.patch(
        'maasapiserver.v3.auth.get_authenticated_user',
        return_value=mock_user
    )
    
    # Mock services
    mock_service = mocker.Mock()
    app.dependency_overrides[get_service] = lambda: mock_service
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client, mock_service

# Usage
@pytest.mark.asyncio
async def test_api_endpoint(mocked_api_client_user):
    """Test API endpoint."""
    client, service = mocked_api_client_user
    
    service.get_by_id.return_value = Machine(id=1, hostname="test")
    
    response = await client.get("/api/v3/machines/1")
    
    assert response.status_code == 200
    assert response.json()["hostname"] == "test"
```

### Pytest Plugins

Custom pytest plugins for MAAS:

```python
# conftest.py
import pytest

def pytest_configure(config):
    """Configure pytest for MAAS tests."""
    config.addinivalue_line(
        "markers", 
        "db: mark test as requiring database"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running"
    )

@pytest.fixture(autouse=True)
def reset_database(request):
    """Reset database after each test."""
    if "db" in request.keywords:
        yield
        # Clean up database
        cleanup_test_database()
    else:
        yield

@pytest.fixture
def isolated_filesystem(tmp_path):
    """Provide isolated filesystem for tests."""
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    
    yield tmp_path
    
    os.chdir(old_cwd)
```

### Mock Helpers

Utilities for mocking:

```python
from unittest.mock import Mock, AsyncMock, patch

class MockHelper:
    """Helper for creating common mocks."""
    
    @staticmethod
    def mock_service(spec_class, **methods):
        """Create mocked service with async methods."""
        mock = Mock(spec=spec_class)
        
        for method_name, return_value in methods.items():
            setattr(mock, method_name, AsyncMock(return_value=return_value))
        
        return mock
    
    @staticmethod
    def mock_repository(spec_class):
        """Create mocked repository."""
        mock = Mock(spec=spec_class)
        
        # Common async methods
        mock.get_by_id = AsyncMock()
        mock.create = AsyncMock()
        mock.update = AsyncMock()
        mock.delete = AsyncMock()
        mock.list = AsyncMock()
        
        return mock

# Usage
def test_with_mocked_service(mocker):
    """Test using mock helper."""
    mock_service = MockHelper.mock_service(
        MachineService,
        get_by_id=Machine(id=1),
        create=Machine(id=2)
    )
    
    result = await mock_service.get_by_id(1)
    assert result.id == 1
```

### Test Data Builders

Builders for complex test data:

```python
class MachineTestBuilder:
    """Builder for creating test machines."""
    
    def __init__(self):
        self._hostname = "test-machine"
        self._status = "ready"
        self._architecture = "amd64"
        self._interfaces = []
        self._storage = []
    
    def with_hostname(self, hostname):
        self._hostname = hostname
        return self
    
    def with_status(self, status):
        self._status = status
        return self
    
    def with_interfaces(self, count=1):
        for i in range(count):
            self._interfaces.append({
                "name": f"eth{i}",
                "mac": f"00:11:22:33:44:{i:02x}"
            })
        return self
    
    def with_storage(self, size_gb=100):
        self._storage.append({
            "name": f"sda",
            "size": size_gb * 1024 * 1024 * 1024
        })
        return self
    
    def build(self):
        """Build the test machine."""
        machine = factory.make_Machine(
            hostname=self._hostname,
            status=self._status,
            architecture=self._architecture
        )
        
        for iface in self._interfaces:
            factory.make_Interface(node=machine, **iface)
        
        for disk in self._storage:
            factory.make_PhysicalBlockDevice(node=machine, **disk)
        
        return machine

# Usage
def test_complex_machine():
    """Test with complex machine setup."""
    machine = (
        MachineTestBuilder()
        .with_hostname("complex-machine")
        .with_interfaces(count=2)
        .with_storage(size_gb=500)
        .build()
    )
    
    assert len(machine.interface_set.all()) == 2
```

## Testing Requirements

### Self-Testing

Test the testing utilities themselves:

```python
def test_factory_creates_unique_names():
    """Test factory name generation."""
    name1 = factory.make_name('test')
    name2 = factory.make_name('test')
    
    assert name1 != name2
    assert name1.startswith('test-')

def test_database_fixture_provides_connection(db_connection):
    """Test database fixture."""
    assert db_connection is not None
    
@pytest.mark.asyncio
async def test_mock_helper_creates_async_mocks():
    """Test mock helper."""
    mock = MockHelper.mock_service(MachineService)
    
    mock.get_by_id.return_value = Machine(id=1)
    result = await mock.get_by_id(1)
    
    assert result.id == 1
```

### Documentation Tests

Ensure utilities are well-documented:

```python
def test_factory_methods_have_docstrings():
    """Test that factory methods are documented."""
    from maastesting.factory import factory
    
    for method_name in dir(factory):
        if method_name.startswith('make_'):
            method = getattr(factory, method_name)
            assert method.__doc__ is not None
```

## Development Guidelines

### Adding New Fixtures

When adding new test fixtures:

1. **Document Purpose**: Clear docstring explaining use
2. **Scope Appropriately**: Function, module, or session scope
3. **Clean Up Resources**: Ensure proper teardown
4. **Test the Fixture**: Verify fixture works correctly
5. **Update Documentation**: Add to fixture catalog

```python
@pytest.fixture(scope="function")
def temporary_directory(tmp_path):
    """
    Provide a temporary directory that is cleaned up after test.
    
    Yields:
        Path: Temporary directory path
        
    Example:
        def test_file_operations(temporary_directory):
            file_path = temporary_directory / "test.txt"
            file_path.write_text("test content")
    """
    yield tmp_path
    # Cleanup handled by pytest's tmp_path
```

### Adding New Factories

When adding factory methods:

1. **Follow Naming Convention**: `make_<ResourceType>`
2. **Sensible Defaults**: Provide working defaults
3. **Customization**: Allow parameter overrides
4. **Related Resources**: Create related entities as needed
5. **Return Created Object**: Always return the created instance

```python
def make_Subnet(cidr=None, vlan=None, **kwargs):
    """
    Create a test subnet.
    
    Args:
        cidr: CIDR notation (auto-generated if None)
        vlan: VLAN object (created if None)
        **kwargs: Additional Subnet fields
        
    Returns:
        Subnet: Created subnet instance
    """
    if cidr is None:
        cidr = generate_test_cidr()
    
    if vlan is None:
        vlan = make_VLAN()
    
    return Subnet.objects.create(
        cidr=cidr,
        vlan=vlan,
        **kwargs
    )
```

### Adding Common Test Classes

When adding test base classes:

1. **Abstract Methods**: Clearly define what subclasses must implement
2. **Test Coverage**: Cover common functionality
3. **Flexible**: Allow customization via overrides
4. **Well-Documented**: Explain usage and requirements

### Performance Considerations

Keep tests fast:
- Use database transactions for rollback
- Mock external services
- Cache expensive fixtures at session scope
- Provide fast alternatives for slow operations

## Integration Points

### pytest

Primary test framework integration:
- Custom plugins in `conftest.py`
- Fixture registration
- Marker registration
- Configuration options

### testtools

Legacy test framework support:
- Base test cases for Django
- Scenario-based testing
- Deferred test runners

### Database Systems

Database test setup:
- PostgreSQL test database
- Transaction management
- Fixture data loading
- Schema setup

### All MAAS Subsystems

Used across all subsystems:
- `maasserver`: Django test fixtures
- `maasapiserver`: API test clients
- `maasservicelayer`: Repository/service test bases
- `provisioningserver`: Twisted test utilities
- `maasagent`: Go test helpers (future)

## Common Pitfalls

### Shared Mutable State

❌ **Don't**: Share mutable objects between tests
```python
# Module-level mutable state - WRONG!
shared_machine = factory.make_Machine()

def test_1():
    shared_machine.hostname = "test1"  # Mutates shared state!

def test_2():
    # Fails if test_1 runs first
    assert shared_machine.hostname == "machine"
```

✅ **Do**: Create fresh instances per test
```python
@pytest.fixture
def machine():
    return factory.make_Machine()

def test_1(machine):
    machine.hostname = "test1"  # Isolated

def test_2(machine):
    # Fresh machine instance
    assert machine.hostname.startswith("machine-")
```

### Fixture Scope Issues

❌ **Don't**: Use function-scoped fixtures in module/session scope
```python
@pytest.fixture(scope="session")
def session_fixture(function_scoped_fixture):  # WRONG!
    return something
```

✅ **Do**: Match or increase scope
```python
@pytest.fixture(scope="session")
def session_fixture(session_scoped_fixture):  # Correct
    return something
```

### Missing Cleanup

❌ **Don't**: Leak resources
```python
@pytest.fixture
def temp_file():
    f = open("/tmp/test", "w")
    yield f
    # Missing f.close()!
```

✅ **Do**: Always clean up
```python
@pytest.fixture
def temp_file():
    f = open("/tmp/test", "w")
    yield f
    f.close()
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **pytest**: Modern Python testing
- **testtools**: Legacy test framework
- **Factory Pattern**: Test data generation
- **Mocking**: Test doubles and stubs
- **Database Testing**: Database test strategies
- **Async Testing**: Testing async code

## Best Practices

### Test Isolation

Each test should be independent:
- No dependencies between tests
- Clean state before each test
- Rollback database changes
- Mock external dependencies

### Meaningful Names

Use descriptive names:
- Test names describe what is tested
- Fixture names describe what they provide
- Factory names describe what they create

### Fast Tests

Optimize for speed:
- Mock slow operations
- Use in-memory databases where possible
- Parallel test execution
- Session-scoped expensive fixtures

### Maintainability

Keep tests maintainable:
- DRY principle with fixtures and helpers
- Clear test structure (Arrange-Act-Assert)
- Update tests with code changes
- Refactor tests as needed

## Documentation

### Fixture Catalog

Maintain catalog of available fixtures:
- Purpose of each fixture
- Parameters and configuration
- Usage examples
- Scope and cleanup behavior

### Factory Documentation

Document factory methods:
- What resource is created
- Available parameters
- Default values
- Related factories

### Common Test Patterns

Document testing patterns:
- Repository testing approach
- Service testing with mocks
- API endpoint testing
- Async test patterns

## Additional Resources

- pytest Documentation: https://docs.pytest.org/
- testtools Documentation: https://testtools.readthedocs.io/
- Factory Boy: https://factoryboy.readthedocs.io/
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/
- `AGENTS.md`: General coding guidelines
- Test examples across MAAS codebase