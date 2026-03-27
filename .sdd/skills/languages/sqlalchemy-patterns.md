# SQLAlchemy Patterns

## Purpose

Define SQLAlchemy Core patterns for MAAS v3 API repository layer, including repository design, ClauseFactory for filters, QuerySpec integration, parameterized queries, and transaction management.

## When to Use

- Writing repository layer code in `maasservicelayer`
- Creating database queries for v3 API
- Implementing filterable list methods
- Building reusable query components
- Managing database transactions in service layer

**Note**: Use SQLAlchemy Core (not ORM) for all new v3 API code. Legacy code uses Django ORM.

## Pattern Examples

### Repository Structure

**Basic Repository**:

```python
from sqlalchemy import select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncConnection
from maasservicelayer.db.tables import MachineTable
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
        stmt = insert(MachineTable).values(**builder.model_dump()).returning(MachineTable)
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

### QuerySpec Integration

**Repository with QuerySpec**:

```python
from maasservicelayer.db.filters import QuerySpec

class MachineRepository:
    async def list(self, query: QuerySpec) -> list[Machine]:
        stmt = select(MachineTable)
        stmt = query.apply_to_statement(stmt)
        result = await self._connection.execute(stmt)
        return [Machine(**row._asdict()) for row in result]
```

**Service Layer Using QuerySpec**:

```python
from maasservicelayer.db.filters import QuerySpec

class MachineService:
    async def get_ready_machines(self, zone_id: int | None = None) -> list[Machine]:
        clauses = [MachineClauseFactory.with_status("ready")]
        if zone_id is not None:
            clauses.append(MachineClauseFactory.with_zone_id(zone_id))
        
        query = QuerySpec(where=clauses)
        return await self._repository.list(query)
```

### ClauseFactory Pattern

**Define Reusable Filters**:

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

### Parameterized Queries

```python
# Always use parameterized queries (automatic with SQLAlchemy)
stmt = select(MachineTable).where(MachineTable.c.hostname == hostname)
stmt = select(MachineTable).where(MachineTable.c.id.in_(machine_ids))

# Complex filters with AND/OR
from sqlalchemy import and_, or_

stmt = select(MachineTable).where(
    and_(
        MachineTable.c.zone_id == zone_id,
        MachineTable.c.status == "ready",
    )
)
```

### Joins

```python
from sqlalchemy import join

stmt = (
    select(MachineTable, ZoneTable)
    .select_from(
        join(
            MachineTable,
            ZoneTable,
            MachineTable.c.zone_id == ZoneTable.c.id,
        )
    )
    .where(ZoneTable.c.name == "production")
)
```

### Aggregations

```python
from sqlalchemy import func

# Count
stmt = select(func.count(MachineTable.c.id)).where(MachineTable.c.status == "ready")
count = (await connection.execute(stmt)).scalar()

# Group by with aggregates
stmt = (
    select(
        MachineTable.c.zone_id,
        func.count(MachineTable.c.id).label("machine_count"),
        func.avg(MachineTable.c.cpu_count).label("avg_cpu"),
    )
    .group_by(MachineTable.c.zone_id)
)
```

### Ordering and Limiting

```python
# Order by
stmt = select(MachineTable).order_by(MachineTable.c.hostname)
stmt = select(MachineTable).order_by(MachineTable.c.created.desc())

# Multiple order columns
stmt = select(MachineTable).order_by(
    MachineTable.c.zone_id,
    MachineTable.c.hostname.asc(),
)

# Limit and offset
stmt = select(MachineTable).limit(10).offset(20)
```

### Insert Operations

```python
stmt = insert(MachineTable).values(
    hostname="node1",
    zone_id=1,
    cpu_count=4,
).returning(MachineTable)

result = await connection.execute(stmt)
row = result.one()
machine = Machine(**row._asdict())
```

### Update Operations

```python
stmt = (
    update(MachineTable)
    .where(MachineTable.c.id == machine_id)
    .values(status="allocated", owner_id=user_id)
    .returning(MachineTable)
)

result = await connection.execute(stmt)
row = result.one()
```

### Delete Operations

```python
stmt = delete(MachineTable).where(MachineTable.c.id == machine_id)
await connection.execute(stmt)
```

### Transactions

**Transaction in Repository**:

```python
class MachineRepository:
    async def create_with_interfaces(
        self,
        machine_data: MachineRequest,
        interfaces: list[InterfaceRequest],
    ) -> Machine:
        # Connection is already in transaction from service layer
        machine_stmt = insert(MachineTable).values(
            **machine_data.model_dump()
        ).returning(MachineTable)
        
        machine_result = await self._connection.execute(machine_stmt)
        machine_row = machine_result.one()
        machine_id = machine_row.id
        
        # Create interfaces in same transaction
        for interface in interfaces:
            interface_stmt = insert(InterfaceTable).values(
                machine_id=machine_id,
                **interface.model_dump(),
            )
            await self._connection.execute(interface_stmt)
        
        return Machine(**machine_row._asdict())
```

**Transaction in Service Layer**:

```python
class MachineService:
    async def create_machine_with_config(
        self,
        machine: MachineRequest,
        config: ConfigRequest,
    ) -> Machine:
        # Service layer manages transaction
        async with self._connection.begin():
            created_machine = await self._machine_repo.create(machine)
            await self._config_repo.create(created_machine.id, config)
            return created_machine
