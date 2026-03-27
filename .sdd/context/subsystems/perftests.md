# perftests Subsystem

## Purpose

Performance testing framework for MAAS that measures and validates system performance under various load conditions. This subsystem provides tools, scenarios, and metrics collection for performance regression testing, benchmarking, and capacity planning.

**Status**: Active - critical for performance validation and regression testing.

## Location

`src/perftests`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Locust**: Load testing framework
- **pytest**: Test orchestration
- **Prometheus**: Metrics collection

### Key Libraries
- **locust**: Distributed load testing
- **pytest-benchmark**: Microbenchmarking
- **psutil**: System resource monitoring
- **requests**: HTTP client for API testing
- **asyncio**: Async load generation

## Architectural Constraints

### Isolated Environment

Performance tests run in dedicated environments:
- Separate from production
- Controlled resource allocation
- Consistent baseline configuration
- No interference from other workloads

### Repeatable Tests

All tests must be deterministic and repeatable:
- Fixed seed data
- Controlled concurrency
- Consistent load patterns
- Reproducible results

### Metrics-Driven

Focus on quantifiable metrics:
- Response time (p50, p95, p99)
- Throughput (requests/sec)
- Resource utilization (CPU, memory, I/O)
- Error rates

## Key Patterns

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for general testing patterns.
> **See**: [python-testing.md](../../skills/languages/python-testing.md) for Python testing best practices.

### Locust Load Test Pattern

Define load test scenarios with Locust:

```python
from locust import HttpUser, task, between

class MachineUser(HttpUser):
    """Simulate user interacting with machines."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between tasks
    
    def on_start(self):
        """Login once per user."""
        self.client.post("/api/v3/auth/login", json={
            "username": "perftest",
            "password": "perftest"
        })
    
    @task(3)
    def list_machines(self):
        """List machines (common operation - weight 3)."""
        self.client.get("/api/v3/machines")
    
    @task(1)
    def get_machine(self):
        """Get single machine (less common - weight 1)."""
        machine_id = self._get_random_machine_id()
        self.client.get(f"/api/v3/machines/{machine_id}")
    
    @task(1)
    def deploy_machine(self):
        """Deploy machine (heavy operation - weight 1)."""
        machine_id = self._get_available_machine()
        self.client.post(f"/api/v3/machines/{machine_id}/deploy", json={
            "os": "ubuntu",
            "distro_series": "jammy"
        })
```

### Benchmark Pattern

Microbenchmarks for specific operations:

```python
import pytest

@pytest.mark.benchmark(group="database")
def test_list_machines_query(benchmark, db_connection):
    """Benchmark database query performance."""
    repo = MachineRepository(db_connection)
    
    # Benchmark the query
    result = benchmark(repo.list, limit=100)
    
    assert len(result) <= 100

@pytest.mark.benchmark(group="serialization")
def test_machine_serialization(benchmark):
    """Benchmark Pydantic serialization."""
    machine = Machine(
        id=1,
        hostname="test",
        status="ready",
        architecture="amd64"
    )
    
    # Benchmark serialization
    result = benchmark(lambda: MachineResponse.from_model(machine))
    
    assert result.hostname == "test"
```

### Resource Monitor Pattern

Monitor system resources during tests:

```python
import psutil
import time
from contextlib import contextmanager

@contextmanager
def monitor_resources(interval=1.0):
    """Monitor CPU, memory, and I/O during test."""
    metrics = {
        'cpu_percent': [],
        'memory_percent': [],
        'disk_io': [],
        'network_io': []
    }
    
    process = psutil.Process()
    start_time = time.time()
    monitoring = True
    
    def collect_metrics():
        while monitoring:
            metrics['cpu_percent'].append(psutil.cpu_percent(interval=0.1))
            metrics['memory_percent'].append(process.memory_percent())
            metrics['disk_io'].append(psutil.disk_io_counters())
            metrics['network_io'].append(psutil.net_io_counters())
            time.sleep(interval)
    
    # Start monitoring thread
    import threading
    thread = threading.Thread(target=collect_metrics, daemon=True)
    thread.start()
    
    try:
        yield metrics
    finally:
        monitoring = False
        thread.join(timeout=2.0)
        metrics['duration'] = time.time() - start_time

# Usage
def test_deployment_performance():
    """Test deployment with resource monitoring."""
    with monitor_resources() as metrics:
        # Run deployment
        result = deploy_machines(count=10)
    
    # Assert performance requirements
    assert max(metrics['cpu_percent']) < 80
    assert max(metrics['memory_percent']) < 70
    assert result['success_rate'] > 0.95
```

