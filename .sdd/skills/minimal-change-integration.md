# Minimal-Change Integration for MAAS

## Overview

Minimal-Change Integration is the discipline of making the smallest possible modifications to existing code when adding new functionality. Rather than rewriting or heavily refactoring working code, you preserve the existing structure and surgically integrate new capabilities. This approach reduces risk, maintains code stability, and respects the codebase's established patterns.

## Purpose

- **Reduce Risk**: Smaller changes mean fewer things that can break
- **Preserve Stability**: Working code stays working
- **Faster Reviews**: Less code to review means faster approval
- **Maintain Consistency**: Existing patterns and style are preserved
- **Enable Rollback**: Minimal changes are easier to revert
- **Focus Effort**: Only change what's necessary for the feature
- **Respect History**: Existing code has survived production—don't break it

## Philosophy

### The Hippocratic Oath of Code Modification

**"First, do no harm."**

When integrating new functionality:
1. Assume existing code works correctly
2. Change only what's absolutely necessary
3. Preserve existing behavior
4. Match existing patterns and style
5. Don't "fix" unrelated issues
6. Don't refactor for its own sake

### The Surgical Mindset

Think of code modification like surgery:
- **Precise incisions**: Target exactly what needs changing
- **Minimal invasion**: Disturb as little tissue as possible
- **Preserve function**: Maintain existing capabilities
- **Clean integration**: New code blends seamlessly
- **Quick recovery**: System returns to normal quickly

### When to Use Minimal-Change Integration

**Use this approach when:**
- Adding feature to existing codebase
- Integrating with established systems
- Modifying production-tested code
- Working in unfamiliar code areas
- Time/risk constraints are tight
- Code review bandwidth is limited

**Don't use this approach when:**
- Existing code is fundamentally broken
- Security vulnerabilities must be fixed
- Technical debt is blocking progress
- Code is being deprecated anyway
- Complete rewrite is planned and approved

## Core Principles

### Principle 1: Preserve Existing Code Structure

**Keep the existing organization, flow, and architecture.**

```python
# Existing code
class MachineRepository:
    def get_by_id(self, machine_id):
        return Machine.objects.get(id=machine_id)
    
    def list_all(self):
        return Machine.objects.all()

# ✓ Good: Add method, preserve structure
class MachineRepository:
    def get_by_id(self, machine_id):
        return Machine.objects.get(id=machine_id)
    
    def list_all(self):
        return Machine.objects.all()
    
    def list_by_status(self, status):  # New method added
        return Machine.objects.filter(status=status)

# ✗ Bad: Restructure everything
class MachineRepository:
    # Reorganized all methods alphabetically
    # Changed method signatures
    # Introduced new abstractions
    # Refactored error handling
```

### Principle 2: Match Existing Patterns

**New code should look like it was always there.**

```python
# Existing pattern: Methods use early returns
def allocate_machine(self, system_id, user):
    if not self._can_allocate(system_id):
        return None
    
    machine = self._get_machine(system_id)
    if machine.status != NODE_STATUS.READY:
        return None
    
    machine.allocate_to(user)
    return machine

# ✓ Good: New method follows same pattern
def deallocate_machine(self, system_id):
    if not self._can_deallocate(system_id):
        return None
    
    machine = self._get_machine(system_id)
    if machine.status != NODE_STATUS.ALLOCATED:
        return None
    
    machine.release()
    return machine

# ✗ Bad: New method uses different pattern
def deallocate_machine(self, system_id):
    try:
        machine = self._get_machine(system_id)
        if self._can_deallocate(system_id) and machine.status == NODE_STATUS.ALLOCATED:
            machine.release()
            return machine
        else:
            return None
    except Exception as e:
        logging.error(f"Deallocation failed: {e}")
        return None
```

### Principle 3: Minimal Line Changes

**Change the fewest lines possible to achieve the goal.**