```

### Row Mapping to Models

```python
# Single row
result = await connection.execute(stmt)
row = result.one_or_none()
if row:
    machine = Machine(**row._asdict())

# Multiple rows
result = await connection.execute(stmt)
machines = [Machine(**row._asdict()) for row in result]

# With explicit field mapping
result = await connection.execute(stmt)
row = result.one()
machine = Machine(
    id=row.id,
    hostname=row.hostname,
    zone_id=row.zone_id,
)
```

### Subqueries

```python
# Scalar subquery
subq = (
    select(func.count(InterfaceTable.c.id))
    .where(InterfaceTable.c.machine_id == MachineTable.c.id)
    .scalar_subquery()
)

stmt = select(MachineTable.c.hostname, subq.label("interface_count"))
```

## Anti-patterns

### ❌ Using ORM Instead of Core

```python
# NEVER use SQLAlchemy ORM in v3 API
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Machine(Base):  # Wrong: Use Core tables
    __tablename__ = "machines"
```

### ❌ String Concatenation for SQL

```python
# NEVER build SQL with string concatenation
query = f"SELECT * FROM machines WHERE id = {machine_id}"  # SQL injection!
await connection.execute(text(query))  # Wrong

# Correct
stmt = select(MachineTable).where(MachineTable.c.id == machine_id)
```

### ❌ Not Using ClauseFactory

```python
# NEVER inline filters that will be reused
class MachineRepository:
    async def get_ready_in_zone(self, zone_id: int):
        # Wrong: Hard-coded, not reusable
        stmt = select(MachineTable).where(
            and_(
                MachineTable.c.status == "ready",
                MachineTable.c.zone_id == zone_id,
            )
        )

# Correct: Use ClauseFactory
async def get_ready_in_zone(self, zone_id: int):
    query = QuerySpec(where=[
        MachineClauseFactory.with_status("ready"),
        MachineClauseFactory.with_zone_id(zone_id),
    ])
    return await self.list(query)
```

### ❌ Ignoring QuerySpec

```python
# NEVER create custom list methods without QuerySpec support
class MachineRepository:
    async def list_ready(self):  # Wrong: Not filterable
        stmt = select(MachineTable).where(MachineTable.c.status == "ready")
        return await self._execute(stmt)

# Correct: Single list method with QuerySpec
async def list(self, query: QuerySpec):
    stmt = select(MachineTable)
    stmt = query.apply_to_statement(stmt)
    return await self._execute(stmt)
```

### ❌ Not Using Async Properly

```python
# NEVER use synchronous methods
def get_machine(self, id: int):  # Wrong: Should be async
    stmt = select(MachineTable).where(MachineTable.c.id == id)
    result = self._connection.execute(stmt)  # Wrong: Missing await

# Correct
async def get_machine(self, id: int):
    stmt = select(MachineTable).where(MachineTable.c.id == id)
    result = await self._connection.execute(stmt)
```

### ❌ Fetching All Rows When You Need One

```python
# NEVER fetch all when you need one
async def get_by_hostname(self, hostname: str):
    stmt = select(MachineTable)  # Wrong: No filter
    result = await self._connection.execute(stmt)
    all_machines = [Machine(**row._asdict()) for row in result]
    return next((m for m in all_machines if m.hostname == hostname), None)

# Correct
async def get_by_hostname(self, hostname: str):
    stmt = select(MachineTable).where(MachineTable.c.hostname == hostname)
    result = await self._connection.execute(stmt)
    row = result.one_or_none()
    return Machine(**row._asdict()) if row else None
```

### ❌ Not Handling NULL Properly

```python
# NEVER use == None for NULL checks
stmt = select(MachineTable).where(MachineTable.c.owner_id == None)  # Wrong

# Correct: Use is_() and is_not()
stmt = select(MachineTable).where(MachineTable.c.owner_id.is_(None))
stmt = select(MachineTable).where(MachineTable.c.owner_id.is_not(None))
```



## Core vs ORM Decision

| Feature | SQLAlchemy Core | SQLAlchemy ORM |
|---------|-----------------|----------------|
| **MAAS v3 API** | ✅ Use this | ❌ Don't use |
| **Explicit queries** | ✅ Yes | ⚠️ Hidden behind abstraction |
| **Performance** | ✅ Optimized | ⚠️ Overhead |
| **Async support** | ✅ Full support | ⚠️ Limited |
| **Learning curve** | ⚠️ SQL knowledge needed | ✅ Easier for beginners |
| **Query composability** | ✅ Excellent with QuerySpec | ⚠️ More complex |

**MAAS Standard**: Always use SQLAlchemy Core for v3 API code.

## Common Patterns Summary

1. **Repository**: Define `get_by_id`, `list`, `create`, `update`, `delete`
2. **QuerySpec**: Use for all `list` methods
3. **ClauseFactory**: Create reusable filters
4. **Async**: All repository methods are `async`
5. **Parameterized**: Never use string concatenation
6. **Transactions**: Manage at service layer, not repository
7. **Row Mapping**: Use `row._asdict()` for model instantiation

## Configuration

- **Connection**: `AsyncConnection` from SQLAlchemy
- **Database**: PostgreSQL
- **Driver**: asyncpg
- **Tables**: Defined in `maasservicelayer.db.tables`
- **Location**: `src/maasservicelayer/db/repositories/`
