# perftests Subsystem

## Purpose

Performance testing infrastructure for MAAS, providing benchmarks, load tests, and performance regression detection. This subsystem ensures MAAS maintains acceptable performance characteristics under various workloads and helps identify bottlenecks before they reach production.

**Status**: Active - continuous performance monitoring and testing.

## Location

`src/perftests`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **pytest**: Test framework
- **pytest-benchmark**: Benchmarking plugin

### Key Libraries
- **locust**: Load testing framework
- **pytest-benchmark**: Performance benchmarking
- **memory-profiler**: Memory usage profiling
- **matplotlib**: Performance visualization
- **httpx**: Async HTTP client for API testing

## Architectural Constraints

### Independent Test Suite

Performance tests are separate from unit/integration tests:
- Run on-demand, not in CI by default
- Require dedicated test infrastructure
- May take significant time to execute
- Need baseline measurements for comparison

### Realistic Workloads

Tests should simulate production scenarios:
- Realistic data volumes
- Concurrent operations
- Mixed workload patterns
- Peak load scenarios

### Reproducible Results

Ensure consistent measurements:
- Controlled test environment
- Isolated execution
- Multiple iterations for statistical significance
- Baseline comparison

## Key Patterns

### Benchmark Pattern

Use pytest-benchmark for micro-benchmarks:

```python
import pytest
from maasservicelayer.services.machines import MachineService

def test_machine_list_performance(benchmark, db_connection):
    """Benchmark machine listing operation."""
    # Setup test data
    service = MachineService(db_connection)
    
    # Populate with test machines
    for i in range(1000):
        create_test_machine(f"machine-{i}")
    
    # Benchmark the operation
    result = benchmark(service.list, limit=100)
    
    # Assert reasonable performance
    assert len(result) == 100
    # Benchmark automatically measures time

@pytest.mark.benchmark(
    group="database",
    min_rounds=10,
    warmup=True
)
def test_query_performance(benchmark, db_connection):
    """Benchmark database query performance."""
    repository = MachineRepository(db_connection)
    
    def query_machines():
        return repository.list(
            query=QuerySpec(
                where=MachineClauseFactory.with_status("ready")
            )
        )
    
    result = benchmark(query_machines)
    assert len(result) > 0
```

### Load Testing Pattern

Use Locust for API load testing:

```python
from locust import HttpUser, task, between

class MachineAPIUser(HttpUser):
    """Simulate user interacting with machine API."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Authenticate when user starts."""
        response = self.client.post("/MAAS/api/v3/auth/login", json={
            "username": "testuser",
            "password": "testpass"
        })
        self.token = response.json()["token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
    
    @task(3)
    def list_machines(self):
        """List machines (common operation - higher weight)."""
        self.client.get("/MAAS/api/v3/machines")
    
    @task(2)
    def get_machine(self):
        """Get single machine details."""
        self.client.get(f"/MAAS/api/v3/machines/{self.get_random_machine_id()}")
    
    @task(1)
    def create_machine(self):
        """Create new machine (less common - lower weight)."""
        self.client.post("/MAAS/api/v3/machines", json={
            "hostname": f"test-machine-{self.random_id()}",
            "architecture": "amd64"
        })
    
    def get_random_machine_id(self):
        """Get random machine ID for testing."""
        import random
        return random.randint(1, 1000)
    
    def random_id(self):
        """Generate random ID."""
        import uuid
        return str(uuid.uuid4())[:8]

class AdminUser(HttpUser):
    """Simulate admin performing heavy operations."""
    
    wait_time = between(5, 10)
    
    @task
    def bulk_commission(self):
        """Commission multiple machines."""
        machine_ids = [1, 2, 3, 4, 5]
        self.client.post("/MAAS/api/v3/machines/commission", json={
            "machine_ids": machine_ids
        })
```

### Memory Profiling Pattern

Profile memory usage for operations:

```python
from memory_profiler import profile

@profile
def test_memory_usage_during_deployment():
    """Profile memory usage during machine deployment."""
    service = DeploymentService()
    
    # Deploy 100 machines
    for i in range(100):
        service.deploy(f"machine-{i}", config)
    
    # Memory profiler will show line-by-line memory usage

def test_memory_leak_detection():
    """Detect memory leaks in long-running operations."""
    import gc
    import tracemalloc
    
    tracemalloc.start()
    
    service = MachineService()
    
    # Baseline
    baseline_snapshot = tracemalloc.take_snapshot()
    
    # Perform operations
    for i in range(1000):
        service.create(MachineCreateBuilder().with_hostname(f"test-{i}"))
        if i % 100 == 0:
            gc.collect()
    
    # Check memory growth
    current_snapshot = tracemalloc.take_snapshot()
    top_stats = current_snapshot.compare_to(baseline_snapshot, 'lineno')
    
    # Assert reasonable memory growth
    total_growth = sum(stat.size_diff for stat in top_stats)
    assert total_growth < 100 * 1024 * 1024  # Less than 100MB growth
```

### Stress Testing Pattern

Test system limits and failure modes:

```python
import pytest
import asyncio

@pytest.mark.stress
async def test_concurrent_machine_creation():
    """Test system under high concurrent load."""
    service = MachineService()
    
    # Create 1000 machines concurrently
    tasks = []
    for i in range(1000):
        task = service.create(
            MachineCreateBuilder().with_hostname(f"stress-{i}")
        )
        tasks.append(task)
    
    # Execute all concurrently
    start_time = time.time()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    duration = time.time() - start_time
    
    # Check results
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    
    print(f"Duration: {duration:.2f}s")
    print(f"Successes: {len(successes)}")
    print(f"Failures: {len(failures)}")
    
    # Assert acceptable success rate
    success_rate = len(successes) / len(results)
    assert success_rate > 0.95  # 95% success rate
    
    # Assert reasonable throughput
    throughput = len(successes) / duration
    assert throughput > 10  # At least 10 machines/second

@pytest.mark.stress
def test_database_connection_pool_limits():
    """Test database connection pool under load."""
    from concurrent.futures import ThreadPoolExecutor
    
    def query_database(i):
        """Perform database query."""
        service = MachineService()
        return service.list(limit=10)
    
    # Simulate 100 concurrent requests
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(query_database, i) for i in range(100)]
        results = [f.result() for f in futures]
    
    # All should succeed
    assert len(results) == 100
```

### Regression Detection Pattern

Compare against baseline performance:

```python
import pytest
import json

def load_baseline(test_name):
    """Load baseline performance metrics."""
    try:
        with open(f"perftests/baselines/{test_name}.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def save_baseline(test_name, metrics):
    """Save baseline performance metrics."""
    with open(f"perftests/baselines/{test_name}.json", "w") as f:
        json.dump(metrics, f, indent=2)

def test_api_response_time_regression(benchmark):
    """Detect regression in API response times."""
    test_name = "api_machine_list"
    
    # Run benchmark
    stats = benchmark(lambda: api_client.get("/machines"))
    
    # Load baseline
    baseline = load_baseline(test_name)
    
    if baseline is None:
        # First run - save as baseline
        save_baseline(test_name, {
            "mean": stats.stats.mean,
            "stddev": stats.stats.stddev,
            "min": stats.stats.min,
            "max": stats.stats.max
        })
        pytest.skip("Baseline established")
    
    # Compare to baseline
    regression_threshold = 1.2  # 20% slower is regression
    
    if stats.stats.mean > baseline["mean"] * regression_threshold:
        pytest.fail(
            f"Performance regression detected!\n"
            f"Baseline: {baseline['mean']:.4f}s\n"
            f"Current: {stats.stats.mean:.4f}s\n"
            f"Regression: {(stats.stats.mean / baseline['mean'] - 1) * 100:.1f}%"
        )
```

### Profiling Pattern

Profile CPU usage to identify bottlenecks:

```python
import cProfile
import pstats
from io import StringIO

def test_profile_machine_deployment():
    """Profile machine deployment to identify bottlenecks."""
    profiler = cProfile.Profile()
    
    # Profile the operation
    profiler.enable()
    
    service = DeploymentService()
    service.deploy(machine_id=123, config=deployment_config)
    
    profiler.disable()
    
    # Analyze results
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats('cumulative')
    stats.print_stats(20)  # Top 20 functions
    
    print(stream.getvalue())
    
    # Save profile for later analysis
    stats.dump_stats("perftests/profiles/deployment.prof")
```

