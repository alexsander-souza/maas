# Go Testing

## Purpose

Define testing patterns for MAAS Go code using Go's testing package and testify, including table-driven tests, test organization, mocking strategies, and idiomatic test design.

## When to Use

- Writing tests for Go code in `maasagent` or `host-info`
- Creating table-driven tests for multiple test cases
- Mocking interfaces and dependencies
- Testing concurrent code
- Organizing test suites

## Pattern Examples

### Basic Test Structure

```go
package machine

import (
    "testing"
)

func TestGetMachineByID(t *testing.T) {
    repo := NewInMemoryRepository()
    machine := &Machine{ID: 1, Hostname: "test-node"}
    repo.Store(machine)
    
    result, err := repo.GetByID(1)
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    
    if result.ID != 1 {
        t.Errorf("expected ID 1, got %d", result.ID)
    }
    if result.Hostname != "test-node" {
        t.Errorf("expected hostname 'test-node', got %s", result.Hostname)
    }
}
```

### Table-Driven Tests

**Basic Table-Driven Test**:

```go
func TestValidateHostname(t *testing.T) {
    tests := []struct {
        name     string
        hostname string
        wantErr  bool
    }{
        {
            name:     "valid hostname",
            hostname: "valid-hostname",
            wantErr:  false,
        },
        {
            name:     "valid with dots",
            hostname: "valid.hostname.com",
            wantErr:  false,
        },
        {
            name:     "empty hostname",
            hostname: "",
            wantErr:  true,
        },
        {
            name:     "invalid underscore",
            hostname: "invalid_hostname",
            wantErr:  true,
        },
        {
            name:     "too long",
            hostname: string(make([]byte, 256)),
            wantErr:  true,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := ValidateHostname(tt.hostname)
            if (err != nil) != tt.wantErr {
                t.Errorf("ValidateHostname() error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}
```

**Table-Driven Test with Expected Values**:

```go
func TestMachineStatus(t *testing.T) {
    tests := []struct {
        name   string
        status string
        ready  bool
        valid  bool
    }{
        {"ready state", "ready", true, true},
        {"allocated state", "allocated", false, true},
        {"deployed state", "deployed", false, true},
        {"broken state", "broken", false, true},
        {"invalid state", "invalid", false, false},
        {"empty state", "", false, false},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            machine := &Machine{Status: tt.status}
            
            if machine.IsReady() != tt.ready {
                t.Errorf("IsReady() = %v, want %v", machine.IsReady(), tt.ready)
            }
            
            if machine.IsValidStatus() != tt.valid {
                t.Errorf("IsValidStatus() = %v, want %v", machine.IsValidStatus(), tt.valid)
            }
        })
    }
}
```

**Table-Driven Test with Complex Input/Output**:

```go
func TestProcessMachineRequest(t *testing.T) {
    tests := []struct {
        name    string
        request MachineRequest
        want    *Machine
        wantErr error
    }{
        {
            name: "valid request",
            request: MachineRequest{
                Hostname: "node1",
                ZoneID:   1,
                CPUCount: 4,
            },
            want: &Machine{
                Hostname: "node1",
                ZoneID:   1,
                CPUCount: 4,
                Status:   "new",
            },
            wantErr: nil,
        },
        {
            name: "invalid zone",
            request: MachineRequest{
                Hostname: "node2",
                ZoneID:   -1,
                CPUCount: 2,
            },
            want:    nil,
            wantErr: ErrInvalidZone,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := ProcessMachineRequest(tt.request)
            
            if !errors.Is(err, tt.wantErr) {
                t.Errorf("error = %v, wantErr %v", err, tt.wantErr)
                return
            }
            
            if tt.want != nil && got != nil {
                if got.Hostname != tt.want.Hostname {
                    t.Errorf("Hostname = %v, want %v", got.Hostname, tt.want.Hostname)
                }
                if got.ZoneID != tt.want.ZoneID {
                    t.Errorf("ZoneID = %v, want %v", got.ZoneID, tt.want.ZoneID)
                }
            }
        })
    }
}
```

### Using Testify

**Assertions**:

```go
import (
    "testing"
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)

func TestMachineCreation(t *testing.T) {
    machine, err := CreateMachine("node1", 1)
    
    // require stops test on failure
    require.NoError(t, err, "should not error on valid input")
    require.NotNil(t, machine, "should return machine")
    
    // assert continues test on failure
    assert.Equal(t, "node1", machine.Hostname)
    assert.Equal(t, 1, machine.ZoneID)
    assert.Equal(t, "new", machine.Status)
}

func TestMachineValidation(t *testing.T) {
    machine := &Machine{Hostname: "", ZoneID: 1}
    err := machine.Validate()
    
    assert.Error(t, err, "should error on empty hostname")
    assert.Contains(t, err.Error(), "hostname")
}
```

