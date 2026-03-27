# maasservicelayer Subsystem

## Purpose

Business logic and data access layer for MAAS v3 API, implementing both the Service and Repository layers of the three-tier architecture. This subsystem encapsulates all business rules, domain logic, and database operations.

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
- **pytest-asyncio**: Async test support

## Architectural Constraints

### Two-Layer Structure

This subsystem enforces strict separation between Service and Repository layers:

**Service Layer** (`services/`):
- Business logic and validation
- Workflow orchestration
- Cross-repository coordination
- Transaction management
- Event emission

**Repository Layer** (`db/repos/`):
- SQL query construction
- CRUD operations
- Row-to-model mapping
- Query composition
- **NO business logic**

```python
# Service Layer - Business logic
class MachineService(BaseService):
    async def deploy(self, machine_id: int, config: DeployConfig) -> Machine:
        # Business validation
        machine = await self.repository.get_by_id(machine_id)
        if machine.status != "ready":
            raise InvalidStatusError("Machine must be ready")
        
        # Orchestrate deployment
        machine = await self.repository.update_status(machine_id, "deploying")
        await self.event_service.emit_deployment_started(machine)
        return machine

# Repository Layer - Data access only
class MachineRepository(BaseRepository[Machine]):
    async def get_by_id(self, id: int) -> Machine | None:
        stmt = select(self.table).where(self.table.c.id == id)
        result = await self.connection.execute(stmt)
        row = result.fetchone()
        return self._row_to_model(row) if row else None
```

### SQLAlchemy Core (Not ORM)

**Critical**: Use SQLAlchemy Core expression language, NOT the ORM.

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
- Easier migration from Django ORM
- No session management complexity

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) for common Python patterns.

### Service Coordination Pattern

Services orchestrate multiple repositories for complex operations:

```python
class DeploymentService(BaseService):
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
        # Gather resources from multiple repositories
        machine = await self.machine_repo.get_by_id(machine_id)
        networks = await self.network_repo.list_for_machine(machine_id)
        storage = await self.storage_repo.get_for_machine(machine_id)
        
        # Validate across resources
        self._validate_deployment(machine, networks, storage, config)
        
        # Execute coordinated update
        machine = await self.machine_repo.update_status(machine_id, "deploying")
        await self.network_repo.configure(machine_id, config.networks)
        await self.storage_repo.configure(machine_id, config.storage)
        
        await self.event_service.emit_deployment_started(machine)
        return machine
```

### ClauseFactory Pattern

Reusable query filters for common conditions:

```python
class MachineClauseFactory:
    """Reusable query clauses for machines."""
    
    @staticmethod
    def with_status(status: str):
        return MachineTable.c.status == status
    
    @staticmethod
    def with_architecture(arch: str):
        return MachineTable.c.architecture == arch
    
    @staticmethod
    def ready_for_deployment():
        return and_(
            MachineTable.c.status == "ready",
            MachineTable.c.power_state == "on",
            MachineTable.c.cpu_count >= 2,
            MachineTable.c.memory >= 2048
        )

# Usage in repository
stmt = select(MachineTable).where(
    MachineClauseFactory.ready_for_deployment()
)
```

### Builder Pattern for Resource Creation

Builders provide type-safe resource construction:

```python
class MachineCreateBuilder:
    def __init__(self):
        self._data = {}
    
    def with_hostname(self, hostname: str):
        self._data["hostname"] = hostname
        return self
    
    def with_architecture(self, arch: str):
        self._data["architecture"] = arch
        return self
    
    def build(self) -> dict:
        return self._data

# Usage
builder = MachineCreateBuilder().with_hostname("node1").with_architecture("amd64")
machine = await service.create(builder)
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Critical Rule: Test Repositories with Real Database

Always test repositories against a real PostgreSQL connection:

```python
@pytest.mark.asyncio
async def test_repository(db_connection):
    repository = MachineRepository(db_connection)
    machine = await repository.create({"hostname": "test"})
    assert machine.id is not None
```

### Critical Rule: Test Services with Mocked Repositories

Always test services with mocked repository dependencies:

```python
@pytest.mark.asyncio
async def test_service(mocker):
    mock_repo = mocker.Mock(spec=MachineRepository)
    mock_repo.create = AsyncMock(return_value=Machine(id=1))
    
    service = MachineService(mock_repo)
    machine = await service.create(builder)
    
    mock_repo.create.assert_called_once()
```

### Running Tests

```bash
# All service layer tests
pytest src/maasservicelayer/tests/

# Repository tests only
pytest src/maasservicelayer/tests/db/repositories/

# Service tests only
pytest src/maasservicelayer/tests/services/
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
    Column("created", DateTime, nullable=False),
    Column("updated", DateTime, nullable=False),
)
```

**Important**: Table definitions must match actual database schema. Coordinate with Django models in `src/maasserver`.

### Alembic Migrations

```bash
# Create migration
alembic revision -m "Description"

