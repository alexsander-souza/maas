# API Versioning

## Overview

MAAS implements a versioning strategy to support backward compatibility while enabling modernization. The system maintains two concurrent API versions with different architectural foundations and capabilities.

## Version Overview

### v2 API (Legacy)

**Status**: Maintenance mode, backward compatibility maintained

**Technology**: Django REST Framework, Django ORM
**Location**: `src/maasserver`
**Architecture**: Monolithic Django application
**Protocol**: REST-like with custom conventions
**Authentication**: 
- OAuth 1.0a
- Session-based
- Macaroons

**Characteristics**:
- Established, stable API
- Extensive feature coverage
- Django-specific patterns
- Limited async support
- Legacy authentication methods

### v3 API (Modern)

**Status**: Active development, recommended for new features

**Technology**: FastAPI, SQLAlchemy Core, Pydantic
**Location**: `src/maasapiserver` + `src/maasservicelayer`
**Architecture**: Three-tier (API, Service, Repository)
**Protocol**: REST with OpenAPI 3.0 specification
**Authentication**:
- Bearer tokens (JWT)
- Django sessionid (backward compatibility)
- Macaroons (backward compatibility)

**Characteristics**:
- Modern async architecture
- Type-safe with Pydantic models
- Auto-generated OpenAPI documentation
- Improved performance
- Better testability

## Versioning Strategy

### URL-Based Versioning

Both API versions are accessible via URL paths:

```
/MAAS/api/2.0/         # v2 API endpoints
/MAAS/api/v3/          # v3 API endpoints
```

**Benefits**:
- Clear version identification
- Easy routing and separation
- Multiple versions can coexist
- Client explicitly chooses version

### Independent Evolution

Each version evolves independently:

- **v2**: Bug fixes and critical updates only
- **v3**: New features and improvements

This approach allows:
- Stable v2 API for existing clients
- Innovation in v3 without breaking changes
- Gradual migration path for users

## API Comparison

### Request/Response Format

#### v2 API

Custom format with Django conventions:

```json
{
    "system_id": "abc123",
    "hostname": "machine-1",
    "status_name": "Ready",
    "architecture": "amd64/generic"
}
```

#### v3 API

OpenAPI-compliant with Pydantic schemas:

```json
{
    "id": 123,
    "system_id": "abc123",
    "hostname": "machine-1",
    "status": "ready",
    "architecture": "amd64"
}
```

**Key Differences**:
- v3 uses numeric IDs alongside system_id
- v3 normalizes enum values (lowercase)
- v3 follows REST conventions more strictly
- v3 has comprehensive schema validation

### Error Handling

#### v2 API

Django-style error responses:

```json
{
    "error": "Machine not found",
    "traceback": "..."
}
```

#### v3 API

RFC 7807 Problem Details:

```json
{
    "type": "https://api.maas.io/problems/not-found",
    "title": "Resource Not Found",
    "status": 404,
    "detail": "Machine with id 123 not found",
    "instance": "/api/v3/machines/123"
}
```

### Authentication

#### v2 API

```
Authorization: OAuth oauth_consumer_key="...", oauth_token="..."
```

#### v3 API (Preferred)

```
Authorization: Bearer <jwt_token>
```

#### v3 API (Backward Compatible)

Also supports:
- `Cookie: sessionid=...` (Django sessions)
- `Macaroons: ...` (Macaroon authentication)

## Migration Path

### Feature Parity Approach

MAAS is gradually achieving feature parity between v2 and v3:

1. **Phase 1**: Core resource operations (machines, devices, subnets)
2. **Phase 2**: Advanced operations (deployment, commissioning)
3. **Phase 3**: Administrative functions (settings, users)
4. **Phase 4**: Legacy features and edge cases

### When to Use Each Version

#### Use v3 API for:
- New integrations
- New features
- Greenfield projects
- Applications requiring OpenAPI
- Modern async workflows
- High-performance requirements

#### Use v2 API for:
- Existing integrations (until migration)
- Features not yet in v3
- Legacy tooling compatibility
- Specific backward compatibility needs

### Implementing New Features

**Rule**: All new features MUST be implemented in v3 API first.

```python
# ✅ Good: New feature in v3
# src/maasapiserver/v3/handlers/machines.py
@handler
class MachineHandler(Handler):
    async def get_power_metrics(self, machine_id: int) -> PowerMetrics:
        return await self.service.get_power_metrics(machine_id)
```

**Exception**: Only add to v2 if:
1. Critical bug fix required
2. Security patch needed
3. Explicit product requirement for v2 support

### Backward Compatibility in v3

v3 maintains limited backward compatibility with v2:

```python
# Support both v2 and v3 authentication
@check_permissions(required_permissions=[MachinePermission.VIEW])
async def get_machine(self, machine_id: int):
    # Accepts Bearer, sessionid, or Macaroon
    pass
```

**Fields**:
- Include `system_id` alongside numeric `id` for transition period
- Map v2 enum values to v3 normalized values where possible

## Deprecation Strategy

### v2 API Deprecation Timeline

**Current Status**: Maintenance mode

1. **Now**: New features only in v3
2. **6 months**: Deprecation warnings in v2 responses
3. **12 months**: Documentation updated to recommend v3
4. **24 months**: v2 marked as deprecated in headers
5. **36+ months**: Evaluate v2 sunset based on usage

### Deprecation Headers

v2 responses include deprecation information:

```
Deprecation: true
Sunset: Sat, 31 Dec 2025 23:59:59 GMT
Link: <https://maas.io/docs/api-v3-migration>; rel="deprecation"
```

### Communication

- Release notes highlight v3 features
- Documentation prioritizes v3 examples
- CLI defaults to v3 endpoints
- Migration guides provided

## Versioning Best Practices

### For New v3 Endpoints

1. **Follow OpenAPI Standards**: Use standard HTTP methods and status codes
2. **Design for Stability**: APIs should be stable from first release
3. **Use Pydantic Models**: Comprehensive request/response validation
4. **Document Thoroughly**: OpenAPI spec must be complete and accurate
5. **Consider Pagination**: Use consistent pagination patterns
6. **Plan for Expansion**: Design extensible schemas

### Example v3 Endpoint

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from maasapiserver.v3.handlers import Handler

class MachineResponse(BaseModel):
    """Machine resource representation."""
    id: int
    system_id: str
    hostname: str
    status: MachineStatus
    architecture: str
    
    class Config:
        schema_extra = {
            "example": {
                "id": 123,
                "system_id": "abc123",
                "hostname": "machine-1",
                "status": "ready",
                "architecture": "amd64"
            }
        }

@handler
class MachineHandler(Handler):
    @check_permissions(MachinePermission.VIEW)
    async def get(self, machine_id: int) -> MachineResponse:
        """
        Get machine by ID.
        
        Returns a single machine resource.
        """
        machine = await self.service.get_by_id(machine_id)
        if not machine:
            raise NotFoundException(f"Machine {machine_id} not found")
        return MachineResponse.from_model(machine)
```

### Schema Evolution in v3

Within v3, handle schema evolution carefully:

**Adding Fields**: ✅ Safe (backward compatible)
```python
class MachineResponse(BaseModel):
    id: int
    hostname: str
    new_field: str | None = None  # Optional, backward compatible
```

**Removing Fields**: ❌ Breaking change
```python
# Don't remove fields - deprecate and set to null instead
deprecated_field: str | None = None  # Mark as deprecated
```

**Changing Types**: ❌ Breaking change
```python
# Don't change types - create new field instead
old_value: str
new_value: int  # Add new field, deprecate old
```

**Renaming Fields**: ❌ Breaking change
```python
# Support both during transition
old_name: str  # Deprecated
new_name: str  # Map from old_name
```

### Semantic Versioning for v3 Changes

Though the API is "v3", individual resources may have sub-versions:

- **3.0.x**: Patch - bug fixes, no API changes
- **3.x.0**: Minor - backward-compatible additions
- **x.0.0**: Major - breaking changes (requires v4)

## OpenAPI Specification

### Generating Specs

v3 API automatically generates OpenAPI 3.0 specification:

```
GET /MAAS/api/v3/openapi.json
```

**Features**:
- Complete schema definitions
- Authentication schemes
- Request/response examples
- Error responses documented

### Using OpenAPI Spec

Clients can generate code from the spec:

```bash
# Generate Python client
openapi-generator generate -i openapi.json -g python -o maas-client

# Generate TypeScript client
openapi-generator generate -i openapi.json -g typescript-axios -o maas-client-ts
```

### Maintaining Accuracy

Ensure OpenAPI spec stays accurate:

1. **Use Pydantic Models**: Automatically serialized to OpenAPI
2. **Document Endpoints**: Add docstrings to handler methods
3. **Test Against Spec**: Validate responses match schema
4. **Review Changes**: Schema changes reviewed in PRs

## Client Compatibility

### MAAS CLI

The MAAS CLI supports both versions:

```bash
# Explicitly use v2
maas admin machines read --api-version=2.0

# Use v3 (default in newer versions)
maas admin machines read --api-version=3
```

### Python Client Libraries

Separate client libraries for each version:

```python
# v2 client (legacy)
from maas.client import Client as ClientV2

# v3 client (recommended)
from maas.client.v3 import Client as ClientV3
```

### Third-Party Integrations

Recommend v3 for new integrations:

- Terraform provider: v3
- Ansible modules: Migrating to v3
- Custom scripts: Use v3 for new development

## Testing Across Versions

### Integration Tests

Test both versions where feature parity exists:

```python
@pytest.mark.parametrize("api_version", ["2.0", "v3"])
async def test_machine_list(api_version, client):
    """Test machine listing in both API versions."""
    machines = await client.machines.list(api_version=api_version)
    assert len(machines) > 0
```

### API Contract Tests

Validate v3 against OpenAPI spec:

```python
from schemathesis import from_uri

schema = from_uri("/MAAS/api/v3/openapi.json")

@schema.parametrize()
def test_api_contract(case):
    """Validate all v3 endpoints match OpenAPI spec."""
    case.call_and_validate()
```

## Related Documentation

- **Three-Tier Architecture**: See `architecture/three-tier-architecture.md`
- **API Implementation**: See `subsystems/maasapiserver.md`
- **Service Layer**: See `subsystems/maasservicelayer.md`
- **Legacy Server**: See `subsystems/maasserver.md`

## References

- [OpenAPI Specification](https://spec.openapis.org/oas/v3.0.3)
- [RFC 7807 - Problem Details](https://tools.ietf.org/html/rfc7807)
- [API Versioning Best Practices](https://www.troyhunt.com/your-api-versioning-is-wrong-which-is/)
- `src/maasapiserver/README.md` - v3 API documentation
- `AGENTS.md` - Coding guidelines for API development