**Table-Driven Tests with Testify**:

```go
func TestMachineOperations(t *testing.T) {
    tests := []struct {
        name        string
        machineID   int
        expectError bool
        errorMsg    string
    }{
        {"valid machine", 1, false, ""},
        {"invalid machine", 999, true, "not found"},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            machine, err := GetMachine(tt.machineID)
            
            if tt.expectError {
                assert.Error(t, err)
                assert.Contains(t, err.Error(), tt.errorMsg)
                assert.Nil(t, machine)
            } else {
                assert.NoError(t, err)
                assert.NotNil(t, machine)
                assert.Equal(t, tt.machineID, machine.ID)
            }
        })
    }
}
```

### Mocking Interfaces

**Manual Mock**:

```go
// Mock implementation of MachineRepository
type MockMachineRepository struct {
    machines map[int]*Machine
    err      error
}

func NewMockMachineRepository() *MockMachineRepository {
    return &MockMachineRepository{
        machines: make(map[int]*Machine),
    }
}

func (m *MockMachineRepository) GetByID(id int) (*Machine, error) {
    if m.err != nil {
        return nil, m.err
    }
    machine, exists := m.machines[id]
    if !exists {
        return nil, ErrNotFound
    }
    return machine, nil
}

func (m *MockMachineRepository) SetError(err error) {
    m.err = err
}

// Test using mock
func TestMachineService(t *testing.T) {
    repo := NewMockMachineRepository()
    repo.machines[1] = &Machine{ID: 1, Hostname: "test"}
    
    service := NewMachineService(repo)
    machine, err := service.GetMachine(1)
    
    assert.NoError(t, err)
    assert.Equal(t, "test", machine.Hostname)
}
```

**Testify Mock**:

```go
import (
    "github.com/stretchr/testify/mock"
)

type MockRepository struct {
    mock.Mock
}

func (m *MockRepository) GetByID(id int) (*Machine, error) {
    args := m.Called(id)
    if args.Get(0) == nil {
        return nil, args.Error(1)
    }
    return args.Get(0).(*Machine), args.Error(1)
}

func (m *MockRepository) Create(machine *Machine) error {
    args := m.Called(machine)
    return args.Error(0)
}

// Test using testify mock
func TestMachineServiceWithMock(t *testing.T) {
    mockRepo := new(MockRepository)
    expectedMachine := &Machine{ID: 1, Hostname: "test"}
    
    mockRepo.On("GetByID", 1).Return(expectedMachine, nil)
    
    service := NewMachineService(mockRepo)
    machine, err := service.GetMachine(1)
    
    assert.NoError(t, err)
    assert.Equal(t, expectedMachine, machine)
    mockRepo.AssertExpectations(t)
}
```

### Test Fixtures and Setup

**Test Setup and Teardown**:

```go
func TestMachineRepository(t *testing.T) {
    // Setup
    db := setupTestDatabase(t)
    defer db.Close() // Teardown
    
    repo := NewMachineRepository(db)
    
    // Test
    machine, err := repo.GetByID(1)
    assert.NoError(t, err)
}

func setupTestDatabase(t *testing.T) *sql.DB {
    t.Helper() // Marks this as a helper function
    
    db, err := sql.Open("sqlite3", ":memory:")
    if err != nil {
        t.Fatalf("failed to open database: %v", err)
    }
    
    // Run migrations
    if err := runMigrations(db); err != nil {
        t.Fatalf("failed to run migrations: %v", err)
    }
    
    return db
}
```

**Subtests with Shared Setup**:

```go
func TestMachineOperations(t *testing.T) {
    // Shared setup
    db := setupTestDatabase(t)
    defer db.Close()
    repo := NewMachineRepository(db)
    
    t.Run("Create", func(t *testing.T) {
        machine := &Machine{Hostname: "test1", ZoneID: 1}
        err := repo.Create(machine)
        assert.NoError(t, err)
        assert.NotZero(t, machine.ID)
    })
    
    t.Run("GetByID", func(t *testing.T) {
        machine, err := repo.GetByID(1)
        assert.NoError(t, err)
        assert.Equal(t, "test1", machine.Hostname)
    })
    
    t.Run("Update", func(t *testing.T) {
        machine := &Machine{ID: 1, Hostname: "updated", ZoneID: 1}
        err := repo.Update(machine)
        assert.NoError(t, err)
    })
}
```

### Testing Errors

