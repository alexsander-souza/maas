# Python Patterns

## Purpose

Define standard Python patterns used in MAAS v3 API and service layer code, including three-tier architecture, QuerySpec filtering, Pydantic v2 models, and async patterns.

## When to Use

- Writing new v3 API endpoints
- Creating service layer methods
- Defining data models and validators
- Implementing repository query methods
- Working with async/await in v3 API code

## Pattern Examples

### Three-Tier Architecture

MAAS v3 API follows a strict separation of concerns:

```python
# Repository Layer (data access)
class MachineRepository:
    def list(self, query: QuerySpec) -> list[Machine]:
        stmt = select(MachineTable)
        stmt = query.apply_to_statement(stmt)
        return self._execute(stmt)

# Service Layer (business logic)
class MachineService:
    def __init__(self, repository: MachineRepository):
        self._repository = repository
    
    def list_machines(self, query: QuerySpec) -> list[Machine]:
        return self._repository.list(query)

# API Layer (HTTP interface)
@router.get("/machines")
async def list_machines(
    service: MachineService = Depends(get_machine_service),
) -> list[MachineResponse]:
    machines = await service.list_machines(QuerySpec())
    return [MachineResponse.from_model(m) for m in machines]
```

**Flow**: API → Service → Repository → Database

### QuerySpec Pattern

Use `QuerySpec` for filtering in repository methods:

```python
from maasservicelayer.db.filters import QuerySpec

# In repository
def list(self, query: QuerySpec) -> list[Machine]:
    stmt = select(MachineTable)
    stmt = query.apply_to_statement(stmt)  # Apply filters dynamically
    return self._execute(stmt)

# In service
def get_machines_by_zone(self, zone_id: int) -> list[Machine]:
    query = QuerySpec(where=MachineClauseFactory.with_zone_id(zone_id))
    return self._repository.list(query)
```

### ClauseFactory Pattern

Implement reusable query filters:

```python
from maasservicelayer.db.filters import ClauseFactory
from sqlalchemy.sql.expression import ColumnElement

class MachineClauseFactory(ClauseFactory):
    @staticmethod
    def with_zone_id(zone_id: int) -> ColumnElement[bool]:
        return MachineTable.c.zone_id == zone_id
    
    @staticmethod
    def with_status(status: str) -> ColumnElement[bool]:
        return MachineTable.c.status == status
    
    @staticmethod
    def with_owner(owner_id: int | None) -> ColumnElement[bool]:
        if owner_id is None:
            return MachineTable.c.owner_id.is_(None)
        return MachineTable.c.owner_id == owner_id
```

### Pydantic v2 Models

**Basic Model Definition**:

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import ClassVar

class MachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    hostname: str = Field(min_length=1, max_length=255)
    zone_id: int = Field(gt=0)
    description: str | None = None
    
    # Non-field class attributes must use ClassVar
    _table_name: ClassVar[str] = "machines"
```

**Field Validators**:

```python
from pydantic import field_validator, model_validator

class MachineRequest(BaseModel):
    hostname: str
    cpu_count: int
    
    @field_validator("hostname", mode="before")
    @classmethod
    def normalize_hostname(cls, value: str) -> str:
        return value.strip().lower()
    
    @field_validator("cpu_count", mode="after")
    @classmethod
    def validate_cpu_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("cpu_count must be positive")
        return value
    
    @model_validator(mode="after")
    def validate_model(self) -> "MachineRequest":
        # Cross-field validation
        if self.hostname.startswith("test-") and self.cpu_count > 2:
            raise ValueError("Test machines limited to 2 CPUs")
        return self
```

**Field Aliases**:

```python
from pydantic import Field, AliasChoices

class MachineRequest(BaseModel):
    # Simple alias (input and output both use "mac_address")
    mac_address: str = Field(alias="macAddress")
    
    # Different input vs output names
    cpu_count: int = Field(
        validation_alias="cpuCount",      # Accept "cpuCount" on input
        serialization_alias="num_cpus"    # Output as "num_cpus"
    )
    
    # Accept multiple input formats
    zone_id: int = Field(
        validation_alias=AliasChoices("zone_id", "zoneId", "zone")
    )
    
    model_config = ConfigDict(populate_by_name=True)  # Accept field name too
```

**Serialization**:

```python
# Model to dict
data = machine.model_dump()
data_with_aliases = machine.model_dump(by_alias=True)

# Model to JSON
json_str = machine.model_dump_json()

# Dict to model
machine = MachineRequest.model_validate({"hostname": "node1", "zone_id": 1})

# JSON to model
machine = MachineRequest.model_validate_json('{"hostname": "node1", "zone_id": 1}')

# Get JSON schema
schema = MachineRequest.model_json_schema()
```

### Builder Pattern (Pydantic Models)

Use Pydantic models for creating/updating entities:

```python
# Service layer
class MachineService:
    async def create(self, builder: MachineRequest) -> Machine:
        return await self._repository.create(builder)
    
    async def update(self, id: int, builder: MachineRequest) -> Machine:
        return await self._repository.update(id, builder)

# API layer
@router.post("/machines")
async def create_machine(
    request: MachineRequest,
    service: MachineService = Depends(),
) -> MachineResponse:
    machine = await service.create(request)
    return MachineResponse.from_model(machine)
```

### Async Patterns

**V3 API (async/await)**:

```python
# Repository with async database access
class MachineRepository:
    def __init__(self, connection: AsyncConnection):
        self._connection = connection
    
    async def get_by_id(self, id: int) -> Machine | None:
        stmt = select(MachineTable).where(MachineTable.c.id == id)
        result = await self._connection.execute(stmt)
        row = result.one_or_none()
        return Machine(**row._asdict()) if row else None

