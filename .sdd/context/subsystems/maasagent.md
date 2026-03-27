# maasagent Subsystem

## Purpose

Modern Go-based MAAS agent using microcluster framework to provide distributed DHCP, DNS, and rack controller services. This subsystem represents the next-generation agent architecture for MAAS, replacing legacy Python-based rack controllers with a scalable, cloud-native approach.

**Status**: Active development - modern replacement for legacy rack controllers.

## Location

`src/maasagent`

## Technology Stack

### Core Technologies
- **Go**: 1.24.4
- **microcluster**: Distributed clustering framework
- **Temporal**: Workflow orchestration
- **PostgreSQL**: Local agent database (via microcluster)
- **dqlite**: Distributed SQLite for cluster state

### Key Libraries
- **microcluster**: Core clustering and API framework
- **temporalio/sdk-go**: Temporal workflow SDK
- **prometheus/client_golang**: Metrics collection
- **go.opentelemetry.io**: Distributed tracing
- **testify**: Testing framework and assertions
- **ISC DHCP**: DHCP server integration
- **BIND/CoreDNS**: DNS server integration

## Architectural Constraints

### Microcluster Architecture

The MAAS agent is built on microcluster, which provides:

```
┌─────────────────────────────────────────┐
│         MAAS Agent (microcluster)       │
│  ┌───────────────────────────────────┐  │
│  │     REST API (microcluster)       │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│  ┌───────────▼───────────────────────┐  │
│  │      Service Layer                │  │
│  │  - DHCP Service                   │  │
│  │  - DNS Service                    │  │
│  │  - Image Service                  │  │
│  │  - Metrics Service                │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│  ┌───────────▼───────────────────────┐  │
│  │    Temporal Worker                │  │
│  │  - Workflows                      │  │
│  │  - Activities                     │  │
│  └───────────────────────────────────┘  │
│                                          │
│  ┌───────────────────────────────────┐  │
│  │   dqlite (Cluster State)          │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Distributed Operation

- **Clustering**: Multiple agents form a cluster via microcluster
- **High Availability**: Automatic failover and leader election
- **State Synchronization**: dqlite provides distributed consensus
- **Service Discovery**: Built-in cluster member discovery

### Cloud-Native Design

- **12-Factor App**: Follows cloud-native principles
- **Stateless Services**: State in distributed database
- **Observability**: Comprehensive metrics and tracing
- **Graceful Shutdown**: Proper cleanup and connection draining

## Key Patterns

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
    // Initialize DHCP server
    return s.startDHCPServer(ctx)
}

func (s *DHCPService) Stop() error {
    // Gracefully shutdown DHCP server
    return s.stopDHCPServer()
}

func (s *DHCPService) Reload(ctx context.Context) error {
    // Reload configuration without downtime
    return s.reloadDHCPConfig(ctx)
}
```

### Temporal Workflow Pattern

Workflows orchestrate long-running operations:

```go
package workflows

import (
    "go.temporal.io/sdk/workflow"
    "time"
)

func DeployMachineWorkflow(ctx workflow.Context, machineID string) error {
    // Define workflow execution
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 10 * time.Minute,
    }
    ctx = workflow.WithActivityOptions(ctx, ao)
    
    // Execute activities
    var bootConfig BootConfig
    err := workflow.ExecuteActivity(ctx, GenerateBootConfig, machineID).Get(ctx, &bootConfig)
    if err != nil {
        return err
    }
    
    err = workflow.ExecuteActivity(ctx, ConfigureDHCP, machineID, bootConfig).Get(ctx, nil)
    if err != nil {
        return err
    }
    
    err = workflow.ExecuteActivity(ctx, PowerOnMachine, machineID).Get(ctx, nil)
    if err != nil {
        return err
    }
    
    return nil
}
```

### Temporal Activity Pattern

Activities perform individual work units:

```go
package activities

import (
    "context"
)

type DHCPActivity struct {
    dhcpService *DHCPService
}

func (a *DHCPActivity) ConfigureDHCP(ctx context.Context, machineID string, config BootConfig) error {
    // Idempotent DHCP configuration
    lease := DHCPLease{
        MAC:      config.MAC,
        IP:       config.IP,
        Hostname: config.Hostname,
        BootFile: config.BootFile,
    }
    
    return a.dhcpService.CreateOrUpdateLease(ctx, lease)
}

func (a *DHCPActivity) RemoveDHCPLease(ctx context.Context, machineID string) error {
    // Clean up DHCP lease
    return a.dhcpService.RemoveLease(ctx, machineID)
}
```

### Prometheus Metrics Pattern

Export metrics for monitoring:

