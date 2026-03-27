# Naming Conventions

## Purpose

Define clear naming conventions for MAAS code across Python and Go, emphasizing descriptive names that make code self-documenting and eliminate the need for excessive comments.

## When to Use

- Naming variables, functions, classes, methods, constants
- Naming test functions and fixtures
- Naming files and modules
- Choosing identifiers for database tables and columns
- Naming API endpoints and request/response models

## Pattern Examples

### Python Naming Conventions

**Variables and Functions (snake_case)**:

```python
# Variables: Descriptive nouns
machine_count = 10
active_machines = []
deployment_start_time = datetime.now()
user_provided_hostname = request.data.get("hostname")

# Functions: Verb phrases describing action
def get_machine_by_id(machine_id: int) -> Machine:
    pass

def create_deployment_workflow(machine: Machine) -> str:
    pass

def validate_hostname_format(hostname: str) -> bool:
    pass

def calculate_total_memory_in_zone(zone_id: int) -> int:
    pass
```

**Classes (PascalCase)**:

```python
# Classes: Nouns describing the entity
class Machine:
    pass

class MachineRepository:
    pass

class DeploymentWorkflow:
    pass

class MachineNotFoundError(Exception):
    pass

class MachineRequest(BaseModel):
    pass

class MachineResponse(BaseModel):
    pass
```

**Constants (UPPER_SNAKE_CASE)**:

```python
# Module-level constants
MAX_HOSTNAME_LENGTH = 255
DEFAULT_TIMEOUT_SECONDS = 30
DEPLOYMENT_RETRY_LIMIT = 3

# Enum-like constants
MACHINE_STATUS_NEW = "new"
MACHINE_STATUS_READY = "ready"
MACHINE_STATUS_DEPLOYED = "deployed"
```

**Private/Internal (Leading Underscore)**:

```python
# Private module-level
_internal_cache = {}
_DEFAULT_CONFIG = {}

# Private class members
class MachineService:
    def __init__(self):
        self._repository = None  # Internal/protected
        self.__private_data = None  # Name mangling (rare)
    
    def _internal_helper(self):  # Internal method
        pass
```

**Boolean Variables (Affirmative Prefixes)**:

```python
# Use is_, has_, can_, should_, etc.
is_ready = machine.status == "ready"
has_owner = machine.owner_id is not None
can_deploy = machine.is_ready and zone.is_active
should_retry = attempt_count < MAX_RETRIES
is_valid_hostname = validate_hostname(hostname)
```

### Go Naming Conventions

**Variables and Functions (camelCase/PascalCase)**:

```go
// Exported (public) - PascalCase
type Machine struct {
    ID       int
    Hostname string
}

func GetMachine(id int) (*Machine, error) {
    // Implementation
}

// Unexported (private) - camelCase
var machineCache = make(map[int]*Machine)

func validateHostname(hostname string) error {
    // Implementation
}
```

**Interfaces (Often -er Suffix)**:

```go
// Standard Go convention: interface names end in -er
type Reader interface {
    Read(p []byte) (n int, err error)
}

type MachineReader interface {
    GetByID(id int) (*Machine, error)
}

type Deployer interface {
    Deploy(machine *Machine) error
}

type MachineRepository interface {
    Get(id int) (*Machine, error)
    List() ([]*Machine, error)
}
```

**Constants and Enums**:

```go
// Exported constants - PascalCase
const (
    MaxHostnameLength = 255
    DefaultTimeout    = 30 * time.Second
)

// Enum-like constants
const (
    StatusNew       = "new"
    StatusReady     = "ready"
    StatusDeployed  = "deployed"
)

// Iota enums
type MachineStatus int

const (
    StatusUnknown MachineStatus = iota
    StatusPending
    StatusActive
)
```

**Acronyms (Keep Case Consistent)**:

```go
// Exported: All caps for acronyms
type HTTPAPI struct {}
type URLParser struct {}
type IDGenerator struct {}
var APIKey string

// Unexported: Lowercase first letter, then caps
var httpClient *http.Client
var urlPrefix string
var apiEndpoint string
```

### Descriptive Names Over Comments

**Bad: Unclear names requiring comments**:

```python
# NEVER use unclear names that need explanation
def proc_m(m, z):  # Process machine in zone
    # m is machine ID
    # z is zone ID
    pass

x = get_data()  # Get machine list
t = datetime.now()  # Deployment time
```

**Good: Self-documenting names**:

```python
# Names explain themselves
def deploy_machine_in_zone(machine_id: int, zone_id: int) -> Deployment:
    pass

machines = get_all_machines()
deployment_start_time = datetime.now()
```

### Test Naming

**Python Test Functions (Descriptive sentences)**:

```python
# Pattern: test_<method>_<condition>_<expected_result>
def test_get_machine_with_valid_id_returns_machine():
    pass

def test_get_machine_with_invalid_id_raises_not_found():
    pass

def test_create_machine_with_duplicate_hostname_fails():
    pass

def test_deploy_machine_when_not_ready_raises_error():
    pass

def test_list_machines_with_zone_filter_returns_only_zone_machines():
    pass
```

**Go Test Functions (TestXxx pattern)**:

```go
// Pattern: Test<Function>_<Condition>
func TestGetMachine_ValidID_ReturnsMachine(t *testing.T) {
    // Test
}

func TestGetMachine_InvalidID_ReturnsError(t *testing.T) {
    // Test
}

func TestDeployMachine_MachineNotReady_ReturnsError(t *testing.T) {
    // Test
}
```

**Test Fixture Names (Describe what they provide)**:

```python
@pytest.fixture
def sample_machine():  # Not 'fixture1' or 'data'
    return Machine(id=1, hostname="test-machine")

@pytest.fixture
def machine_with_interfaces():
    machine = Machine(id=1, hostname="test")
    machine.interfaces = [Interface(name="eth0")]
    return machine

@pytest.fixture
def deployed_machine_in_production_zone():
    pass
```