```python
# Existing code
def get_machines_summary(self):
    machines = Machine.objects.all()
    return {
        'total': machines.count(),
        'ready': machines.filter(status=NODE_STATUS.READY).count(),
        'allocated': machines.filter(status=NODE_STATUS.ALLOCATED).count(),
    }

# Task: Add deployed count

# ✓ Good: One line added
def get_machines_summary(self):
    machines = Machine.objects.all()
    return {
        'total': machines.count(),
        'ready': machines.filter(status=NODE_STATUS.READY).count(),
        'allocated': machines.filter(status=NODE_STATUS.ALLOCATED).count(),
        'deployed': machines.filter(status=NODE_STATUS.DEPLOYED).count(),  # Added
    }

# ✗ Bad: Unnecessary refactoring
def get_machines_summary(self):
    machines = Machine.objects.all()
    statuses = [NODE_STATUS.READY, NODE_STATUS.ALLOCATED, NODE_STATUS.DEPLOYED]
    result = {'total': machines.count()}
    
    for status in statuses:
        key = status.lower()
        result[key] = machines.filter(status=status).count()
    
    return result
```

### Principle 4: Integration Over Replacement

**Add to existing code rather than replacing it.**

```python
# Existing API endpoint
class MachineHandler:
    def read(self, request, system_id):
        """Get machine details."""
        machine = Machine.objects.get(system_id=system_id)
        return {
            'system_id': machine.system_id,
            'hostname': machine.hostname,
            'status': machine.status,
        }

# Task: Add hardware info to response

# ✓ Good: Integrate into existing response
class MachineHandler:
    def read(self, request, system_id):
        """Get machine details."""
        machine = Machine.objects.get(system_id=system_id)
        return {
            'system_id': machine.system_id,
            'hostname': machine.hostname,
            'status': machine.status,
            'hardware': self._get_hardware_info(machine),  # Added
        }
    
    def _get_hardware_info(self, machine):  # New helper method
        return {
            'cpu_count': machine.cpu_count,
            'memory': machine.memory,
        }

# ✗ Bad: Replace entire method
class MachineHandler:
    def read(self, request, system_id):
        """Get machine details."""
        machine = self._fetch_machine_with_hardware(system_id)
        serializer = MachineDetailSerializer(machine)
        return serializer.to_dict()
```

### Principle 5: Respect Existing Interfaces

**Don't change signatures of existing methods.**

```python
# Existing interface
class QueryCoordinator:
    def query_regions(self, filters):
        """Query all regions with given filters."""
        # Implementation
        pass

# Task: Add timeout parameter

# ✓ Good: Optional parameter with default
class QueryCoordinator:
    def query_regions(self, filters, timeout=30):  # Backward compatible
        """Query all regions with given filters."""
        # Implementation with timeout
        pass

# ✗ Bad: Required parameter breaks existing callers
class QueryCoordinator:
    def query_regions(self, filters, timeout):  # Breaking change!
        """Query all regions with given filters."""
        pass
```

### Principle 6: Localize Changes

**Keep changes confined to smallest possible scope.**

```python
# Existing service with multiple methods
class MachineService:
    def allocate(self, system_id, user):
        # 50 lines
        pass
    
    def deploy(self, system_id, distro):
        # 30 lines
        pass
    
    def release(self, system_id):
        # 20 lines
        pass

# Task: Add event logging to allocation

# ✓ Good: Changes only in allocate method
class MachineService:
    def allocate(self, system_id, user):
        # Existing allocation logic...
        result = machine.allocate_to(user)
        
        # New: Log event
        self._log_allocation_event(machine, user)
        
        return result
    
    def _log_allocation_event(self, machine, user):  # New helper
        event_bus.publish(AllocationEvent(machine, user))
    
    def deploy(self, system_id, distro):
        # Unchanged
        pass
    
    def release(self, system_id):
        # Unchanged
        pass

# ✗ Bad: Refactor entire service to add logging framework
class MachineService:
    def __init__(self, event_logger):  # Changed signature
        self.event_logger = event_logger
    
    def allocate(self, system_id, user):
        # Rewritten to use new logging abstraction
        pass
    
    def deploy(self, system_id, distro):
        # Rewritten to use new logging abstraction
        pass
    
    def release(self, system_id):
        # Rewritten to use new logging abstraction
        pass
```

