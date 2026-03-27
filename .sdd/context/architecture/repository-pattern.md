# Repository Pattern

## Overview

The Repository Pattern is a data access pattern that encapsulates the logic required to access data sources. In MAAS, repositories provide a clean abstraction layer between the service layer and the database, using SQLAlchemy Core for all database operations.

## Purpose

The repository pattern serves several critical purposes in MAAS:

1. **Abstraction**: Hides database implementation details from business logic
2. **Testability**: Enables easy mocking of data access in service tests
3. **Maintainability**: Centralizes data access logic in one place
4. **Flexibility**: Allows changing data storage mechanisms without affecting business logic
5. **Reusability**: Provides reusable query components and filters

## MAAS Implementation

### Technology Stack

- **SQLAlchemy Core**: Used exclusively (NOT the ORM)
- **Raw SQL Queries**: Built using SQLAlchemy's expression language
- **Table Definitions**: Centralized in `src/maasservicelayer/db/tables.py`
- **Migrations**: Managed through Alembic

### Why SQLAlchemy Core (Not ORM)?

MAAS deliberately uses SQLAlchemy Core instead of the ORM for several reasons:

1. **Performance**: Core is lighter weight and more performant
2. **Explicit Queries**: Queries are explicit and visible, not hidden behind magic
3. **Control**: Fine-grained control over SQL generation
4. **Simplicity**: Avoids ORM complexity and session management
5. **Migration Path**: Easier to migrate from Django ORM gradually

## Base Repository Classes

### BaseRepository

Located in `src/maasservicelayer/db/repositories/base.py`

Provides full CRUD operations for entities:

```python
class BaseRepository(Generic[T]):
    """Base repository with full CRUD operations."""
    
    async def get_by_id(self, id: int) -> T | None:
        """Retrieve a single entity by ID."""
        
    async def get_one(self, query: QuerySpec) -> T:
        """Get one entity matching query, raise if not found or multiple."""
        
    async def list(self, query: QuerySpec) -> list[T]:
        """List entities matching query specification."""
        
    async def create(self, resource: Builder) -> T:
        """Create a new entity."""
        
    async def update(self, id: int, resource: Builder) -> T:
        """Update an existing entity."""
        
    async def delete(self, id: int) -> None:
        """Delete an entity by ID."""
```

### ReadOnlyRepository

For entities that should not be modified through the API:

```python
class ReadOnlyRepository(Generic[T]):
    """Repository for read-only access."""
    
    async def get_by_id(self, id: int) -> T | None:
        """Retrieve a single entity by ID."""
        
    async def get_one(self, query: QuerySpec) -> T:
        """Get one entity matching query."""
        
    async def list(self, query: QuerySpec) -> list[T]:
        """List entities matching query specification."""
```

## Key Patterns

### QuerySpec Pattern

`QuerySpec` encapsulates query parameters and is passed from services to repositories:

```python
from maasservicelayer.db.filters import QuerySpec

# In service layer
spec = QuerySpec(
    where=MachineClauseFactory.with_status("ready"),
    limit=10,
    offset=0
)
machines = await repository.list(query=spec)
```

**Benefits**:
- Type-safe query building
- Composable filters
- Pagination support
- Separation of query construction from execution

### ClauseFactory Pattern

`ClauseFactory` provides reusable, composable query filters:

```python
class MachineClauseFactory:
    """Reusable query clauses for machines."""
    
    @staticmethod
    def with_status(status: str) -> ClauseElement:
        """Filter machines by status."""
        return MachineTable.c.status == status
    
    @staticmethod
    def with_architecture(architecture: str) -> ClauseElement:
        """Filter machines by architecture."""
        return MachineTable.c.architecture == architecture
    
    @staticmethod
    def with_owner(owner_id: int) -> ClauseElement:
        """Filter machines by owner."""
        return MachineTable.c.owner_id == owner_id
```

**Usage**:
```python
# Compose multiple filters
spec = QuerySpec(
    where=and_(
        MachineClauseFactory.with_status("ready"),
        MachineClauseFactory.with_architecture("amd64")
    )
)
```

**Benefits**:
- Reusable across services
- Testable in isolation
- Self-documenting
- Prevents SQL duplication

### Builder Pattern

Builders encapsulate resource creation and updates:

```python
class MachineCreateBuilder:
    """Builder for creating machines."""
    
    def __init__(self):
        self._hostname = None
        self._architecture = None
        self._memory = None
    
    def with_hostname(self, hostname: str) -> Self:
        self._hostname = hostname
        return self
    
    def with_architecture(self, arch: str) -> Self:
        self._architecture = arch
        return self
    
    def build(self) -> dict:
        """Build the resource dictionary."""
        return {
            "hostname": self._hostname,
            "architecture": self._architecture,
            "memory": self._memory,
        }
```

**Usage**:
```python
# In service layer
machine = await repository.create(
    MachineCreateBuilder()
        .with_hostname("machine-1")
        .with_architecture("amd64")
        .build()
)
```

## Repository Implementation Example

### Complete Example

```python
from sqlalchemy import select, update, delete
from maasservicelayer.db.repositories.base import BaseRepository
from maasservicelayer.db.tables import MachineTable
from maasservicelayer.models.machines import Machine

class MachineRepository(BaseRepository[Machine]):
    """Repository for machine data access."""
    
    def __init__(self, connection):
        super().__init__(MachineTable, connection)
    
    async def find_by_hostname(self, hostname: str) -> Machine | None:
        """Find a machine by hostname."""
        stmt = (
            select(self.table)
            .where(self.table.c.hostname == hostname)
        )
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        return self._row_to_model(row) if row else None
    
    async def list_by_status(self, status: str) -> list[Machine]:
        """List all machines with given status."""
        stmt = (
            select(self.table)
            .where(self.table.c.status == status)
            .order_by(self.table.c.hostname)
        )
        result = await self.connection.execute(stmt)
        return [self._row_to_model(row) for row in result.fetchall()]
    
    async def update_status(self, machine_id: int, status: str) -> Machine:
        """Update machine status."""
        stmt = (
            update(self.table)
            .where(self.table.c.id == machine_id)
            .values(status=status)
            .returning(*self.table.c)
        )
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        if not row:
            raise NotFoundException(f"Machine {machine_id} not found")
        return self._row_to_model(row)
    
    def _row_to_model(self, row) -> Machine:
        """Convert database row to domain model."""
        return Machine(
            id=row.id,
            hostname=row.hostname,
            status=row.status,
            architecture=row.architecture,
            created=row.created,
            updated=row.updated,
        )
```

## Database Connection Management

Repositories receive a database connection from the service layer:

```python
# In service layer
async with self.db_pool.get_connection() as connection:
    repository = MachineRepository(connection)
    machine = await repository.get_by_id(machine_id)
```

**Key Points**:
- Repositories don't manage connections themselves
- Connection management is a service layer concern
- Enables transaction boundaries at service level
- Connection is passed as dependency

## Testing Repositories

### Test with Real Database

Repositories should be tested with a real database connection, not mocks:

```python
import pytest
from maasservicelayer.db.repositories.machines import MachineRepository

@pytest.mark.asyncio
async def test_find_by_hostname(db_connection):
    """Test finding machine by hostname."""
    repository = MachineRepository(db_connection)
    
    # Setup test data
    machine = await repository.create(
        MachineCreateBuilder()
            .with_hostname("test-machine")
            .build()
    )
    
    # Test
    result = await repository.find_by_hostname("test-machine")
    
    # Assert
    assert result is not None
    assert result.hostname == "test-machine"
    assert result.id == machine.id
```

### Use RepositoryCommonTests

MAAS provides `RepositoryCommonTests` base class for standard test coverage:

```python
from maastesting.repository import RepositoryCommonTests

class TestMachineRepository(RepositoryCommonTests):
    """Test suite for MachineRepository."""
    
    def get_repository_class(self):
        return MachineRepository
    
    def get_create_builder(self):
        return MachineCreateBuilder().with_hostname("test")
```

## Best Practices

### Do: Keep Repositories Focused on Data Access

✅ **Good**:
```python
class MachineRepository:
    async def get_by_id(self, machine_id: int) -> Machine | None:
        stmt = select(self.table).where(self.table.c.id == machine_id)
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        return self._row_to_model(row) if row else None
```

### Do: Use SQLAlchemy Core Expression Language

✅ **Good**:
```python
stmt = (
    select(MachineTable)
    .where(MachineTable.c.status == "ready")
    .order_by(MachineTable.c.hostname)
)
```

### Do: Return Domain Models

✅ **Good**:
```python
def _row_to_model(self, row) -> Machine:
    return Machine(
        id=row.id,
        hostname=row.hostname,
        status=row.status,
    )
```

### Do: Use Explicit Queries

