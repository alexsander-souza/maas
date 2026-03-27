# maasagent Subsystem

## Purpose

Modern Go-based MAAS agent using microcluster framework to provide distributed DHCP, DNS, and rack controller services. Represents the next-generation agent architecture, replacing legacy Python-based rack controllers with a scalable, cloud-native approach.

**Status**: Active development - modern replacement for legacy rack controllers.

## Location

`src/maasagent`

## Technology Stack

### Core Technologies
- **Go**: 1.24.4
- **microcluster**: Distributed clustering framework
- **Temporal**: Workflow orchestration
- **dqlite**: Distributed SQLite for cluster state
- **ISC DHCP**: DHCP server integration

### Key Libraries
- **microcluster**: Core clustering and API framework
- **temporalio/sdk-go**: Temporal workflow SDK
- **prometheus/client_golang**: Metrics collection
- **go.opentelemetry.io**: Distributed tracing
- **testify**: Testing framework

## Architectural Constraints

### Microcluster Architecture

The MAAS agent is built on microcluster, which provides:
- **Clustering**: Multiple agents form a cluster with automatic discovery
- **High Availability**: Automatic failover and leader election
- **State Synchronization**: dqlite provides distributed consensus
- **REST API**: Built-in API server for cluster management

Services implement the microcluster service interface with `Start()`, `Stop()`, and `Reload()` methods.

### Distributed Operation

- Multiple agents coordinate via dqlite distributed database
- Automatic failover if primary agent fails
- State synchronized across cluster members
- Built-in service discovery

### Cloud-Native Design

- **12-Factor App**: Configuration via environment, stateless services
- **Observability**: Prometheus metrics and OpenTelemetry tracing
- **Graceful Shutdown**: Proper cleanup and connection draining

## Key Patterns

> **See**: [go-patterns.md](../../skills/languages/go-patterns.md) for common Go patterns.

### Microcluster Service Pattern

Services implement the microcluster service interface:

```go
package dhcp

import (
    "context"
    "github.com/canonical/microcluster/state"
)

type DHCPService struct {
    state *state.State
}

func (s *DHCPService) Name() string {
    return "dhcp"
}

func (s *DHCPService) Start(ctx context.Context) error {
    return s.startDHCPServer(ctx)
}

func (s *DHCPService) Stop() error {
    return s.stopDHCPServer()
}

func (s *DHCPService) Reload(ctx context.Context) error {
    return s.reloadDHCPConfig(ctx)
}
```

### Temporal Workflow Pattern

Workflows orchestrate long-running operations:

```go
func DeployMachineWorkflow(ctx workflow.Context, machineID string) error {
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 10 * time.Minute,
    }
    ctx = workflow.WithActivityOptions(ctx, ao)
    
    var bootConfig BootConfig
    err := workflow.ExecuteActivity(ctx, GenerateBootConfig, machineID).Get(ctx, &bootConfig)
    if err != nil {
        return err
    }
    
    err = workflow.ExecuteActivity(ctx, ConfigureDHCP, machineID, bootConfig).Get(ctx, nil)
    if err != nil {
        return err
    }
    
    return workflow.ExecuteActivity(ctx, PowerOnMachine, machineID).Get(ctx, nil)
}
```

### Temporal Activity Pattern

Activities perform individual work units:

```go
type DHCPActivity struct {
    dhcpService *DHCPService
}

func (a *DHCPActivity) ConfigureDHCP(ctx context.Context, machineID string, config BootConfig) error {
    lease := DHCPLease{
        MAC:      config.MAC,
        IP:       config.IP,
        Hostname: config.Hostname,
        BootFile: config.BootFile,
    }
    return a.dhcpService.CreateOrUpdateLease(ctx, lease)
}
```

### Prometheus Metrics Pattern

Export metrics for monitoring:

```go
var (
    dhcpLeasesTotal = promauto.NewGauge(prometheus.GaugeOpts{
        Name: "maas_agent_dhcp_leases_total",
        Help: "Total number of DHCP leases",
    })
    
    dhcpRequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
        Name: "maas_agent_dhcp_requests_total",
        Help: "Total DHCP requests by type",
    }, []string{"type"})
)

func RecordDHCPLease(count int) {
    dhcpLeasesTotal.Set(float64(count))
}

func RecordDHCPRequest(requestType string) {
    dhcpRequestsTotal.WithLabelValues(requestType).Inc()
}
```