## Integration Patterns

### Pattern 1: Add, Don't Modify

**Prefer adding new code over modifying existing code.**

```python
# Existing
def get_machine_info(machine):
    return {
        'hostname': machine.hostname,
        'status': machine.status,
    }

# Task: Include power state

# ✓ Good: Add new function, keep existing
def get_machine_info(machine):
    return {
        'hostname': machine.hostname,
        'status': machine.status,
    }

def get_machine_info_with_power(machine):  # New function
    info = get_machine_info(machine)  # Reuse existing
    info['power_state'] = machine.power_state
    return info

# Alternative: Extend existing carefully
def get_machine_info(machine, include_power=False):
    info = {
        'hostname': machine.hostname,
        'status': machine.status,
    }
    if include_power:
        info['power_state'] = machine.power_state
    return info
```

### Pattern 2: Wrap, Don't Rewrite

**Add wrapper layer instead of changing internals.**

```python
# Existing (used in 50 places)
def fetch_machine_data(system_id):
    return requests.get(f'/api/machines/{system_id}').json()

# Task: Add caching

# ✓ Good: Wrapper preserves existing behavior
_cache = {}

def fetch_machine_data_cached(system_id):
    if system_id not in _cache:
        _cache[system_id] = fetch_machine_data(system_id)
    return _cache[system_id]

# Existing code unchanged, migrate callers gradually

# ✗ Bad: Modify existing function, risk breaking 50 callers
def fetch_machine_data(system_id):
    if system_id in _cache:
        return _cache[system_id]
    
    data = requests.get(f'/api/machines/{system_id}').json()
    _cache[system_id] = data
    return data
```

### Pattern 3: Compose, Don't Consolidate

**Build on existing primitives rather than merging them.**

```python
# Existing primitives
def get_machines_by_status(status):
    return Machine.objects.filter(status=status)

def get_machines_by_zone(zone):
    return Machine.objects.filter(zone=zone)

# Task: Get machines by status AND zone

# ✓ Good: Compose existing functions
def get_machines_by_status_and_zone(status, zone):
    return get_machines_by_status(status).filter(zone=zone)

# Or: New independent function
def get_machines_by_status_and_zone(status, zone):
    return Machine.objects.filter(status=status, zone=zone)

# ✗ Bad: Merge into one complex function
def get_machines(status=None, zone=None):
    queryset = Machine.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    if zone:
        queryset = queryset.filter(zone=zone)
    return queryset
# Now you've changed behavior of existing functions!
```

### Pattern 4: Extend at Edges

**Add new functionality at boundaries, not in core.**

```python
# Existing core logic
class MachineRepository:
    def save(self, machine):
        machine.full_clean()
        machine.save()

# Task: Add audit logging

# ✓ Good: Extend at service layer (edge)
class MachineService:
    def __init__(self, repo, audit_log):
        self.repo = repo
        self.audit_log = audit_log
    
    def save_machine(self, machine):
        self.repo.save(machine)  # Core unchanged
        self.audit_log.record('machine_saved', machine.system_id)  # Extension

# ✗ Bad: Modify core repository
class MachineRepository:
    def __init__(self, audit_log):  # Changed interface
        self.audit_log = audit_log
    
    def save(self, machine):
        machine.full_clean()
        machine.save()
        self.audit_log.record('machine_saved', machine.system_id)  # Mixed concerns
```

### Pattern 5: Parameter Extension

**Extend behavior through optional parameters.**