```go
func TestMachineErrors(t *testing.T) {
    tests := []struct {
        name      string
        machineID int
        wantErr   error
    }{
        {"not found", 999, ErrNotFound},
        {"invalid ID", -1, ErrInvalidID},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            _, err := GetMachine(tt.machineID)
            assert.Error(t, err)
            assert.True(t, errors.Is(err, tt.wantErr))
        })
    }
}

func TestCustomErrorType(t *testing.T) {
    _, err := GetMachine(999)
    
    var notFoundErr *NotFoundError
    if assert.True(t, errors.As(err, &notFoundErr)) {
        assert.Equal(t, "machine", notFoundErr.Resource)
        assert.Equal(t, 999, notFoundErr.ID)
    }
}
```

### Testing Concurrent Code

```go
func TestConcurrentAccess(t *testing.T) {
    cache := NewCache()
    const goroutines = 100
    
    var wg sync.WaitGroup
    wg.Add(goroutines)
    
    for i := 0; i < goroutines; i++ {
        i := i
        go func() {
            defer wg.Done()
            cache.Set(i, &Machine{ID: i})
        }()
    }
    
    wg.Wait()
    
    assert.Equal(t, goroutines, cache.Size())
}

func TestChannelProcessing(t *testing.T) {
    input := make(chan *Machine, 10)
    output := make(chan *Machine, 10)
    
    go ProcessMachines(input, output)
    
    // Send test data
    testMachine := &Machine{ID: 1, Hostname: "test"}
    input <- testMachine
    close(input)
    
    // Verify output
    result := <-output
    assert.Equal(t, testMachine.ID, result.ID)
}
```

### Benchmark Tests

```go
func BenchmarkMachineCreation(b *testing.B) {
    for i := 0; i < b.N; i++ {
        _ = NewMachine("test", 1)
    }
}

func BenchmarkMachineValidation(b *testing.B) {
    machine := &Machine{Hostname: "test-node", ZoneID: 1}
    
    b.ResetTimer() // Reset timer after setup
    for i := 0; i < b.N; i++ {
        _ = machine.Validate()
    }
}

// Table-driven benchmark
func BenchmarkMachineOperations(b *testing.B) {
    benchmarks := []struct {
        name string
        op   func()
    }{
        {"Create", func() { NewMachine("test", 1) }},
        {"Validate", func() { (&Machine{Hostname: "test", ZoneID: 1}).Validate() }},
    }
    
    for _, bm := range benchmarks {
        b.Run(bm.name, func(b *testing.B) {
            for i := 0; i < b.N; i++ {
                bm.op()
            }
        })
    }
}
```

### Test Helpers

```go
// Helper function to create test machine
func createTestMachine(t *testing.T, hostname string, zoneID int) *Machine {
    t.Helper() // Marks this as helper for better error reporting
    
    machine := &Machine{
        Hostname: hostname,
        ZoneID:   zoneID,
        Status:   "new",
    }
    
    if err := machine.Validate(); err != nil {
        t.Fatalf("failed to create test machine: %v", err)
    }
    
    return machine
}

func TestWithHelper(t *testing.T) {
    machine := createTestMachine(t, "test-node", 1)
    assert.Equal(t, "test-node", machine.Hostname)
}
```

## Anti-patterns

### ❌ Not Using Table-Driven Tests for Multiple Cases

```go
// NEVER write repetitive tests
func TestValidHostname1(t *testing.T) {
    err := ValidateHostname("valid")
    assert.NoError(t, err)
}

func TestValidHostname2(t *testing.T) {
    err := ValidateHostname("also-valid")
    assert.NoError(t, err)
}

func TestInvalidHostname1(t *testing.T) {
    err := ValidateHostname("")
    assert.Error(t, err)
}

// Correct: Use table-driven test
func TestValidateHostname(t *testing.T) {
    tests := []struct {
        name     string
        hostname string
        wantErr  bool
    }{
        {"valid", "valid", false},
        {"also valid", "also-valid", false},
        {"empty", "", true},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := ValidateHostname(tt.hostname)
            if (err != nil) != tt.wantErr {
                t.Errorf("error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}
```

### ❌ Not Using t.Run for Subtests

```go
// NEVER skip t.Run
for _, test := range tests {
    // Wrong: No t.Run, errors don't show which case failed
    err := Process(test.input)
    assert.NoError(t, err)
}

// Correct: Use t.Run
for _, tt := range tests {
    t.Run(tt.name, func(t *testing.T) {
        err := Process(tt.input)
        assert.NoError(t, err)
    })
}
```

### ❌ Not Using t.Helper()