### OpenTelemetry Tracing Pattern

Instrument code with distributed tracing:

```go
var tracer = otel.Tracer("maas-agent/dhcp")

func (s *DHCPService) CreateLease(ctx context.Context, lease DHCPLease) error {
    ctx, span := tracer.Start(ctx, "DHCPService.CreateLease")
    defer span.End()
    
    span.SetAttributes(
        attribute.String("mac", lease.MAC),
        attribute.String("ip", lease.IP),
    )
    
    err := s.writeLease(ctx, lease)
    if err != nil {
        span.RecordError(err)
        return err
    }
    return nil
}
```

### Configuration Management

Use structured configuration with validation:

```go
type AgentConfig struct {
    ClusterAddress string `yaml:"cluster_address"`
    RegionURL      string `yaml:"region_url"`
    DHCP           DHCPConfig `yaml:"dhcp"`
    Temporal       TemporalConfig `yaml:"temporal"`
}

type DHCPConfig struct {
    Enabled    bool   `yaml:"enabled"`
    Interface  string `yaml:"interface"`
    SubnetCIDR string `yaml:"subnet_cidr"`
}

func LoadConfig(path string) (*AgentConfig, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, err
    }
    
    var config AgentConfig
    if err := yaml.Unmarshal(data, &config); err != nil {
        return nil, err
    }
    return &config, config.Validate()
}

func (c *AgentConfig) Validate() error {
    if c.ClusterAddress == "" {
        return errors.New("cluster_address is required")
    }
    return nil
}
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md), [go-testing.md](../../skills/languages/go-testing.md)

### Test Framework

Use Go's testing package with testify:

```go
func TestDHCPService_CreateLease(t *testing.T) {
    service := NewDHCPService()
    lease := DHCPLease{
        MAC:      "00:11:22:33:44:55",
        IP:       "192.168.1.100",
        Hostname: "test-machine",
    }
    
    err := service.CreateLease(context.Background(), lease)
    require.NoError(t, err)
    
    retrieved, err := service.GetLease(lease.MAC)
    require.NoError(t, err)
    assert.Equal(t, lease.IP, retrieved.IP)
}
```

### Table-Driven Tests

Use table-driven tests for comprehensive coverage:

```go
func TestValidateMAC(t *testing.T) {
    tests := []struct {
        name    string
        mac     string
        wantErr bool
    }{
        {"valid MAC", "00:11:22:33:44:55", false},
        {"invalid MAC", "invalid", true},
        {"empty MAC", "", true},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            _, err := ValidateMAC(tt.mac)
            if tt.wantErr {
                assert.Error(t, err)
            } else {
                assert.NoError(t, err)
            }
        })
    }
}
```

### Mock Interfaces

Use interfaces and mocks for testability:

```go
type DHCPServer interface {
    Start(ctx context.Context) error
    CreateLease(lease DHCPLease) error
}

type MockDHCPServer struct {
    mock.Mock
}

func (m *MockDHCPServer) CreateLease(lease DHCPLease) error {
    args := m.Called(lease)
    return args.Error(0)
}

func TestDHCPService_WithMock(t *testing.T) {
    mockServer := new(MockDHCPServer)
    mockServer.On("CreateLease", mock.Anything).Return(nil)
    
    service := NewDHCPService(mockServer)
    err := service.CreateLease(DHCPLease{MAC: "00:11:22:33:44:55"})
    
    assert.NoError(t, err)
    mockServer.AssertExpectations(t)
}
```

### Running Tests

```bash
# All tests
go test ./...

# With coverage
go test -cover ./...

# Skip integration tests
go test -short ./...

# Run integration tests
go test -tags=integration ./...

# Specific test
go test -run TestDHCPService_CreateLease ./pkg/dhcp
```

## Development Guidelines

### Code Organization

Follow standard Go project layout:

```
src/maasagent/
├── cmd/maasagent/         # Main application
├── pkg/
│   ├── dhcp/              # DHCP service
│   ├── dns/               # DNS service
│   ├── workflows/         # Temporal workflows
│   ├── activities/        # Temporal activities
│   └── metrics/           # Metrics collection
├── internal/
│   ├── config/            # Configuration
│   └── database/          # Database layer
└── go.mod
```

### Error Handling

Follow Go error handling best practices:

```go
func (s *DHCPService) CreateLease(ctx context.Context, lease DHCPLease) error {
    if err := s.validateLease(lease); err != nil {
        return fmt.Errorf("validate lease: %w", err)
    }
    
    if err := s.writeLease(ctx, lease); err != nil {
        return fmt.Errorf("write lease for %s: %w", lease.MAC, err)
    }
    return nil
}

