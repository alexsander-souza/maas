# maastemporalworker Subsystem

## Purpose

Temporal workflow workers that execute long-running, distributed workflows for MAAS operations. This subsystem handles asynchronous, durable task execution for operations like machine deployment, commissioning, hardware testing, and other multi-step processes that require reliability, observability, and fault tolerance.

**Status**: Active development - critical for async operations.

## Location

`src/maastemporalworker`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Temporal**: Workflow orchestration platform
- **Temporal Python SDK**: Client library for workflows and activities

### Key Libraries
- **temporalio**: Official Temporal Python SDK
- **pydantic**: Data validation for workflow inputs
- **pytest**: Testing framework
- **pytest-asyncio**: Async test support

## Architectural Constraints

### Workflow Determinism

Workflows **MUST** be deterministic:
- Same inputs always produce same outputs
- No random number generation
- No direct I/O operations
- No system time calls (use workflow time)
- No direct database access

### Activity for Non-Deterministic Operations

All non-deterministic operations go in activities:
- Database queries
- External API calls
- File I/O
- Random number generation
- Current time access

### Type Safety

Ensure full type hints for Pyright compliance:
- All workflow methods fully typed
- All activity methods fully typed
- Input/output models use Pydantic
- No `Any` types without justification

## Key Patterns

### Workflow Pattern

Workflows orchestrate long-running processes:

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Optional

@workflow.defn
class DeployMachineWorkflow:
    """Workflow for machine deployment orchestration."""
    
    @workflow.run
    async def run(self, machine_id: int, config: DeploymentConfig) -> DeploymentResult:
        """
        Execute machine deployment workflow.
        
        Args:
            machine_id: ID of machine to deploy
            config: Deployment configuration
            
        Returns:
            Deployment result with status and details
        """
        # Start deployment
        await workflow.execute_activity(
            start_deployment,
            args=[machine_id, config],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
        )
        
        # Configure networking
        await workflow.execute_activity(
            configure_network,
            args=[machine_id, config.network],
            start_to_close_timeout=timedelta(minutes=3),
        )
        
        # Configure storage
        await workflow.execute_activity(
            configure_storage,
            args=[machine_id, config.storage],
            start_to_close_timeout=timedelta(minutes=5),
        )
        
        # Power on and wait for deployment
        await workflow.execute_activity(
            power_on_machine,
            args=[machine_id],
            start_to_close_timeout=timedelta(minutes=2),
        )
        
        # Wait for deployment completion (with timeout)
        try:
            result = await workflow.execute_activity(
                wait_for_deployment,
                args=[machine_id],
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
            )
            return result
        except Exception as e:
            # Handle failure
            await workflow.execute_activity(
                cleanup_failed_deployment,
                args=[machine_id],
                start_to_close_timeout=timedelta(minutes=5),
            )
            raise
```

### Activity Pattern

Activities perform actual work:

```python
from temporalio import activity
from maasservicelayer.services.machines import MachineService
import asyncio

@activity.defn
async def start_deployment(machine_id: int, config: DeploymentConfig) -> None:
    """
    Start machine deployment process.
    
    Args:
        machine_id: Machine to deploy
        config: Deployment configuration
    """
    # Activities can access external services
    service = get_machine_service()
    
    # Record heartbeats for long operations
    activity.heartbeat(f"Starting deployment for machine {machine_id}")
    
    # Update machine status
    await service.update_status(machine_id, "deploying")
    
    activity.heartbeat("Deployment started")

@activity.defn
async def wait_for_deployment(machine_id: int) -> DeploymentResult:
    """
    Wait for deployment to complete.
    
    This is a long-running activity that polls for completion.
    
    Args:
        machine_id: Machine being deployed
        
    Returns:
        Deployment result
    """
    service = get_machine_service()
    max_iterations = 240  # 2 hours at 30s intervals
    
    for i in range(max_iterations):
        # Send heartbeat to prevent timeout
        activity.heartbeat(f"Checking deployment status (iteration {i})")
        
        # Check machine status
        machine = await service.get_by_id(machine_id)
        
        if machine.status == "deployed":
            return DeploymentResult(
                success=True,
                machine_id=machine_id,
                message="Deployment successful"
            )
        elif machine.status == "failed":
            raise DeploymentFailedError(f"Deployment failed: {machine.error}")
        
        # Wait before next check
        await asyncio.sleep(30)
    
    raise TimeoutError("Deployment timed out after 2 hours")
