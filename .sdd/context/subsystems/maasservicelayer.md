# maasservicelayer Subsystem

## Purpose

Business logic and data access layer for MAAS v3 API, implementing both the Service and Repository layers of the three-tier architecture. This subsystem encapsulates all business rules, domain logic, and database operations for the modern MAAS API.

**Status**: Active development - core of v3 API architecture.

## Location

`src/maasservicelayer`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **SQLAlchemy Core**: Database queries (NOT ORM)
- **Pydantic**: Data models and validation
- **Alembic**: Database migrations
- **PostgreSQL**: Database backend

### Key Libraries
- **sqlalchemy**: Core expression language for queries
- **pydantic**: Domain models and validation
- **alembic**: Schema migration management
- **pytest**: Testing framework
- **pytest-asyncio**: Async test support

## Architectural Constraints

### Two-Layer Structure

This subsystem contains two distinct architectural layers:

```
┌──────────────────────────────┐
│   maasapiserver (API)        │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   SERVICE LAYER              │  ← Business Logic
│   services/                  │
│   - Business rules           │
│   - Orchestration            │
│   - Transaction boundaries   │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   REPOSITORY LAYER           │  ← Data Access
│   db/repos/                  │
│   - SQL queries              │
│   - CRUD operations          │
│   - Query composition        │
└──────────┬───────────────────┘
           │
           ▼
      [PostgreSQL]
```

### Services Contain Business Logic

Services are the **only place** for business logic:
- Validation beyond data types
- Business rules enforcement
- Workflow orchestration
- Cross-repository coordination
- Transaction management
- Event emission

### Repositories Only Access Data

Repositories are **purely data access**:
- SQL query construction
- CRUD operations
- Row-to-model mapping
- Query composition
- NO business logic

### SQLAlchemy Core (Not ORM)

**Critical**: Use SQLAlchemy Core expression language, NOT the ORM:

✅ **Correct** (Core):
```python
stmt = select(MachineTable).where(MachineTable.c.id == machine_id)
result = await connection.execute(stmt)
```

❌ **Wrong** (ORM):
```python
machine = session.query(Machine).filter_by(id=machine_id).first()
```

**Why Core over ORM**:
- More explicit and performant
- Better control over SQL generation
- Simpler mental model
- Easier migration from Django
- No session management complexity

## Key Patterns

### Service Layer Patterns

#### BaseService

Services extend `BaseService` for full CRUD operations:

```python
from maasservicelayer.services.base import BaseService
from maasservicelayer.db.repositories.machines import MachineRepository

class MachineService(BaseService):
    """Service for machine business logic."""
    
    def __init__(
        self,
        repository: MachineRepository,
        event_service: EventService
    ):
        super().__init__(repository)
        self.event_service = event_service
    
    async def create(self, resource: MachineCreateBuilder) -> Machine:
        """Create a new machine with business logic."""
        # Business validation
        if not await self._validate_resources(resource):
            raise InsufficientResourcesError()
        
        # Create via repository
        machine = await self.repository.create(resource.build())
        
        # Side effects
        await self.event_service.emit_machine_created(machine)
        
        return machine
    
    async def update(self, id: int, resource: MachineUpdateBuilder) -> Machine:
        """Update machine with business rules."""
        # Get existing machine
        existing = await self.repository.get_by_id(id)
        if not existing:
            raise NotFoundException(f"Machine {id} not found")
        
        # Business validation
        if not await self._can_modify_machine(existing):
            raise ForbiddenError("Cannot modify deployed machine")
        
        # Update via repository
        machine = await self.repository.update(id, resource.build())
        
        # Side effects
        await self.event_service.emit_machine_updated(machine)
        
        return machine
    
    async def _validate_resources(self, resource: MachineCreateBuilder) -> bool:
        """Business logic: validate sufficient resources."""
        # Complex business rules here
        return True
    
    async def _can_modify_machine(self, machine: Machine) -> bool:
        """Business logic: check if machine can be modified."""
        return machine.status not in ["deploying", "deployed"]
```

#### ReadOnlyService

For read-only resources:

