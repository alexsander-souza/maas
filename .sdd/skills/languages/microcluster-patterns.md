# Microcluster Patterns

## Purpose

Define microcluster-specific patterns for MAAS agent (`maasagent`), including service architecture, API endpoints, cluster management, Temporal workflow integration, metrics, and tracing.

## When to Use

- Implementing services in `maasagent`
- Creating microcluster API endpoints
- Integrating with Temporal workflows
- Adding Prometheus metrics
- Implementing distributed tracing with OpenTelemetry
- Managing DHCP and DNS services in the agent

## Pattern Examples

### Microcluster Service Structure

**Basic Service Definition**:

```go
package myservice

import (
    "context"
    "github.com/canonical/microcluster/v2/cluster"
)

type Service struct {
    cluster *cluster.Cluster
    config  Config
}

func NewService(cluster *cluster.Cluster, config Config) *Service {
    return &Service{
        cluster: cluster,
        config:  config,
    }
}

func (s *Service) Start(ctx context.Context) error {
    // Service startup logic
    return nil
}

func (s *Service) Stop() error {
    // Service shutdown logic
    return nil
}
```

**Service Registration**:

```go
func RegisterServices(cluster *cluster.Cluster) error {
    dhcpService := dhcp.NewService(cluster)
    if err := dhcpService.Start(context.Background()); err != nil {
        return fmt.Errorf("failed to start DHCP service: %w", err)
    }
    
    dnsService := dns.NewService(cluster)
    if err := dnsService.Start(context.Background()); err != nil {
        return fmt.Errorf("failed to start DNS service: %w", err)
    }
    
    return nil
}
```

### API Endpoint Patterns

**REST Endpoint Handler**:

```go
package api

import (
    "encoding/json"
    "net/http"
    "github.com/canonical/microcluster/v2/rest"
)

type MachineHandler struct {
    service MachineService
}

func (h *MachineHandler) Get(r *http.Request) rest.Response {
    id := r.URL.Query().Get("id")
    if id == "" {
        return rest.BadRequest(fmt.Errorf("missing id parameter"))
    }
    
    machine, err := h.service.GetMachine(r.Context(), id)
    if err != nil {
        return rest.InternalError(err)
    }
    
    return rest.SyncResponse(true, machine)
}

func (h *MachineHandler) Post(r *http.Request) rest.Response {
    var req MachineRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        return rest.BadRequest(fmt.Errorf("invalid request: %w", err))
    }
    
    if err := req.Validate(); err != nil {
        return rest.BadRequest(err)
    }
    
    machine, err := h.service.CreateMachine(r.Context(), req)
    if err != nil {
        return rest.InternalError(err)
    }
    
    return rest.SyncResponse(true, machine)
}
```

**Registering API Endpoints**:

```go
func RegisterEndpoints(mux *http.ServeMux, service MachineService) {
    handler := &MachineHandler{service: service}
    
    mux.HandleFunc("/1.0/machines", func(w http.ResponseWriter, r *http.Request) {
        var resp rest.Response
        
        switch r.Method {
        case http.MethodGet:
            resp = handler.Get(r)
        case http.MethodPost:
            resp = handler.Post(r)
        default:
            resp = rest.MethodNotAllowed(fmt.Errorf("method %s not allowed", r.Method))
        }
        
        resp.Render(w)
    })
}
```

### Temporal Workflow Integration

**Workflow Client Setup**:

```go
package temporal

import (
    "go.temporal.io/sdk/client"
)

type WorkflowClient struct {
    client client.Client
}

func NewWorkflowClient(hostPort string) (*WorkflowClient, error) {
    c, err := client.Dial(client.Options{
        HostPort: hostPort,
    })
    if err != nil {
        return nil, fmt.Errorf("failed to create temporal client: %w", err)
    }
    
    return &WorkflowClient{client: c}, nil
}

func (w *WorkflowClient) Close() error {
    w.client.Close()
    return nil
}
```

**Executing Workflows**:

```go
func (w *WorkflowClient) DeployMachine(ctx context.Context, machineID string) error {
    workflowOptions := client.StartWorkflowOptions{
        ID:        fmt.Sprintf("deploy-machine-%s", machineID),
        TaskQueue: "machine-deployment",
    }
    
    we, err := w.client.ExecuteWorkflow(
        ctx,
        workflowOptions,
        "DeployMachineWorkflow",
        machineID,
    )
    if err != nil {
        return fmt.Errorf("failed to start workflow: %w", err)
    }
    
    // Wait for workflow completion
    var result DeploymentResult
    if err := we.Get(ctx, &result); err != nil {
        return fmt.Errorf("workflow failed: %w", err)
    }
    
    return nil
}
```

**Workflow Definition**:

```go
package workflows

import (
    "time"
    "go.temporal.io/sdk/workflow"
)

func DeployMachineWorkflow(ctx workflow.Context, machineID string) (DeploymentResult, error) {
    logger := workflow.GetLogger(ctx)
    logger.Info("Starting machine deployment", "machineID", machineID)
    
    // Activity options
    activityOptions := workflow.ActivityOptions{
        StartToCloseTimeout: 10 * time.Minute,
        RetryPolicy: &workflow.RetryPolicy{
            MaximumAttempts: 3,
        },
    }
    ctx = workflow.WithActivityOptions(ctx, activityOptions)
    
    // Execute activities
    var config MachineConfig
    if err := workflow.ExecuteActivity(ctx, FetchMachineConfig, machineID).Get(ctx, &config); err != nil {
        return DeploymentResult{}, err
    }
    
    var imageResult ImageResult
    if err := workflow.ExecuteActivity(ctx, DownloadImage, config.ImageURL).Get(ctx, &imageResult); err != nil {
        return DeploymentResult{}, err
    }
    
    var deployResult DeploymentResult
    if err := workflow.ExecuteActivity(ctx, DeployImage, machineID, imageResult).Get(ctx, &deployResult); err != nil {
        return DeploymentResult{}, err
    }
    
    logger.Info("Machine deployment completed", "machineID", machineID)
    return deployResult, nil
}
```

### Prometheus Metrics

**Metrics Registration**:

```go
package metrics

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
)

var (
    MachineDeployments = promauto.NewCounterVec(
        prometheus.CounterOpts{
            Name: "maasagent_machine_deployments_total",
            Help: "Total number of machine deployments",
        },
        []string{"status", "zone"},
    )
    
    DeploymentDuration = promauto.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "maasagent_deployment_duration_seconds",
            Help:    "Duration of machine deployments",
            Buckets: prometheus.DefBuckets,
        },
        []string{"zone"},
    )
    
    ActiveMachines = promauto.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "maasagent_active_machines",
            Help: "Number of active machines",
        },
        []string{"status", "zone"},
    )
)

func RecordDeployment(status, zone string) {
    MachineDeployments.WithLabelValues(status, zone).Inc()
}

func ObserveDuration(zone string, duration float64) {
    DeploymentDuration.WithLabelValues(zone).Observe(duration)
}

func SetActiveMachines(status, zone string, count float64) {
    ActiveMachines.WithLabelValues(status, zone).Set(count)
}
```

**Using Metrics in Service**:

```go
func (s *MachineService) DeployMachine(ctx context.Context, machineID string) error {
    start := time.Now()
    
    machine, err := s.getMachine(machineID)
    if err != nil {
        metrics.RecordDeployment("error", machine.Zone)
        return err
    }
    
    if err := s.executeDeploy(ctx, machine); err != nil {
        metrics.RecordDeployment("failed", machine.Zone)
        return err
    }
    
    duration := time.Since(start).Seconds()
    metrics.RecordDeployment("success", machine.Zone)
    metrics.ObserveDuration(machine.Zone, duration)
    
    return nil
}
```

**Exposing Metrics Endpoint**:

```go
import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

func SetupMetricsServer(addr string) *http.Server {
    mux := http.NewServeMux()
    mux.Handle("/metrics", promhttp.Handler())
    
    return &http.Server{
        Addr:    addr,
        Handler: mux,
    }
}
```

### OpenTelemetry Tracing

**Tracer Setup**:

```go
package tracing

import (
    "context"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.4.0"
)

func InitTracer(serviceName, endpoint string) (func(), error) {
    ctx := context.Background()
    
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpoint(endpoint),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, fmt.Errorf("failed to create exporter: %w", err)
    }
    
    res, err := resource.New(ctx,
        resource.WithAttributes(
            semconv.ServiceNameKey.String(serviceName),
        ),
    )
    if err != nil {
        return nil, fmt.Errorf("failed to create resource: %w", err)
    }
    
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter),
        sdktrace.WithResource(res),
    )
    
    otel.SetTracerProvider(tp)
    
    cleanup := func() {
        if err := tp.Shutdown(context.Background()); err != nil {
            log.Printf("Error shutting down tracer provider: %v", err)
        }
    }
    
    return cleanup, nil
}
```

**Using Tracing in Service**:

```go
import (
    "context"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/trace"
)

func (s *MachineService) DeployMachine(ctx context.Context, machineID string) error {
    tracer := otel.Tracer("machine-service")
    ctx, span := tracer.Start(ctx, "DeployMachine")
    defer span.End()
    
    span.SetAttributes(
        attribute.String("machine.id", machineID),
    )
    
    machine, err := s.getMachine(ctx, machineID)
    if err != nil {
        span.RecordError(err)
        return err
    }
    
    span.SetAttributes(
        attribute.String("machine.zone", machine.Zone),
        attribute.String("machine.status", machine.Status),
    )
    
    if err := s.executeDeploy(ctx, machine); err != nil {
        span.RecordError(err)
        return err
    }
    
    span.SetStatus(codes.Ok, "deployment successful")
    return nil
}
```

### DHCP and DNS Service Patterns

**DHCP Service**:

```go
package dhcp

type Service struct {
    cluster *cluster.Cluster
    config  DHCPConfig
}

func NewService(cluster *cluster.Cluster) *Service {
    return &Service{
        cluster: cluster,
        config:  LoadDHCPConfig(),
    }
}

func (s *Service) Start(ctx context.Context) error {
    // Initialize DHCP server
    return s.startDHCPServer()
}

func (s *Service) UpdateLease(mac, ip string, duration time.Duration) error {
    // Update DHCP lease
    return nil
}
```

**DNS Service**:

```go
package dns

type Service struct {
    cluster *cluster.Cluster
    zones   map[string]*Zone
}

func NewService(cluster *cluster.Cluster) *Service {
    return &Service{
        cluster: cluster,
        zones:   make(map[string]*Zone),
    }
}

func (s *Service) AddRecord(zone, name, recordType, value string) error {
    // Add DNS record
    return nil
}
```

## Anti-patterns

### ❌ Not Using Error Wrapping

```go
// NEVER lose error context
if err != nil {
    return err  // Wrong: Lost context about where error occurred
}

// Correct: Wrap with context
if err != nil {
    return fmt.Errorf("failed to deploy machine: %w", err)
}
```

### ❌ Blocking in API Handlers

```go
// NEVER block in API handlers
func (h *Handler) Post(r *http.Request) rest.Response {
    // Wrong: Long-running operation in handler
    time.Sleep(10 * time.Minute)
    return rest.SyncResponse(true, result)
}

// Correct: Use async workflow
func (h *Handler) Post(r *http.Request) rest.Response {
    // Start workflow asynchronously
    workflowID, err := h.startDeployWorkflow(r.Context(), request)
    if err != nil {
        return rest.InternalError(err)
    }
    return rest.SyncResponse(true, map[string]string{"workflow_id": workflowID})
}
```

### ❌ Not Validating Requests

```go
// NEVER skip request validation
func (h *Handler) Post(r *http.Request) rest.Response {
    var req MachineRequest
    json.NewDecoder(r.Body).Decode(&req)
    // Wrong: No validation, no error check
    
    machine, _ := h.service.Create(req)  // Wrong: Ignored error
    return rest.SyncResponse(true, machine)
}

// Correct
func (h *Handler) Post(r *http.Request) rest.Response {
    var req MachineRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        return rest.BadRequest(fmt.Errorf("invalid request: %w", err))
    }
    
    if err := req.Validate(); err != nil {
        return rest.BadRequest(err)
    }
    
    machine, err := h.service.Create(r.Context(), req)
    if err != nil {
        return rest.InternalError(err)
    }
    
    return rest.SyncResponse(true, machine)
}
```

### ❌ Not Using Context Properly

```go
// NEVER ignore context
func ProcessMachine(machineID string) error {
    // Wrong: No context for cancellation
    return doWork(machineID)
}

// Correct: Pass context through
func ProcessMachine(ctx context.Context, machineID string) error {
    return doWork(ctx, machineID)
}
```

### ❌ Forgetting Metrics and Tracing

```go
// NEVER skip observability
func (s *Service) DeployMachine(id string) error {
    // Wrong: No metrics, no tracing
    return s.deploy(id)
}

// Correct: Add metrics and tracing
func (s *Service) DeployMachine(ctx context.Context, id string) error {
    ctx, span := tracer.Start(ctx, "DeployMachine")
    defer span.End()
    
    start := time.Now()
    err := s.deploy(ctx, id)
    
    status := "success"
    if err != nil {
        status = "error"
        span.RecordError(err)
    }
    
    metrics.RecordDeployment(status, s.zone)
    metrics.ObserveDuration(s.zone, time.Since(start).Seconds())
    
    return err
}
```


## MAAS Agent Context

### Technology Stack

- **Microcluster v2**: Distributed cluster framework
- **Temporal**: Workflow orchestration for long-running operations
- **Prometheus**: Metrics collection and monitoring
- **OpenTelemetry**: Distributed tracing
- **Go 1.24.4**: Language version

### Key Services

- **DHCP Service**: Dynamic IP address allocation
- **DNS Service**: Domain name resolution
- **Machine Deployment**: Temporal workflows for deployments
- **Cluster Management**: Microcluster-based coordination

### API Structure

- **Version**: `/1.0/` prefix for all endpoints
- **Responses**: Use `rest.Response` from microcluster
- **Methods**: Handle GET, POST, PUT, DELETE appropriately
- **Errors**: Return appropriate HTTP status codes

## Common Patterns Summary

1. **Service Structure**: Cluster-aware services with Start/Stop methods
2. **API Handlers**: Return `rest.Response`, validate input, handle errors
3. **Workflows**: Use Temporal for long-running operations
4. **Metrics**: Record all significant operations with Prometheus
5. **Tracing**: Add spans for distributed request tracking
6. **Context**: Always pass context for cancellation and tracing
7. **Error Handling**: Wrap errors with context using `%w`

## Configuration

- **Location**: `src/maasagent/`
- **Go Version**: 1.24.4 (check `go.mod`)
- **Dependencies**: Managed via `go.mod`
- **Build**: Standard Go build process
- **Testing**: Go test with testify