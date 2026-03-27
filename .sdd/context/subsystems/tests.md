# tests Subsystem

## Purpose

Integration and cross-component tests that validate interactions between multiple MAAS subsystems. This subsystem contains tests that span architectural boundaries, verify end-to-end workflows, and ensure proper integration of the various components that make up MAAS.

**Status**: Active - critical for system-level quality assurance.

## Location

`src/tests`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **pytest**: Primary test framework
- **pytest-asyncio**: Async test support

### Key Libraries
- **pytest**: Test framework and fixtures
- **pytest-mock**: Mocking support
- **pytest-cov**: Coverage reporting
- **httpx**: HTTP client for API testing
- **testtools**: Additional testing utilities

## Architectural Constraints

### Cross-Component Testing

Tests in this subsystem validate interactions across multiple components:

```
┌─────────────────────────────────────┐
│        Integration Tests            │
│   (src/tests)                       │
│                                     │
│  ┌─────────────────────────────┐   │
│  │  API ↔ Service ↔ Repository │   │
│  │  Region ↔ Rack ↔ Agent      │   │
│  │  Workflows ↔ Services        │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

### System-Level Validation

Focus on realistic scenarios:
- Complete user workflows
- Multi-component interactions
- Database state consistency
- External service integration
- Performance characteristics

### Test Environment Requirements

Integration tests may require:
- Running database
- Multiple service instances
- Network connectivity
- External dependencies
- Longer execution times

## Key Patterns

### End-to-End API Testing

Test complete API workflows:

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
@pytest.mark.integration
async def test_machine_deployment_workflow(
    running_api_server,
    db_connection,
    temporal_client
):
    """Test complete machine deployment from API to completion."""
    
    # Create machine via API
    async with AsyncClient(base_url=running_api_server) as client:
        # Step 1: Create machine
        response = await client.post(
            "/api/v3/machines/",
            json={
                "hostname": "test-machine",
                "architecture": "amd64",
                "memory": 8192,
                "cpuCount": 4
            },
            headers={"Authorization": f"Bearer {get_test_token()}"}
        )
        assert response.status_code == 201
        machine = response.json()
        machine_id = machine["id"]
        
        # Step 2: Commission machine
        response = await client.post(
            f"/api/v3/machines/{machine_id}/commission",
            headers={"Authorization": f"Bearer {get_test_token()}"}
        )
        assert response.status_code == 200
        
        # Step 3: Wait for commissioning to complete
        await wait_for_machine_status(client, machine_id, "ready", timeout=300)
        
        # Step 4: Deploy machine
        response = await client.post(
            f"/api/v3/machines/{machine_id}/deploy",
            json={
                "osystem": "ubuntu",
                "distro_series": "jammy"
            },
            headers={"Authorization": f"Bearer {get_test_token()}"}
        )
        assert response.status_code == 200
        
        # Step 5: Verify workflow started
        workflow_id = response.json()["workflow_id"]
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)
        
        # Step 6: Wait for deployment
        result = await workflow_handle.result(timeout=timedelta(hours=1))
        assert result.success is True
        
        # Step 7: Verify final state
        response = await client.get(
            f"/api/v3/machines/{machine_id}",
            headers={"Authorization": f"Bearer {get_test_token()}"}
        )
        machine = response.json()
        assert machine["status"] == "deployed"
```

### Multi-Service Integration

Test interactions between multiple services:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_layer_integration(db_connection):
    """Test service layer interactions."""
    
    # Setup services with real database
    machine_service = MachineService(
        MachineRepository(db_connection)
    )
    network_service = NetworkService(
        NetworkRepository(db_connection)
    )
    deployment_service = DeploymentService(
        machine_repo=MachineRepository(db_connection),
        network_repo=NetworkRepository(db_connection)
    )
    
    # Create machine
    machine = await machine_service.create(
        MachineCreateBuilder()
            .with_hostname("test-machine")
            .with_architecture("amd64")
    )
    
    # Configure network
    network = await network_service.create_for_machine(
        machine.id,
        NetworkConfigBuilder()
            .with_interface("eth0")
            .with_subnet("192.168.1.0/24")
    )
    
    # Deploy machine with network
    deployment = await deployment_service.deploy(
        machine.id,
        DeploymentConfig(
            networks=[network.id]
        )
    )
    
    # Verify all services updated correctly
    updated_machine = await machine_service.get_by_id(machine.id)
    assert updated_machine.status == "deploying"
    
    networks = await network_service.list_for_machine(machine.id)
    assert len(networks) == 1
    assert networks[0].configured is True
