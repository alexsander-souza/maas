# host-info Subsystem

## Purpose

Standalone Go utility for collecting and reporting host hardware information. This tool detects and reports detailed hardware specifications including CPU, memory, storage, and network interfaces for MAAS machine commissioning and inventory management.

**Status**: Active - stable utility for hardware detection.

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

This is a self-contained executable with minimal dependencies:
- No external service dependencies
- Runs directly on target machines
- Outputs structured data (JSON)
- Lightweight and portable

### Minimal Dependencies

Deliberately keeps dependencies minimal:
- Only essential libraries
- Standard library preferred
- LXD shared libraries for hardware detection
- No heavy frameworks

### Cross-Platform Considerations

Must work across different architectures and systems:
- x86_64 (amd64)
- ARM64 (arm64)
- PowerPC (ppc64el)
- s390x (IBM Z)

## Key Patterns

### Hardware Detection

Detects various hardware components:

```go
package main

import (
    "encoding/json"
    "fmt"
    "github.com/lxc/lxd/shared/osarch"
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

type NICInfo struct {
    Name       string `json:"name"`
    MACAddress string `json:"mac_address"`
    Speed      int    `json:"speed_mbps"`
    Vendor     string `json:"vendor"`
    Product    string `json:"product"`
}

type SystemInfo struct {
    Manufacturer string `json:"manufacturer"`
    Product      string `json:"product"`
    Serial       string `json:"serial"`
    UUID         string `json:"uuid"`
    Firmware     string `json:"firmware"`
}

func collectHardwareInfo() (*HardwareInfo, error) {
    info := &HardwareInfo{}
    
    // Collect CPU information
    cpuInfo, err := collectCPUInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect CPU info: %w", err)
    }
    info.CPU = cpuInfo
    
    // Collect memory information
    memInfo, err := collectMemoryInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect memory info: %w", err)
    }
    info.Memory = memInfo
    
    // Collect storage information
    storageInfo, err := collectStorageInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect storage info: %w", err)
    }
    info.Storage = storageInfo
    
    // Collect network information
    networkInfo, err := collectNetworkInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect network info: %w", err)
    }
    info.Network = networkInfo
    
    // Collect system information
    systemInfo, err := collectSystemInfo()
    if err != nil {
        return nil, fmt.Errorf("failed to collect system info: %w", err)
    }
    info.System = systemInfo
    
    return info, nil
}

func main() {
    info, err := collectHardwareInfo()
    if err != nil {
        fmt.Fprintf(os.Stderr, "Error collecting hardware info: %v\n", err)
        os.Exit(1)
    }
    
    // Output as JSON
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

### Error Handling

Graceful error handling for missing hardware:

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

Reads information from /sys and /proc:

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