```python
from maasservicelayer.services.base import ReadOnlyService

class RegionService(ReadOnlyService):
    """Read-only service for regions."""
    
    async def get_by_name(self, name: str) -> Region | None:
        """Get region by name."""
        return await self.repository.find_by_name(name)
```

#### Service Coordination

Services orchestrate multiple repositories:

```python
class DeploymentService(BaseService):
    """Orchestrates machine deployment."""
    
    def __init__(
        self,
        machine_repo: MachineRepository,
        network_repo: NetworkRepository,
        storage_repo: StorageRepository,
        event_service: EventService
    ):
        self.machine_repo = machine_repo
        self.network_repo = network_repo
        self.storage_repo = storage_repo
        self.event_service = event_service
    
    async def deploy(self, machine_id: int, config: DeployConfig) -> Machine:
        """Deploy machine with full orchestration."""
        # Get resources from multiple repositories
        machine = await self.machine_repo.get_by_id(machine_id)
        networks = await self.network_repo.list_for_machine(machine_id)
        storage = await self.storage_repo.get_for_machine(machine_id)
        
        # Business validation across resources
        if not self._validate_deployment(machine, networks, storage, config):
            raise ValidationError("Invalid deployment configuration")
        
        # Execute deployment workflow
        machine = await self._update_machine_status(machine_id, "deploying")
        await self._configure_networks(machine_id, config.networks)
        await self._configure_storage(machine_id, config.storage)
        
        # Emit event
        await self.event_service.emit_deployment_started(machine)
        
        return machine
```

### Repository Layer Patterns

#### BaseRepository

Repositories extend `BaseRepository` for full CRUD:

```python
from maasservicelayer.db.repositories.base import BaseRepository
from maasservicelayer.db.tables import MachineTable
from maasservicelayer.models.machines import Machine

class MachineRepository(BaseRepository[Machine]):
    """Repository for machine data access."""
    
    def __init__(self, connection):
        super().__init__(MachineTable, connection)
    
    async def find_by_hostname(self, hostname: str) -> Machine | None:
        """Find machine by hostname."""
        stmt = (
            select(self.table)
            .where(self.table.c.hostname == hostname)
        )
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        return self._row_to_model(row) if row else None
    
    async def list_by_status(
        self, 
        status: str, 
        limit: int = 100,
        offset: int = 0
    ) -> list[Machine]:
        """List machines by status with pagination."""
        stmt = (
            select(self.table)
            .where(self.table.c.status == status)
            .order_by(self.table.c.hostname)
            .limit(limit)
            .offset(offset)
        )
        result = await self.connection.execute(stmt)
        return [self._row_to_model(row) for row in result.fetchall()]
    
    def _row_to_model(self, row) -> Machine:
        """Convert database row to domain model."""
        return Machine(
            id=row.id,
            system_id=row.system_id,
            hostname=row.hostname,
            status=row.status,
            architecture=row.architecture,
            created=row.created,
            updated=row.updated,
        )
```

#### QuerySpec Pattern

Use `QuerySpec` to pass filtering criteria from services to repositories:

```python
from maasservicelayer.db.filters import QuerySpec

# In service layer
spec = QuerySpec(
    where=MachineClauseFactory.with_status("ready"),
    limit=10,
    offset=0
)
machines = await repository.list(query=spec)

# In repository layer
async def list(self, query: QuerySpec) -> list[Machine]:
    """List machines matching query specification."""
    stmt = select(self.table)
    
    if query.where is not None:
        stmt = stmt.where(query.where)
    
    if query.order_by:
        stmt = stmt.order_by(*query.order_by)
    
    if query.limit:
        stmt = stmt.limit(query.limit)
    
    if query.offset:
        stmt = stmt.offset(query.offset)
    
    result = await self.connection.execute(stmt)
    return [self._row_to_model(row) for row in result.fetchall()]
```

#### ClauseFactory Pattern

Create reusable query filters with `ClauseFactory`:

```python
from sqlalchemy import ClauseElement, and_, or_

class MachineClauseFactory:
    """Reusable query clauses for machines."""
    
    @staticmethod
    def with_status(status: str) -> ClauseElement:
        """Filter by machine status."""
        return MachineTable.c.status == status
    
    @staticmethod
    def with_architecture(architecture: str) -> ClauseElement:
        """Filter by architecture."""
        return MachineTable.c.architecture == architecture
    
    @staticmethod
    def with_pool(pool_id: int) -> ClauseElement:
        """Filter by resource pool."""
        return MachineTable.c.pool_id == pool_id
    
    @staticmethod
    def ready_for_deployment() -> ClauseElement:
        """Filter machines ready for deployment."""
        return and_(
            MachineTable.c.status == "ready",
            MachineTable.c.power_state == "off",
            MachineTable.c.cpu_count > 0,
            MachineTable.c.memory > 0
        )
    
    @staticmethod
    def in_pool_with_architecture(
        pool_id: int, 
        architecture: str
    ) -> ClauseElement:
        """Combine multiple filters."""
        return and_(
            MachineClauseFactory.with_pool(pool_id),
            MachineClauseFactory.with_architecture(architecture)
        )

# Usage
spec = QuerySpec(
    where=MachineClauseFactory.ready_for_deployment()
)
ready_machines = await repository.list(query=spec)
```

### Builder Pattern

Use builders for create and update operations:

```python
from typing import Self

class MachineCreateBuilder:
    """Builder for creating machines."""
    
    def __init__(self):
        self._hostname: str | None = None
        self._architecture: str | None = None
        self._memory: int | None = None
        self._cpu_count: int | None = None
        self._pool_id: int | None = None
    
    def with_hostname(self, hostname: str) -> Self:
        """Set hostname."""
        self._hostname = hostname
        return self
    
    def with_architecture(self, architecture: str) -> Self:
        """Set architecture."""
        self._architecture = architecture
        return self
    
    def with_memory(self, memory: int) -> Self:
        """Set memory in MB."""
        self._memory = memory
        return self
    
    def with_cpu_count(self, cpu_count: int) -> Self:
        """Set CPU count."""
        self._cpu_count = cpu_count
        return self
    
    def with_pool(self, pool_id: int) -> Self:
        """Set resource pool."""
        self._pool_id = pool_id
        return self
    
    def build(self) -> dict:
        """Build the resource dictionary for repository."""
        return {
            "hostname": self._hostname,
            "architecture": self._architecture,
            "memory": self._memory,
            "cpu_count": self._cpu_count,
            "pool_id": self._pool_id,
        }

class MachineUpdateBuilder:
    """Builder for updating machines."""
    
    def __init__(self):
        self._updates: dict = {}
    
    def with_hostname(self, hostname: str) -> Self:
        """Update hostname."""
        self._updates["hostname"] = hostname
        return self
    
    def with_status(self, status: str) -> Self:
        """Update status."""
        self._updates["status"] = status
        return self
    
    def build(self) -> dict:
        """Build the update dictionary."""
        return self._updates

# Usage
machine = await service.create(
    MachineCreateBuilder()
        .with_hostname("machine-1")
        .with_architecture("amd64")
        .with_memory(8192)
        .with_cpu_count(4)
)
```

## Testing Requirements

### Test Repositories with Real Database

**Critical**: Always test repositories with a real database connection:

```python
import pytest
from maasservicelayer.db.repositories.machines import MachineRepository

@pytest.mark.asyncio
async def test_create_machine(db_connection):
    """Test creating a machine."""
    repository = MachineRepository(db_connection)
    
    # Create machine
    machine = await repository.create({
        "hostname": "test-machine",
        "architecture": "amd64",
        "memory": 8192,
        "cpu_count": 4
    })
    
    # Verify
    assert machine.id is not None
    assert machine.hostname == "test-machine"
    
    # Retrieve
    retrieved = await repository.get_by_id(machine.id)
    assert retrieved.hostname == "test-machine"

@pytest.mark.asyncio
async def test_find_by_hostname(db_connection):
    """Test finding machine by hostname."""
    repository = MachineRepository(db_connection)
    
    # Setup
    await repository.create({"hostname": "unique-machine"})
    
    # Test
    machine = await repository.find_by_hostname("unique-machine")
    
    # Assert
    assert machine is not None
    assert machine.hostname == "unique-machine"
```