```

### Retry Policies

Configure appropriate retry policies:

```python
from temporalio.common import RetryPolicy
from datetime import timedelta

# Standard retry policy
standard_retry = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

# Aggressive retry for critical operations
critical_retry = RetryPolicy(
    maximum_attempts=10,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
)

# No retry for non-idempotent operations
no_retry = RetryPolicy(
    maximum_attempts=1,
)

# Usage
await workflow.execute_activity(
    critical_operation,
    args=[data],
    retry_policy=critical_retry,
    start_to_close_timeout=timedelta(minutes=5),
)
```

### Timeout Policies

Set appropriate timeouts:

```python
# Short-lived activities
await workflow.execute_activity(
    quick_operation,
    args=[data],
    start_to_close_timeout=timedelta(seconds=30),
    schedule_to_close_timeout=timedelta(minutes=1),
)

# Long-running activities with heartbeats
await workflow.execute_activity(
    long_operation,
    args=[data],
    start_to_close_timeout=timedelta(hours=2),
    heartbeat_timeout=timedelta(minutes=5),  # Must heartbeat every 5 min
    schedule_to_close_timeout=timedelta(hours=3),
)
```

### Workflow Signals

Use signals for external events:

```python
@workflow.defn
class DeployMachineWorkflow:
    """Workflow with signal support."""
    
    def __init__(self):
        self._cancelled = False
        self._paused = False
    
    @workflow.signal
    async def cancel(self) -> None:
        """Signal to cancel deployment."""
        self._cancelled = True
    
    @workflow.signal
    async def pause(self) -> None:
        """Signal to pause deployment."""
        self._paused = True
    
    @workflow.signal
    async def resume(self) -> None:
        """Signal to resume deployment."""
        self._paused = False
    
    @workflow.run
    async def run(self, machine_id: int) -> DeploymentResult:
        """Execute with cancellation support."""
        while self._paused:
            await workflow.wait_condition(lambda: not self._paused)
        
        if self._cancelled:
            raise WorkflowCancelledError("Deployment cancelled by user")
        
        # Continue deployment...
```

### Workflow Queries

Use queries to inspect workflow state:

```python
@workflow.defn
class DeployMachineWorkflow:
    """Workflow with query support."""
    
    def __init__(self):
        self._status = "initializing"
        self._progress = 0
    
    @workflow.query
    def get_status(self) -> str:
        """Query current deployment status."""
        return self._status
    
    @workflow.query
    def get_progress(self) -> int:
        """Query deployment progress percentage."""
        return self._progress
    
    @workflow.run
    async def run(self, machine_id: int) -> DeploymentResult:
        """Execute with status tracking."""
        self._status = "configuring"
        self._progress = 10
        await workflow.execute_activity(configure_machine, args=[machine_id])
        
        self._status = "deploying"
        self._progress = 50
        await workflow.execute_activity(deploy_os, args=[machine_id])
        
        self._status = "finalizing"
        self._progress = 90
        await workflow.execute_activity(finalize_deployment, args=[machine_id])
        
        self._status = "complete"
        self._progress = 100
        return DeploymentResult(success=True)
```

### Child Workflows

Decompose complex workflows:

```python
@workflow.defn
class MasterDeploymentWorkflow:
    """Parent workflow orchestrating multiple machine deployments."""
    
    @workflow.run
    async def run(self, machine_ids: list[int], config: DeploymentConfig) -> list[DeploymentResult]:
        """Deploy multiple machines in parallel."""
        
        # Start child workflows for each machine
        child_handles = []
        for machine_id in machine_ids:
            handle = await workflow.start_child_workflow(
                DeployMachineWorkflow.run,
                args=[machine_id, config],
                id=f"deploy-machine-{machine_id}",
            )
            child_handles.append(handle)
        
        # Wait for all to complete
        results = []
        for handle in child_handles:
            result = await handle
            results.append(result)
        
        return results
```

## Testing Requirements

### Mock Temporal Client

Always mock Temporal client in tests:

```python
import pytest
from unittest.mock import Mock, AsyncMock
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