```go
// NEVER omit t.Helper() in test helper functions
func setupTest(t *testing.T) *Machine {
    // Wrong: Errors will point to this line, not the test
    machine := &Machine{}
    if err := machine.Validate(); err != nil {
        t.Fatalf("setup failed: %v", err)
    }
    return machine
}

// Correct: Mark as helper
func setupTest(t *testing.T) *Machine {
    t.Helper() // Errors now point to the calling test
    machine := &Machine{}
    if err := machine.Validate(); err != nil {
        t.Fatalf("setup failed: %v", err)
    }
    return machine
}
```

### ❌ Testing Implementation Instead of Behavior

```go
// NEVER test internal implementation
func TestMachineInternalCache(t *testing.T) {
    machine := NewMachine("test", 1)
    // Wrong: Testing internal cache implementation
    assert.NotNil(t, machine.internalCache)
}

// Correct: Test behavior
func TestMachineGetCached(t *testing.T) {
    machine := NewMachine("test", 1)
    // Test observable behavior
    result := machine.GetSomething()
    assert.Equal(t, expectedValue, result)
}
```

### ❌ Not Cleaning Up Resources

```go
// NEVER leave resources open
func TestDatabaseOperation(t *testing.T) {
    db, _ := sql.Open("sqlite3", ":memory:")
    // Wrong: No cleanup
    
    repo := NewRepository(db)
    // test...
}

// Correct: Always defer cleanup
func TestDatabaseOperation(t *testing.T) {
    db, err := sql.Open("sqlite3", ":memory:")
    require.NoError(t, err)
    defer db.Close()
    
    repo := NewRepository(db)
    // test...
}
```

### ❌ Using t.Fatal in Goroutines

```go
// NEVER use t.Fatal/t.Fatalf in goroutines
func TestConcurrent(t *testing.T) {
    go func() {
        if err := doSomething(); err != nil {
            t.Fatalf("error: %v", err) // Wrong: Unsafe in goroutine
        }
    }()
}

// Correct: Use error channel or t.Error
func TestConcurrent(t *testing.T) {
    errChan := make(chan error, 1)
    go func() {
        errChan <- doSomething()
    }()
    
    if err := <-errChan; err != nil {
        t.Errorf("error: %v", err)
    }
}
```

### ❌ Ignoring Test Failures

```go
// NEVER ignore or suppress test failures
func TestSomething(t *testing.T) {
    result, err := DoSomething()
    _ = err // Wrong: Ignoring error
    
    // Or worse:
    if err != nil {
        return // Wrong: Silently passing test
    }
}

// Correct: Check all errors
func TestSomething(t *testing.T) {
    result, err := DoSomething()
    require.NoError(t, err)
    assert.NotNil(t, result)
}
```

## Related Skills

- **Go Patterns**: [go-patterns.md](go-patterns.md) - Code patterns being tested
- **Microcluster**: [microcluster-patterns.md](microcluster-patterns.md) - Testing microcluster code
- **Test Quality**: [../techniques/test-code-quality.md](../techniques/test-code-quality.md) - Writing clean tests
- **Testing Suite**: [../compositions/testing-suite.md](../compositions/testing-suite.md) - Complete testing workflow

## Common Test Patterns Summary

1. **Table-Driven**: Use for multiple test cases
2. **t.Run**: Always use for subtests
3. **t.Helper()**: Mark helper functions
4. **Testify**: Use assert/require for cleaner assertions
5. **Mock**: Mock interfaces, not concrete types
6. **Setup/Teardown**: Use defer for cleanup
7. **Concurrent**: Test with goroutines and channels
8. **Benchmarks**: Use for performance testing

## Running Tests

```bash
# Run all tests
go test ./...

# Run specific test
go test -run TestMachineSomething

# Run with verbose output
go test -v ./...

# Run with coverage
go test -cover ./...
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out

# Run benchmarks
go test -bench=. ./...
go test -bench=BenchmarkMachine -benchmem

# Run tests in parallel
go test -parallel 4 ./...
```

## Test Organization

```
package/
├── machine.go
├── machine_test.go          # Tests for machine.go
├── repository.go
├── repository_test.go       # Tests for repository.go
├── testdata/                # Test fixtures and data files
│   ├── valid_config.json
│   └── invalid_config.json
└── testing.go               # Test utilities (not _test.go)
```

## MAAS-Specific Context

- **Testify**: Primary assertion library
- **Mock**: Use testify/mock for interface mocking
- **Integration**: Test with real microcluster when needed
- **Unit**: Prefer unit tests over integration tests
- **Coverage**: Aim for meaningful coverage, not 100%

## Configuration

- **Test files**: `*_test.go` suffix
- **Test functions**: `func TestXxx(t *testing.T)`
- **Benchmark functions**: `func BenchmarkXxx(b *testing.B)`
- **Example functions**: `func ExampleXxx()`