// Custom error types
type LeaseNotFoundError struct {
    MAC string
}

func (e *LeaseNotFoundError) Error() string {
    return fmt.Sprintf("lease not found for MAC %s", e.MAC)
}
```

### Concurrency

Handle concurrency safely with mutexes:

```go
type DHCPService struct {
    mu     sync.RWMutex
    leases map[string]DHCPLease
}

func (s *DHCPService) CreateLease(lease DHCPLease) error {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.leases[lease.MAC] = lease
    return nil
}

func (s *DHCPService) GetLease(mac string) (DHCPLease, error) {
    s.mu.RLock()
    defer s.mu.RUnlock()
    
    lease, ok := s.leases[mac]
    if !ok {
        return DHCPLease{}, &LeaseNotFoundError{MAC: mac}
    }
    return lease, nil
}
```

## Integration Points

### MAAS Region Controller
- Register agent with region via REST API
- Fetch configuration and deployment instructions
- Report status and metrics

### Temporal Server
- Connect to shared Temporal server
- Execute deployment workflows
- Handle commissioning activities
- See [maastemporalworker.md](./maastemporalworker.md)

### DHCP Server (ISC DHCP)
- Generate DHCP configuration files
- Reload daemon on changes
- Monitor daemon status

### DNS Server (BIND/CoreDNS)
- Dynamic DNS updates
- Zone file generation
- Service discovery records

### Prometheus
- Expose `/metrics` endpoint
- Service health metrics
- DHCP/DNS statistics
- Workflow execution metrics

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Blocking Temporal Workflows

❌ **Don't** perform I/O directly in workflows:
```go
func MyWorkflow(ctx workflow.Context) error {
    data, err := http.Get("http://example.com")  // WRONG!
    return err
}
```

✅ **Do** use activities for I/O:
```go
func MyWorkflow(ctx workflow.Context) error {
    var data []byte
    err := workflow.ExecuteActivity(ctx, FetchDataActivity, "http://example.com").Get(ctx, &data)
    return err
}

func FetchDataActivity(ctx context.Context, url string) ([]byte, error) {
    resp, err := http.Get(url)
    // ... handle response
    return data, err
}
```

### Race Conditions

❌ **Don't** access shared state without synchronization:
```go
type Service struct {
    counter int  // WRONG! No synchronization
}

func (s *Service) Increment() {
    s.counter++
}
```

✅ **Do** use mutexes for shared state:
```go
type Service struct {
    mu      sync.Mutex
    counter int
}

func (s *Service) Increment() {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.counter++
}
```

### Resource Leaks

❌ **Don't** forget to close resources:
```go
func processData() error {
    file, err := os.Open("data.txt")
    if err != nil {
        return err
    }
    // Missing file.Close() - LEAK!
    data, err := io.ReadAll(file)
    return process(data)
}
```

✅ **Do** use defer for cleanup:
```go
func processData() error {
    file, err := os.Open("data.txt")
    if err != nil {
        return err
    }
    defer file.Close()  // Ensure cleanup
    
    data, err := io.ReadAll(file)
    if err != nil {
        return err
    }
    return process(data)
}
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### API Authentication
- Mutual TLS for cluster communication
- API token validation for external access
- Role-based access control

### Network Isolation
- DHCP on dedicated interface
- DNS query restrictions
- Firewall rules for cluster communication

### Secrets Management
- Never hardcode credentials
- Use environment variables or secret stores
- Rotate credentials regularly

## Performance Considerations

### Concurrency
- Use goroutines for parallel operations
- Channel-based communication
- Worker pools for bounded concurrency

### Memory Management
- Reuse buffers with `sync.Pool`
- Stream large files instead of loading entirely
- Profile memory usage with `pprof`

### Database Connections
- Connection pooling via microcluster
- Prepared statements for repeated queries
- Batch operations where possible

## Additional Resources

- **Go Documentation**: https://go.dev/doc/
- **microcluster**: https://github.com/canonical/microcluster
- **Temporal Go SDK**: https://docs.temporal.io/dev-guide/go
- **Related**: [go-patterns.md](../../skills/languages/go-patterns.md), [microcluster-patterns.md](../../skills/languages/microcluster-patterns.md)