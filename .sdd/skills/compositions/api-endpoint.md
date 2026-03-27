# API Endpoint Composition

## Purpose

Complete workflow for creating a v3 API endpoint in MAAS, combining repository patterns, service layer logic, API handlers, validation, security, and testing.

## When to Use

- Creating new REST API endpoints in v3 API
- Implementing CRUD operations for resources
- Adding filtered list endpoints
- Building endpoints with request/response validation

## Complete Workflow

### Step 1: Define Request/Response Models

**Create Pydantic models for validation**:

```python
# src/maasapiserver/v3/api/models/machines.py
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
        # Whitelist validation
        if not re.match(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$', value.lower()):
            raise ValueError("Invalid hostname format")
        return value.lower()

class MachineResponse(BaseModel):
    """Response model for machine data."""
    id: int
    hostname: str
    zone_id: int
    cpu_count: int
    memory: int
    status: str
    
    @classmethod
    def from_model(cls, machine: Machine) -> "MachineResponse":
        return cls(
            id=machine.id,
            hostname=machine.hostname,
            zone_id=machine.zone_id,
            cpu_count=machine.cpu_count,
            memory=machine.memory,
            status=machine.status,
        )
```

**Skills Applied**: [python-patterns.md](../languages/python-patterns.md), [input-validation.md](../techniques/input-validation.md)

### Step 2: Create Repository Layer

**Implement data access with SQLAlchemy Core**:

```python
# src/maasservicelayer/db/repositories/machines.py
from sqlalchemy import select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncConnection
from maasservicelayer.db.tables import MachineTable
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.models.machines import Machine

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

**ClauseFactory for filters**:

```python
# src/maasservicelayer/db/filters.py
from sqlalchemy.sql.expression import ColumnElement

class MachineClauseFactory:
    @staticmethod
    def with_zone_id(zone_id: int) -> ColumnElement[bool]:
        return MachineTable.c.zone_id == zone_id
    
    @staticmethod
    def with_status(status: str) -> ColumnElement[bool]:
        return MachineTable.c.status == status
```

**Skills Applied**: [sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md), [secure-coding.md](../techniques/secure-coding.md)

### Step 3: Create Service Layer

**Implement business logic**:

```python
# src/maasservicelayer/services/machines.py
from maasservicelayer.db.repositories.machines import MachineRepository
from maasservicelayer.db.filters import QuerySpec, MachineClauseFactory
from maasservicelayer.models.machines import Machine
from maasapiserver.v3.api.models.machines import MachineRequest

class MachineNotFoundError(Exception):
    """Raised when machine is not found."""
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
    
    async def list(
        self,
        zone_id: int | None = None,
        status: str | None = None,
    ) -> list[Machine]:
        clauses = []
        if zone_id is not None:
            clauses.append(MachineClauseFactory.with_zone_id(zone_id))
        if status is not None:
            clauses.append(MachineClauseFactory.with_status(status))
        
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

**Skills Applied**: [python-patterns.md](../languages/python-patterns.md)

### Step 4: Create API Endpoint

**FastAPI router with handlers**:

```python
# src/maasapiserver/v3/api/routers/machines.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from maasapiserver.v3.api.models.machines import MachineRequest, MachineResponse
from maasservicelayer.services.machines import MachineService, MachineNotFoundError

router = APIRouter(prefix="/machines", tags=["machines"])

async def get_machine_service() -> MachineService:
    # Dependency injection - get service from request context
    pass

@router.get("/{machine_id}", response_model=MachineResponse)
async def get_machine(
    machine_id: int,
    service: MachineService = Depends(get_machine_service),
) -> MachineResponse:
    """Get a machine by ID."""
    try:
        machine = await service.get_by_id(machine_id)
        return MachineResponse.from_model(machine)
    except MachineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine {machine_id} not found",
        )

@router.get("", response_model=list[MachineResponse])
async def list_machines(
    zone_id: int | None = Query(None, gt=0),
    status: str | None = Query(None),
    service: MachineService = Depends(get_machine_service),
) -> list[MachineResponse]:
    """List machines with optional filters."""
    machines = await service.list(zone_id=zone_id, status=status)
    return [MachineResponse.from_model(m) for m in machines]

@router.post("", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
async def create_machine(
    request: MachineRequest,
    service: MachineService = Depends(get_machine_service),
) -> MachineResponse:
    """Create a new machine."""
    machine = await service.create(request)
    return MachineResponse.from_model(machine)

@router.put("/{machine_id}", response_model=MachineResponse)
async def update_machine(
    machine_id: int,
    request: MachineRequest,
    service: MachineService = Depends(get_machine_service),
) -> MachineResponse:
    """Update an existing machine."""
    try:
        machine = await service.update(machine_id, request)
        return MachineResponse.from_model(machine)
    except MachineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine {machine_id} not found",
        )

@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_machine(
    machine_id: int,
    service: MachineService = Depends(get_machine_service),
) -> None:
    """Delete a machine."""
    try:
        await service.delete(machine_id)
    except MachineNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine {machine_id} not found",
        )
```

**Skills Applied**: [python-patterns.md](../languages/python-patterns.md), [input-validation.md](../techniques/input-validation.md)

### Step 5: Add Authorization

**Check permissions in endpoints**:

```python
from maasapiserver.v3.auth import require_permission

@router.post("", response_model=MachineResponse, status_code=status.HTTP_201_CREATED)
async def create_machine(
    request: MachineRequest,
    service: MachineService = Depends(get_machine_service),
    user: User = Depends(require_permission("machine.create")),
) -> MachineResponse:
    """Create a new machine (requires permission)."""
    machine = await service.create(request)
    return MachineResponse.from_model(machine)
```

