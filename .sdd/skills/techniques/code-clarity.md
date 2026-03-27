# Code Clarity

## Purpose

Define practices for writing clear, self-documenting code that is easy to read, understand, and maintain without relying on excessive comments or complex constructs.

## When to Use

- Writing any new code
- Refactoring existing code
- Reviewing code for readability
- Simplifying complex logic
- Naming variables, functions, and classes
- Structuring modules and packages

## Pattern Examples

### Descriptive Naming Over Comments

**Poor Naming with Comments**:

```python
# Check if the machine is ready for deployment
def check(m):
    # Get the status
    s = m.status
    # Return true if ready
    return s == "ready" and m.cpu > 0
```

**Clear Naming Without Comments**:

```python
def is_machine_ready_for_deployment(machine: Machine) -> bool:
    return machine.status == "ready" and machine.cpu_count > 0
```

**Go Example**:

```go
// Poor
func p(m *M) bool {  // What does p mean? What's M?
    return m.s == "r"
}

// Clear
func IsMachineReady(machine *Machine) bool {
    return machine.Status == "ready"
}
```

### Extract Complex Conditions

**Complex Inline Condition**:

```python
if machine.status == "ready" and machine.cpu_count >= 4 and machine.memory >= 8192 and machine.zone_id in allowed_zones and machine.owner_id is None:
    deploy_machine(machine)
```

**Extracted to Named Function**:

```python
def is_deployable(machine: Machine, allowed_zones: list[int]) -> bool:
    return (
        machine.status == "ready"
        and machine.cpu_count >= 4
        and machine.memory >= 8192
        and machine.zone_id in allowed_zones
        and machine.owner_id is None
    )

if is_deployable(machine, allowed_zones):
    deploy_machine(machine)
```

**Go Example**:

```go
func isDeployable(machine *Machine, allowedZones []int) bool {
    return machine.Status == "ready" &&
        machine.CPUCount >= 4 &&
        machine.Memory >= 8192 &&
        contains(allowedZones, machine.ZoneID) &&
        machine.OwnerID == nil
}

if isDeployable(machine, allowedZones) {
    deployMachine(machine)
}
```

### Small, Focused Functions

**Large Function Doing Multiple Things**:

```python
def process_machine(machine_id: int):
    # Validate machine
    machine = Machine.objects.get(id=machine_id)
    if machine.status != "ready":
        raise ValueError("Not ready")
    
    # Configure network
    interfaces = Interface.objects.filter(machine=machine)
    for interface in interfaces:
        interface.ip_address = allocate_ip()
        interface.save()
    
    # Setup storage
    disks = Disk.objects.filter(machine=machine)
    for disk in disks:
        disk.partition()
        disk.format("ext4")
        disk.save()
    
    # Deploy OS
    image = get_image(machine.os_version)
    write_image(machine, image)
    machine.status = "deployed"
    machine.save()
```

**Refactored to Focused Functions**:

```python
def process_machine(machine_id: int):
    machine = validate_machine(machine_id)
    configure_network(machine)
    setup_storage(machine)
    deploy_os(machine)

def validate_machine(machine_id: int) -> Machine:
    machine = Machine.objects.get(id=machine_id)
    if machine.status != "ready":
        raise ValueError(f"Machine {machine_id} is not ready")
    return machine

def configure_network(machine: Machine):
    interfaces = Interface.objects.filter(machine=machine)
    for interface in interfaces:
        interface.ip_address = allocate_ip()
        interface.save()

def setup_storage(machine: Machine):
    disks = Disk.objects.filter(machine=machine)
    for disk in disks:
        prepare_disk(disk)

def deploy_os(machine: Machine):
    image = get_image(machine.os_version)
    write_image(machine, image)
    machine.status = "deployed"
    machine.save()
```

### Meaningful Variable Names

**Unclear Names**:

```python
def f(m, z, t):
    d = []
    for i in m:
        if i.z == z and i.t == t:
            d.append(i)
    return d
```

**Clear Names**:

```python
def filter_machines_by_zone_and_type(
    machines: list[Machine],
    zone_id: int,
    machine_type: str,
) -> list[Machine]:
    filtered_machines = []
    for machine in machines:
        if machine.zone_id == zone_id and machine.type == machine_type:
            filtered_machines.append(machine)
    return filtered_machines

# Even better: use comprehension
def filter_machines_by_zone_and_type(
    machines: list[Machine],
    zone_id: int,
    machine_type: str,
) -> list[Machine]:
    return [
        machine for machine in machines
        if machine.zone_id == zone_id and machine.type == machine_type
    ]
```

