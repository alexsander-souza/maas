# Backend Feature Composition

## Purpose

Complete workflow for implementing a backend feature in MAAS v3 API, combining repository layer, service layer, data models, testing, and security practices.

## When to Use

- Implementing new backend functionality in v3 API
- Adding new data entities with CRUD operations
- Building features that span repository → service → API layers
- Creating complete, tested, secure backend features

## Workflow

### 1. Define Data Model (Pydantic)

**Create Request/Response Models**:

```python
# src/maasservicelayer/models/machines.py
from pydantic import BaseModel, Field, field_validator
import re

class MachineRequest(BaseModel):
    """Request model for creating/updating machines."""
    hostname: str = Field(min_length=1, max_length=255)
    zone_id: int = Field(gt=0)
    cpu_count: int = Field(ge=1, le=256)
    memory: int = Field(gt=0, description="Memory in MB")
    
    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
        if not re.match(pattern, value.lower()):
            raise ValueError("Invalid hostname format")
        return value.lower()

class Machine(BaseModel):
    """Machine domain model."""
    id: int
    hostname: str
    zone_id: int
    cpu_count: int
    memory: int
    status: str
    created: datetime
    updated: datetime
```

**Skills**: [python-patterns.md](../languages/python-patterns.md), [input-validation.md](../techniques/input-validation.md)

### 2. Implement ClauseFactory (Query Filters)

```python
# src/maasservicelayer/db/filters.py
from maasservicelayer.db.filters import ClauseFactory
from maasservicelayer.db.tables import MachineTable
from sqlalchemy.sql.expression import ColumnElement

class MachineClauseFactory(ClauseFactory):
    @staticmethod
    def with_id(machine_id: int) -> ColumnElement[bool]:
        return MachineTable.c.id == machine_id
    
    @staticmethod
    def with_zone_id(zone_id: int) -> ColumnElement[bool]:
        return MachineTable.c.zone_id == zone_id
    
    @staticmethod
    def with_status(status: str) -> ColumnElement[bool]:
        return MachineTable.c.status == status
    
    @staticmethod
    def in_zone_list(zone_ids: list[int]) -> ColumnElement[bool]:
        return MachineTable.c.zone_id.in_(zone_ids)
```

**Skills**: [sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md)

### 3. Create Repository Layer

```python
# src/maasservicelayer/db/repositories/machines.py
from sqlalchemy import select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncConnection
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.tables import MachineTable
from maasservicelayer.models.machines import Machine, MachineRequest

class MachineRepository:
    def __init__(self, connection: AsyncConnection):
        self._connection = connection
    
    async def get_by_id(self, machine_id: int) -> Machine | None:
        stmt = select(MachineTable).where(MachineTable.c.id == machine_id)
        result = await self._connection.execute(stmt)
        row = result.one_or_none()
        return Machine(**row._asdict()) if row else None
    
    async def list(self, query: QuerySpec) -> list[Machine]:
        stmt = select(MachineTable)
        stmt = query.apply_to_statement(stmt)
        result = await self._connection.execute(stmt)
        return [Machine(**row._asdict()) for row in result]
    
    async def create(self, builder: MachineRequest) -> Machine:
        stmt = (
            insert(MachineTable)
            .values(**builder.model_dump())
            .returning(MachineTable)
        )
        result = await self._connection.execute(stmt)
        row = result.one()
        return Machine(**row._asdict())
    
    async def update(self, machine_id: int, builder: MachineRequest) -> Machine:
        stmt = (
            update(MachineTable)
            .where(MachineTable.c.id == machine_id)
            .values(**builder.model_dump())
            .returning(MachineTable)
        )
        result = await self._connection.execute(stmt)
        row = result.one()
        return Machine(**row._asdict())
    
    async def delete(self, machine_id: int) -> None:
        stmt = delete(MachineTable).where(MachineTable.c.id == machine_id)
        await self._connection.execute(stmt)
```

**Skills**: [sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md), [secure-coding.md](../techniques/secure-coding.md)

### 4. Implement Service Layer

```python
# src/maasservicelayer/services/machines.py
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.models.machines import Machine, MachineRequest

class MachineNotFoundError(Exception):
    def __init__(self, machine_id: int):
        self.machine_id = machine_id
        super().__init__(f"Machine {machine_id} not found")

class MachineService:
    def __init__(self, repository: MachineRepository):
        self._repository = repository
    
    async def get_by_id(self, machine_id: int) -> Machine:
        machine = await self._repository.get_by_id(machine_id)
        if not machine:
            raise MachineNotFoundError(machine_id)
        return machine
    
    async def list(self, zone_id: int | None = None) -> list[Machine]:
        clauses = []
        if zone_id is not None:
            clauses.append(MachineClauseFactory.with_zone_id(zone_id))
        
        query = QuerySpec(where=clauses)
        return await self._repository.list(query)
    
    async def create(self, request: MachineRequest) -> Machine:
        return await self._repository.create(request)
    
    async def update(self, machine_id: int, request: MachineRequest) -> Machine:
        # Verify machine exists
        await self.get_by_id(machine_id)
        return await self._repository.update(machine_id, request)
    
    async def delete(self, machine_id: int) -> None:
        # Verify machine exists
        await self.get_by_id(machine_id)
        await self._repository.delete(machine_id)
```