```python
# Existing
def query_machines(filters):
    return Machine.objects.filter(**filters)

# Task: Add pagination support

# ✓ Good: Optional parameters
def query_machines(filters, limit=None, offset=None):
    queryset = Machine.objects.filter(**filters)
    
    if offset:
        queryset = queryset[offset:]
    if limit:
        queryset = queryset[:limit]
    
    return queryset

# Existing callers work unchanged
# New callers can use pagination

# ✗ Bad: Required parameters
def query_machines(filters, page, page_size):  # Breaks existing callers
    offset = (page - 1) * page_size
    return Machine.objects.filter(**filters)[offset:offset + page_size]
```

### Pattern 6: Hook Points

**Insert hooks for extension without changing logic.**

```python
# Existing
class MachineAllocator:
    def allocate(self, machine, user):
        machine.status = NODE_STATUS.ALLOCATED
        machine.owner = user
        machine.save()

# Task: Add custom business logic hooks

# ✓ Good: Add hook points
class MachineAllocator:
    def allocate(self, machine, user):
        self._before_allocate(machine, user)  # Hook
        
        machine.status = NODE_STATUS.ALLOCATED
        machine.owner = user
        machine.save()
        
        self._after_allocate(machine, user)  # Hook
    
    def _before_allocate(self, machine, user):
        """Override in subclass for custom logic."""
        pass
    
    def _after_allocate(self, machine, user):
        """Override in subclass for custom logic."""
        pass

# Now users can extend without modifying core
```

## MAAS-Specific Integration Strategies

### Django Model Extension

```python
# Existing model
class Machine(Model):
    hostname = CharField(max_length=255)
    status = IntegerField()
    
    def allocate(self, user):
        self.status = NODE_STATUS.ALLOCATED
        self.save()

# Task: Track allocation timestamp

# ✓ Good: Add field and minimal change
class Machine(Model):
    hostname = CharField(max_length=255)
    status = IntegerField()
    allocated_at = DateTimeField(null=True, blank=True)  # New field
    
    def allocate(self, user):
        self.status = NODE_STATUS.ALLOCATED
        self.allocated_at = timezone.now()  # One line added
        self.save()
```

### API Endpoint Extension

```python
# Existing API handler
class MachinesHandler(OperationsHandler):
    def read(self, request):
        """List all machines."""
        machines = Machine.objects.all()
        return [self._serialize(m) for m in machines]
    
    def _serialize(self, machine):
        return {
            'system_id': machine.system_id,
            'hostname': machine.hostname,
        }

# Task: Add filtering by status

# ✓ Good: Extend with backward compatibility
class MachinesHandler(OperationsHandler):
    def read(self, request):
        """List all machines."""
        machines = Machine.objects.all()
        
        # New: Optional filtering
        status = request.GET.get('status')
        if status:
            machines = machines.filter(status=status)
        
        return [self._serialize(m) for m in machines]
    
    def _serialize(self, machine):
        return {
            'system_id': machine.system_id,
            'hostname': machine.hostname,
        }
```

### React Component Extension

```javascript
// Existing component
const MachineList = ({ machines }) => {
  return (
    <ul>
      {machines.map(m => (
        <li key={m.system_id}>{m.hostname}</li>
      ))}
    </ul>
  );
};

// Task: Add click handler

// ✓ Good: Minimal addition
const MachineList = ({ machines, onMachineClick }) => {  // New prop
  return (
    <ul>
      {machines.map(m => (
        <li 
          key={m.system_id}
          onClick={() => onMachineClick && onMachineClick(m)}  // Added
        >
          {m.hostname}
        </li>
      ))}
    </ul>
  );
};

// ✗ Bad: Complete rewrite
const MachineList = ({ machines, onMachineClick }) => {
  const [selected, setSelected] = useState(null);
  const handleClick = useCallback((machine) => {
    setSelected(machine);
    if (onMachineClick) onMachineClick(machine);
  }, [onMachineClick]);
  
  return (
    <MachineListContainer>
      <MachineListHeader>Machines</MachineListHeader>
      <MachineListItems>
        {machines.map(m => (
          <MachineListItem
            key={m.system_id}
            machine={m}
            selected={selected?.system_id === m.system_id}
            onClick={handleClick}
          />
        ))}
      </MachineListItems>
    </MachineListContainer>
  );
};
```