# Service layer
async def get_machine(self, id: int) -> Machine:
    machine = await self._repository.get_by_id(id)
    if not machine:
        raise MachineNotFound(id)
    return machine
```

**Legacy Django (deferToDatabase)**:

```python
from twisted.internet.defer import inlineCallbacks
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase

@inlineCallbacks
def async_function_with_db():
    result = yield deferToDatabase(synchronous_db_function)
    return result

@transactional
def synchronous_db_function():
    # Django ORM queries here
    return Machine.objects.filter(status="ready")
```

### Import Organization

Follow isort order:

```python
# 1. Standard library
import json
from typing import TYPE_CHECKING
from datetime import datetime

# 2. Third-party
from pydantic import BaseModel, Field
from sqlalchemy import select
import pytest

# 3. MAAS first-party (in specific order)
from apiclient.utils import parse_url
from maasapiserver.common.api.base import API
from maascommon.enums import MachineStatus
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.services.machines import MachineService
from maastesting.fixtures import TestFixture
```

### Type Hints

```python
# Function signatures
def get_machine(machine_id: int) -> Machine | None:
    pass

async def list_machines(
    zone_id: int | None = None,
    limit: int = 100,
) -> list[Machine]:
    pass

# Modern union syntax (Python 3.10+)
def process(value: str | int | None) -> dict[str, Any]:
    pass

# For compatibility with Python 3.9
from typing import Optional, Union, Dict, Any

def process(value: Optional[Union[str, int]]) -> Dict[str, Any]:
    pass
```

### Code Style

```python
# Max 79 characters per line
def long_function_name(
    first_parameter: str,
    second_parameter: int,
    third_parameter: bool = False,
) -> dict[str, Any]:
    """Docstring is concise and focused on purpose."""
    result = {
        "key1": first_parameter,
        "key2": second_parameter,
    }
    return result

# Double quotes for strings
message = "Hello, world"
query = "SELECT * FROM machines WHERE id = ?"

# 4-space indentation
if condition:
    do_something()
    if nested_condition:
        do_nested_thing()
```

## Anti-patterns

### ❌ String Concatenation for SQL

```python
# NEVER do this
query = f"SELECT * FROM machines WHERE id = {machine_id}"
query = "SELECT * FROM machines WHERE name = '" + name + "'"
```

### ❌ Breaking Three-Tier Architecture

```python
# NEVER access database directly from API layer
@router.get("/machines/{id}")
async def get_machine(id: int, db: AsyncConnection = Depends()):
    # Wrong: API talking to database directly
    result = await db.execute(select(MachineTable).where(...))
    
# NEVER put business logic in repository
class MachineRepository:
    def create(self, builder: MachineRequest) -> Machine:
        # Wrong: Business logic in repository
        if builder.cpu_count > 100:
            raise ValueError("Too many CPUs")
        # Repository should only handle data access
```

### ❌ Using Django ORM in V3 API

```python
# NEVER use Django ORM in new v3 API code
from maasserver.models import Machine  # Wrong layer

@router.get("/machines")
async def list_machines():
    machines = Machine.objects.all()  # Wrong: Use SQLAlchemy Core
```

### ❌ Ignoring QuerySpec

```python
# NEVER create custom filtering without QuerySpec
class MachineRepository:
    def list_by_zone(self, zone_id: int) -> list[Machine]:
        # Wrong: Hard-coded filter, not composable
        stmt = select(MachineTable).where(MachineTable.c.zone_id == zone_id)
        
# Correct: Use QuerySpec
def list(self, query: QuerySpec) -> list[Machine]:
    stmt = select(MachineTable)
    stmt = query.apply_to_statement(stmt)
    return self._execute(stmt)
```

### ❌ Pydantic v1 Patterns

```python
# NEVER use Pydantic v1 syntax
class MachineRequest(BaseModel):
    class Config:  # Wrong: v1 syntax
        extra = "forbid"
        
# Correct: v2 syntax
class MachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

### ❌ Missing Type Annotations

```python
# NEVER omit type hints in new code
def process_machine(machine):  # Wrong: No type hints
    return machine.hostname
    
# Correct
def process_machine(machine: Machine) -> str:
    return machine.hostname
```

## Related Skills

- **Testing**: [python-testing.md](python-testing.md) - Test patterns for Python code
- **Django**: [django-patterns.md](django-patterns.md) - Legacy Django ORM patterns
- **SQLAlchemy**: [sqlalchemy-patterns.md](sqlalchemy-patterns.md) - Repository and query patterns
- **Code Clarity**: [../techniques/code-clarity.md](../techniques/code-clarity.md) - Readable code practices
- **Naming**: [../techniques/naming-conventions.md](../techniques/naming-conventions.md) - Naming standards
- **Backend Feature**: [../compositions/backend-feature.md](../compositions/backend-feature.md) - Complete workflow
- **API Endpoint**: [../compositions/api-endpoint.md](../compositions/api-endpoint.md) - Building endpoints

## Configuration Reference

- **Line length**: 79 characters (pyproject.toml)
- **Python version**: 3.9+ (check pyproject.toml)
- **Formatter**: Ruff
- **Linter**: Ruff (pycodestyle, pyflakes, isort, flake8-bugbear)
- **Type checker**: Pyright (for maascommon, maasservicelayer, maasapiserver, maastemporalworker)