**Skills Applied**: [secure-coding.md](../techniques/secure-coding.md)

### Step 6: Write Tests

**Repository Tests**:

```python
# tests/maasservicelayer/db/repositories/test_machines.py
import pytest
from maasservicelayer.db.repositories.machines import MachineRepository
from maasapiserver.v3.api.models.machines import MachineRequest

@pytest.mark.asyncio
async def test_create_machine_returns_instance_with_id(machine_repository):
    request = MachineRequest(hostname="test-node", zone_id=1, cpu_count=4, memory=8192)
    
    machine = await machine_repository.create(request)
    
    assert machine.id is not None
    assert machine.hostname == "test-node"

@pytest.mark.asyncio
async def test_get_by_id_returns_existing_machine(machine_repository, sample_machine):
    result = await machine_repository.get_by_id(sample_machine.id)
    
    assert result is not None
    assert result.id == sample_machine.id
```

**Service Tests**:

```python
# tests/maasservicelayer/services/test_machines.py
import pytest
from maasservicelayer.services.machines import MachineService, MachineNotFoundError

@pytest.mark.asyncio
async def test_get_by_id_raises_not_found_for_invalid_id(machine_service):
    with pytest.raises(MachineNotFoundError):
        await machine_service.get_by_id(99999)

@pytest.mark.asyncio
async def test_list_filters_by_zone_id(machine_service, machines_in_zones):
    machines = await machine_service.list(zone_id=1)
    
    assert len(machines) > 0
    assert all(m.zone_id == 1 for m in machines)
```

**API Tests**:

```python
# tests/maasapiserver/v3/api/test_machines.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_machine_returns_200_for_valid_id(client: AsyncClient, sample_machine):
    response = await client.get(f"/api/v3/machines/{sample_machine.id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_machine.id
    assert data["hostname"] == sample_machine.hostname

@pytest.mark.asyncio
async def test_get_machine_returns_404_for_invalid_id(client: AsyncClient):
    response = await client.get("/api/v3/machines/99999")
    
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_create_machine_returns_201_with_valid_data(client: AsyncClient):
    request_data = {
        "hostname": "new-machine",
        "zone_id": 1,
        "cpu_count": 4,
        "memory": 8192,
    }
    
    response = await client.post("/api/v3/machines", json=request_data)
    
    assert response.status_code == 201
    data = response.json()
    assert data["hostname"] == "new-machine"
    assert data["id"] is not None

@pytest.mark.asyncio
async def test_create_machine_returns_400_with_invalid_hostname(client: AsyncClient):
    request_data = {
        "hostname": "",  # Invalid
        "zone_id": 1,
        "cpu_count": 4,
        "memory": 8192,
    }
    
    response = await client.post("/api/v3/machines", json=request_data)
    
    assert response.status_code == 400
```

**Skills Applied**: [python-testing.md](../languages/python-testing.md), [test-code-quality.md](../techniques/test-code-quality.md)

## Security Checklist

- [ ] Input validation with Pydantic models
- [ ] Parameterized SQL queries (automatic with SQLAlchemy)
- [ ] Authorization checks on endpoints
- [ ] No secrets in code
- [ ] Proper error handling without exposing internals
- [ ] Rate limiting (if applicable)
- [ ] HTTPS only in production

**Skills Applied**: [secure-coding.md](../techniques/secure-coding.md), [secret-management.md](../techniques/secret-management.md)

## Code Quality Checklist

- [ ] Clear, descriptive names for functions and variables
- [ ] Minimal comments (code is self-documenting)
- [ ] Small, focused functions
- [ ] Consistent error handling
- [ ] Type hints on all functions
- [ ] Tests for all endpoints and logic paths

**Skills Applied**: [code-clarity.md](../techniques/code-clarity.md), [naming-conventions.md](../techniques/naming-conventions.md), [minimal-comments.md](../techniques/minimal-comments.md)

## Related Skills

- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Three-tier architecture
- **SQLAlchemy**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md) - Repository layer
- **Testing**: [../languages/python-testing.md](../languages/python-testing.md) - Test patterns
- **Security**: [../techniques/secure-coding.md](../techniques/secure-coding.md) - Security practices
- **Input Validation**: [../techniques/input-validation.md](../techniques/input-validation.md) - Request validation
- **Backend Feature**: [backend-feature.md](backend-feature.md) - Complete feature workflow

## File Structure

```
src/
├── maasapiserver/v3/api/
│   ├── models/
│   │   └── machines.py          # Request/Response models
│   └── routers/
│       └── machines.py          # API endpoints
├── maasservicelayer/
│   ├── db/
│   │   ├── repositories/
│   │   │   └── machines.py      # Data access
│   │   └── filters.py           # ClauseFactory
│   ├── services/
│   │   └── machines.py          # Business logic
│   └── models/
│       └── machines.py          # Domain models
tests/
├── maasapiserver/v3/api/
│   └── test_machines.py         # API integration tests
└── maasservicelayer/
    ├── db/repositories/
    │   └── test_machines.py     # Repository tests
    └── services/
        └── test_machines.py     # Service tests
```

## Summary

1. **Models**: Define Pydantic request/response models with validation
2. **Repository**: Implement SQLAlchemy Core data access with QuerySpec
3. **Service**: Add business logic and error handling
4. **API**: Create FastAPI endpoints with proper HTTP status codes
5. **Authorization**: Add permission checks
6. **Tests**: Write unit and integration tests for all layers
7. **Security**: Validate input, use parameterized queries, check permissions
8. **Quality**: Use clear names, minimal comments, focused functions