### Service Layer Integration

```python
# Existing service
class MachineService:
    def __init__(self, repository):
        self.repository = repository
    
    def allocate_machine(self, system_id, user):
        machine = self.repository.get(system_id)
        machine.allocate(user)
        return machine

# Task: Add event publishing

# ✓ Good: Dependency injection, minimal change
class MachineService:
    def __init__(self, repository, event_bus=None):  # Optional dependency
        self.repository = repository
        self.event_bus = event_bus
    
    def allocate_machine(self, system_id, user):
        machine = self.repository.get(system_id)
        machine.allocate(user)
        
        if self.event_bus:  # Conditional new behavior
            self.event_bus.publish('machine.allocated', machine)
        
        return machine
```

## Change Scope Guidelines

### File-Level Scope

**Goal:** Minimize number of files touched

```
Task: Add new API endpoint

✓ Good: 2 files changed
  - src/maasserver/api/machines.py (add endpoint)
  - src/maasserver/tests/test_api_machines.py (add tests)

✗ Bad: 8 files changed
  - Refactored API framework
  - Updated all handlers
  - Restructured tests
  - Modified serializers
  - Changed routing
```

### Method-Level Scope

**Goal:** Minimize methods modified per file

```python
# File has 20 methods

# ✓ Good: Modify 1 method, add 1 method
def existing_method(self):
    # Modified: Added one line
    pass

def new_method(self):
    # Added
    pass

# ✗ Bad: Modified 10 methods
# Refactored error handling in all methods
```

### Line-Level Scope

**Goal:** Minimize lines changed per method

```python
# ✓ Good: 2 lines changed
def get_summary(self):
    machines = Machine.objects.all()
    ready = machines.filter(status=NODE_STATUS.READY).count()
    allocated = machines.filter(status=NODE_STATUS.ALLOCATED).count()
    deployed = machines.filter(status=NODE_STATUS.DEPLOYED).count()  # Added
    
    return {
        'total': machines.count(),
        'ready': ready,
        'allocated': allocated,
        'deployed': deployed,  # Added
    }

# ✗ Bad: 15 lines changed (entire method rewritten)
```

## Testing Minimal Changes

### Test Only New Behavior

```python
# Existing tests (don't touch these)
def test_list_machines_returns_all():
    # Existing test
    pass

# New test for new functionality
def test_list_machines_filters_by_status_when_provided():
    """list_machines filters by status when status parameter provided."""
    factory.make_Machine(status=NODE_STATUS.READY)
    factory.make_Machine(status=NODE_STATUS.ALLOCATED)
    
    result = list_machines(status=NODE_STATUS.READY)
    
    assert len(result) == 1
    assert result[0].status == NODE_STATUS.READY

def test_list_machines_returns_all_when_no_status():
    """list_machines returns all machines when no status provided."""
    factory.make_Machine(status=NODE_STATUS.READY)
    factory.make_Machine(status=NODE_STATUS.ALLOCATED)
    
    result = list_machines()  # No status parameter
    
    assert len(result) == 2  # Backward compatibility verified
```

### Integration Tests for Seams

```python
# Test that new code integrates with existing
def test_new_feature_works_with_existing_workflow():
    """New filtering integrates with existing pagination."""
    # Create test data
    for i in range(10):
        factory.make_Machine(status=NODE_STATUS.READY)
    
    # Use existing pagination with new filtering
    result = list_machines(
        status=NODE_STATUS.READY,  # New parameter
        limit=5,                    # Existing parameter
        offset=0                    # Existing parameter
    )
    
    assert len(result) == 5
    assert all(m.status == NODE_STATUS.READY for m in result)
```