**Skills**: [python-patterns.md](../languages/python-patterns.md)

### 5. Write Repository Tests

```python
# tests/maasservicelayer/db/repositories/test_machines.py
import pytest
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.models.machines import MachineRequest

@pytest.mark.asyncio
async def test_create_machine_returns_instance_with_id(db_connection):
    repository = MachineRepository(db_connection)
    request = MachineRequest(
        hostname="test-node",
        zone_id=1,
        cpu_count=4,
        memory=8192,
    )
    
    machine = await repository.create(request)
    
    assert machine.id is not None
    assert machine.hostname == "test-node"

@pytest.mark.asyncio
async def test_get_by_id_returns_existing_machine(db_connection, sample_machine):
    repository = MachineRepository(db_connection)
    
    result = await repository.get_by_id(sample_machine.id)
    
    assert result is not None
    assert result.id == sample_machine.id

@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_invalid_id(db_connection):
    repository = MachineRepository(db_connection)
    
    result = await repository.get_by_id(99999)
    
    assert result is None

@pytest.mark.asyncio
async def test_list_with_zone_filter_returns_only_zone_machines(
    db_connection,
    machines_in_multiple_zones,
):
    repository = MachineRepository(db_connection)
    query = QuerySpec(where=[MachineClauseFactory.with_zone_id(1)])
    
    machines = await repository.list(query)
    
    assert all(m.zone_id == 1 for m in machines)
```

**Skills**: [python-testing.md](../languages/python-testing.md), [test-code-quality.md](../techniques/test-code-quality.md)

### 6. Write Service Tests

```python
# tests/maasservicelayer/services/test_machines.py
import pytest
from maasservicelayer.services.machines import MachineService, MachineNotFoundError

@pytest.fixture
def machine_service(machine_repository):
    return MachineService(machine_repository)

def test_get_by_id_returns_existing_machine(machine_service, sample_machine):
    machine = machine_service.get_by_id(sample_machine.id)
    assert machine.id == sample_machine.id

def test_get_by_id_raises_not_found_for_invalid_id(machine_service):
    with pytest.raises(MachineNotFoundError) as exc_info:
        machine_service.get_by_id(99999)
    assert exc_info.value.machine_id == 99999

def test_create_machine_validates_input(machine_service):
    invalid_request = MachineRequest(
        hostname="",  # Invalid
        zone_id=1,
        cpu_count=4,
        memory=8192,
    )
    
    with pytest.raises(ValidationError):
        machine_service.create(invalid_request)
```

**Skills**: [python-testing.md](../languages/python-testing.md)

### 7. Security Review Checklist

- [ ] Input validation on all user-provided data
- [ ] Parameterized database queries (automatic with SQLAlchemy Core)
- [ ] No hardcoded credentials
- [ ] Authorization checks (if applicable)
- [ ] Error messages don't expose sensitive information
- [ ] Secure defaults for any configurable options

**Skills**: [secure-coding.md](../techniques/secure-coding.md), [input-validation.md](../techniques/input-validation.md)

### 8. Code Quality Review

- [ ] Descriptive variable and function names
- [ ] No magic numbers (use named constants)
- [ ] Functions are focused and small
- [ ] Comments only explain "why", not "what"
- [ ] Tests have clear names, no verbose docstrings
- [ ] No trivial assertions in tests

**Skills**: [naming-conventions.md](../techniques/naming-conventions.md), [code-clarity.md](../techniques/code-clarity.md), [minimal-comments.md](../techniques/minimal-comments.md)

## Complete Example Structure

```
src/maasservicelayer/
├── models/
│   └── machines.py              # Pydantic models
├── db/
│   ├── tables.py                # SQLAlchemy table definitions
│   ├── filters.py               # ClauseFactory
│   └── repositories/
│       └── machines.py          # Repository implementation
└── services/
    └── machines.py              # Service layer

tests/maasservicelayer/
├── db/repositories/
│   └── test_machines.py         # Repository tests
└── services/
    └── test_machines.py         # Service tests
```

## Related Skills

- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Three-tier architecture
- **SQLAlchemy**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md) - Repository patterns
- **Python Testing**: [../languages/python-testing.md](../languages/python-testing.md) - Testing strategies
- **Secure Coding**: [../techniques/secure-coding.md](../techniques/secure-coding.md) - Security practices
- **Input Validation**: [../techniques/input-validation.md](../techniques/input-validation.md) - Validating requests
- **API Endpoint**: [api-endpoint.md](api-endpoint.md) - Adding HTTP layer

## Workflow Summary

1. **Models**: Define Pydantic request/response models with validation
2. **ClauseFactory**: Create reusable query filters
3. **Repository**: Implement data access with QuerySpec support
4. **Service**: Add business logic layer
5. **Tests**: Write repository and service tests
6. **Security**: Review for vulnerabilities
7. **Quality**: Check naming, clarity, comments

## Common Patterns

- **Three-Tier**: Repository → Service → API (add API in separate composition)
- **QuerySpec**: All list methods support filtering
- **Builder Pattern**: Use Pydantic models for create/update
- **Validation**: Pydantic validators catch bad input early
- **Async**: All repository methods are async
- **Testing**: Test each layer independently with fixtures