```go
package metrics

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

var (
    dhcpLeasesTotal = promauto.NewGauge(prometheus.GaugeOpts{
        Name: "maas_agent_dhcp_leases_total",
        Help: "Total number of DHCP leases",
    })
    
    dhcpRequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
        Name: "maas_agent_dhcp_requests_total",
        Help: "Total DHCP requests by type",
    }, []string{"type"})
    
    workflowDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
        Name:    "maas_agent_workflow_duration_seconds",
        Help:    "Workflow execution duration",
        Buckets: prometheus.DefBuckets,
    }, []string{"workflow"})
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
package dhcp

import (
    "context"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/trace"
)

var tracer = otel.Tracer("maas-agent/dhcp")

func (s *DHCPService) CreateLease(ctx context.Context, lease DHCPLease) error {
    ctx, span := tracer.Start(ctx, "DHCPService.CreateLease")
    defer span.End()
    
    span.SetAttributes(
        attribute.String("mac", lease.MAC),
        attribute.String("ip", lease.IP),
        attribute.String("hostname", lease.Hostname),
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
package config

type AgentConfig struct {
    ClusterAddress string `yaml:"cluster_address"`
    RegionURL      string `yaml:"region_url"`
    
    DHCP DHCPConfig `yaml:"dhcp"`
    DNS  DNSConfig  `yaml:"dns"`
    
    Temporal TemporalConfig `yaml:"temporal"`
    Metrics  MetricsConfig  `yaml:"metrics"`
}

type DHCPConfig struct {
    Enabled   bool   `yaml:"enabled"`
    Interface string `yaml:"interface"`
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
    // Additional validation...
    return nil
}
```

## Testing Requirements

### Test Framework

Use Go's testing package with testify:

```go
package dhcp_test

import (
    "testing"
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

func TestDHCPService_CreateLease(t *testing.T) {
    // Arrange
    service := NewDHCPService()
    lease := DHCPLease{
        MAC:      "00:11:22:33:44:55",
        IP:       "192.168.1.100",
        Hostname: "test-machine",
    }
    
    // Act
    err := service.CreateLease(context.Background(), lease)
    
    // Assert
    require.NoError(t, err)
    
    retrieved, err := service.GetLease(lease.MAC)
    require.NoError(t, err)
    assert.Equal(t, lease.IP, retrieved.IP)
    assert.Equal(t, lease.Hostname, retrieved.Hostname)
}
```

### Table-Driven Tests

Use table-driven tests for comprehensive coverage:

```go
func TestValidateMAC(t *testing.T) {
    tests := []struct {
        name    string
        mac     string
        want    bool
        wantErr bool
    }{
        {
            name:    "valid MAC",
            mac:     "00:11:22:33:44:55",
            want:    true,
            wantErr: false,
        },
        {
            name:    "invalid MAC",
            mac:     "invalid",
            want:    false,
            wantErr: true,
        },
        {
            name:    "empty MAC",
            mac:     "",
            want:    false,
            wantErr: true,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := ValidateMAC(tt.mac)
            if tt.wantErr {
                assert.Error(t, err)
            } else {
                assert.NoError(t, err)
                assert.Equal(t, tt.want, got)
            }
        })
    }
}
```

### Mock Interfaces

Use interfaces and mocks for testability:

```go
// Interface definition
type DHCPServer interface {
    Start(ctx context.Context) error
    Stop() error
    CreateLease(lease DHCPLease) error
    DeleteLease(mac string) error
}

// Mock implementation
type MockDHCPServer struct {
    mock.Mock
}

func (m *MockDHCPServer) CreateLease(lease DHCPLease) error {
    args := m.Called(lease)
    return args.Error(0)
}

// Test using mock
func TestDHCPService_WithMock(t *testing.T) {
    mockServer := new(MockDHCPServer)
    mockServer.On("CreateLease", mock.Anything).Return(nil)
    
    service := NewDHCPService(mockServer)
    err := service.CreateLease(DHCPLease{MAC: "00:11:22:33:44:55"})
    
    assert.NoError(t, err)
    mockServer.AssertExpectations(t)
}
```

### Integration Tests

Test with real dependencies when appropriate:

```go
// +build integration

func TestDHCPIntegration(t *testing.T) {
    if testing.Short() {
        t.Skip("Skipping integration test")
    }
    
    // Setup real DHCP server
    server := setupRealDHCPServer(t)
    defer server.Cleanup()
    
    // Run integration test
    lease := DHCPLease{MAC: "00:11:22:33:44:55", IP: "192.168.1.100"}
    err := server.CreateLease(context.Background(), lease)
    require.NoError(t, err)
}
```

### Running Tests

```bash
# Run all tests
go test ./...

# Run tests with coverage
go test -cover ./...

# Run tests with verbose output
go test -v ./...

# Run only unit tests (skip integration)
go test -short ./...

# Run integration tests
go test -tags=integration ./...

# Run specific test
go test -run TestDHCPService_CreateLease ./pkg/dhcp

# Generate coverage report
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

## Development Guidelines

### Code Organization

Follow standard Go project layout:

```
src/maasagent/
├── cmd/
│   └── maasagent/          # Main application
│       └── main.go
├── pkg/
│   ├── dhcp/               # DHCP service
│   ├── dns/                # DNS service
│   ├── workflows/          # Temporal workflows
│   ├── activities/         # Temporal activities
│   └── metrics/            # Metrics collection
├── internal/
│   ├── config/             # Configuration
│   └── database/           # Database layer
├── api/                    # API definitions (if any)
├── go.mod
├── go.sum
└── README.md
```

### Dependency Management

Check `go.mod` before adding dependencies:

```bash
# Add a new dependency
go get github.com/some/package