## Common Mistakes

### ❌ Scope Creep During Implementation

```python
# Task: Add deployed count to summary

# Wrong: "While I'm here, let me refactor..."
def get_summary(self):
    # Refactored to use list comprehension
    # Changed variable names for clarity  
    # Extracted helper methods
    # Updated docstrings
    # Added type hints
    # Optimized query performance
    # Added caching layer
    # Oh, and added deployed count somewhere in there

# Right: Just add deployed count
def get_summary(self):
    machines = Machine.objects.all()
    return {
        'total': machines.count(),
        'ready': machines.filter(status=NODE_STATUS.READY).count(),
        'allocated': machines.filter(status=NODE_STATUS.ALLOCATED).count(),
        'deployed': machines.filter(status=NODE_STATUS.DEPLOYED).count(),  # Added
    }
```

### ❌ Premature Abstraction

```python
# Task: Add second filter type

# Wrong: Create elaborate framework
class FilterRegistry:
    def __init__(self):
        self.filters = {}
    
    def register(self, name, filter_func):
        self.filters[name] = filter_func
    
    def apply(self, queryset, filters):
        for name, value in filters.items():
            if name in self.filters:
                queryset = self.filters[name](queryset, value)
        return queryset

# Right: Just add the filter
def list_machines(status=None, zone=None):
    machines = Machine.objects.all()
    if status:
        machines = machines.filter(status=status)
    if zone:
        machines = machines.filter(zone=zone)
    return machines
```

### ❌ Inconsistent Style

```python
# Existing style: early returns
def process_machine(machine):
    if not machine.is_ready():
        return None
    
    if not machine.has_power():
        return None
    
    machine.allocate()
    return machine

# Wrong: New code uses different style
def process_device(device):
    try:
        if device.is_ready() and device.has_power():
            device.allocate()
            return device
        else:
            return None
    except Exception as e:
        logger.error(f"Failed: {e}")
        return None

# Right: Match existing style
def process_device(device):
    if not device.is_ready():
        return None
    
    if not device.has_power():
        return None
    
    device.allocate()
    return device
```

### ❌ Breaking Backward Compatibility

```python
# Existing (called in 100 places)
def get_machine(system_id):
    return Machine.objects.get(system_id=system_id)

# Wrong: Change signature
def get_machine(system_id, include_deleted=False):  # Breaks callers expecting 1 arg
    queryset = Machine.objects.all()
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    return queryset.get(system_id=system_id)

# Right: Backward compatible
def get_machine(system_id, include_deleted=False):  # Default preserves behavior
    queryset = Machine.objects.all()
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    return queryset.get(system_id=system_id)

# Even better: New function
def get_machine_including_deleted(system_id):
    return Machine.all_objects.get(system_id=system_id)
```

## Review Checklist

Before submitting minimal-change integration:

- [ ] Have I changed the minimum number of files?
- [ ] Have I changed the minimum number of methods?
- [ ] Have I changed the minimum number of lines?
- [ ] Does new code match existing style and patterns?
- [ ] Have I preserved backward compatibility?
- [ ] Have I avoided refactoring unrelated code?
- [ ] Have I avoided fixing unrelated issues?
- [ ] Are existing tests still passing?
- [ ] Do my tests focus only on new behavior?
- [ ] Could this change be made even smaller?

## Summary

Minimal-Change Integration requires:

1. **Surgical Precision**: Change exactly what's needed, nothing more
2. **Preservation**: Keep existing code structure and patterns intact
3. **Integration**: Add to existing code rather than replacing it
4. **Compatibility**: Maintain existing interfaces and behavior
5. **Localization**: Confine changes to smallest possible scope
6. **Respect**: Trust that existing code works and has value
7. **Discipline**: Resist the urge to refactor while implementing

In MAAS, where stability is critical and the codebase is mature, minimal-change integration reduces risk and accelerates delivery. Make the smallest change that could possibly work, then stop.