```

### Database Integration Tests

Test database consistency across operations:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_database_transaction_integrity(db_connection):
    """Test transaction integrity across multiple operations."""
    
    service = MachineService(MachineRepository(db_connection))
    
    # Start transaction
    async with db_connection.begin():
        # Create multiple machines
        machines = []
        for i in range(10):
            machine = await service.create(
                MachineCreateBuilder()
                    .with_hostname(f"machine-{i}")
            )
            machines.append(machine)
        
        # Update all machines
        for machine in machines:
            await service.update(
                machine.id,
                MachineUpdateBuilder().with_status("ready")
            )
        
        # Verify all updates within transaction
        for machine in machines:
            updated = await service.get_by_id(machine.id)
            assert updated.status == "ready"
        
        # Rollback to test transaction
        raise Exception("Intentional rollback")
    
    # Verify rollback worked
    for machine in machines:
        result = await service.get_by_id(machine.id)
        assert result is None
```

### Temporal Workflow Integration

Test complete workflow execution:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_deployment_workflow_integration(
    temporal_client,
    db_connection
):
    """Test complete deployment workflow with real services."""
    
    # Setup real services
    machine_service = MachineService(MachineRepository(db_connection))
    
    # Create machine
    machine = await machine_service.create(
        MachineCreateBuilder()
            .with_hostname("workflow-test")
            .with_status("ready")
    )
    
    # Start workflow
    handle = await temporal_client.start_workflow(
        DeployMachineWorkflow.run,
        args=[machine.id, DeploymentConfig(...)],
        id=f"deploy-integration-{machine.id}",
        task_queue="maas-workflows"
    )
    
    # Monitor workflow progress
    async for event in handle.fetch_history():
        if event.event_type == "ActivityTaskCompleted":
            # Verify database state after each activity
            machine = await machine_service.get_by_id(machine.id)
            assert machine is not None
    
    # Wait for completion
    result = await handle.result()
    assert result.success is True
    
    # Verify final state in database
    final_machine = await machine_service.get_by_id(machine.id)
    assert final_machine.status == "deployed"
```

### Performance Integration Tests

Test system performance under load:

```python
@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_concurrent_machine_creation(db_connection):
    """Test creating many machines concurrently."""
    
    service = MachineService(MachineRepository(db_connection))
    
    import time
    start_time = time.time()
    
    # Create 100 machines concurrently
    tasks = []
    for i in range(100):
        task = service.create(
            MachineCreateBuilder()
                .with_hostname(f"perf-test-{i}")
        )
        tasks.append(task)
    
    machines = await asyncio.gather(*tasks)
    
    elapsed = time.time() - start_time
    
    # Verify all created
    assert len(machines) == 100
    
    # Performance assertion
    assert elapsed < 10.0, f"Took {elapsed}s, expected < 10s"
    
    # Verify database consistency
    for machine in machines:
        retrieved = await service.get_by_id(machine.id)
        assert retrieved is not None
```

### External Service Mocking

Mock external dependencies for integration tests:

```python
@pytest.mark.asyncio
@pytest.mark.integration
async def test_with_mocked_external_services(
    db_connection,
    mock_power_driver,
    mock_image_service
):
    """Test integration with mocked external services."""
    
    # Real services
    machine_service = MachineService(MachineRepository(db_connection))
    deployment_service = DeploymentService(
        machine_repo=MachineRepository(db_connection),
        power_service=mock_power_driver,
        image_service=mock_image_service
    )
    
    # Create and deploy machine
    machine = await machine_service.create(
        MachineCreateBuilder().with_hostname("external-test")
    )
    
    await deployment_service.deploy(machine.id, DeploymentConfig(...))
    
    # Verify external service calls
    mock_power_driver.power_on.assert_called_once_with(machine.id)
    mock_image_service.download_image.assert_called_once()
```

## Testing Requirements

### Test Categories

Organize tests by category:

```python
# Mark tests appropriately
@pytest.mark.integration  # Cross-component integration
@pytest.mark.slow         # Long-running tests
@pytest.mark.database     # Requires database
@pytest.mark.temporal     # Requires Temporal
@pytest.mark.network      # Requires network access
@pytest.mark.external     # Requires external services
```

### Test Fixtures

Provide comprehensive fixtures:

```python
import pytest
from maasservicelayer.db.connection import DatabaseConnection

@pytest.fixture
async def db_connection():
    """Provide real database connection for integration tests."""
    connection = await DatabaseConnection.create()
    yield connection
    await connection.close()

@pytest.fixture
async def running_api_server():
    """Start real API server for testing."""
    from maasapiserver.app import create_app
    import uvicorn
    
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)
    
    # Start server in background
    import asyncio
    task = asyncio.create_task(server.serve())
    
    # Wait for server to start
    await asyncio.sleep(1)
    
    yield "http://127.0.0.1:8000"
    
    # Cleanup
    server.should_exit = True
    await task

@pytest.fixture
async def temporal_client():
    """Provide Temporal client for workflow tests."""
    from temporalio.client import Client
    
    client = await Client.connect("localhost:7233")
    yield client
    await client.close()
```

### Running Tests

```bash
# Run all integration tests
pytest src/tests/ -m integration

