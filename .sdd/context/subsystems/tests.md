# tests Subsystem

## Purpose

Root-level test suite and test configuration for the entire MAAS project. This subsystem contains integration tests, end-to-end tests, and test infrastructure that spans multiple components, ensuring the system works correctly as a whole.

**Status**: Active - comprehensive test coverage for all MAAS components.

## Location

`src/tests`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **pytest**: Primary test framework
- **pytest-django**: Django integration for pytest
- **pytest-asyncio**: Async test support

### Key Libraries
- **pytest**: Test framework and runner
- **pytest-xdist**: Parallel test execution
- **pytest-cov**: Coverage reporting
- **selenium**: Browser automation for UI tests
- **locust**: Performance and load testing

## Architectural Constraints

### Cross-Component Testing

Tests in this subsystem span multiple components:
- Integration tests across service boundaries
- End-to-end tests simulating real workflows
- System-level performance tests
- Browser-based UI tests

### Realistic Test Environment

Tests run in environments that closely mirror production:
- Full database setup
- Multiple services running
- Real network communication
- Actual file system operations

### CI/CD Integration

Test suite designed for continuous integration:
- Fast execution for quick feedback
- Parallel execution support
- Clear failure reporting
- Incremental test execution

## Key Patterns

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Integration Test Pattern

Test multiple components working together:

```python
import pytest
from maasserver.models import Machine, Node
from maasservicelayer.services.machines import MachineService

@pytest.mark.django_db
@pytest.mark.asyncio
async def test_machine_deployment_flow(db_connection):
    """Test complete machine deployment flow."""
    # Create machine via Django ORM
    machine = Machine.objects.create(
        hostname="test-machine",
        status=NODE_STATUS.READY
    )
    
    # Deploy via service layer
    service = MachineService(db_connection)
    deployed = await service.deploy(
        machine.system_id,
        os="ubuntu",
        distro_series="jammy"
    )
    
    # Verify deployment
    assert deployed.status == NODE_STATUS.DEPLOYING
    
    # Verify Django ORM sees the change
    machine.refresh_from_db()
    assert machine.status == NODE_STATUS.DEPLOYING
```

### End-to-End Test Pattern

Test complete user workflows:

```python
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By

@pytest.mark.e2e
class TestMachineDeploymentE2E:
    """End-to-end tests for machine deployment."""
    
    @pytest.fixture
    def browser(self):
        """Provide browser instance."""
        driver = webdriver.Chrome()
        driver.implicitly_wait(10)
        yield driver
        driver.quit()
    
    def test_deploy_machine_via_ui(self, browser, live_maas_server):
        """Test deploying machine through web UI."""
        # Login
        browser.get(f"{live_maas_server}/login")
        browser.find_element(By.ID, "username").send_keys("admin")
        browser.find_element(By.ID, "password").send_keys("password")
        browser.find_element(By.ID, "login-button").click()
        
        # Navigate to machines
        browser.get(f"{live_maas_server}/machines")
        
        # Select machine
        machine = browser.find_element(By.CSS_SELECTOR, ".machine-row:first-child")
        machine.click()
        
        # Deploy
        deploy_button = browser.find_element(By.ID, "deploy-button")
        deploy_button.click()
        
        # Verify status change
        status = browser.find_element(By.CLASS_NAME, "machine-status")
        assert "Deploying" in status.text
```

### Performance Test Pattern

Test system performance under load:

```python
from locust import HttpUser, task, between

class MAASUser(HttpUser):
    """Simulated MAAS user for load testing."""
    
    wait_time = between(1, 3)
    
    def on_start(self):
        """Login when user starts."""
        self.client.post("/api/2.0/users/login", json={
            "username": "admin",
            "password": "test"
        })
    
    @task(3)
    def list_machines(self):
        """List machines endpoint."""
        self.client.get("/api/2.0/machines/")
    
    @task(1)
    def get_machine(self):
        """Get single machine."""
        self.client.get("/api/2.0/machines/abc123/")
    
    @task(1)
    def commission_machine(self):
        """Commission machine."""
        self.client.post("/api/2.0/machines/abc123/?op=commission")
```

### Database Migration Test Pattern

Test database migrations work correctly:

```python
import pytest
from django.core.management import call_command
from django.db import connection

@pytest.mark.django_db
class TestMigrations:
    """Test database migrations."""
    
    def test_migrations_complete(self):
        """Test all migrations run successfully."""
        call_command('migrate', verbosity=0)
        
        # Verify expected tables exist
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public'"
            )
            tables = [row[0] for row in cursor.fetchall()]
        
        assert 'maasserver_node' in tables
        assert 'maasserver_interface' in tables
    
    def test_migration_reversible(self):
        """Test migrations can be reversed."""
        # Apply latest migration
        call_command('migrate', 'maasserver', verbosity=0)
        
        # Reverse one migration
        call_command('migrate', 'maasserver', '0001', verbosity=0)
        
        # Reapply
        call_command('migrate', 'maasserver', verbosity=0)
```

### Test Fixture Pattern

Shared fixtures for integration tests:

```python
import pytest
from django.contrib.auth.models import User
from maasserver.models import Node

@pytest.fixture
def admin_user(db):
    """Create admin user."""
    return User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='password'
    )

@pytest.fixture
def ready_machine(db):
    """Create machine ready for deployment."""
    return Node.objects.create(
        hostname='test-machine',
        status=NODE_STATUS.READY,
        power_type='manual',
        architecture='amd64/generic'
    )

@pytest.fixture
async def api_client(admin_user):
    """Create authenticated API client."""
    from httpx import AsyncClient
    from maasapiserver.main import app
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login
        response = await client.post("/auth/login", json={
            "username": "admin",
            "password": "password"
        })
        token = response.json()["token"]
        
        # Set auth header
        client.headers["Authorization"] = f"Bearer {token}"
        
        yield client
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing guidelines.

### Test Categories

Tests organized by scope:
- **Unit Tests**: Individual components in isolation
- **Integration Tests**: Multiple components together
- **E2E Tests**: Complete user workflows
- **Performance Tests**: Load and stress testing
- **Smoke Tests**: Quick validation of critical paths

### Coverage Requirements

Minimum coverage targets:
- **Critical paths**: 100% coverage
- **Business logic**: 95% coverage
- **API endpoints**: 90% coverage
- **Overall codebase**: 80% coverage

### Running Tests

```bash
# All tests
pytest src/tests/

# Integration tests only
pytest src/tests/integration/

# E2E tests (requires live server)
pytest src/tests/e2e/ --live-server

# Performance tests
locust -f src/tests/performance/test_api.py

# Parallel execution
pytest -n auto src/tests/

# With coverage
pytest --cov=src --cov-report=html src/tests/
```

## Development Guidelines

### Adding Integration Tests

1. Identify components being tested
2. Set up required fixtures and services
3. Write test simulating real usage
4. Verify state across all components
5. Clean up resources after test

### Writing E2E Tests

1. Start with user story or workflow
2. Use Page Object pattern for UI tests
3. Make tests resilient to UI changes
4. Include explicit waits, not fixed delays
5. Test happy path and common error cases

### Performance Test Guidelines

1. Define realistic load scenarios
2. Test with production-like data volumes
3. Monitor response times and error rates
4. Identify bottlenecks and optimize
5. Set performance regression alerts

## Integration Points

### All MAAS Components
- Tests import from all subsystems
- Verifies component interactions
- Ensures API contracts are met
- Validates data consistency across layers

### CI/CD Pipeline
- Automated test execution on commits
- Parallel test execution for speed
- Test results reported to GitHub
- Coverage reports published

### Test Infrastructure
- Uses [maastesting](./maastesting.md) for utilities
- Shares fixtures across test suites
- Common test data factories
- Standardized test patterns

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Flaky Tests

❌ **Don't** write tests that pass/fail randomly:
```python
# WRONG - Time-dependent test
def test_deployment():
    deploy_machine()
    time.sleep(5)  # Might not be enough!
    assert machine.status == "deployed"
```

✅ **Do** use proper waiting mechanisms:
```python
# Correct - Wait for condition
def test_deployment():
    deploy_machine()
    wait_for_condition(
        lambda: machine.status == "deployed",
        timeout=30
    )
    assert machine.status == "deployed"
```

### Tests Depending on Order

❌ **Don't** write tests that depend on execution order:
```python
# WRONG - Depends on previous test
def test_create_machine():
    global machine_id
    machine_id = create_machine()

def test_deploy_machine():
    deploy_machine(machine_id)  # Breaks if run alone!
```

✅ **Do** make tests independent:
```python
# Correct - Self-contained
def test_deploy_machine():
    machine_id = create_machine()  # Create own test data
    deploy_machine(machine_id)
    assert_deployed(machine_id)
```

### Not Cleaning Up Resources

❌ **Don't** leave test data behind:
```python
# WRONG - No cleanup
def test_machine():
    machine = create_machine()
    # Test logic...
    # Machine left in database!
```

✅ **Do** use fixtures or explicit cleanup:
```python
# Correct - Automatic cleanup
@pytest.fixture
def machine():
    m = create_machine()
    yield m
    m.delete()

def test_machine(machine):
    # Test logic...
    # Machine cleaned up automatically
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Test Credentials
- Use separate credentials for testing
- Never use production credentials
- Rotate test credentials regularly
- Don't commit credentials to repository

### Test Data
- Sanitize any production data used in tests
- Don't test with real user data
- Use generated or anonymized data
- Clean up test data after execution

### Test Isolation
- Ensure tests don't affect production
- Use separate test databases
- Isolate test environments from production
- Prevent test code from running in production

## Performance Considerations

### Test Speed
- Run fast unit tests first
- Parallelize independent tests
- Use pytest-xdist for parallel execution
- Cache expensive setup operations

### Resource Usage
- Clean up resources promptly
- Use connection pooling
- Limit concurrent test execution
- Monitor memory usage in long test runs

### CI/CD Optimization
- Split test suite into fast/slow
- Run smoke tests on every commit
- Run full suite on merge to main
- Cache dependencies between runs

## Additional Resources

- **pytest Documentation**: https://docs.pytest.org/
- **pytest-django**: https://pytest-django.readthedocs.io/
- **Selenium**: https://www.selenium.dev/documentation/
- **Locust**: https://docs.locust.io/
- **Related**: [test-code-quality.md](../../skills/techniques/test-code-quality.md), [maastesting.md](./maastesting.md)