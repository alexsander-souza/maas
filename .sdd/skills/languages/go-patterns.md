# Go Patterns

## Purpose

Define idiomatic Go patterns for MAAS Go code (primarily `maasagent` and `host-info`), including error handling, code style, interface design, and Go-specific conventions.

## When to Use

- Writing Go code in `maasagent` or `host-info`
- Implementing microcluster-based services
- Creating Temporal workflows
- Handling errors in Go
- Designing Go interfaces and structs

## Pattern Examples

### Error Handling

**Basic Error Handling**:

```go
// Always check errors
func GetMachine(id int) (*Machine, error) {
    machine, err := repo.FindByID(id)
    if err != nil {
        return nil, fmt.Errorf("failed to get machine %d: %w", id, err)
    }
    return machine, nil
}

// Use %w to wrap errors for error chain inspection
func ProcessMachine(id int) error {
    machine, err := GetMachine(id)
    if err != nil {
        return fmt.Errorf("processing failed: %w", err)
    }
    
    if err := machine.Deploy(); err != nil {
        return fmt.Errorf("deployment failed for machine %d: %w", id, err)
    }
    
    return nil
}
```

**Custom Errors and Sentinel Errors**:

```go
// Sentinel errors for common cases
var (
    ErrMachineNotReady = errors.New("machine is not ready")
    ErrNotFound        = errors.New("not found")
)

// Custom error type for detailed context
type NotFoundError struct {
    Resource string
    ID       int
}

func (e *NotFoundError) Error() string {
    return fmt.Sprintf("%s with ID %d not found", e.Resource, e.ID)
}

// Usage
func GetMachine(id int) (*Machine, error) {
    machine, err := repo.FindByID(id)
    if err != nil {
        if errors.Is(err, sql.ErrNoRows) {
            return nil, &NotFoundError{Resource: "machine", ID: id}
        }
        return nil, fmt.Errorf("database error: %w", err)
    }
    return machine, nil
}

// Checking errors
func HandleMachine(id int) error {
    machine, err := GetMachine(id)
    if err != nil {
        var notFound *NotFoundError
        if errors.As(err, &notFound) {
            return fmt.Errorf("resource missing: %w", err)
        }
        return err
    }
    
    if machine.Status != "ready" {
        return ErrMachineNotReady
    }
    return nil
}
```

### Struct Design

**Basic Struct**:

```go
// Exported struct with exported fields
type Machine struct {
    ID       int
    Hostname string
    ZoneID   int
    CPUCount int
    Memory   int64 // bytes
    Status   string
}

// Constructor function
func NewMachine(hostname string, zoneID int) *Machine {
    return &Machine{
        Hostname: hostname,
        ZoneID:   zoneID,
        Status:   "new",
    }
}
```

**Struct with Methods and Validation**:

```go
type MachineRequest struct {
    Hostname string `json:"hostname"`
    ZoneID   int    `json:"zone_id"`
}

func (r *MachineRequest) Validate() error {
    if r.Hostname == "" {
        return errors.New("hostname is required")
    }
    if r.ZoneID <= 0 {
        return errors.New("invalid zone_id")
    }
    return nil
}

type Machine struct {
    ID       int
    Hostname string
    Status   string
}

// Value receiver for read-only methods
func (m Machine) IsReady() bool {
    return m.Status == "ready"
}

// Pointer receiver for methods that modify
func (m *Machine) SetStatus(status string) error {
    if status == "" {
        return errors.New("status cannot be empty")
    }
    m.Status = status
    return nil
}
```

### Interface Design

```go
// Small, focused interfaces
type MachineReader interface {
    GetByID(id int) (*Machine, error)
    List(filters FilterSpec) ([]*Machine, error)
}

type MachineRepository interface {
    MachineReader
    Create(machine *Machine) error
    Update(machine *Machine) error
}

// Accept interfaces, return structs
func ProcessMachines(repo MachineReader) error {
    machines, err := repo.List(FilterSpec{})
    if err != nil {
        return err
    }
    for _, machine := range machines {
        // Process
    }
    return nil
}

func NewMachineService(repo MachineRepository) *MachineService {
    return &MachineService{repo: repo}
}
```

### Concurrency Patterns

```go
import (
    "context"
    "sync"
)

// WaitGroup with error handling
func ProcessBatch(machines []*Machine) error {
    var wg sync.WaitGroup
    errChan := make(chan error, len(machines))
    
    for _, machine := range machines {
        wg.Add(1)
        machine := machine // Capture loop variable
        
        go func() {
            defer wg.Done()
            if err := processMachine(machine); err != nil {
                errChan <- err
            }
        }()
    }
    
    wg.Wait()
    close(errChan)
    
    for err := range errChan {
        if err != nil {
            return err
        }
    }
    return nil
}

// Context for cancellation
func ProcessWithTimeout(ctx context.Context, machineID int) error {
    ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
    defer cancel()
    
    resultChan := make(chan error, 1)
    go func() {
        resultChan <- doLongRunningWork(machineID)
    }()
    
    select {
    case err := <-resultChan:
        return err
    case <-ctx.Done():
        return fmt.Errorf("timeout: %w", ctx.Err())
    }
}
```

### Idiomatic Go Patterns