## Testing Requirements

### Test Organization

Organize performance tests by category:

```
src/perftests/
├── benchmarks/          # Micro-benchmarks
│   ├── test_services.py
│   ├── test_repositories.py
│   └── test_api.py
├── load/                # Load tests
│   ├── locustfile.py
│   └── scenarios/
├── stress/              # Stress tests
│   ├── test_limits.py
│   └── test_failure_modes.py
├── profiling/           # Profiling tests
│   └── test_profiling.py
├── baselines/           # Baseline metrics
└── profiles/            # Profile outputs
```

### Running Performance Tests

```bash
# Run all benchmarks
pytest src/perftests/benchmarks/ --benchmark-only

# Save benchmark results
pytest src/perftests/benchmarks/ --benchmark-autosave

# Compare to baseline
pytest src/perftests/benchmarks/ --benchmark-compare

# Run specific benchmark group
pytest src/perftests/benchmarks/ --benchmark-only --benchmark-group=database

# Run load tests with Locust
locust -f src/perftests/load/locustfile.py --host=http://localhost:5240

# Run load test headless
locust -f src/perftests/load/locustfile.py \
  --host=http://localhost:5240 \
  --users=100 \
  --spawn-rate=10 \
  --run-time=5m \
  --headless

# Run stress tests
pytest src/perftests/stress/ -m stress

# Profile specific test
python -m cProfile -o output.prof src/perftests/profiling/test_deployment.py
```

### Performance Metrics

Track key performance indicators:

```python
class PerformanceMetrics:
    """Standard performance metrics to track."""
    
    # API Response Times
    API_RESPONSE_TIME_P50 = "api.response.p50"
    API_RESPONSE_TIME_P95 = "api.response.p95"
    API_RESPONSE_TIME_P99 = "api.response.p99"
    
    # Throughput
    REQUESTS_PER_SECOND = "throughput.rps"
    MACHINES_DEPLOYED_PER_MINUTE = "throughput.deployments"
    
    # Database
    DB_QUERY_TIME = "db.query.time"
    DB_CONNECTION_POOL_USAGE = "db.connections.used"
    
    # System Resources
    MEMORY_USAGE = "system.memory.bytes"
    CPU_USAGE_PERCENT = "system.cpu.percent"
    
    # Error Rates
    ERROR_RATE = "errors.rate"
    TIMEOUT_RATE = "timeouts.rate"
```

## Development Guidelines

### Writing Benchmarks

1. **Focus on Critical Paths**: Benchmark operations users perform frequently
2. **Realistic Data**: Use production-like data volumes
3. **Warm-up Iterations**: Allow for JIT compilation and caching
4. **Statistical Significance**: Run multiple iterations
5. **Isolation**: Minimize external factors

### Load Test Scenarios

Design realistic load patterns:

```python
# Gradual ramp-up
locust -f locustfile.py --users=1000 --spawn-rate=10

# Spike test - sudden load increase
locust -f locustfile.py --users=1000 --spawn-rate=100

# Sustained load - constant traffic
locust -f locustfile.py --users=500 --spawn-rate=10 --run-time=1h

# Peak load - stress maximum capacity
locust -f locustfile.py --users=5000 --spawn-rate=50
```

### Baseline Management

Establish and maintain baselines:

1. Run tests on stable release
2. Save results as baseline
3. Run tests on new changes
4. Compare to baseline
5. Update baseline if intentional improvement
6. Investigate regressions

### Performance Budgets

Set performance budgets for critical operations:

```python
PERFORMANCE_BUDGETS = {
    "api.machines.list": {
        "p50": 100,  # 100ms
        "p95": 250,  # 250ms
        "p99": 500,  # 500ms
    },
    "api.machines.deploy": {
        "p50": 1000,  # 1s
        "p95": 2000,  # 2s
        "p99": 5000,  # 5s
    },
    "db.query.machines": {
        "mean": 50,  # 50ms average
    }
}

def test_performance_budget_compliance():
    """Verify operations meet performance budgets."""
    for operation, budget in PERFORMANCE_BUDGETS.items():
        actual = measure_operation(operation)
        for metric, threshold in budget.items():
            assert actual[metric] <= threshold, \
                f"{operation} {metric} exceeds budget: {actual[metric]}ms > {threshold}ms"
```