### Load Profile Pattern

Define realistic load profiles:

```python
from locust import LoadTestShape

class DailyUsagePattern(LoadTestShape):
    """Simulate daily usage pattern with peaks."""
    
    stages = [
        # (duration, users, spawn_rate)
        (60, 10, 2),    # Ramp up to 10 users
        (120, 50, 5),   # Morning peak: 50 users
        (180, 20, 5),   # Midday lull: 20 users
        (120, 100, 10), # Afternoon peak: 100 users
        (60, 10, 10),   # Evening wind down
    ]
    
    def tick(self):
        """Return current user count and spawn rate."""
        run_time = self.get_run_time()
        
        for duration, users, spawn_rate in self.stages:
            if run_time < duration:
                return users, spawn_rate
            run_time -= duration
        
        return None  # Test complete
```

### Performance Assertion Pattern

Define performance requirements:

```python
class PerformanceThresholds:
    """Performance requirements for MAAS operations."""
    
    # Response time thresholds (seconds)
    LIST_MACHINES_P95 = 0.5
    GET_MACHINE_P95 = 0.1
    DEPLOY_MACHINE_P95 = 2.0
    
    # Throughput thresholds (requests/sec)
    MIN_THROUGHPUT = 100
    
    # Resource utilization limits (%)
    MAX_CPU_PERCENT = 80
    MAX_MEMORY_PERCENT = 70
    
    # Error rate limits (%)
    MAX_ERROR_RATE = 1.0

def assert_performance(stats, operation_type):
    """Assert performance meets requirements."""
    thresholds = PerformanceThresholds()
    
    # Check response time
    p95_time = stats['response_time_p95']
    threshold = getattr(thresholds, f"{operation_type}_P95")
    assert p95_time < threshold, f"P95 time {p95_time}s exceeds {threshold}s"
    
    # Check throughput
    assert stats['throughput'] >= thresholds.MIN_THROUGHPUT
    
    # Check error rate
    error_rate = stats['errors'] / stats['total_requests'] * 100
    assert error_rate < thresholds.MAX_ERROR_RATE
```

## Testing Requirements

### Test Environment Setup

Performance tests require dedicated infrastructure:

```python
import pytest

@pytest.fixture(scope="session")
def perf_test_environment():
    """Set up performance test environment."""
    # Provision test infrastructure
    env = PerformanceEnvironment()
    env.provision_cluster(
        region_count=1,
        rack_count=3,
        machine_count=1000
    )
    
    # Load baseline data
    env.load_baseline_data()
    
    yield env
    
    # Cleanup
    env.teardown()

@pytest.fixture
def reset_metrics():
    """Reset metrics between tests."""
    MetricsCollector.reset()
    yield
    MetricsCollector.export()
```

### Running Performance Tests

```bash
# Run all performance tests
pytest src/perftests/ --benchmark-only

# Run load tests with Locust
locust -f src/perftests/load/machines.py --host=http://maas.local

# Run with specific user count
locust -f src/perftests/load/machines.py --users=100 --spawn-rate=10

# Run headless with reports
locust -f src/perftests/load/machines.py --headless --users=100 --run-time=10m --html=report.html

# Run benchmarks with comparison
pytest src/perftests/ --benchmark-compare=baseline
```

## Development Guidelines

### Writing Load Tests

1. **Realistic Scenarios**: Model actual user behavior
2. **Appropriate Wait Times**: Use `wait_time` between actions
3. **Task Weights**: Reflect operation frequency
4. **Error Handling**: Don't fail on expected errors
5. **Data Variation**: Use random/varied test data