@pytest.mark.asyncio
async def test_deployment_workflow():
    """Test deployment workflow with mocked activities."""
    
    # Use Temporal test environment
    async with await WorkflowEnvironment.start_time_skipping() as env:
        # Mock activities
        async def mock_start_deployment(machine_id: int, config) -> None:
            pass
        
        async def mock_configure_network(machine_id: int, network) -> None:
            pass
        
        # Create worker with mocked activities
        worker = Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DeployMachineWorkflow],
            activities=[
                mock_start_deployment,
                mock_configure_network,
            ],
        )
        
        async with worker:
            # Execute workflow
            result = await env.client.execute_workflow(
                DeployMachineWorkflow.run,
                args=[123, DeploymentConfig(...)],
                id="test-deploy-123",
                task_queue="test-queue",
            )
            
            assert result.success is True

@pytest.mark.asyncio
async def test_activity_with_mock_service(mocker):
    """Test activity with mocked service dependencies."""
    
    # Mock the service
    mock_service = mocker.Mock(spec=MachineService)
    mock_service.update_status = AsyncMock()
    
    # Inject mock
    with mocker.patch('maastemporalworker.activities.get_machine_service', return_value=mock_service):
        # Execute activity
        await start_deployment(123, DeploymentConfig(...))
        
        # Verify service called
        mock_service.update_status.assert_called_once_with(123, "deploying")
```

### Test Time Skipping

Use Temporal's time skipping for testing:

```python
@pytest.mark.asyncio
async def test_workflow_with_delays():
    """Test workflow that uses timers."""
    
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DelayedWorkflow],
            activities=[],
        )
        
        async with worker:
            # Time automatically advances
            result = await env.client.execute_workflow(
                DelayedWorkflow.run,
                id="test-delayed",
                task_queue="test-queue",
            )
            
            # Workflow that would take hours completes instantly in tests
            assert result.success is True
```

### Running Tests

```bash
# Run all temporal worker tests
pytest src/maastemporalworker/tests/

# Run specific workflow tests
pytest src/maastemporalworker/tests/workflows/test_deployment.py

# Run with coverage
pytest --cov=maastemporalworker src/maastemporalworker/tests/
```

## Development Guidelines

### Workflow Development

1. **Keep Workflows Deterministic**: No side effects in workflow code
2. **Use Activities for I/O**: All external operations in activities
3. **Set Appropriate Timeouts**: Based on expected operation duration
4. **Configure Retry Policies**: Handle transient failures
5. **Add Heartbeats**: For long-running activities
6. **Use Type Hints**: Full type safety throughout
7. **Document Workflow Logic**: Clear docstrings explaining flow

### Activity Development

1. **Idempotent Operations**: Activities should be safe to retry
2. **Send Heartbeats**: For operations > 30 seconds
3. **Handle Errors**: Raise appropriate exceptions
4. **Validate Inputs**: Check parameters at activity start
5. **Log Progress**: Use activity logger
6. **Clean Up Resources**: Ensure proper cleanup on failure

### Error Handling

```python
from temporalio.exceptions import ApplicationError

@activity.defn
async def risky_operation(data: str) -> Result:
    """Activity with proper error handling."""
    try:
        # Attempt operation
        result = await perform_operation(data)
        return result
    except ValueError as e:
        # Non-retryable error
        raise ApplicationError(
            f"Invalid data: {e}",
            non_retryable=True,
        )
    except ConnectionError as e:
        # Retryable error
        raise ApplicationError(
            f"Connection failed: {e}",
            non_retryable=False,
        )
    except Exception as e:
        # Unexpected error
        activity.logger.error(f"Unexpected error: {e}")
        raise
```

## Integration Points

### Service Layer

Activities interact with MAAS services:

```python
from maasservicelayer.services.machines import MachineService

def get_machine_service() -> MachineService:
    """Get machine service instance."""
    # Dependency injection for service access
    return MachineService(...)

@activity.defn
async def update_machine(machine_id: int, updates: dict) -> Machine:
    """Update machine via service layer."""
    service = get_machine_service()
    return await service.update(machine_id, updates)
```

### API Layer

API triggers workflows:

```python
# In API handler
from temporalio.client import Client

