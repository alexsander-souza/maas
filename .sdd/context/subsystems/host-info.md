# host-info Subsystem

## Purpose

Standalone Go utility for collecting and reporting host hardware information. Detects and reports detailed hardware specifications including CPU, memory, storage, and network interfaces for MAAS machine commissioning and inventory management.

## Location

`src/host-info`

## Technology Stack

### Core Technologies
- **Go**: 1.18+
- **LXD Libraries**: Hardware detection utilities
- **Standard Library**: Minimal external dependencies

### Key Libraries
- `github.com/lxc/lxd/shared`: Hardware detection utilities
- Standard Go libraries for system information

## Architectural Constraints

### Standalone Utility
Self-contained executable with minimal dependencies:
- No external service dependencies
- Runs directly on target machines
- Outputs structured data (JSON)
- Lightweight and portable

### Minimal Dependencies
Deliberately keeps dependencies minimal - only essential libraries, standard library preferred.

### Cross-Platform Support
Must work across different architectures: x86_64, ARM64, PowerPC (ppc64el), s390x (IBM Z).

## Key Patterns

### Hardware Detection

Detects various hardware components:

```go
package main

import (
    "encoding/json"
    "fmt"
    "os"
)

type HardwareInfo struct {
    CPU      CPUInfo      `json:"cpu"`
    Memory   MemoryInfo   `json:"memory"`
    Storage  []DiskInfo   `json:"storage"`
    Network  []NICInfo    `json:"network"`
    System   SystemInfo   `json:"system"`
}

type CPUInfo struct {
    Architecture string `json:"architecture"`
    Model        string `json:"model"`
    Cores        int    `json:"cores"`
    Threads      int    `json:"threads"`
    Frequency    int    `json:"frequency_mhz"`
}

type MemoryInfo struct {
    Total     uint64 `json:"total_bytes"`
    Available uint64 `json:"available_bytes"`
}

type DiskInfo struct {
    Name       string `json:"name"`
    Size       uint64 `json:"size_bytes"`
    Type       string `json:"type"`
    Model      string `json:"model"`
    Serial     string `json:"serial"`
    Removable  bool   `json:"removable"`
}

func collectHardwareInfo() (*HardwareInfo, error) {
    info := &HardwareInfo{}
    
    cpuInfo, err := collectCPUInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect CPU info: %w", err)
    }
    info.CPU = cpuInfo
    
    memInfo, err := collectMemoryInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect memory info: %w", err)
    }
    info.Memory = memInfo
    
    storageInfo, err := collectStorageInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect storage info: %w", err)
    }
    info.Storage = storageInfo
    
    return info, nil
}

func main() {
    info, err := collectHardwareInfo()
    if err != nil {
        fmt.Fprintf(os.Stderr, "Error collecting hardware info: %v\n", err)
        os.Exit(1)
    }
    
    output, err := json.MarshalIndent(info, "", "  ")
    if err != nil {
        fmt.Fprintf(os.Stderr, "Error encoding JSON: %v\n", err)
        os.Exit(1)
    }
    
    fmt.Println(string(output))
}
```

### Structured Reporting

Outputs information in structured JSON format:

```go
func outputHardwareInfo(info *HardwareInfo) error {
    encoder := json.NewEncoder(os.Stdout)
    encoder.SetIndent("", "  ")
    
    if err := encoder.Encode(info); err != nil {
        return fmt.Errorf("failed to encode output: %w", err)
    }
    
    return nil
}
```

### Graceful Error Handling

Handle missing hardware gracefully:

```go
func collectDiskInfo(path string) (*DiskInfo, error) {
    info := &DiskInfo{Name: path}
    
    // Try to get disk information
    if size, err := getDiskSize(path); err == nil {
        info.Size = size
    } else {
        // Log warning but continue
        log.Printf("Warning: Could not get size for disk %s: %v", path, err)
    }
    
    if model, err := getDiskModel(path); err == nil {
        info.Model = model
    }
    
    return info, nil
}
```

### System File Parsing

Reads information from `/sys` and `/proc`:

```go
func readSysFile(path string) (string, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return "", err
    }
    return strings.TrimSpace(string(data)), nil
}

func getCPUModel() (string, error) {
    data, err := os.ReadFile("/proc/cpuinfo")
    if err != nil {
        return "", err
    }
    
    scanner := bufio.NewScanner(bytes.NewReader(data))
    for scanner.Scan() {
        line := scanner.Text()
        if strings.HasPrefix(line, "model name") {
            parts := strings.SplitN(line, ":", 2)
            if len(parts) == 2 {
                return strings.TrimSpace(parts[1]), nil
            }
        }
    }
    
    return "", fmt.Errorf("model name not found in /proc/cpuinfo")
}
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Unit Tests
Test hardware detection functions in isolation:

```go
func TestCollectCPUInfo(t *testing.T) {
    info, err := collectCPUInfo()
    if err != nil {
        t.Fatalf("Failed to collect CPU info: %v", err)
    }
    
    if info.Cores <= 0 {
        t.Errorf("Expected positive core count, got %d", info.Cores)
    }
}
```

### Integration Tests
Test against real hardware or mock filesystems for `/sys` and `/proc` parsing.

## Integration Points

### MAAS Commissioning Scripts
- **Purpose**: Invoked during machine commissioning to gather hardware inventory
- **Interface**: Executed as subprocess, output parsed from stdout
- **Key Considerations**: Must be statically compiled for portability

### Region Controller
- **Purpose**: Sends collected data to MAAS for storage and analysis
- **Interface**: JSON output consumed by commissioning scripts
- **Key Considerations**: Schema stability across versions

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Blocking on Missing Hardware

```go
// WRONG: Fail if optional hardware missing
func collectAllInfo() (*HardwareInfo, error) {
    gpu, err := detectGPU()
    if err != nil {
        return nil, err  // Blocks on missing GPU
    }
    return info, nil
}

// Correct: Continue with warnings
func collectAllInfo() (*HardwareInfo, error) {
    gpu, err := detectGPU()
    if err != nil {
        log.Printf("Warning: GPU detection failed: %v", err)
    }
    return info, nil
}
```

### Platform-Specific Assumptions

```go
// WRONG: Assumes x86_64
cpuFile := "/proc/cpuinfo"
// Parses "model name" field (x86 only)

// Correct: Handle architecture differences
func getCPUInfo() string {
    switch runtime.GOARCH {
    case "amd64":
        return parseX86CPUInfo()
    case "arm64":
        return parseARMCPUInfo()
    default:
        return parseGenericCPUInfo()
    }
}
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Read-Only Access
Only reads system information - no privileged operations or modifications to system state.

### No Sensitive Data
Avoid collecting or exposing sensitive information like serial numbers unless required for hardware identification.

## Performance Considerations

### Fast Execution
Must complete quickly during commissioning:
- Parallel hardware detection where possible
- Timeout on slow operations
- Skip non-essential hardware if time-constrained

## Additional Resources

- LXD Hardware Detection: https://github.com/lxc/lxd
- Go System Programming: https://golang.org/pkg/os/
- Linux `/sys` and `/proc` Documentation