## Integration Points

### CI/CD Pipeline

Integrate performance tests in CI:

```yaml
# .github/workflows/performance.yml
name: Performance Tests

on:
  schedule:
    - cron: '0 2 * * *'  # Nightly
  workflow_dispatch:

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run benchmarks
        run: pytest src/perftests/benchmarks/ --benchmark-json=output.json
      - name: Compare to baseline
        run: python scripts/compare_benchmarks.py
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: benchmark-results
          path: output.json
```

### Monitoring Integration

Feed results to monitoring systems:

```python
def publish_metrics_to_prometheus(metrics):
    """Publish performance metrics to Prometheus."""
    from prometheus_client import Gauge
    
    api_latency = Gauge('api_latency_seconds', 'API latency')
    api_latency.set(metrics['api_response_time'])
    
    throughput = Gauge('api_throughput_rps', 'Requests per second')
    throughput.set(metrics['requests_per_second'])
```

## Common Pitfalls

### Non-Representative Tests

❌ **Don't**: Test with unrealistic data
```python
def test_performance():
    # Only 10 machines - not realistic!
    for i in range(10):
        create_machine(f"test-{i}")
```

✅ **Do**: Use realistic data volumes
```python
def test_performance():
    # 10,000 machines - closer to production
    bulk_create_machines(10000)
```

### Ignoring Warm-up

❌ **Don't**: Measure cold starts
```python
def test_api_performance():
    response_time = measure(api_client.get("/machines"))
    assert response_time < 100  # First request may be slow!
```

✅ **Do**: Warm up before measuring
```python
def test_api_performance(benchmark):
    # Benchmark handles warm-up automatically
    benchmark.pedantic(
        lambda: api_client.get("/machines"),
        iterations=10,
        rounds=100,
        warmup_rounds=10
    )
```

### Noisy Environment

❌ **Don't**: Run on shared infrastructure
```python
# Running on developer's laptop with other processes
pytest src/perftests/  # Results will vary!
```

✅ **Do**: Use dedicated environment
```python
# Dedicated performance test server
# Minimal background processes
# Consistent hardware
pytest src/perftests/
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Performance Testing**: Testing strategies and tools
- **Load Testing**: Simulating user load
- **Profiling**: CPU and memory profiling
- **Benchmarking**: Micro-benchmark design
- **Statistics**: Interpreting performance data
- **Monitoring**: Performance monitoring and alerting

## Performance Targets

Establish clear performance targets:

### API Performance
- **P50**: < 100ms for read operations
- **P95**: < 250ms for read operations
- **P99**: < 500ms for read operations

### Throughput
- **Machine Listing**: > 1000 requests/second
- **Machine Creation**: > 100 machines/second
- **Concurrent Deployments**: > 50 simultaneous

### Database
- **Query Time**: < 50ms average
- **Connection Pool**: < 80% utilization under normal load
- **Deadlock Rate**: < 0.1%

### Resource Usage
- **Memory**: < 2GB for API server
- **CPU**: < 70% average under normal load

## Documentation

### Test Documentation

Document each performance test:
- What is being tested
- Why it matters
- Expected performance
- Baseline values
- Regression thresholds

### Results Reporting

Generate comprehensive reports:

```python
def generate_performance_report(results):
    """Generate HTML performance report."""
    report = f"""
    # Performance Test Report
    
    Date: {datetime.now()}
    
    ## Summary
    - Total Tests: {len(results)}
    - Passed: {results.passed}
    - Regressions: {results.regressions}
    
    ## Key Metrics
    {format_metrics_table(results.metrics)}
    
    ## Regressions Detected
    {format_regressions(results.regressions)}
    
    ## Trends
    {generate_trend_charts(results)}
    """
    return report
```

## Additional Resources

- pytest-benchmark: https://pytest-benchmark.readthedocs.io/
- Locust: https://docs.locust.io/
- Python Profilers: https://docs.python.org/3/library/profile.html
- Memory Profiler: https://pypi.org/project/memory-profiler/
- `AGENTS.md`: General coding guidelines
- Performance Testing Best Practices: https://martinfowler.com/bliki/PerformanceTest.html