### Test Services with Mocked Repositories

**Critical**: Always test services with mocked repositories:

```python
import pytest
from unittest.mock import Mock, AsyncMock
from maasservicelayer.services.machines import MachineService

@pytest.mark.asyncio
async def test_create_machine_service(mocker):
    """Test machine creation service logic."""
    # Mock repository
    mock_repo = mocker.Mock(spec=MachineRepository)
    mock_repo.create = AsyncMock(return_value=Machine(
        id=1,
        hostname="test-machine",
        status="new"
    ))
    
    # Mock event service
    mock_event_service = mocker.Mock()
    mock_event_service.emit_machine_created = AsyncMock()
    
    # Create service with mocked dependencies
    service = MachineService(mock_repo, mock_event_service)
    
    # Test
    builder = MachineCreateBuilder().with_hostname("test-machine")
    machine = await service.create(builder)
    
    # Assert
    assert machine.hostname == "test-machine"
    mock_repo.create.assert_called_once()
    mock_event_service.emit_machine_created.assert_called_once_with(machine)

@pytest.mark.asyncio
async def test_create_validation_error(mocker):
    """Test service validation logic."""
    mock_repo = mocker.Mock(spec=MachineRepository)
    service = MachineService(mock_repo, mocker.Mock())
    
    # Mock validation to fail
    service._validate_resources = AsyncMock(return_value=False)
    
    # Test
    builder = MachineCreateBuilder().with_hostname("test")
    
    with pytest.raises(InsufficientResourcesError):
        await service.create(builder)
    
    # Repository should not be called
    mock_repo.create.assert_not_called()
```

### Use Common Test Base Classes

MAAS provides base test classes for standard coverage:

```python
from maastesting.repository import RepositoryCommonTests
from maastesting.service import ServiceCommonTests

class TestMachineRepository(RepositoryCommonTests):
    """Standard repository tests."""
    
    def get_repository_class(self):
        return MachineRepository
    
    def get_create_resource(self):
        return {"hostname": "test-machine", "architecture": "amd64"}

class TestMachineService(ServiceCommonTests):
    """Standard service tests."""
    
    def get_service_class(self):
        return MachineService
    
    def get_create_builder(self):
        return MachineCreateBuilder().with_hostname("test-machine")
```

### Running Tests

```bash
# Run all service layer tests
pytest src/maasservicelayer/tests/

# Run only repository tests
pytest src/maasservicelayer/tests/db/repositories/

# Run only service tests
pytest src/maasservicelayer/tests/services/

# Run with database setup
pytest --db-setup src/maasservicelayer/tests/

# Run with coverage
pytest --cov=maasservicelayer src/maasservicelayer/tests/
```

## Database Management

### Table Definitions

All table definitions in `src/maasservicelayer/db/tables.py`:

```python
from sqlalchemy import Table, Column, Integer, String, DateTime, MetaData

metadata = MetaData()

MachineTable = Table(
    "maasserver_node",  # Django legacy table name
    metadata,
    Column("id", Integer, primary_key=True),
    Column("system_id", String(41), unique=True, nullable=False),
    Column("hostname", String(255), nullable=False),
    Column("status", String(50), nullable=False),
    Column("architecture", String(50)),
    Column("memory", Integer),
    Column("cpu_count", Integer),
    Column("created", DateTime, nullable=False),
    Column("updated", DateTime, nullable=False),
)
```

**Keep Synchronized**:
- Table definitions must match actual database schema
- Coordinate with Django models in `src/maasserver`
- Update after migrations

### Alembic Migrations

Use Alembic for schema migrations:

```bash
# Create a new migration
alembic revision -m "Add machine tags table"

# Auto-generate migration from model changes
alembic revision --autogenerate -m "Update machine schema"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# Show current version
alembic current

# Show migration history
alembic history
```