```go
// Prefer nil slice for zero-length
func GetMachines(filter FilterSpec) ([]*Machine, error) {
    var machines []*Machine
    if noResults {
        return nil, nil
    }
    return machines, nil
}

// Defer for cleanup
func ProcessFile(filename string) error {
    file, err := os.Open(filename)
    if err != nil {
        return err
    }
    defer file.Close() // Always closes
    // Process file
    return nil
}

// Range over collections
for _, machine := range machines {
    process(machine)
}

for key, value := range machineMap {
    process(key, value)
}
```

### Code Organization

```go
// Package machine provides machine management functionality.
package machine

import (
    "errors"
    "fmt"
)

const (
    StatusNew   = "new"
    StatusReady = "ready"
)

var ErrNotFound = errors.New("machine not found")

type Machine struct {
    ID       int    // Exported
    hostname string // Unexported
}

func NewMachine() *Machine {
    return &Machine{}
}
```

For complete testing patterns, see [go-testing.md](go-testing.md).

## Anti-patterns

### ❌ Ignoring Errors

```go
// NEVER ignore errors
machine, _ := GetMachine(id) // Wrong: Silent failure

// Correct
machine, err := GetMachine(id)
if err != nil {
    return fmt.Errorf("failed to get machine: %w", err)
}
```

### ❌ Panic in Library Code

```go
// NEVER panic in library/service code
func GetMachine(id int) *Machine {
    machine, err := repo.FindByID(id)
    if err != nil {
        panic(err) // Wrong: Let caller handle errors
    }
    return machine
}

// Correct: Return error
func GetMachine(id int) (*Machine, error) {
    machine, err := repo.FindByID(id)
    if err != nil {
        return nil, err
    }
    return machine, nil
}
```

### ❌ Not Using fmt.Errorf with %w

```go
// NEVER lose error context
if err != nil {
    return errors.New("failed to process") // Wrong: Lost original error
}

// Correct: Wrap error
if err != nil {
    return fmt.Errorf("failed to process: %w", err)
}
```

### ❌ Using Pointer to Interface

```go
// NEVER use pointer to interface
func Process(repo *MachineRepository) error { // Wrong: Interface already a reference
    // ...
}

// Correct
func Process(repo MachineRepository) error {
    // ...
}
```

### ❌ Not Capturing Loop Variables

```go
// NEVER use loop variable directly in goroutine (Go < 1.22)
for _, machine := range machines {
    go func() {
        process(machine) // Wrong: All goroutines see last value
    }()
}

// Correct: Capture loop variable
for _, machine := range machines {
    machine := machine // Create new variable
    go func() {
        process(machine)
    }()
}
```

### ❌ Breaking Channel Before Draining

```go
// NEVER close channel with active senders
close(ch)
// goroutine writes to ch <- value // Panic!

// Correct: Coordinate with senders
```

### ❌ Not Closing Resources

```go
// NEVER forget to close resources
func ReadFile(name string) error {
    file, err := os.Open(name)
    if err != nil {
        return err
    }
    // Wrong: No defer close
    
    // If error occurs here, file leaks
    data, err := io.ReadAll(file)
    return err
}

// Correct
func ReadFile(name string) error {
    file, err := os.Open(name)
    if err != nil {
        return err
    }
    defer file.Close() // Always closes
    
    data, err := io.ReadAll(file)
    // Use data
    return err
}
```



## MAAS-Specific Go Context

### Projects

- **maasagent**: Go 1.24.4, microcluster-based agent
- **host-info**: Go 1.18, host information collection

### Key Technologies

- **Microcluster**: Distributed cluster framework
- **Temporal**: Workflow orchestration
- **Prometheus**: Metrics collection
- **OpenTelemetry**: Distributed tracing
- **Testify**: Testing assertions and mocks

### Reference

For complete Go style guidelines, see [`go-style-guide.md`](../../go-style-guide.md) in the project root.

## Code Style

- **Formatting**: Use `gofmt` or `go fmt` (standard Go formatting)
- **Imports**: Group standard library, external, and internal packages
- **Line length**: No strict limit, but prefer readability
- **Naming**:
  - Exported: `MachineService`, `GetMachine`
  - Unexported: `internalCache`, `parseConfig`
  - Interfaces: Often `-er` suffix (`Reader`, `Writer`, `Processor`)
  - Acronyms: `ID`, `URL`, `HTTP` (all caps when exported)

## Common Patterns Summary

1. **Error Handling**: Always check errors, wrap with context using `%w`
2. **Interfaces**: Accept interfaces, return structs
3. **Concurrency**: Use goroutines with proper synchronization
4. **Resources**: Always defer cleanup (close, unlock, rollback)
5. **Nil**: Prefer nil slice/map over empty when appropriate
6. **Context**: Pass `context.Context` for cancellation/timeout
7. **Testing**: Table-driven tests with clear cases

## Configuration

- **Go Version**: Check `go.mod` in project root
  - maasagent: Go 1.24.4
  - host-info: Go 1.18
- **Modules**: Dependency management via `go.mod`
- **Build**: Standard `go build`, `go test`
- **Format**: `gofmt` or `go fmt`
- **Vet**: `go vet` for static analysis