### File and Module Naming

**Python (snake_case)**:

```
# Modules and packages
machine_service.py
deployment_workflow.py
machine_repository.py

# Test files mirror source files
test_machine_service.py
test_deployment_workflow.py
```

**Go (lowercase, no underscores)**:

```
# Go files
machine.go
machineservice.go
deployment.go

# Test files
machine_test.go
machineservice_test.go
```

### API and Model Naming

**Request/Response Models**:

```python
# Pattern: <Entity><Request|Response>
class MachineRequest(BaseModel):
    hostname: str
    zone_id: int

class MachineResponse(BaseModel):
    id: int
    hostname: str
    status: str

class DeploymentRequest(BaseModel):
    machine_id: int
    image_url: str

class DeploymentStatusResponse(BaseModel):
    status: str
    progress: float
```

**Repository and Service Names**:

```python
# Pattern: <Entity>Repository, <Entity>Service
class MachineRepository:
    pass

class MachineService:
    pass

class ZoneRepository:
    pass

class DeploymentService:
    pass
```

### Database Naming

**Table Names (plural, snake_case)**:

```python
# Django/SQLAlchemy tables
class Meta:
    db_table = "maasserver_machines"
    db_table = "maasserver_zones"
    db_table = "maasserver_network_interfaces"
```

**Column Names (snake_case)**:

```python
# Database columns
hostname = Column(String(255))
zone_id = Column(Integer, ForeignKey("zones.id"))
cpu_count = Column(Integer)
created_at = Column(DateTime)
updated_at = Column(DateTime)
```

## Anti-patterns

### ❌ Single Letter Variables (Except Loops)

```python
# NEVER use single letters (except i, j in simple loops)
m = get_machine()  # What is m?
z = 5  # What does z represent?
t = datetime.now()  # Is it time? timestamp? timeout?

# Correct
machine = get_machine()
zone_count = 5
deployment_start_time = datetime.now()

# Acceptable: Loop counters
for i in range(10):
    pass
```

### ❌ Abbreviated Names

```python
# NEVER use unclear abbreviations
def proc_mach_depl(m_id):  # Unreadable
    pass

mach_repo = MachineRepo()  # Inconsistent
usr_mgr = UserManager()  # Hard to search

# Correct
def process_machine_deployment(machine_id):
    pass

machine_repository = MachineRepository()
user_manager = UserManager()
```

### ❌ Hungarian Notation

```python
# NEVER use type prefixes (Python is typed differently)
str_hostname = "node1"  # Wrong
int_count = 5  # Wrong
list_machines = []  # Wrong

# Correct: Use type hints instead
hostname: str = "node1"
count: int = 5
machines: list[Machine] = []
```

### ❌ Redundant Naming

```python
# NEVER be redundant
class MachineClass:  # 'Class' is redundant
    pass

def get_machine_function():  # 'function' is redundant
    pass

machine_variable = Machine()  # 'variable' is redundant

# Correct
class Machine:
    pass

def get_machine():
    pass

machine = Machine()
```

### ❌ Misleading Names

```python
# NEVER use misleading names
def get_machine(machine_id):
    # Wrong: Function modifies state but name says 'get'
    machine = Machine.objects.get(id=machine_id)
    machine.delete()  # Misleading!
    return machine

# Correct: Name reflects action
def delete_machine(machine_id):
    machine = Machine.objects.get(id=machine_id)
    machine.delete()
    return machine
```

### ❌ Magic Numbers Without Names

```python
# NEVER use magic numbers
if len(hostname) > 255:  # What is 255?
    raise ValueError()

time.sleep(30)  # What is 30?

# Correct: Named constants
MAX_HOSTNAME_LENGTH = 255
DEFAULT_TIMEOUT_SECONDS = 30

if len(hostname) > MAX_HOSTNAME_LENGTH:
    raise ValueError()

time.sleep(DEFAULT_TIMEOUT_SECONDS)
```

## Related Skills

- **Code Clarity**: [code-clarity.md](code-clarity.md) - Writing readable code
- **Minimal Comments**: [minimal-comments.md](minimal-comments.md) - Letting names explain code
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Python style guide
- **Go Patterns**: [../languages/go-patterns.md](../languages/go-patterns.md) - Go conventions
- **Test Quality**: [test-code-quality.md](test-code-quality.md) - Clear test names

## Naming Principles

1. **Clarity Over Brevity**: `deployment_start_time` > `dep_time` > `t`
2. **Consistency**: Use same terms throughout (not `get_machine` and `fetch_machine`)
3. **Searchability**: Full words are easier to search than abbreviations
4. **Pronounceability**: Can you say it out loud? `machine_count` > `mch_cnt`
5. **Intention-Revealing**: Name shows purpose, not implementation
6. **Domain Language**: Use terms from the problem domain (machine, zone, deployment)
7. **No Mental Mapping**: Reader shouldn't translate names to understand them

## Quick Reference

| Element | Python | Go |
|---------|--------|-----|
| Variables | `snake_case` | `camelCase` (unexported), `PascalCase` (exported) |
| Functions | `snake_case` | `camelCase` (unexported), `PascalCase` (exported) |
| Classes/Structs | `PascalCase` | `PascalCase` |
| Constants | `UPPER_SNAKE_CASE` | `PascalCase` (exported), `camelCase` (unexported) |
| Private | `_leading_underscore` | `camelCase` (lowercase first letter) |
| Packages | `snake_case` | `lowercase` (no underscores) |
| Files | `snake_case.py` | `lowercase.go` |
| Tests | `test_description_of_test` | `TestDescriptionOfTest` |