# Run excluding slow tests
pytest src/tests/ -m "integration and not slow"

# Run with specific markers
pytest src/tests/ -m "integration and database"

# Run with verbose output
pytest src/tests/ -v -m integration

# Run with coverage
pytest src/tests/ --cov=maasservicelayer --cov=maasapiserver -m integration

# Run in parallel
pytest src/tests/ -n auto -m integration
```

## Development Guidelines

### Writing Integration Tests

1. **Test Real Scenarios**: Focus on actual user workflows
2. **Use Real Dependencies**: Prefer real database over mocks
3. **Verify State**: Check database and service state
4. **Clean Up**: Ensure proper teardown
5. **Document Purpose**: Clear test descriptions
6. **Set Timeouts**: Prevent hanging tests
7. **Mark Appropriately**: Use pytest markers

### Test Isolation

Ensure tests don't interfere with each other:

```python
@pytest.fixture(autouse=True)
async def cleanup_database(db_connection):
    """Clean database before each test."""
    yield
    # Cleanup after test
    await db_connection.execute("TRUNCATE TABLE maasserver_node CASCADE")
```

### Test Data Management

Create and manage test data:

```python
@pytest.fixture
def test_data_factory():
    """Factory for creating test data."""
    
    class TestDataFactory:
        async def create_machine(self, **kwargs):
            defaults = {
                "hostname": "test-machine",
                "architecture": "amd64",
                "memory": 8192
            }
            defaults.update(kwargs)
            return await machine_service.create(
                MachineCreateBuilder(**defaults)
            )
        
        async def create_deployed_machine(self):
            machine = await self.create_machine()
            await deployment_service.deploy(machine.id, DeploymentConfig())
            return machine
    
    return TestDataFactory()
```

## Integration Points

### All Subsystems

Integration tests validate interactions between:

- **API ↔ Service Layer**: HTTP requests to business logic
- **Service ↔ Repository**: Business logic to data access
- **Region ↔ Rack**: Region and rack controller communication
- **Workflows ↔ Services**: Temporal workflows with services
- **Agent ↔ Region**: MAAS agent integration
- **Metadata ↔ Machines**: Metadata service during provisioning

## Common Pitfalls

### Test Pollution

❌ **Don't**: Leave data in shared database
```python
async def test_bad_cleanup():
    machine = await create_machine()
    # No cleanup - pollutes next test!
```

✅ **Do**: Clean up after tests
```python
async def test_good_cleanup(db_connection):
    machine = await create_machine()
    # Test operations...
    
    # Cleanup
    await machine_service.delete(machine.id)
```

### Flaky Tests

❌ **Don't**: Rely on timing
```python
async def test_flaky():
    await start_async_operation()
    await asyncio.sleep(1)  # Hope it's done!
    assert operation_complete()
```

✅ **Do**: Wait for conditions
```python
async def test_reliable():
    await start_async_operation()
    await wait_for_condition(
        lambda: operation_complete(),
        timeout=30
    )
    assert operation_complete()
```

### Missing Markers

❌ **Don't**: Forget test markers
```python
async def test_slow_integration():  # Missing markers!
    # Long-running test...
```

✅ **Do**: Mark tests appropriately
```python
@pytest.mark.integration
@pytest.mark.slow
async def test_slow_integration():
    # Long-running test...
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Integration Testing**: Cross-component test strategies
- **pytest**: Test framework and fixtures
- **Test Data Management**: Creating and managing test data
- **Database Testing**: Testing with real databases
- **Async Testing**: Testing asynchronous code
- **Performance Testing**: Load and performance testing

## Best Practices

### Test Organization

Organize by scenario:
- `test_machine_lifecycle.py`: Complete machine workflows
- `test_network_integration.py`: Network configuration scenarios
- `test_deployment_workflows.py`: Deployment end-to-end
- `test_api_service_integration.py`: API to service layer
- `test_database_consistency.py`: Data integrity tests

### Test Documentation

Document test scenarios:
```python
async def test_machine_deployment_with_custom_network():
    """
    Integration test for machine deployment with custom network configuration.
    
    Scenario:
    1. Create machine via API
    2. Configure custom network settings
    3. Deploy machine with network configuration
    4. Verify deployment successful
    5. Verify network settings applied
    
    Tests:
    - API → Service → Repository data flow
    - Temporal workflow execution
    - Network configuration persistence
    - Machine state transitions
    """
```

### Timeouts

Always set timeouts:
```python
@pytest.mark.timeout(300)  # 5 minute timeout
async def test_long_running_integration():
    """Long-running integration test with timeout."""
```

## Additional Resources

- pytest Documentation: https://docs.pytest.org/
- Integration Testing Best Practices: https://martinfowler.com/bliki/IntegrationTest.html
- `AGENTS.md`: General coding guidelines
- Individual subsystem documentation in `.sdd/context/subsystems/`