# Update dependencies
go get -u ./...

# Tidy dependencies
go mod tidy

# Verify dependencies
go mod verify
```

**Guidelines**:
- Minimize external dependencies
- Prefer standard library when possible
- Vendor critical dependencies if needed
- Keep dependencies up-to-date

### Error Handling

Follow Go error handling best practices:

```go
// Wrap errors with context
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

### Logging

Use structured logging:

```go
import (
    "go.uber.org/zap"
)

var logger *zap.Logger

func init() {
    logger, _ = zap.NewProduction()
}

func (s *DHCPService) CreateLease(ctx context.Context, lease DHCPLease) error {
    logger.Info("creating DHCP lease",
        zap.String("mac", lease.MAC),
        zap.String("ip", lease.IP),
        zap.String("hostname", lease.Hostname),
    )
    
    if err := s.writeLease(ctx, lease); err != nil {
        logger.Error("failed to create lease",
            zap.String("mac", lease.MAC),
            zap.Error(err),
        )
        return err
    }
    
    logger.Info("lease created successfully", zap.String("mac", lease.MAC))
    return nil
}
```

### Concurrency

Handle concurrency safely:

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

Communicates with region controller via REST API:
- Register agent with region
- Fetch configuration
- Report status and metrics
- Receive deployment instructions

### Temporal Server

Connects to shared Temporal server:
- Execute deployment workflows
- Handle commissioning activities
- Coordinate with other services

### DHCP Server (ISC DHCP)

Manages external DHCP daemon:
- Generate configuration files
- Reload daemon on changes
- Monitor daemon status

### DNS Server (BIND/CoreDNS)

Manages DNS service:
- Dynamic DNS updates
- Zone file generation
- Service discovery records

### Prometheus

Exposes metrics endpoint:
- Service health metrics
- DHCP/DNS statistics
- Workflow execution metrics
- System resource metrics

## Common Pitfalls

### Blocking Temporal Workflows

❌ **Don't**:
```go
func MyWorkflow(ctx workflow.Context) error {
    // Direct I/O in workflow - WRONG!
    data, err := http.Get("http://example.com")
    if err != nil {
        return err
    }
}
```

✅ **Do**:
```go
func MyWorkflow(ctx workflow.Context) error {
    // Use activity for I/O
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

❌ **Don't**:
```go
type Service struct {
    counter int // No synchronization - WRONG!
}

func (s *Service) Increment() {
    s.counter++
}
```

✅ **Do**:
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

❌ **Don't**:
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

✅ **Do**:
```go
func processData() error {
    file, err := os.Open("data.txt")
    if err != nil {
        return err
    }
    defer file.Close() // Ensure cleanup
    
    data, err := io.ReadAll(file)
    if err != nil {
        return err
    }
    return process(data)
}
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Go Development**: Go language best practices
- **Microcluster**: Distributed clustering patterns
- **Temporal Workflows**: Workflow orchestration
- **DHCP Management**: DHCP server configuration
- **DNS Management**: DNS server administration
- **Prometheus Metrics**: Observability and monitoring
- **Distributed Systems**: Consensus and clustering
- **Testing Go**: Go testing strategies

## Security Considerations

### API Authentication

Secure microcluster API endpoints:
- Mutual TLS for cluster communication
- API token validation
- Role-based access control

### Network Isolation

Isolate sensitive services:
- DHCP on dedicated interface
- DNS query restrictions
- Firewall rules for cluster communication

### Secrets Management

Handle secrets securely:
- Never hardcode credentials
- Use environment variables or secret stores
- Rotate credentials regularly

## Performance Considerations

### Concurrency

Leverage Go's concurrency:
- Use goroutines for parallel operations
- Channel-based communication
- Worker pools for bounded concurrency

### Memory Management

Optimize memory usage:
- Reuse buffers with sync.Pool
- Stream large files instead of loading entirely
- Profile memory usage regularly

### Database Connections

Efficient database usage:
- Connection pooling
- Prepared statements
- Batch operations where possible

## Additional Resources

- Go Documentation: https://go.dev/doc/
- microcluster: https://github.com/canonical/microcluster
- Temporal Go SDK: https://docs.temporal.io/dev-guide/go
- Prometheus Client: https://prometheus.io/docs/guides/go-application/
- OpenTelemetry Go: https://opentelemetry.io/docs/instrumentation/go/
- `AGENTS.md`: General coding guidelines
- Go best practices: https://go.dev/doc/effective_go