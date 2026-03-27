# Minimal Comments

## Purpose

Define when and how to write comments in MAAS code, emphasizing self-documenting code through better naming over explanatory comments, and focusing comments on "why" rather than "what".

## When to Use

- Reviewing code that has excessive or trivial comments
- Writing new code and deciding if a comment is needed
- Refactoring code to improve clarity
- Documenting complex business logic
- Writing public APIs or library functions

## Pattern Examples

### Self-Documenting Code (No Comments Needed)

**Good Naming Eliminates Comments**:

```python
# Bad: Comment explains what unclear code does
# Get machines that are ready
m = Machine.objects.filter(s="ready")

# Good: Clear code needs no comment
ready_machines = Machine.objects.filter(status="ready")
```

```go
// Bad: Comment restates obvious code
// Check if the machine is ready
if m.Status == "ready" {
    // ...
}

// Good: No comment needed
if machine.IsReady() {
    // ...
}
```

**Extract Complex Logic into Named Functions**:

```python
# Bad: Comment explains complex condition
# Check if machine has enough resources and is in correct state
if machine.cpu_count >= 4 and machine.memory >= 8192 and machine.status in ["ready", "allocated"] and machine.zone_id in allowed_zones:
    deploy(machine)

# Good: Named function explains intent
def is_deployable(machine: Machine, allowed_zones: list[int]) -> bool:
    has_sufficient_resources = machine.cpu_count >= 4 and machine.memory >= 8192
    has_valid_status = machine.status in ["ready", "allocated"]
    is_in_allowed_zone = machine.zone_id in allowed_zones
    return has_sufficient_resources and has_valid_status and is_in_allowed_zone

if is_deployable(machine, allowed_zones):
    deploy(machine)
```

### When Comments ARE Needed

**Explain WHY, Not WHAT**:

```python
# Good: Explains reasoning
def allocate_machine(machine_id: int, user_id: int):
    # Lock the machine row to prevent race condition where two users
    # try to allocate the same machine simultaneously
    machine = Machine.objects.select_for_update().get(id=machine_id)
    
    # Set timeout to 24 hours per company policy for resource reservation
    timeout = timezone.now() + timedelta(hours=24)
    machine.allocate_to(user_id, timeout)
```

**Document Non-Obvious Business Logic**:

```python
def calculate_deployment_priority(machine: Machine) -> int:
    """Calculate deployment priority based on machine characteristics.
    
    Priority is higher for machines with more resources, but machines
    in the default zone get a 10-point bonus to ensure they're used first
    (default zone has better network connectivity per infrastructure team).
    """
    base_priority = machine.cpu_count + (machine.memory // 1024)
    
    # Default zone bonus: better network performance (see INFRA-1234)
    if machine.zone_id == DEFAULT_ZONE_ID:
        base_priority += 10
    
    return base_priority
```

**Note Important Gotchas**:

```python
async def deploy_machine(machine_id: int):
    machine = await get_machine(machine_id)
    
    # Must update status BEFORE starting workflow to prevent duplicate
    # deployments if this function is called concurrently (bug #LP1234567)
    machine.status = "deploying"
    await machine.save()
    
    await start_deployment_workflow(machine_id)
```

**Explain Complex Algorithms**:

```python
def find_optimal_machine(requirements: Requirements) -> Machine | None:
    """Find best-fit machine using bin packing algorithm.
    
    Uses first-fit decreasing strategy: sort machines by capacity,
    then select first machine that meets requirements. This provides
    reasonable efficiency while keeping allocation time low.
    """
    # Sort by capacity (descending) for first-fit decreasing
    machines = sorted(
        available_machines,
        key=lambda m: (m.cpu_count, m.memory),
        reverse=True,
    )
    
    for machine in machines:
        if meets_requirements(machine, requirements):
            return machine
    
    return None
```

### Concise Docstrings

**Public API Functions**:

```python
def create_machine(hostname: str, zone_id: int) -> Machine:
    """Create a new machine in the specified zone.
    
    Args:
        hostname: Unique hostname for the machine
        zone_id: ID of the zone where machine will be created
        
    Returns:
        Created machine instance
        
    Raises:
        ValueError: If hostname is already in use
    """
    # Implementation
```

**Classes - Purpose and Usage, Not Implementation**:

```python
class MachineRepository:
    """Repository for machine data access.
    
    Provides CRUD operations and query methods for machines
    using SQLAlchemy Core. All methods are async.
    """
    
    def __init__(self, connection: AsyncConnection):
        self._connection = connection
```

### No Comments for Tests

**Test Names Should Be Descriptive Enough**:

