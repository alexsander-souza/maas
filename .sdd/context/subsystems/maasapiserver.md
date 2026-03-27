# maasapiserver Subsystem

## Purpose

FastAPI-based REST API server for MAAS v3, serving as the presentation layer in the three-tier architecture. This subsystem handles HTTP requests, authentication, request/response serialization, and delegates all business logic to the service layer.

**Status**: Active development - modern API for MAAS v3.

## Location

`src/maasapiserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **FastAPI**: Modern async web framework
- **Pydantic**: Request/response validation
- **uvicorn**: ASGI server

### Key Libraries
- **fastapi**: Web framework and routing
- **pydantic**: Data validation and serialization
- **pytest**: Testing framework
- **httpx**: Async HTTP client for testing

## Architectural Constraints

### Presentation Layer Only

This subsystem is **strictly presentation layer**:

**Responsibilities (YES)**:
- HTTP request/response handling
- Request validation (data types, formats)
- Response serialization to JSON
- Authentication/authorization checks
- Routing and endpoint definition
- OpenAPI documentation

**Not Allowed (NO)**:
- Business logic or validation rules
- Database queries or connections
- Direct repository access
- Complex data transformations
- Workflow orchestration

```python
# Handler structure
API Request → Handler → Service Layer → Repository → Database
                ↓
          JSON Response
```

### No Business Logic

Handlers must delegate all business logic to services:

```python
# ❌ WRONG - Business logic in handler
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    if request.memory < 1024:  # Business rule - WRONG!
        raise ValidationError("Insufficient memory")
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)

# ✅ CORRECT - Delegate to service
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

### No Direct Database Access

Never access repositories directly - always go through services.

### Stateless

Handlers must be stateless - all state in database or external services.

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) and [django-patterns.md](../../skills/languages/django-patterns.md) for common patterns.

### Handler Pattern

Handlers are thin wrappers around service calls:

```python
from fastapi import APIRouter, Depends
from maasapiserver.common.api.base import Handler
from maasservicelayer.services.machines import MachineService

class MachineHandler(Handler):
    """Handler for machine API endpoints."""
    
    async def get(self, machine_id: int) -> MachineResponse:
        """Get machine by ID."""
        machine = await self.service.get_by_id(machine_id)
        if not machine:
            raise NotFoundException(f"Machine {machine_id} not found")
        return MachineResponse.from_model(machine)
    
    async def list(
        self, 
        status: str | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[MachineResponse]:
        """List machines with optional filtering."""
        machines = await self.service.list(
            status=status,
            limit=limit,
            offset=offset
        )
        return [MachineResponse.from_model(m) for m in machines]
    
    async def create(self, request: MachineCreateRequest) -> MachineResponse:
        """Create new machine."""
        machine = await self.service.create(request.to_builder())
        return MachineResponse.from_model(machine)
    
    async def delete(self, machine_id: int) -> None:
        """Delete machine."""
        await self.service.delete(machine_id)
```

### Pydantic Models for Validation

Use Pydantic for request validation and response serialization:

```python
from pydantic import BaseModel, Field, validator

class MachineCreateRequest(BaseModel):
    """Request model for creating a machine."""
    hostname: str = Field(..., min_length=1, max_length=255)
    architecture: str = Field(..., pattern=r'^(amd64|arm64|ppc64el)$')
    memory: int = Field(..., gt=0)
    cpu_count: int = Field(..., gt=0)
    
    @validator('hostname')
    def validate_hostname(cls, v):
        """Validate hostname format."""
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError('Hostname must be alphanumeric')
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

class MachineResponse(BaseModel):
    """Response model for machine data."""
    id: int
    system_id: str
    hostname: str
    status: str
    architecture: str
    memory: int
    cpu_count: int
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
            updated=machine.updated,
        )
```

### Permission Checking

Check permissions before operations:

```python
from maasapiserver.common.auth import User, require_permission

class MachineHandler(Handler):
    async def get(self, machine_id: int, user: User = Depends(get_current_user)) -> MachineResponse:
        """Get machine with permission check."""
        require_permission(user, "maasserver.view_machine")
        machine = await self.service.get_by_id(machine_id)
        return MachineResponse.from_model(machine)
    
    async def delete(self, machine_id: int, user: User = Depends(get_current_user)) -> None:
        """Delete machine with permission check."""
        require_permission(user, "maasserver.delete_machine")
        machine = await self.service.get_by_id(machine_id)
        if machine.owner != user and not user.is_admin:
            raise ForbiddenError("Cannot delete machines owned by others")
        await self.service.delete(machine_id)
```

### Error Handling

Convert service exceptions to HTTP responses:

```python
from fastapi import HTTPException, status

class MachineHandler(Handler):
    async def get(self, machine_id: int) -> MachineResponse:
        """Get machine with error handling."""
        try:
            machine = await self.service.get_by_id(machine_id)
            if not machine:
                raise HTTPException(status_code=404, detail="Machine not found")
            return MachineResponse.from_model(machine)
        except PermissionDenied as e:
            raise HTTPException(status_code=403, detail=str(e))
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) and [python-testing.md](../../skills/languages/python-testing.md) for testing patterns.

### Test Handlers with Mocked Services

Always mock service layer dependencies:

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_machine(api_client: AsyncClient, mock_machine_service):
    """Test getting a machine."""
    # Mock service
    mock_machine_service.get_by_id.return_value = Machine(
        id=1,
        hostname="test-machine",
        status="ready"
    )
    
    # Make request
    response = await api_client.get("/api/v3/machines/1")
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["hostname"] == "test-machine"
    mock_machine_service.get_by_id.assert_called_once_with(1)
```

### Test Authentication

Test authentication and authorization:

```python
@pytest.mark.asyncio
async def test_unauthorized(api_client: AsyncClient):
    """Test endpoint without authentication."""
    response = await api_client.get("/api/v3/machines/1")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_forbidden(api_client: AsyncClient, regular_user_token):
    """Test endpoint without permission."""
    response = await api_client.delete(
        "/api/v3/machines/1",
        headers={"Authorization": f"Bearer {regular_user_token}"}
    )
    assert response.status_code == 403
```

### Running Tests

```bash
# All API server tests
pytest src/maasapiserver/tests/

# Specific handler tests
pytest src/maasapiserver/tests/v3/handlers/test_machines.py

# With coverage
pytest --cov=maasapiserver src/maasapiserver/tests/
```

## Development Guidelines

### Adding New Endpoints

1. Define Pydantic request/response models
2. Create handler class extending `Handler`
3. Implement handler methods (thin wrappers)
4. Add permission checks
5. Register routes in router
6. Test with mocked services

### Handler Method Naming

Use standard HTTP verb naming:
- `get()` - GET single resource
- `list()` - GET collection
- `create()` - POST new resource
- `update()` - PUT/PATCH existing resource
- `delete()` - DELETE resource

### Thin Handlers Rule

Handlers should be 5-10 lines maximum:

```python
# ❌ TOO COMPLEX
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    if request.memory < 1024:
        raise ValidationError()
    if not self._is_valid_architecture(request.architecture):
        raise ValidationError()
    builder = self._build_machine_request(request)
    machine = await self.service.create(builder)
    self._log_creation(machine)
    return MachineResponse.from_model(machine)

# ✅ SIMPLE AND CLEAR
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

### OpenAPI Documentation

Add comprehensive docstrings for auto-generated API docs:

```python
async def get(self, machine_id: int) -> MachineResponse:
    """
    Get machine by ID.
    
    Retrieves detailed information about a specific machine.
    
    Args:
        machine_id: Unique identifier of the machine
        
    Returns:
        Machine details including status, resources, and configuration
        
    Raises:
        HTTPException: 404 if machine not found, 403 if no permission
    """
    machine = await self.service.get_by_id(machine_id)
    return MachineResponse.from_model(machine)
```

## Authentication

### Supported Methods
- **Bearer Token**: JWT tokens for API clients
- **Session Cookie**: Browser-based authentication
- **API Key**: For service-to-service communication

### Authentication Flow

All authenticated endpoints use FastAPI dependencies:

```python
from fastapi import Depends
from maasapiserver.common.auth import get_current_user, User