**Migration File Example**:
```python
"""Add machine tags table

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2024-01-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'abc123def456'
down_revision = 'previous_revision'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'maasserver_machine_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('machine_id', sa.Integer(), nullable=False),
        sa.Column('tag', sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['machine_id'], ['maasserver_node.id']),
    )

def downgrade():
    op.drop_table('maasserver_machine_tags')
```

### Database Connections

Connection management in services:

```python
from maasservicelayer.db.connection import DatabaseConnection

class MachineService:
    def __init__(self, db_pool: DatabaseConnection):
        self.db_pool = db_pool
    
    async def create(self, resource: MachineCreateBuilder) -> Machine:
        """Create with transaction."""
        async with self.db_pool.get_connection() as connection:
            repository = MachineRepository(connection)
            
            # All operations in this block share same connection/transaction
            machine = await repository.create(resource.build())
            await self._log_creation(connection, machine)
            
            return machine
```

## Development Guidelines

### Adding New Services

1. **Define Domain Model**: Create Pydantic model
2. **Create Table Definition**: Add to `db/tables.py`
3. **Implement Repository**: Extend `BaseRepository`
4. **Test Repository**: Use real database
5. **Implement Service**: Extend `BaseService`
6. **Test Service**: Use mocked repository
7. **Create Builders**: For create/update operations
8. **Add Clause Factory**: For reusable filters

### Adding New Repository Methods

```python
class MachineRepository(BaseRepository[Machine]):
    
    async def custom_query(self, param: str) -> list[Machine]:
        """Add custom query method."""
        stmt = (
            select(self.table)
            .where(self.table.c.custom_field == param)
            .order_by(self.table.c.created.desc())
        )
        result = await self.connection.execute(stmt)
        return [self._row_to_model(row) for row in result.fetchall()]
```

### Adding Business Logic

**Always in services, never in repositories**:

```python
class MachineService(BaseService):
    
    async def deploy(self, machine_id: int, config: DeployConfig) -> Machine:
        """Business logic for deployment."""
        # Get machine
        machine = await self.repository.get_by_id(machine_id)
        
        # Business validation
        if machine.status != "ready":
            raise InvalidStatusError("Machine must be ready to deploy")
        
        if not await self._has_sufficient_resources(machine, config):
            raise InsufficientResourcesError()
        
        # Execute workflow
        machine = await self._update_status(machine_id, "deploying")
        await self._configure_deployment(machine, config)
        
        return machine
    
    async def _has_sufficient_resources(
        self, 
        machine: Machine, 
        config: DeployConfig
    ) -> bool:
        """Private method for business logic."""
        return machine.memory >= config.min_memory
```

## Integration Points

### API Layer

Services consumed by API handlers:

```python
# In maasapiserver
from maasservicelayer.services.machines import MachineService

@handler
class MachineHandler(Handler):
    def __init__(self, service: MachineService):
        self.service = service
```

### Database

Shared PostgreSQL database:
- Same schema as Django application
- Coordinate migrations with `src/maasserver`
- Transaction isolation per request

### Event System

Services emit domain events:

```python
class MachineService(BaseService):
    def __init__(self, repository, event_service):
        super().__init__(repository)
        self.event_service = event_service
    
    async def create(self, resource):
        machine = await self.repository.create(resource.build())
        await self.event_service.emit({
            "type": "machine.created",
            "machine_id": machine.id
        })
        return machine
```

### Temporal Workflows

Services can trigger Temporal workflows:

```python
class DeploymentService(BaseService):
    def __init__(self, repository, temporal_client):
        super().__init__(repository)
        self.temporal_client = temporal_client
    
    async def deploy(self, machine_id: int, config: DeployConfig):
        # Update database
        machine = await self.repository.update_status(machine_id, "deploying")
        
        # Start Temporal workflow
        await self.temporal_client.start_workflow(
            "deploy-machine",
            args=[machine_id, config]
        )
        
        return machine
```

## Common Pitfalls

### Business Logic in Repositories

❌ **Don't**:
```python
class MachineRepository:
    async def create(self, resource: dict):
        # Business validation - WRONG!
        if resource["memory"] < 1024:
            raise ValidationError()
        
        stmt = insert(self.table).values(**resource)
        await self.connection.execute(stmt)
```

