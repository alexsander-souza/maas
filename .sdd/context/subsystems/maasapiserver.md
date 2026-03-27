# maasapiserver Subsystem

## Purpose

FastAPI-based v3 REST API that serves as the presentation layer in MAAS's three-tier architecture. This subsystem handles HTTP communication, request validation, response serialization, and authentication for the modern MAAS API.

**Status**: Active development - recommended for all new features.

## Location

`src/maasapiserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **FastAPI**: Modern async web framework
- **Pydantic**: Data validation and serialization
- **Uvicorn**: ASGI server

### Key Libraries
- **pydantic**: Request/response models and validation
- **fastapi**: Routing, dependency injection, OpenAPI generation
- **httpx**: HTTP client for testing
- **pytest**: Testing framework
- **pytest-asyncio**: Async test support

## Architectural Constraints

### Presentation Layer Only

This subsystem is strictly the **API/Presentation layer** in the three-tier architecture:

```
┌──────────────────────────────┐
│   maasapiserver (API)        │  ← YOU ARE HERE
│   - HTTP endpoints           │
│   - Request validation       │
│   - Response serialization   │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│   maasservicelayer           │
│   - Business logic           │
│   - Repository coordination  │
└──────────────────────────────┘
```

### No Business Logic

Handlers should contain **ZERO business logic**. All business rules, validation, and orchestration belong in the service layer.

### No Direct Database Access

Handlers **NEVER** access the database directly. All data access goes through services, which use repositories.

### Stateless

All handlers must be stateless. Request handling should not depend on any server-side state except through the database.

## Key Patterns

### Handler Pattern

Extend the `Handler` base class for new API endpoints:

```python
from maasapiserver.v3.handlers.base import Handler
from maasapiserver.v3.auth.decorators import handler, check_permissions

@handler
class MachineHandler(Handler):
    """Handler for machine resources."""
    
    @check_permissions(MachinePermission.VIEW)
    async def get(self, machine_id: int) -> MachineResponse:
        """Get a single machine by ID."""
        machine = await self.service.get_by_id(machine_id)
        if not machine:
            raise NotFoundException(f"Machine {machine_id} not found")
        return MachineResponse.from_model(machine)
    
    @check_permissions(MachinePermission.VIEW)
    async def list(self, params: MachineListParams) -> MachineListResponse:
        """List machines with optional filtering."""
        machines = await self.service.list(
            status=params.status,
            architecture=params.architecture,
            limit=params.limit,
            offset=params.offset
        )
        return MachineListResponse(
            items=[MachineResponse.from_model(m) for m in machines],
            total=len(machines)
        )
    
    @check_permissions(MachinePermission.EDIT)
    async def create(self, request: MachineCreateRequest) -> MachineResponse:
        """Create a new machine."""
        machine = await self.service.create(request.to_builder())
        return MachineResponse.from_model(machine)
    
    @check_permissions(MachinePermission.EDIT)
    async def update(
        self, 
        machine_id: int, 
        request: MachineUpdateRequest
    ) -> MachineResponse:
        """Update an existing machine."""
        machine = await self.service.update(machine_id, request.to_builder())
        return MachineResponse.from_model(machine)
    
    @check_permissions(MachinePermission.DELETE)
    async def delete(self, machine_id: int) -> None:
        """Delete a machine."""
        await self.service.delete(machine_id)
```

### @handler Decorator

Use the `@handler` decorator to register handler classes:

```python
@handler
class MachineHandler(Handler):
    """Marks this as a handler class for automatic registration."""
    pass
```

**What it does**:
- Registers handler with FastAPI router
- Sets up dependency injection
- Configures OpenAPI documentation
- Enables automatic service injection

### Pydantic Models

Define request and response models using Pydantic:

```python
from pydantic import BaseModel, Field, validator
from typing import Optional