async def get_machine(
    machine_id: int,
    user: User = Depends(get_current_user)
) -> MachineResponse:
    """Endpoint with automatic authentication."""
    # user is automatically injected and validated
    machine = await service.get_by_id(machine_id)
    return MachineResponse.from_model(machine)
```

## Integration Points

### Service Layer (maasservicelayer)
- Handlers inject services via dependency injection
- All business logic delegated to services
- See [maasservicelayer.md](./maasservicelayer.md)

### OpenAPI Specification
- Auto-generated from Pydantic models and docstrings
- Available at `/docs` (Swagger UI) and `/redoc` (ReDoc)
- OpenAPI JSON at `/openapi.json`

### FastAPI Router
- Handlers registered to FastAPI routers
- Version-specific routes (e.g., `/api/v3/`)
- Automatic request validation and serialization

### Web UI
- API consumed by MAAS web interface
- CORS configuration for browser access
- WebSocket support for real-time updates

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Business Logic in Handlers

❌ **Don't** put business logic in handlers:
```python
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    # Business validation - WRONG!
    if request.memory < self._calculate_minimum_memory(request.cpu_count):
        raise ValidationError("Insufficient memory")
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

✅ **Do** delegate to service layer:
```python
async def create(self, request: MachineCreateRequest) -> MachineResponse:
    machine = await self.service.create(request.to_builder())
    return MachineResponse.from_model(machine)
```

### Direct Repository Access

❌ **Don't** access repositories directly:
```python
async def get(self, machine_id: int) -> MachineResponse:
    machine = await machine_repository.get_by_id(machine_id)  # WRONG!
    return MachineResponse.from_model(machine)
```

✅ **Do** use service layer:
```python
async def get(self, machine_id: int) -> MachineResponse:
    machine = await self.service.get_by_id(machine_id)
    return MachineResponse.from_model(machine)
```

### Mocking Services in Tests (Not Repositories)

❌ **Don't** mock repositories in API tests:
```python
async def test_get_machine(mock_repository):
    # WRONG! Test handler, not repository
    mock_repository.get_by_id.return_value = Machine(...)
```

✅ **Do** mock services:
```python
async def test_get_machine(mock_service):
    mock_service.get_by_id.return_value = Machine(...)
    response = await client.get("/api/v3/machines/1")
    assert response.status_code == 200
```

### Inconsistent Error Handling

❌ **Don't** use inconsistent error responses:
```python
async def get(self, machine_id: int) -> MachineResponse:
    machine = await self.service.get_by_id(machine_id)
    if not machine:
        return None  # WRONG! Inconsistent response type
```

✅ **Do** use standard HTTP exceptions:
```python
async def get(self, machine_id: int) -> MachineResponse:
    machine = await self.service.get_by_id(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return MachineResponse.from_model(machine)
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Input Validation
- All inputs validated via Pydantic models
- Use Field constraints for length, range, pattern validation
- See [input-validation.md](../../skills/techniques/input-validation.md)

### Authorization
- Check permissions before every operation
- Validate resource ownership
- Use role-based access control (RBAC)

### Rate Limiting
- Configure rate limiting per endpoint
- Prevent abuse and DoS attacks
- Use FastAPI middleware for rate limiting

### CORS
- Configure CORS appropriately for web UI
- Restrict allowed origins in production
- Enable credentials only when necessary

## Performance Considerations

### Async All the Way
- Use async/await throughout handler chain
- Avoid blocking operations
- Use async database drivers

### Response Serialization
- Use Pydantic for efficient serialization
- Avoid N+1 queries by eager loading in service layer
- Paginate large result sets

### Database Connection Pooling
- Connection pooling handled by service layer
- Don't create new connections in handlers
- Reuse injected service instances

## Additional Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Pydantic Documentation**: https://docs.pydantic.dev/
- **OpenAPI Specification**: https://swagger.io/specification/
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [maasservicelayer.md](./maasservicelayer.md)