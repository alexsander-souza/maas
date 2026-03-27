# maastemporalworker Subsystem

## Purpose

Temporal workflow workers that execute long-running, distributed workflows for MAAS operations. This subsystem handles asynchronous, durable task execution for operations like machine deployment, commissioning, and hardware testing that require reliability, observability, and fault tolerance.

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
- **pytest-asyncio**: Async test support

## Architectural Constraints

### Workflow Determinism

**Critical**: Workflows MUST be deterministic:
- Same inputs always produce same outputs
- No random number generation (use `workflow.random()`)
- No direct I/O operations
- No system time calls (use `workflow.now()`)
- No direct database access

Workflows are replayed from history when resuming, so any non-deterministic behavior will cause inconsistent state.

### Activity for Non-Deterministic Operations

All non-deterministic operations go in activities:
- Database queries
- External API calls
- File I/O
- Random number generation
- Current time access

**Why**: Activities are not replayed; their results are recorded in history.

### Type Safety

Ensure full type hints for Pyright compliance:
- All workflow methods fully typed
- All activity methods fully typed
- Input/output models use Pydantic
- No `Any` types without justification

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) for common Python patterns.

### Workflow Pattern

Workflows orchestrate long-running processes with activities:

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn
class DeployMachineWorkflow:
    """Workflow for machine deployment orchestration."""
    
    @workflow.run
    async def run(self, machine_id: int, config: DeploymentConfig) -> DeploymentResult:
        # Start deployment
        await workflow.execute_activity(
            start_deployment,
            args=[machine_id, config],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        
        # Configure networking
        await workflow.execute_activity(
            configure_network,
            args=[machine_id, config.network],
            start_to_close_timeout=timedelta(minutes=3),
        )
        
        # Wait for deployment completion (long-running)
        try:
            result = await workflow.execute_activity(
                wait_for_deployment,
                args=[machine_id],
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
            )
            return result
        except Exception:
            # Cleanup on failure
            await workflow.execute_activity(
                cleanup_failed_deployment,
                args=[machine_id],
                start_to_close_timeout=timedelta(minutes=5),
            )
            raise
```

### Activity Pattern

Activities perform actual work and can access external systems:

```python
from temporalio import activity
from maasservicelayer.services.machines import MachineService
import asyncio

@activity.defn
async def start_deployment(machine_id: int, config: DeploymentConfig) -> None:
    """Start machine deployment process."""
    service = get_machine_service()
    
    # Send heartbeat for long operations
    activity.heartbeat(f"Starting deployment for machine {machine_id}")
    
    await service.update_status(machine_id, "deploying")
    activity.heartbeat("Deployment started")

@activity.defn
async def wait_for_deployment(machine_id: int) -> DeploymentResult:
    """Wait for deployment to complete with heartbeats."""
    service = get_machine_service()
    max_iterations = 240  # 2 hours at 30s intervals
    
    for i in range(max_iterations):
        # Heartbeat prevents timeout
        activity.heartbeat(f"Checking status (iteration {i})")
        
        machine = await service.get_by_id(machine_id)
        if machine.status == "deployed":
            return DeploymentResult(success=True, machine_id=machine_id)
        elif machine.status == "failed":
            raise DeploymentFailedError(f"Deployment failed: {machine.error}")
        
        await asyncio.sleep(30)
    
    raise TimeoutError("Deployment timed out")
```

### Retry and Timeout Policies

Configure appropriate retry and timeout policies:

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

# Critical operations with aggressive retry
critical_retry = RetryPolicy(
    maximum_attempts=10,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
)

# Short-lived activities
await workflow.execute_activity(
    quick_operation,
    args=[data],
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy=standard_retry,
)

# Long-running activities require heartbeats
await workflow.execute_activity(
    long_operation,
    args=[data],
    start_to_close_timeout=timedelta(hours=2),
    heartbeat_timeout=timedelta(minutes=5),  # Must heartbeat every 5 min
    retry_policy=critical_retry,
)
```

### Workflow Signals and Queries

Use signals for external events and queries for state inspection:

```python
@workflow.defn
class DeployMachineWorkflow:
    def __init__(self):
        self._cancelled = False
        self._status = "initializing"
        self._progress = 0
    
    @workflow.signal
    async def cancel(self) -> None:
        """Signal to cancel deployment."""
        self._cancelled = True
    
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
        if self._cancelled:
            raise WorkflowCancelledError("Deployment cancelled by user")
        
        self._status = "configuring"
        self._progress = 25
        await workflow.execute_activity(configure_machine, args=[machine_id])
        
        self._status = "deploying"
        self._progress = 50
        await workflow.execute_activity(deploy_os, args=[machine_id])
        
        self._status = "complete"
        self._progress = 100
        return DeploymentResult(success=True)
```

### Child Workflows

Decompose complex workflows into child workflows:

```python
@workflow.defn
class MasterDeploymentWorkflow:
    @workflow.run
    async def run(self, machine_ids: list[int], config: DeploymentConfig) -> list[DeploymentResult]:
        """Deploy multiple machines in parallel."""
        # Start child workflows
        child_handles = []
        for machine_id in machine_ids:
            handle = await workflow.start_child_workflow(
                DeployMachineWorkflow.run,
                args=[machine_id, config],
                id=f"deploy-machine-{machine_id}",
            )
            child_handles.append(handle)
        
        # Wait for all to complete
        return [await handle for handle in child_handles]
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Mock Temporal Client

Always use Temporal's test environment for workflow tests:

```python
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

@pytest.mark.asyncio
async def test_deployment_workflow():
    """Test deployment workflow with time skipping."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        # Create worker with workflows and activities
        worker = Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DeployMachineWorkflow],
            activities=[start_deployment, configure_network],
        )
        
        async with worker:
            # Execute workflow - time advances automatically
            result = await env.client.execute_workflow(
                DeployMachineWorkflow.run,
                args=[123, DeploymentConfig(...)],
                id="test-deploy-123",
                task_queue="test-queue",
            )
            
            assert result.success is True
```

### Test Activities with Mocked Services

Test activities independently with mocked service dependencies:

```python
@pytest.mark.asyncio
async def test_activity_with_mock_service(mocker):
    """Test activity with mocked service layer."""
    mock_service = mocker.Mock(spec=MachineService)
    mock_service.update_status = mocker.AsyncMock()
    
    with mocker.patch('maastemporalworker.activities.get_machine_service', return_value=mock_service):
        await start_deployment(123, DeploymentConfig(...))
        mock_service.update_status.assert_called_once_with(123, "deploying")
```

### Running Tests

```bash
# All temporal worker tests
pytest src/maastemporalworker/tests/

# Specific workflow tests
pytest src/maastemporalworker/tests/workflows/

# Activity tests
pytest src/maastemporalworker/tests/activities/
```

## Development Guidelines

### Workflow Development

1. **Keep Workflows Deterministic**: No side effects in workflow code
2. **Use Activities for I/O**: All external operations in activities
3. **Set Appropriate Timeouts**: Based on expected operation duration
4. **Configure Retry Policies**: Handle transient failures appropriately
5. **Add Type Hints**: Full type safety throughout
6. **Document Flow**: Clear docstrings explaining orchestration logic

### Activity Development

1. **Idempotent Operations**: Activities should be safe to retry
2. **Send Heartbeats**: For operations longer than 30 seconds
3. **Handle Errors Appropriately**: Use `ApplicationError` with proper flags
4. **Validate Inputs**: Check parameters at activity start
5. **Clean Up Resources**: Ensure proper cleanup on failure

```python
from temporalio.exceptions import ApplicationError

@activity.defn
async def risky_operation(data: str) -> Result:
    """Activity with proper error handling."""
    try:
        result = await perform_operation(data)
        return result
    except ValueError as e:
        # Non-retryable error
        raise ApplicationError(f"Invalid data: {e}", non_retryable=True)
    except ConnectionError as e:
        # Retryable error
        raise ApplicationError(f"Connection failed: {e}", non_retryable=False)
    except Exception as e:
        activity.logger.error(f"Unexpected error: {e}")
        raise
```

## Integration Points

### Service Layer (maasservicelayer)
- Activities call MAAS services for business logic and data access
- Services injected via dependency injection
- See [maasservicelayer.md](./maasservicelayer.md)

```python
@activity.defn
async def update_machine(machine_id: int, updates: dict) -> Machine:
    service = get_machine_service()  # Dependency injection
    return await service.update(machine_id, updates)
```

### API Layer (maasapiserver)
- API handlers trigger workflows via Temporal client
- Workflows return handles for tracking
- See [maasapiserver.md](./maasapiserver.md)

```python
# In API handler
async def deploy(self, machine_id: int, config: DeploymentConfig):
    handle = await self.temporal_client.start_workflow(
        DeployMachineWorkflow.run,
        args=[machine_id, config],
        id=f"deploy-{machine_id}",
        task_queue="maas-workflows",
    )
    return {"workflow_id": handle.id}
```

### MAAS Agent (maasagent)
- Workflows coordinate with MAAS agents via activities
- Agent communication through RPC or message bus
- See [maasagent.md](./maasagent.md)

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Non-Deterministic Workflows

❌ **Don't** use non-deterministic operations in workflows:
```python
@workflow.defn
class BadWorkflow:
    @workflow.run
    async def run(self):
        if random.random() > 0.5:  # WRONG! Non-deterministic
            await workflow.execute_activity(option_a)
```

✅ **Do** use workflow-provided random:
```python
@workflow.defn
class GoodWorkflow:
    @workflow.run
    async def run(self):
        if workflow.random().random() > 0.5:  # Deterministic
            await workflow.execute_activity(option_a)
```

### Missing Timeouts

❌ **Don't** execute activities without timeouts:
```python
await workflow.execute_activity(long_operation, args=[data])  # WRONG!
```

✅ **Do** set appropriate timeouts:
```python
await workflow.execute_activity(
    long_operation,
    args=[data],
    start_to_close_timeout=timedelta(hours=1),
    heartbeat_timeout=timedelta(minutes=5),
)
```

### Activities Without Heartbeats

❌ **Don't** run long operations without heartbeats:
```python
@activity.defn
async def long_operation(data: list) -> None:
    for item in data:  # WRONG! Could take hours without heartbeat
        await process_item(item)
```

✅ **Do** send heartbeats regularly:
```python
@activity.defn
async def long_operation(data: list) -> None:
    for i, item in enumerate(data):
        activity.heartbeat(f"Processing {i}/{len(data)}")
        await process_item(item)
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Input Validation
- Validate all workflow inputs using Pydantic models
- Validate activity parameters at entry
- See [input-validation.md](../../skills/techniques/input-validation.md)

### Authorization
- Check permissions before starting workflows
- Validate user has access to resources
- Audit workflow starts

### Secrets Management
- Never hardcode secrets in workflow or activity code
- Use environment variables or secret management systems
- Rotate credentials regularly

## Performance Considerations

### Workflow Efficiency
- Minimize workflow code complexity
- Use parallel activities where possible with `asyncio.gather()`
- Set appropriate timeouts based on real operation duration
- Configure sensible retry policies to avoid excessive retries

### Activity Optimization
- Keep activities focused and small
- Use batching for bulk operations
- Implement efficient heartbeat intervals (every 10-30 seconds)
- Clean up resources promptly

### Worker Scaling
- Scale workers based on task queue depth
- Configure appropriate worker pool sizes
- Monitor worker health and performance
- Use multiple task queues for different workload types (e.g., fast vs. slow operations)

## Additional Resources

- **Temporal Documentation**: https://docs.temporal.io/
- **Temporal Python SDK**: https://docs.temporal.io/python
- **Best Practices**: https://docs.temporal.io/dev-guide/python/best-practices
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [maasservicelayer.md](./maasservicelayer.md)