```python
# Bad: Verbose docstring in test
def test_create_machine():
    """
    This test verifies that when we call the create_machine function
    with valid parameters, it successfully creates a machine in the
    database and returns the created machine instance with all fields
    properly populated.
    """
    pass

# Good: Descriptive name, no docstring
def test_create_machine_returns_instance_with_generated_id():
    machine = create_machine("test-node", zone_id=1)
    assert machine.id is not None
    assert machine.hostname == "test-node"
```

**Clear Test Structure**:

```python
def test_allocate_machine_fails_when_machine_already_allocated():
    # Arrange
    machine = create_machine("node1", zone_id=1)
    machine.allocate_to(user_id=1)
    
    # Act & Assert
    with pytest.raises(MachineAlreadyAllocated):
        machine.allocate_to(user_id=2)
```

### Copyright Headers (Required)

```python
#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Module for machine management operations."""
```

## Anti-patterns

### ❌ Obvious Comments

```python
# NEVER comment on what code obviously does

# Bad: Stating the obvious
# Increment counter by 1
counter += 1

# Set status to ready
machine.status = "ready"

# Return the result
return result

# Loop through machines
for machine in machines:
    pass
```

### ❌ Restating Code

```python
# NEVER just restate what the code says

# Bad: Comment adds no value
# Get machine by ID
machine = get_machine(id)

# Create new machine object
machine = Machine(hostname="test", zone_id=1)

# Save to database
machine.save()

# Good: Let code speak for itself (no comments needed)
machine = get_machine(id)
machine = Machine(hostname="test", zone_id=1)
machine.save()
```

### ❌ Explaining Poor Code

```python
# NEVER use comments to explain unclear code

# Bad: Comment compensates for bad naming
# m is machine, s is status, z is zone
m = get_obj(id)
s = m.get_s()
z = m.get_z()

# Good: Clear names, no comments needed
machine = get_machine(id)
status = machine.get_status()
zone = machine.get_zone()
```

### ❌ Verbose Test Docstrings

```python
# NEVER write verbose docstrings in tests

# Bad: Too much explanation
def test_machine_creation():
    """
    Test Case: Machine Creation
    
    Description:
        This test case verifies the functionality of creating a new
        machine instance through the machine service. It ensures that
        all required fields are properly set and that the machine is
        persisted to the database correctly.
        
    Steps:
        1. Create a new machine with valid parameters
        2. Verify the machine has an ID
        3. Verify all fields are set correctly
    """
    pass

# Good: Descriptive name only
def test_create_machine_sets_all_fields_correctly():
    machine = service.create("test-node", zone_id=1)
    assert machine.id is not None
    assert machine.hostname == "test-node"
    assert machine.zone_id == 1
```

### ❌ Outdated Comments

```python
# NEVER leave outdated comments

# Bad: Comment doesn't match code
# Returns list of ready machines
def get_machines(status: str | None = None) -> list[Machine]:
    # Function was changed but comment wasn't updated
    return Machine.objects.filter(status=status) if status else Machine.objects.all()

# Good: No comment, clear code
def get_machines(status: str | None = None) -> list[Machine]:
    return Machine.objects.filter(status=status) if status else Machine.objects.all()
```

### ❌ Commented-Out Code

```python
# NEVER leave commented-out code

# Bad: Dead code
def deploy(machine):
    # old_deploy(machine)  # Old implementation
    # machine.setup()  # Not needed anymore
    new_deploy(machine)

# Good: Remove dead code (use version control)
def deploy(machine):
    new_deploy(machine)
```

## Related Skills

- **Naming Conventions**: [naming-conventions.md](naming-conventions.md) - Clear naming reduces need for comments
- **Code Clarity**: [code-clarity.md](code-clarity.md) - Self-documenting code practices
- **Test Code Quality**: [test-code-quality.md](test-code-quality.md) - Clean tests without verbose docs
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Pythonic code
- **Go Patterns**: [../languages/go-patterns.md](../languages/go-patterns.md) - Idiomatic Go

## Comment Guidelines Summary

### Write Comments For:
1. **Why** something is done (not what)
2. Non-obvious business logic or domain knowledge
3. Complex algorithms or performance considerations
4. Important gotchas or edge cases
5. Workarounds for external bugs (with bug reference)
6. Public API documentation (concise)

### Never Comment:
1. Obvious code or trivial logic
2. What the code does (code should show this)
3. Implementation details that code already shows
4. Tests (use descriptive names instead)
5. Poor code quality (refactor instead)

### Instead of Comments:
1. Use clear, descriptive names
2. Extract complex logic into named functions
3. Simplify conditional expressions
4. Use type hints for clarity
5. Follow established patterns

## The Golden Rule

**If you need a comment to explain WHAT the code does, the code is unclear. Refactor it first.**

Comments should explain WHY, not WHAT.