✅ **Good**:
```python
# Clear what columns are selected
stmt = select(
    MachineTable.c.id,
    MachineTable.c.hostname,
    MachineTable.c.status
).where(...)
```

### Don't: Include Business Logic

❌ **Bad**:
```python
class MachineRepository:
    async def create(self, resource: dict) -> Machine:
        # Business validation doesn't belong here
        if resource["memory"] < MIN_MEMORY:
            raise ValidationError("Insufficient memory")
        
        stmt = insert(self.table).values(**resource)
        await self.connection.execute(stmt)
```

✅ **Good** (validation in service layer):
```python
class MachineRepository:
    async def create(self, resource: dict) -> Machine:
        stmt = insert(self.table).values(**resource).returning(*self.table.c)
        result = await self.connection.execute(stmt)
        return self._row_to_model(result.fetchone())
```

### Don't: Use SQLAlchemy ORM

❌ **Bad**:
```python
from sqlalchemy.orm import Session

class MachineRepository:
    def __init__(self, session: Session):
        self.session = session
    
    async def get_by_id(self, id: int):
        return self.session.query(Machine).filter_by(id=id).first()
```

✅ **Good** (use Core):
```python
class MachineRepository:
    def __init__(self, connection):
        self.connection = connection
    
    async def get_by_id(self, id: int):
        stmt = select(MachineTable).where(MachineTable.c.id == id)
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        return self._row_to_model(row) if row else None
```

### Don't: Mix Concerns

❌ **Bad**:
```python
class MachineRepository:
    async def create_and_notify(self, resource: dict) -> Machine:
        # Data access + side effects mixed
        machine = await self._insert(resource)
        await self._send_notification(machine)  # Side effect
        return machine
```

✅ **Good** (side effects in service layer):
```python
# Repository - just data access
class MachineRepository:
    async def create(self, resource: dict) -> Machine:
        return await self._insert(resource)

# Service - orchestrates side effects
class MachineService:
    async def create(self, resource: dict) -> Machine:
        machine = await self.repository.create(resource)
        await self.notification_service.notify_created(machine)
        return machine
```

## Common Query Patterns

### Filtering with WHERE Clauses

```python
stmt = select(MachineTable).where(
    and_(
        MachineTable.c.status == "ready",
        MachineTable.c.architecture == "amd64"
    )
)
```

### Joins

```python
stmt = (
    select(MachineTable, OwnerTable)
    .join(OwnerTable, MachineTable.c.owner_id == OwnerTable.c.id)
    .where(MachineTable.c.status == "ready")
)
```

### Pagination

```python
stmt = (
    select(MachineTable)
    .where(MachineTable.c.status == "ready")
    .order_by(MachineTable.c.id)
    .limit(spec.limit)
    .offset(spec.offset)
)
```

### Aggregation

```python
from sqlalchemy import func

stmt = (
    select(
        MachineTable.c.status,
        func.count(MachineTable.c.id).label("count")
    )
    .group_by(MachineTable.c.status)
)
```

### Using RETURNING for Inserts/Updates

```python
stmt = (
    insert(MachineTable)
    .values(**resource)
    .returning(*MachineTable.c)  # Return all columns
)
result = await connection.execute(stmt)
row = result.fetchone()
return self._row_to_model(row)
```

## Table Synchronization

Keep table definitions in `src/maasservicelayer/db/tables.py` synchronized with actual database schema:

```python
from sqlalchemy import Table, Column, Integer, String, MetaData

metadata = MetaData()

MachineTable = Table(
    "maasserver_node",  # Django table name
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hostname", String(255), nullable=False),
    Column("status", String(50), nullable=False),
    Column("architecture", String(50)),
)
```

## Migration Strategy

When migrating from Django ORM to repositories:

1. Create table definition in `tables.py`
2. Implement repository with basic CRUD
3. Create corresponding service
4. Write tests for repository (with real DB)
5. Write tests for service (with mocked repository)
6. Update API handlers to use new service
7. Deprecate old Django code path

## Related Documentation

- **Three-Tier Architecture**: See `architecture/three-tier-architecture.md`
- **Service Layer**: See `subsystems/maasservicelayer.md`
- **Database Migrations**: See `subsystems/maasservicelayer.md#migrations`

## References

- [SQLAlchemy Core Documentation](https://docs.sqlalchemy.org/en/20/core/)
- Martin Fowler's [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)
- `src/maasservicelayer/README.md` - Service layer architecture
- `src/maasservicelayer/db/repositories/base.py` - Base repository implementation