### Writing Benchmarks

1. **Isolated Operations**: Test one thing at a time
2. **Warm-up Rounds**: Allow JIT/caching to stabilize
3. **Sufficient Iterations**: Run enough times for statistical significance
4. **Consistent Environment**: Control external factors
5. **Document Baseline**: Record expected performance

### Performance Regression Detection

Track performance over time:

```python
# Store baseline metrics
baseline = {
    'list_machines_p95': 0.45,
    'deploy_machine_p95': 1.8,
    'throughput': 150
}

def test_no_performance_regression(benchmark_results):
    """Ensure performance hasn't regressed."""
    for metric, baseline_value in baseline.items():
        current_value = benchmark_results[metric]
        regression = (current_value - baseline_value) / baseline_value * 100
        
        # Allow 10% degradation
        assert regression < 10, f"{metric} regressed by {regression:.1f}%"
```

## Integration Points

### Prometheus Metrics
- Export metrics during tests
- Query historical performance data
- Compare against production metrics
- Alert on performance degradation

### CI/CD Pipeline
- Run performance tests on PRs
- Compare against baseline
- Block merges on regressions
- Generate performance reports

### Monitoring Systems
- Integrate with Grafana dashboards
- Real-time performance tracking
- Alert on threshold violations

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Testing in Production

❌ **Don't** run load tests against production:
```python
# WRONG!
MAAS_URL = "https://production.maas.io"
```

✅ **Do** use dedicated test environments:
```python
# Correct
MAAS_URL = os.environ.get("PERF_TEST_URL", "http://perf-test.local")
assert "perf-test" in MAAS_URL or "staging" in MAAS_URL
```

### Inconsistent Test Data

❌ **Don't** use random data without seeds:
```python
# WRONG! Non-reproducible
machine_count = random.randint(100, 1000)
```

✅ **Do** use fixed or seeded data:
```python
# Correct - reproducible
random.seed(42)
machine_count = 500  # Fixed
```

### Ignoring Warm-up

❌ **Don't** measure first runs:
```python
# WRONG! Includes cold start
start = time.time()
result = operation()
duration = time.time() - start
```

✅ **Do** warm up before measuring:
```python
# Correct - warm up first
for _ in range(10):
    operation()  # Warm up

start = time.time()
for _ in range(100):
    operation()
duration = (time.time() - start) / 100
```

### Not Monitoring Resources

❌ **Don't** test without resource monitoring:
```python
# WRONG! No resource tracking
def test_deployment():
    deploy_machines(count=100)
    # How much CPU/memory did this use?
```

✅ **Do** monitor resources:
```python
# Correct
def test_deployment():
    with monitor_resources() as metrics:
        deploy_machines(count=100)
    
    assert max(metrics['cpu_percent']) < 80
    assert max(metrics['memory_percent']) < 70
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Test Credentials

- Use dedicated performance test accounts
- Rotate credentials regularly
- Never use production credentials
- Store credentials securely

### Data Isolation

- Use synthetic test data only
- Never expose sensitive production data
- Clean up test data after runs
- Isolate test environments

## Performance Considerations

### Test Infrastructure

- Adequate resources for test load
- Network capacity for distributed tests
- Sufficient storage for metrics
- Isolated from other workloads

### Metrics Collection

- Low-overhead metrics collection
- Efficient storage and queries
- Sampling for high-volume metrics
- Aggregation for long-term storage

### Test Duration

- Balance thoroughness with runtime
- Short smoke tests for CI
- Comprehensive tests for releases
- Extended soak tests periodically

## Additional Resources

- **Locust Documentation**: https://docs.locust.io/
- **pytest-benchmark**: https://pytest-benchmark.readthedocs.io/
- **Performance Testing Best Practices**: https://www.softwaretestinghelp.com/performance-testing-guide/
- **Related**: [test-code-quality.md](../../skills/techniques/test-code-quality.md), [python-testing.md](../../skills/languages/python-testing.md)