# Auto-generate from model changes
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Development Guidelines

### Adding New Services

1. Define Pydantic model for domain object
2. Add table definition to `db/tables.py`
3. Implement repository extending `BaseRepository`
4. Test repository with real database
5. Implement service extending `BaseService` or `ReadOnlyService`
6. Test service with mocked repository
7. Create builders for create/update operations

### Adding Business Logic

**Always in services, never in repositories**:

```python
class MachineService(BaseService):
    async def deploy(self, machine_id: int, config: DeployConfig) -> Machine:
        # Get data via repository
        machine = await self.repository.get_by_id(machine_id)
        
        # Business validation here
        if machine.status != "ready":
            raise InvalidStatusError("Machine must be ready")
        
        if not self._has_sufficient_resources(machine, config):
            raise InsufficientResourcesError()
        
        # Update via repository
        return await self.repository.update_status(machine_id, "deploying")
```

## Integration Points

### API Layer (maasapiserver)
- Services consumed by API handlers
- Handlers inject services via dependency injection
- See [maasapiserver.md](./maasapiserver.md)

### Database (PostgreSQL)
- Shared schema with Django application (`src/maasserver`)
- Coordinate migrations between both systems
- Transaction isolation per request

### Event System
- Services emit domain events for side effects
- Events published to message bus
- See [maasapiserver.md](./maasapiserver.md#event-system)

### Temporal Workflows
- Services trigger Temporal workflows for long-running operations
- See [maastemporalworker.md](./maastemporalworker.md)

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Business Logic in Repositories

❌ **Don't** put validation or business rules in repositories:
```python
class MachineRepository:
    async def create(self, resource: dict):
        if resource["memory"] < 1024:  # WRONG! Business logic
            raise ValidationError()
        stmt = insert(self.table).values(**resource)
```

✅ **Do** keep repositories pure data access:
```python
# Repository - data access only
class MachineRepository:
    async def create(self, resource: dict):
        stmt = insert(self.table).values(**resource)
        result = await self.connection.execute(stmt)
        return self._row_to_model(result.fetchone())

# Service - business logic
class MachineService:
    async def create(self, builder: MachineCreateBuilder):
        resource = builder.build()
        if resource["memory"] < 1024:  # Validation here
            raise ValidationError()
        return await self.repository.create(resource)
```

### Testing Repositories with Mocks

❌ **Don't** mock database connections for repository tests:
```python
async def test_repository(mocker):
    mock_connection = mocker.Mock()  # WRONG!
    repository = MachineRepository(mock_connection)
```

✅ **Do** use real database connections:
```python
async def test_repository(db_connection):
    repository = MachineRepository(db_connection)  # Real DB
    machine = await repository.create({"hostname": "test"})
    assert machine.id is not None
```

### Testing Services with Real Repositories

❌ **Don't** use real repositories in service tests:
```python
async def test_service(db_connection):
    repository = MachineRepository(db_connection)  # WRONG!
    service = MachineService(repository)
```

✅ **Do** mock repository dependencies:
```python
async def test_service(mocker):
    mock_repo = mocker.Mock(spec=MachineRepository)
    mock_repo.create = AsyncMock(return_value=Machine(...))
    service = MachineService(mock_repo)  # Mocked dependency
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Input Validation

- All service inputs validated via Pydantic models
- Business rule validation in service layer
- See [input-validation.md](../../skills/techniques/input-validation.md)

### SQL Injection Prevention

- SQLAlchemy Core prevents SQL injection by default
- Always use parameterized queries
- Never construct SQL via string concatenation

### Authorization

Services must enforce authorization before operations:

```python
async def delete(self, user: User, machine_id: int) -> None:
    if not user.has_perm("maasserver.delete_machine"):
        raise PermissionDenied()
    
    machine = await self.repository.get_by_id(machine_id)
    if machine.owner != user and not user.is_admin:
        raise PermissionDenied()
    
    await self.repository.delete(machine_id)
```

## Performance Considerations

### Query Optimization
- Use appropriate indexes on frequently queried columns
- Avoid N+1 queries with joins or batch queries
- Use pagination for large result sets

### Connection Pooling
- Configure connection pool size based on load
- Reuse connections from pool
- Clean up resources in finally blocks

### Transaction Management
- Keep transactions short to minimize lock contention
- Use appropriate isolation levels
- Handle deadlocks with retry logic

## Additional Resources

- **Architecture**: See `src/maasservicelayer/README.md` for detailed architecture
- **SQLAlchemy Core**: https://docs.sqlalchemy.org/en/20/core/
- **Alembic**: https://alembic.sqlalchemy.org/
- **Pydantic**: https://docs.pydantic.dev/
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [sqlalchemy-patterns.md](../../skills/languages/sqlalchemy-patterns.md)