### Use Domain Language

**Technical Jargon**:

```python
def process_entity(entity_id: int):
    """Process an entity in the data store."""
    entity = get_from_db(entity_id)
    update_entity_state(entity, "processed")
```

**Domain Language**:

```python
def deploy_machine(machine_id: int):
    """Deploy a machine to a ready state."""
    machine = get_machine(machine_id)
    mark_machine_as_deployed(machine)
```

### Early Returns for Clarity

**Nested Conditionals**:

```python
def deploy_machine(machine: Machine) -> bool:
    if machine is not None:
        if machine.status == "ready":
            if machine.zone is not None:
                if machine.cpu_count > 0:
                    # Finally do the work
                    execute_deployment(machine)
                    return True
                else:
                    return False
            else:
                return False
        else:
            return False
    else:
        return False
```

**Early Returns (Guard Clauses)**:

```python
def deploy_machine(machine: Machine) -> bool:
    if machine is None:
        return False
    
    if machine.status != "ready":
        return False
    
    if machine.zone is None:
        return False
    
    if machine.cpu_count <= 0:
        return False
    
    execute_deployment(machine)
    return True
```

**Even Better with Exceptions**:

```python
def deploy_machine(machine: Machine):
    if machine is None:
        raise ValueError("Machine cannot be None")
    
    if machine.status != "ready":
        raise MachineNotReadyError(f"Machine {machine.id} is not ready")
    
    if machine.zone is None:
        raise ValueError(f"Machine {machine.id} has no zone")
    
    if machine.cpu_count <= 0:
        raise ValueError(f"Machine {machine.id} has invalid CPU count")
    
    execute_deployment(machine)
```

### Avoid Magic Numbers

**Magic Numbers**:

```python
if machine.cpu_count > 16 and machine.memory > 32768:
    mark_as_high_spec(machine)

time.sleep(300)  # What is 300?
```

**Named Constants**:

```python
HIGH_SPEC_MIN_CPU = 16
HIGH_SPEC_MIN_MEMORY_MB = 32768
DEPLOYMENT_TIMEOUT_SECONDS = 300

if machine.cpu_count > HIGH_SPEC_MIN_CPU and machine.memory > HIGH_SPEC_MIN_MEMORY_MB:
    mark_as_high_spec(machine)

time.sleep(DEPLOYMENT_TIMEOUT_SECONDS)
```

### Consistent Abstraction Level

**Mixed Abstraction Levels**:

```python
def deploy_machine(machine_id: int):
    machine = Machine.objects.get(id=machine_id)  # High level
    
    # Suddenly low level
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((machine.ip_address, 22))
    sock.send(b"deploy command")
    
    machine.status = "deployed"  # Back to high level
    machine.save()
```

**Consistent Abstraction**:

```python
def deploy_machine(machine_id: int):
    machine = get_machine(machine_id)
    send_deploy_command(machine)
    mark_as_deployed(machine)

def send_deploy_command(machine: Machine):
    # Low-level details hidden in this function
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((machine.ip_address, 22))
    sock.send(b"deploy command")
```

### Explicit Over Implicit

**Implicit Behavior**:

```python
def create_machine(hostname):
    # Implicit: Creates in zone 1, status "new"
    return Machine.objects.create(hostname=hostname)
```

**Explicit Behavior**:

```python
def create_machine(
    hostname: str,
    zone_id: int = 1,
    status: str = "new",
) -> Machine:
    return Machine.objects.create(
        hostname=hostname,
        zone_id=zone_id,
        status=status,
    )

# Or even better: require explicit values
def create_machine(hostname: str, zone_id: int) -> Machine:
    return Machine.objects.create(
        hostname=hostname,
        zone_id=zone_id,
        status="new",  # Only status has default
    )
```

### Clean Test Code

**Verbose Test**:

```python
def test_machine_deployment():
    """
    This test verifies that when we deploy a machine with status ready,
    the deployment process completes successfully and the machine status
    is updated to deployed.
    """
    # Create a machine
    machine = Machine(id=1, hostname="test", status="ready")
    
    # Call the deploy function
    result = deploy_machine(machine)
    
    # Check that it worked
    assert result is True
```

**Clear Test Without Noise**:

```python
def test_deploy_ready_machine_succeeds():
    machine = Machine(id=1, hostname="test", status="ready")
    
    result = deploy_machine(machine)
    
    assert result is True
    assert machine.status == "deployed"
```

**Go Test Example**:

```go
// Verbose
func TestMachineDeployment(t *testing.T) {
    // This test checks that deployment works
    m := &Machine{ID: 1, Status: "ready"}  // Create machine
    
    err := Deploy(m)  // Deploy it
    
    // Check no error
    if err != nil {
        t.Error("Should not error")
    }
}

// Clear
func TestDeployReadyMachineSucceeds(t *testing.T) {
    machine := &Machine{ID: 1, Status: "ready"}
    
    err := Deploy(machine)
    
    assert.NoError(t, err)
    assert.Equal(t, "deployed", machine.Status)
}
```

## Anti-patterns

### ❌ Abbreviations and Unclear Names

```python
# NEVER use unclear abbreviations
def proc_mch(m, z):  # What is this?
    mch_lst = get_mchs(z)
    for mch in mch_lst:
        proc(mch)

# Correct
def process_machines_in_zone(zone_id: int):
    machines = get_machines_by_zone(zone_id)
    for machine in machines:
        process_machine(machine)
```

### ❌ Comments Explaining What Code Does

```python
# NEVER explain obvious code
# Loop through machines
for machine in machines:
    # Check if machine is ready
    if machine.status == "ready":
        # Deploy the machine
        deploy(machine)

# Correct: Code speaks for itself
for machine in machines:
    if machine.status == "ready":
        deploy(machine)
```

### ❌ Overusing Comments Instead of Refactoring

```python
# NEVER use comments to explain bad code
# This checks if the machine can be deployed (status is ready,
# has enough CPU and memory, is in an allowed zone, and is not
# currently owned by anyone)
if m.s == "r" and m.c >= 4 and m.m >= 8192 and m.z in az and m.o is None:
    deploy(m)

# Correct: Make code self-explanatory
if is_machine_deployable(machine, allowed_zones):
    deploy(machine)
```

### ❌ Clever Code Over Clear Code

```python
# NEVER prioritize cleverness over clarity
result = [m for m in ms if m.s == "r"] if ms else []
status = "ready" if m and m.s == "r" and m.c > 0 else "not ready" if m else "unknown"

# Correct: Clear and simple
def get_ready_machines(machines: list[Machine]) -> list[Machine]:
    if not machines:
        return []
    return [m for m in machines if m.status == "ready"]

def get_machine_status(machine: Machine | None) -> str:
    if machine is None:
        return "unknown"
    if machine.status == "ready" and machine.cpu_count > 0:
        return "ready"
    return "not ready"
```

### ❌ Inconsistent Naming Patterns

```python
# NEVER mix naming styles
def getMachine(id):  # camelCase
def create_zone(name):  # snake_case
def DeleteMACHINE(machine_id):  # Random case

# Correct: Consistent style
def get_machine(machine_id: int) -> Machine:
    pass

def create_zone(name: str) -> Zone:
    pass

def delete_machine(machine_id: int) -> None:
    pass
```

### ❌ Functions That Do Too Much

```python
# NEVER create giant functions
def process_machine_and_network_and_storage_and_deploy(machine_id):
    # 200 lines of code doing everything
    pass

# Correct: Single responsibility
def process_machine(machine_id: int):
    machine = get_machine(machine_id)
    configure_network(machine)
    setup_storage(machine)
    deploy_machine(machine)
```

## Related Skills

- **Naming Conventions**: [naming-conventions.md](naming-conventions.md) - Detailed naming standards
- **Minimal Comments**: [minimal-comments.md](minimal-comments.md) - When and how to comment
- **Test Code Quality**: [test-code-quality.md](test-code-quality.md) - Clean test patterns
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Python code style
- **Go Patterns**: [../languages/go-patterns.md](../languages/go-patterns.md) - Go code organization

## Code Clarity Principles

1. **Self-Documenting**: Code should explain itself through clear names and structure
2. **Single Responsibility**: Functions should do one thing well
3. **Consistent Abstraction**: Keep functions at the same level of detail
4. **Explicit Over Implicit**: Make behavior obvious
5. **Early Returns**: Use guard clauses to reduce nesting
6. **Domain Language**: Use terms from the problem domain
7. **No Magic**: Named constants over magic numbers
8. **Refactor Over Comment**: Improve code instead of explaining bad code