@handler
class MachineHandler(Handler):
    def __init__(self, service: MachineService, temporal_client: Client):
        self.service = service
        self.temporal_client = temporal_client
    
    async def deploy(self, machine_id: int, config: DeploymentConfig):
        """Start deployment workflow."""
        
        # Validate and prepare
        machine = await self.service.get_by_id(machine_id)
        if not machine:
            raise NotFoundException()
        
        # Start Temporal workflow
        handle = await self.temporal_client.start_workflow(
            DeployMachineWorkflow.run,
            args=[machine_id, config],
            id=f"deploy-{machine_id}-{uuid.uuid4()}",
            task_queue="maas-workflows",
        )
        
        return {"workflow_id": handle.id}
```

### MAAS Agent

Workflows coordinate with MAAS agents:

```python
@activity.defn
async def configure_agent(agent_id: str, config: dict) -> None:
    """Configure MAAS agent via RPC."""
    agent_client = get_agent_client()
    await agent_client.configure(agent_id, config)
```

## Common Pitfalls

### Non-Deterministic Workflows

❌ **Don't**:
```python
@workflow.defn
class BadWorkflow:
    @workflow.run
    async def run(self):
        # Non-deterministic! Will cause replay issues
        if random.random() > 0.5:
            await workflow.execute_activity(option_a)
        else:
            await workflow.execute_activity(option_b)
```

✅ **Do**:
```python
@workflow.defn
class GoodWorkflow:
    @workflow.run
    async def run(self, seed: int):
        # Use workflow-provided random
        value = workflow.random().random()
        if value > 0.5:
            await workflow.execute_activity(option_a)
        else:
            await workflow.execute_activity(option_b)
```

### Missing Timeouts

❌ **Don't**:
```python
# Activity could hang forever
await workflow.execute_activity(long_operation, args=[data])
```

✅ **Do**:
```python
await workflow.execute_activity(
    long_operation,
    args=[data],
    start_to_close_timeout=timedelta(hours=1),
    heartbeat_timeout=timedelta(minutes=5),
)
```

### Activities Without Heartbeats

❌ **Don't**:
```python
@activity.defn
async def long_operation(data: list) -> None:
    for item in data:  # Could take hours
        await process_item(item)
```

✅ **Do**:
```python
@activity.defn
async def long_operation(data: list) -> None:
    for i, item in enumerate(data):
        activity.heartbeat(f"Processing item {i}/{len(data)}")
        await process_item(item)
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Temporal Workflows**: Workflow orchestration patterns
- **Python Async**: Modern async/await patterns
- **Distributed Systems**: Distributed computing concepts
- **Error Handling**: Fault tolerance and retry logic
- **Testing**: Testing async workflows
- **Observability**: Workflow monitoring and debugging

## Security Considerations

### Input Validation

Validate all workflow inputs:
- Use Pydantic models for type safety
- Validate data at workflow entry
- Sanitize activity parameters

### Authorization

Check permissions before workflow execution:
- Validate user has permission to start workflow
- Check resource access rights
- Audit workflow starts

### Secrets Management

Never hardcode secrets:
- Use environment variables
- Integrate with secret management systems
- Rotate credentials regularly

## Performance Considerations

### Workflow Efficiency

- Minimize workflow code complexity
- Use parallel activities where possible
- Set appropriate timeouts
- Configure sensible retry policies

### Activity Optimization

- Keep activities focused and small
- Use batching for bulk operations
- Implement efficient heartbeating
- Clean up resources promptly

### Worker Scaling

- Scale workers based on task queue depth
- Configure appropriate worker pool sizes
- Monitor worker health and performance
- Use multiple task queues for different workload types

## Documentation

### Workflow Documentation

Document each workflow's purpose and flow:
- What the workflow does
- Expected inputs and outputs
- Typical execution time
- Error scenarios
- Retry behavior

### Activity Documentation

Document each activity:
- Purpose and operation
- Parameters and return values
- Expected duration
- Side effects
- Error conditions

## Additional Resources

- Temporal Documentation: https://docs.temporal.io/
- Temporal Python SDK: https://docs.temporal.io/python
- `AGENTS.md`: General coding guidelines
- Temporal Best Practices: https://docs.temporal.io/dev-guide/python/best-practices