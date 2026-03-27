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
    
    @model_validator(mode="after")
    def validate_model(self) -> "MachineRequest":
        if self.cpu_count < 1:
            raise ValueError("cpu_count must be positive")
        return self
```

For comprehensive Pydantic v2 patterns including field aliases and serialization, see [common-patterns.md](../common-patterns.md).

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

```python
# 1. Standard library
import json
from datetime import datetime

# 2. Third-party
from pydantic import BaseModel
from sqlalchemy import select

# 3. MAAS first-party
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.services.machines import MachineService
```

### Type Hints

```python
# Modern union syntax (Python 3.10+)
def get_machine(machine_id: int) -> Machine | None:
    pass

async def list_machines(zone_id: int | None = None) -> list[Machine]:
    pass
```

### Code Style

- **Line length**: 79 characters max
- **Quotes**: Double quotes for strings
- **Indentation**: 4 spaces
- **Formatting**: Use Ruff formatter

## Anti-patterns

### ❌ String Concatenation for SQL

```python
# NEVER do this - SQL injection risk
query = f"SELECT * FROM machines WHERE id = {machine_id}"
```

### ❌ Breaking Three-Tier Architecture

```python
# NEVER access database directly from API layer
@router.get("/machines/{id}")
async def get_machine(id: int, db: AsyncConnection = Depends()):
    result = await db.execute(select(MachineTable).where(...))  # Wrong
```

### ❌ Using Django ORM in V3 API

```python
# NEVER use Django ORM in new v3 API code
from maasserver.models import Machine  # Wrong layer
```

### ❌ Missing Type Annotations

```python
# NEVER omit type hints in new code
def process_machine(machine):  # Wrong: No type hints
    return machine.hostname
```



## Configuration Reference

- **Line length**: 79 characters (pyproject.toml)
- **Python version**: 3.9+ (check pyproject.toml)
- **Formatter**: Ruff
- **Linter**: Ruff (pycodestyle, pyflakes, isort, flake8-bugbear)
- **Type checker**: Pyright (for maascommon, maasservicelayer, maasapiserver, maastemporalworker)