✅ **Do**:
```python
# Repository - just data access
class MachineRepository:
    async def create(self, resource: dict):
        stmt = insert(self.table).values(**resource)
        result = await self.connection.execute(stmt)
        return self._row_to_model(result.fetchone())

# Service - business logic
class MachineService:
    async def create(self, builder: MachineCreateBuilder):
        resource = builder.build()
        
        # Validation here
        if resource["memory"] < 1024:
            raise ValidationError()
        
        return await self.repository.create(resource)
```

### Using SQLAlchemy ORM

❌ **Don't**:
```python
from sqlalchemy.orm import Session

class MachineRepository:
    def __init__(self, session: Session):
        self.session = session
    
    async def get_by_id(self, id: int):
        return self.session.query(Machine).get(id)  # WRONG!
```

✅ **Do**:
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

### Testing Repositories with Mocks

❌ **Don't**:
```python
@pytest.mark.asyncio
async def test_repository(mocker):
    mock_connection = mocker.Mock()  # WRONG! Use real DB
    repository = MachineRepository(mock_connection)
```

✅ **Do**:
```python
@pytest.mark.asyncio
async def test_repository(db_connection):
    repository = MachineRepository(db_connection)  # Real database
    machine = await repository.create({"hostname": "test"})
    assert machine.id is not None
```

### Testing Services with Real Repositories

❌ **Don't**:
```python
@pytest.mark.asyncio
async def test_service(db_connection):
    repository = MachineRepository(db_connection)  # WRONG! Mock it
    service = MachineService(repository)
```

✅ **Do**:
```python
@pytest.mark.asyncio
async def test_service(mocker):
    mock_repo = mocker.Mock(spec=MachineRepository)  # Mock repository
    mock_repo.create = AsyncMock(return_value=Machine(...))
    service = MachineService(mock_repo)
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **SQLAlchemy Core**: SQLAlchemy expression language
- **Python Async**: Modern async/await patterns
- **Pydantic Models**: Data validation and modeling
- **Repository Pattern**: Data access patterns
- **Service Layer**: Business logic organization
- **Database Design**: Schema design and migrations
- **Testing**: Unit and integration testing
- **Builder Pattern**: Object construction patterns

## Security Considerations

### Input Validation

Services validate all inputs:
- Type checking via Pydantic
- Business rule validation
- Boundary checking
- Format validation

### SQL Injection Prevention

SQLAlchemy Core prevents SQL injection:
- Parameterized queries
- No string concatenation
- Type-safe expressions

### Authorization

Services enforce authorization:
- Check user permissions
- Resource-level access control
- Ownership validation

## Performance Considerations

### Query Optimization

- Use indexes on frequently queried columns
- Avoid N+1 queries with joins
- Limit result sets appropriately
- Use pagination for large datasets

### Connection Pooling

- Reuse database connections
- Configure pool size appropriately
- Handle connection timeouts
- Clean up resources properly

### Transaction Management

- Keep transactions short
- Minimize lock contention
- Use appropriate isolation levels
- Handle deadlocks gracefully

## Documentation

### README

See `src/maasservicelayer/README.md` for:
- Detailed architecture overview
- Design principles
- Code examples
- Best practices

### Docstrings

Comprehensive docstrings required:
- Service method purposes
- Repository query descriptions
- Parameter explanations
- Return value documentation
- Exception documentation

### Architecture Diagrams

See `.sdd/context/architecture/` for:
- Three-tier architecture
- Repository pattern details
- Data flow diagrams

## Additional Resources

- SQLAlchemy Core: https://docs.sqlalchemy.org/en/20/core/
- Alembic: https://alembic.sqlalchemy.org/
- Pydantic: https://docs.pydantic.dev/
- `src/maasservicelayer/README.md`: Detailed architecture
- `AGENTS.md`: General coding guidelines
- `.sdd/context/architecture/repository-pattern.md`: Repository details
- `.sdd/context/architecture/three-tier-architecture.md`: Architecture overview