class MachineCreateRequest(BaseModel):
    """Request model for creating a machine."""
    
    hostname: str = Field(..., min_length=1, max_length=255)
    architecture: str = Field(..., regex=r"^[a-z0-9]+(/[a-z0-9]+)?$")
    memory: int = Field(..., gt=0, description="Memory in MB")
    cpu_count: int = Field(..., gt=0, alias="cpuCount")
    
    @validator("hostname")
    def validate_hostname(cls, v):
        """Ensure hostname is valid."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Hostname must be alphanumeric")
        return v.lower()
    
    def to_builder(self) -> MachineCreateBuilder:
        """Convert to service layer builder."""
        return (
            MachineCreateBuilder()
            .with_hostname(self.hostname)
            .with_architecture(self.architecture)
            .with_memory(self.memory)
            .with_cpu_count(self.cpu_count)
        )
    
    class Config:
        schema_extra = {
            "example": {
                "hostname": "machine-1",
                "architecture": "amd64/generic",
                "memory": 8192,
                "cpuCount": 4
            }
        }

class MachineResponse(BaseModel):
    """Response model for machine resource."""
    
    id: int
    system_id: str
    hostname: str
    status: str
    architecture: str
    memory: int
    cpu_count: int = Field(alias="cpuCount")
    created: datetime
    updated: datetime
    
    @classmethod
    def from_model(cls, machine: Machine) -> "MachineResponse":
        """Create response from domain model."""
        return cls(
            id=machine.id,
            system_id=machine.system_id,
            hostname=machine.hostname,
            status=machine.status,
            architecture=machine.architecture,
            memory=machine.memory,
            cpu_count=machine.cpu_count,
            created=machine.created,
            updated=machine.updated
        )
    
    class Config:
        orm_mode = True
        allow_population_by_field_name = True
```

### Permission Checking

Use `@check_permissions` decorator for authorization:

```python
from maasapiserver.v3.auth.decorators import check_permissions
from maasapiserver.v3.auth.permissions import MachinePermission

@handler
class MachineHandler(Handler):
    
    @check_permissions(MachinePermission.VIEW)
    async def get(self, machine_id: int) -> MachineResponse:
        """Requires VIEW permission."""
        pass
    
    @check_permissions(MachinePermission.EDIT)
    async def update(self, machine_id: int, request: UpdateRequest) -> MachineResponse:
        """Requires EDIT permission."""
        pass
    
    @check_permissions(MachinePermission.DELETE)
    async def delete(self, machine_id: int) -> None:
        """Requires DELETE permission."""
        pass
```

**Permission Levels**:
- `VIEW`: Read-only access
- `EDIT`: Create and update
- `DELETE`: Delete resources
- `ADMIN`: Administrative operations

### Error Handling

Use standard HTTP exceptions:

```python
from fastapi import HTTPException, status
from maasapiserver.v3.exceptions import (
    NotFoundException,
    ValidationException,
    UnauthorizedException,
    ForbiddenException
)

@handler
class MachineHandler(Handler):
    
    async def get(self, machine_id: int) -> MachineResponse:
        """Get machine or raise 404."""
        machine = await self.service.get_by_id(machine_id)
        if not machine:
            raise NotFoundException(f"Machine {machine_id} not found")
        return MachineResponse.from_model(machine)
    
    async def create(self, request: MachineCreateRequest) -> MachineResponse:
        """Create machine or raise validation error."""
        try:
            machine = await self.service.create(request.to_builder())
        except ValueError as e:
            raise ValidationException(str(e))
        return MachineResponse.from_model(machine)
```

**Standard Exceptions**:
- `NotFoundException` → 404 Not Found
- `ValidationException` → 400 Bad Request
- `UnauthorizedException` → 401 Unauthorized
- `ForbiddenException` → 403 Forbidden
- `ConflictException` → 409 Conflict

## Testing Requirements

### Test Framework

Use pytest with async support:

```python
import pytest
from httpx import AsyncClient
from maasapiserver.v3.app import create_app

@pytest.mark.asyncio
class TestMachineHandler:
    """Test machine API endpoints."""
    
    async def test_get_machine(self, mocked_api_client_user):
        """Test getting a single machine."""
        client, service = mocked_api_client_user
        
        # Mock service response
        service.get_by_id.return_value = Machine(
            id=1,
            hostname="test-machine",
            status="ready"
        )
        
        # Make request
        response = await client.get("/api/v3/machines/1")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "test-machine"
        service.get_by_id.assert_called_once_with(1)
```

### APICommonTests Base Class

Use `APICommonTests` for standard CRUD test coverage:

```python
from maastesting.api import APICommonTests

class TestMachineAPI(APICommonTests):
    """Standard test suite for machine API."""
    
    def get_handler_class(self):
        return MachineHandler
    
    def get_create_request(self):
        return MachineCreateRequest(
            hostname="test-machine",
            architecture="amd64",
            memory=8192,
            cpuCount=4
        )
    
    def get_update_request(self):
        return MachineUpdateRequest(
            hostname="updated-machine"
        )
```

### Mocked Service Fixtures

**Critical**: Always mock services in API tests, never mock repositories:

```python
@pytest.fixture
async def mocked_api_client_user(mocker):
    """API client with mocked services."""
    app = create_app()
    
    # Mock the service layer
    mock_service = mocker.Mock(spec=MachineService)
    
    # Inject mocked service
    app.dependency_overrides[get_machine_service] = lambda: mock_service
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client, mock_service
```

**Why mock services, not repositories**:
- Tests API layer in isolation
- Services already tested separately
- Faster test execution
- Clear separation of concerns

### Test Authentication

Test with different authentication methods:

```python
@pytest.mark.asyncio
async def test_bearer_token_auth(mocked_api_client_user):
    """Test Bearer token authentication."""
    client, service = mocked_api_client_user
    
    headers = {"Authorization": "Bearer test-token"}
    response = await client.get("/api/v3/machines/1", headers=headers)
    
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_session_auth(mocked_api_client_user):
    """Test Django session authentication."""
    client, service = mocked_api_client_user
    
    cookies = {"sessionid": "test-session-id"}
    response = await client.get("/api/v3/machines/1", cookies=cookies)
    
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_unauthorized(mocked_api_client_user):
    """Test unauthorized access."""
    client, service = mocked_api_client_user
    
    response = await client.get("/api/v3/machines/1")
    
    assert response.status_code == 401
```

### Running Tests

```bash
# Run all maasapiserver tests
pytest src/maasapiserver/tests/

# Run specific test file
pytest src/maasapiserver/tests/v3/handlers/test_machines.py

# Run with coverage
pytest --cov=maasapiserver src/maasapiserver/tests/

# Run in verbose mode
pytest -vv src/maasapiserver/tests/
```

## Development Guidelines

### Adding New Endpoints

1. **Define Pydantic Models**: Request/response models first
2. **Create Handler**: Extend `Handler` base class
3. **Implement Methods**: CRUD operations as needed
4. **Add Permissions**: Use `@check_permissions`
5. **Write Tests**: Use mocked services
6. **Update OpenAPI**: Ensure accurate documentation

### Handler Method Naming

Follow REST conventions:

- `get(id)`: Retrieve single resource
- `list(params)`: List resources with filtering
- `create(request)`: Create new resource
- `update(id, request)`: Update existing resource
- `delete(id)`: Delete resource
- `patch(id, request)`: Partial update

### Thin Handlers

Keep handlers thin - delegate everything to services:

✅ **Good** (thin handler):
```python
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

❌ **Bad** (business logic in handler):
```python
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    # Validation in handler - WRONG!
    if request.memory < 1024:
        raise ValidationException("Minimum 1GB memory")
    
    # Direct repository access - WRONG!
    machine = await repository.create(request.dict())
    
    return MachineResponse.from_model(machine)
```

### OpenAPI Documentation

Ensure comprehensive OpenAPI documentation:

```python
@handler
class MachineHandler(Handler):
    
    async def get(self, machine_id: int) -> MachineResponse:
        """
        Get machine by ID.
        
        Retrieves a single machine resource by its unique identifier.
        
        Args:
            machine_id: Unique machine identifier
            
        Returns:
            Machine resource with all attributes
            
        Raises:
            404: Machine not found
            401: Unauthorized
            403: Insufficient permissions
        """
        pass
```

## Authentication

### Supported Methods

1. **Bearer Token** (Recommended):
   ```
   Authorization: Bearer <jwt_token>
   ```

2. **Django Session** (Backward compatibility):
   ```
   Cookie: sessionid=<session_id>
   ```

3. **Macaroon** (Specialized use cases):
   ```
   Macaroons: <macaroon_token>
   ```

### Authentication Flow

```python
from maasapiserver.v3.auth.dependencies import get_authenticated_user

async def get_machine(
    machine_id: int,
    user: User = Depends(get_authenticated_user)
) -> MachineResponse:
    """Automatically authenticated via dependency injection."""
    machine = await service.get_by_id(machine_id)
    return MachineResponse.from_model(machine)
```

## Integration Points

### Service Layer

Primary integration point:

```python
from maasservicelayer.services.machines import MachineService

class MachineHandler(Handler):
    def __init__(self, service: MachineService):
        self.service = service
```

### OpenAPI Specification

Automatically generated at `/api/v3/openapi.json`:
- Complete schema definitions
- Authentication schemes
- Request/response examples
- Error responses

### FastAPI Router

Handlers registered with FastAPI:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/v3")

# Handlers automatically registered via @handler decorator
```

### Web UI

Future: React/Vue frontend consuming v3 API

## Common Pitfalls

### Business Logic in Handlers

❌ **Don't**:
```python
async def create(self, request: MachineCreateRequest):
    # Business validation - belongs in service!
    if request.memory < MIN_MEMORY:
        raise ValidationException()
    
    # Complex orchestration - belongs in service!
    machine = await self.machine_repo.create(request)
    await self.event_repo.log_created(machine)
    await self.notify_service.send(machine)
```

✅ **Do**:
```python
async def create(self, request: MachineCreateRequest):
    # Just delegate to service
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

### Direct Repository Access

❌ **Don't**:
```python
from maasservicelayer.db.repositories.machines import MachineRepository

async def get(self, machine_id: int):
    repository = MachineRepository(connection)
    machine = await repository.get_by_id(machine_id)  # WRONG!
```

✅ **Do**:
```python
async def get(self, machine_id: int):
    machine = await self.service.get_by_id(machine_id)  # Correct
```

### Mocking Repositories in Tests

❌ **Don't**:
```python
@pytest.mark.asyncio
async def test_get_machine(mocker):
    # Mocking repository - WRONG!
    mock_repo = mocker.Mock(spec=MachineRepository)
    handler = MachineHandler(repository=mock_repo)
```

✅ **Do**:
```python
@pytest.mark.asyncio
async def test_get_machine(mocked_api_client_user):
    # Mock service, not repository
    client, mock_service = mocked_api_client_user
    mock_service.get_by_id.return_value = Machine(...)
```

### Inconsistent Error Handling

❌ **Don't**:
```python
async def get(self, machine_id: int):
    machine = await self.service.get_by_id(machine_id)
    if not machine:
        return {"error": "Not found"}  # Inconsistent format
```

✅ **Do**:
```python
async def get(self, machine_id: int):
    machine = await self.service.get_by_id(machine_id)
    if not machine:
        raise NotFoundException(f"Machine {machine_id} not found")
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **FastAPI Development**: FastAPI-specific patterns
- **Pydantic Models**: Data validation and serialization
- **Async Python**: Modern async/await patterns
- **REST API Design**: RESTful API best practices
- **OpenAPI Documentation**: API documentation standards
- **API Testing**: Testing HTTP endpoints
- **Authentication**: Auth mechanisms and security

## Security Considerations

### Input Validation

All input validated via Pydantic:
- Type checking
- Format validation
- Length constraints
- Custom validators

### Authorization

Permission checks on every endpoint:
- Role-based access control
- Resource-level permissions
- Automatic permission enforcement

### Rate Limiting

Future: Implement rate limiting for API endpoints

### CORS

Configure CORS for browser-based clients:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://maas.example.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Performance Considerations

### Async All the Way

All handlers are async:
- Non-blocking I/O
- Efficient resource usage
- High concurrency support

### Response Serialization

Pydantic models efficiently serialize responses:
- Fast C-based validation
- Automatic type conversion
- Schema caching

### Database Connection Pooling

Managed by service layer:
- Connection reuse
- Automatic cleanup
- Transaction management

## Documentation

### OpenAPI Specification

Accessible at `/api/v3/openapi.json`:
- Auto-generated from Pydantic models
- Complete endpoint documentation
- Request/response schemas
- Authentication schemes

### Docstrings

Comprehensive docstrings for all handlers:
- Method purpose
- Parameters
- Return values
- Exceptions
- Examples

### Code Examples

Include examples in Pydantic schema_extra:
```python
class Config:
    schema_extra = {
        "example": {
            "hostname": "machine-1",
            "status": "ready"
        }
    }
```

## Additional Resources

- FastAPI Documentation: https://fastapi.tiangolo.com/
- Pydantic Documentation: https://pydantic-docs.helpmanual.io/
- OpenAPI Specification: https://spec.openapis.org/oas/v3.0.3
- `AGENTS.md`: General coding guidelines
- `src/maasapiserver/README.md`: API server documentation
- `src/maasservicelayer/README.md`: Service layer documentation
- `.sdd/context/architecture/three-tier-architecture.md`: Architecture overview