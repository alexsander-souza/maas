# apiclient Subsystem

## Purpose

Python API client library for interacting with the MAAS REST API. This subsystem provides a programmatic interface for external tools, scripts, and integrations to communicate with MAAS, handling authentication, request formatting, and error handling.

**Status**: Active - stable library for MAAS API access.

## Location

`src/apiclient`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **HTTP Client**: Requests library or httpx
- **OAuth**: OAuth 1.0a authentication

### Key Libraries
- **requests** or **httpx**: HTTP client library
- **oauthlib**: OAuth authentication
- **urllib3**: Low-level HTTP handling
- **json**: Request/response serialization

## Architectural Constraints

### Client Library Pattern

This is a library, not a service:
- No server components
- No database access
- Consumed by external applications
- Stateless request/response model

### Authentication Support

Must support multiple MAAS authentication methods:
- **OAuth 1.0a**: Primary authentication for v2 API
- **Bearer tokens**: For v3 API
- **API keys**: User-specific credentials
- **Session tokens**: For web UI integration

### Backward Compatibility

Maintain compatibility across MAAS versions:
- Support both v2 and v3 API endpoints
- Handle API version differences
- Graceful degradation for missing features
- Clear error messages for version mismatches

## Key Patterns

### Client Initialization

Initialize client with credentials:

```python
from maas.client import Client

# OAuth authentication (v2 API)
client = Client(
    api_url="http://maas.example.com:5240/MAAS/api/2.0/",
    api_key="consumer_key:token_key:token_secret"
)

# Bearer token authentication (v3 API)
client = Client(
    api_url="http://maas.example.com:5240/MAAS/api/v3/",
    bearer_token="your-jwt-token"
)
```

### Resource-Based API

Organize API methods by resource type:

```python
class Client:
    """MAAS API client."""
    
    def __init__(self, api_url: str, api_key: str = None, bearer_token: str = None):
        self.api_url = api_url
        self.api_key = api_key
        self.bearer_token = bearer_token
        self._session = self._create_session()
    
    @property
    def machines(self) -> MachinesResource:
        """Access machine resources."""
        return MachinesResource(self)
    
    @property
    def devices(self) -> DevicesResource:
        """Access device resources."""
        return DevicesResource(self)
    
    @property
    def subnets(self) -> SubnetsResource:
        """Access subnet resources."""
        return SubnetsResource(self)

# Usage
machines = client.machines.list()
machine = client.machines.get(system_id="abc123")
```

### Resource Class Pattern

Implement resource-specific operations:

```python
class MachinesResource:
    """Machine resource operations."""
    
    def __init__(self, client: Client):
        self.client = client
        self.base_path = "machines"
    
    def list(self, **filters) -> list[Machine]:
        """List all machines with optional filters."""
        response = self.client.get(self.base_path, params=filters)
        return [Machine(data) for data in response.json()]
    
    def get(self, system_id: str) -> Machine:
        """Get a single machine by system ID."""
        response = self.client.get(f"{self.base_path}/{system_id}/")
        return Machine(response.json())
    
    def create(self, **kwargs) -> Machine:
        """Create a new machine."""
        response = self.client.post(self.base_path, json=kwargs)
        return Machine(response.json())
    
    def update(self, system_id: str, **kwargs) -> Machine:
        """Update an existing machine."""
        response = self.client.put(
            f"{self.base_path}/{system_id}/",
            json=kwargs
        )
        return Machine(response.json())
    
    def delete(self, system_id: str) -> None:
        """Delete a machine."""
        self.client.delete(f"{self.base_path}/{system_id}/")
    
    def commission(self, system_id: str) -> Machine:
        """Start commissioning a machine."""
        response = self.client.post(
            f"{self.base_path}/{system_id}/commission/"
        )
        return Machine(response.json())
    
    def deploy(
        self, 
        system_id: str, 
        distro_series: str = None,
        **kwargs
    ) -> Machine:
        """Deploy an operating system to a machine."""
        data = {"distro_series": distro_series, **kwargs}
        response = self.client.post(
            f"{self.base_path}/{system_id}/deploy/",
            json=data
        )
        return Machine(response.json())
```

### HTTP Request Handling

Centralized HTTP request handling with authentication:

```python
import requests
from requests_oauthlib import OAuth1
from typing import Optional, Dict, Any

class Client:
    """MAAS API client with HTTP handling."""
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with authentication."""
        session = requests.Session()
        
        if self.api_key:
            # OAuth 1.0a authentication
            consumer_key, token_key, token_secret = self.api_key.split(":")
            session.auth = OAuth1(
                consumer_key,
                client_secret="",
                resource_owner_key=token_key,
                resource_owner_secret=token_secret,
                signature_method="PLAINTEXT"
            )
        elif self.bearer_token:
            # Bearer token authentication
            session.headers.update({
                "Authorization": f"Bearer {self.bearer_token}"
            })
        
        return session
    
    def get(self, path: str, params: Dict = None) -> requests.Response:
        """Execute GET request."""
        url = self._build_url(path)
        response = self._session.get(url, params=params)
        self._raise_for_status(response)
        return response
    
    def post(
        self, 
        path: str, 
        json: Dict = None, 
        data: Dict = None
    ) -> requests.Response:
        """Execute POST request."""
        url = self._build_url(path)
        response = self._session.post(url, json=json, data=data)
        self._raise_for_status(response)
        return response
    
    def put(self, path: str, json: Dict = None) -> requests.Response:
        """Execute PUT request."""
        url = self._build_url(path)
        response = self._session.put(url, json=json)
        self._raise_for_status(response)
        return response
    
    def delete(self, path: str) -> requests.Response:
        """Execute DELETE request."""
        url = self._build_url(path)
        response = self._session.delete(url)
        self._raise_for_status(response)
        return response
    
    def _build_url(self, path: str) -> str:
        """Build full URL from path."""
        return f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"
    
    def _raise_for_status(self, response: requests.Response) -> None:
        """Raise exception for HTTP errors."""
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise MAASClientError.from_response(response) from e
```

### Error Handling

Custom exception hierarchy for API errors:

```python
class MAASClientError(Exception):
    """Base exception for MAAS client errors."""
    
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response
    
    @classmethod
    def from_response(cls, response: requests.Response):
        """Create exception from HTTP response."""
        try:
            error_data = response.json()
            message = error_data.get("error", response.text)
        except ValueError:
            message = response.text
        
        status_code = response.status_code
        
        # Map to specific exception types
        if status_code == 404:
            return ResourceNotFoundError(message, status_code, error_data)
        elif status_code == 400:
            return ValidationError(message, status_code, error_data)
        elif status_code == 401:
            return AuthenticationError(message, status_code, error_data)
        elif status_code == 403:
            return PermissionError(message, status_code, error_data)
        elif status_code == 409:
            return ConflictError(message, status_code, error_data)
        else:
            return cls(message, status_code, error_data)

class ResourceNotFoundError(MAASClientError):
    """Resource not found (404)."""
    pass

class ValidationError(MAASClientError):
    """Request validation failed (400)."""
    pass

class AuthenticationError(MAASClientError):
    """Authentication failed (401)."""
    pass

class PermissionError(MAASClientError):
    """Insufficient permissions (403)."""
    pass

class ConflictError(MAASClientError):
    """Resource conflict (409)."""
    pass

# Usage
try:
    machine = client.machines.get("nonexistent")
except ResourceNotFoundError as e:
    print(f"Machine not found: {e}")
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
```

### Model Objects

Represent API resources as Python objects:

```python
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

@dataclass
class Machine:
    """Machine resource model."""
    
    system_id: str
    hostname: str
    status: str
    architecture: str
    memory: int
    cpu_count: int
    power_state: str
    ip_addresses: List[str]
    created: datetime
    updated: datetime
    
    def __init__(self, data: dict):
        """Initialize from API response data."""
        self.system_id = data["system_id"]
        self.hostname = data["hostname"]
        self.status = data["status"]
        self.architecture = data["architecture"]
        self.memory = data.get("memory", 0)
        self.cpu_count = data.get("cpu_count", 0)
        self.power_state = data.get("power_state", "unknown")
        self.ip_addresses = data.get("ip_addresses", [])
        self.created = self._parse_datetime(data.get("created"))
        self.updated = self._parse_datetime(data.get("updated"))
    
    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "system_id": self.system_id,
            "hostname": self.hostname,
            "status": self.status,
            "architecture": self.architecture,
            "memory": self.memory,
            "cpu_count": self.cpu_count,
        }
```

### Pagination Support

Handle paginated API responses:

```python
class PaginatedResource:
    """Base class for paginated resources."""
    
    def list_all(self, **filters) -> list:
        """List all items across all pages."""
        items = []
        page = 1
        page_size = 100
        
        while True:
            response = self.client.get(
                self.base_path,
                params={"page": page, "page_size": page_size, **filters}
            )
            data = response.json()
            
            items.extend(data["results"])
            
            if not data.get("next"):
                break
            
            page += 1
        
        return [self._model_class(item) for item in items]
    
    def list_page(self, page: int = 1, page_size: int = 50, **filters) -> dict:
        """List single page of items."""
        response = self.client.get(
            self.base_path,
            params={"page": page, "page_size": page_size, **filters}
        )
        data = response.json()
        
        return {
            "results": [self._model_class(item) for item in data["results"]],
            "count": data["count"],
            "next": data.get("next"),
            "previous": data.get("previous"),
        }
```

## Testing Requirements

### Mock HTTP Responses

Test client without making real API calls:

```python
import pytest
from unittest.mock import Mock, patch
from maas.client import Client, MachinesResource

def test_list_machines(mocker):
    """Test listing machines."""
    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "system_id": "abc123",
            "hostname": "machine-1",
            "status": "ready",
            "architecture": "amd64",
        }
    ]
    
    # Mock session.get
    mocker.patch.object(
        Client, 
        'get', 
        return_value=mock_response
    )
    
    client = Client(api_url="http://test.example.com/MAAS/api/2.0/")
    machines = client.machines.list()
    
    assert len(machines) == 1
    assert machines[0].hostname == "machine-1"

def test_authentication_error(mocker):
    """Test authentication error handling."""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"error": "Invalid credentials"}
    mock_response.raise_for_status.side_effect = requests.HTTPError()
    
    mocker.patch.object(
        requests.Session,
        'get',
        return_value=mock_response
    )
    
    client = Client(api_url="http://test.example.com/MAAS/api/2.0/")
    
    with pytest.raises(AuthenticationError):
        client.machines.list()
```

### Integration Tests

Test against real MAAS instance:

```python
@pytest.mark.integration
def test_real_api_connection():
    """Test connection to real MAAS instance."""
    if not os.getenv("MAAS_API_URL"):
        pytest.skip("MAAS_API_URL not set")
    
    client = Client(
        api_url=os.getenv("MAAS_API_URL"),
        api_key=os.getenv("MAAS_API_KEY")
    )
    
    # Should connect successfully
    machines = client.machines.list()
    assert isinstance(machines, list)
```

### Running Tests

```bash
# Run unit tests
pytest src/apiclient/tests/

# Run with mocked HTTP
pytest src/apiclient/tests/unit/

# Run integration tests (requires MAAS instance)
pytest src/apiclient/tests/integration/ -m integration

# Run with coverage
pytest --cov=apiclient src/apiclient/tests/
```

## Development Guidelines

### Adding New Resources

1. Create resource class extending base
2. Implement CRUD methods
3. Add to client as property
4. Create model class for responses
5. Write tests with mocked responses
6. Update documentation

### API Version Support

Support both v2 and v3 APIs:

```python
class Client:
    """Client supporting multiple API versions."""
    
    def __init__(self, api_url: str, **auth):
        self.api_url = api_url
        self.api_version = self._detect_version(api_url)
        
    def _detect_version(self, url: str) -> str:
        """Detect API version from URL."""
        if "/api/2.0/" in url:
            return "2.0"
        elif "/api/v3/" in url:
            return "v3"
        else:
            raise ValueError(f"Unknown API version in URL: {url}")
```

### Error Message Quality

Provide helpful error messages:

```python
def get(self, system_id: str) -> Machine:
    """Get machine with clear error messages."""
    try:
        response = self.client.get(f"machines/{system_id}/")
        return Machine(response.json())
    except ResourceNotFoundError:
        raise ResourceNotFoundError(
            f"Machine '{system_id}' not found. "
            f"Use client.machines.list() to see available machines."
        )
    except AuthenticationError:
        raise AuthenticationError(
            "Authentication failed. Please check your API credentials. "
            "Generate new credentials at: http://maas.example.com/account/prefs/"
        )
```

## Integration Points

### MAAS CLI

The MAAS CLI uses this client library:
- Command implementations use client methods
- Authentication handling
- Output formatting

### External Tools

Third-party tools and scripts:
- Terraform provider
- Ansible modules
- Custom automation scripts
- Monitoring integrations

### Python Applications

Python applications integrating with MAAS:
- Infrastructure automation
- Deployment orchestration
- Inventory management
- Testing frameworks

## Common Pitfalls

### Hardcoded URLs

❌ **Don't**:
```python
client = Client(api_url="http://localhost:5240/MAAS/api/2.0/")
```

✅ **Do**:
```python
client = Client(api_url=os.getenv("MAAS_API_URL"))
```

### Ignoring Errors

❌ **Don't**:
```python
try:
    machine = client.machines.get(system_id)
except:
    pass  # Silent failure
```

✅ **Do**:
```python
try:
    machine = client.machines.get(system_id)
except ResourceNotFoundError:
    logger.error(f"Machine {system_id} not found")
    raise
```

### No Timeout

❌ **Don't**:
```python
response = session.get(url)  # No timeout
```

✅ **Do**:
```python
response = session.get(url, timeout=30)
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **HTTP Clients**: HTTP client libraries and patterns
- **OAuth Authentication**: OAuth 1.0a implementation
- **API Design**: REST API consumption
- **Error Handling**: Exception handling strategies
- **Testing**: Mocking and integration testing
- **Python Libraries**: Library development patterns

## Security Considerations

### Credential Storage

Never hardcode or log credentials:
- Use environment variables
- Support credential files
- Secure permission on credential files
- Warn on insecure credential storage

### HTTPS Enforcement

Prefer HTTPS connections:
- Warn on HTTP URLs
- Validate SSL certificates
- Support custom CA certificates
- Allow SSL verification override (with warning)

### Token Handling

Secure handling of authentication tokens:
- Don't log tokens
- Clear tokens from memory when done
- Support token rotation
- Validate token format

## Performance Considerations

### Connection Pooling

Reuse HTTP connections:
- Single session per client
- Connection pool configuration
- Keep-alive support
- Configurable pool size

### Request Batching

Batch requests where possible:
- Bulk operations
- Parallel requests for independent resources
- Rate limiting awareness

### Response Caching

Cache appropriate responses:
- Cache read-only data
- Configurable cache TTL
- Cache invalidation on updates
- Memory-efficient caching

## Documentation

### API Documentation

Comprehensive API documentation:
- All public methods documented
- Parameter descriptions
- Return value documentation
- Example usage for each method

### User Guide

User-facing documentation:
- Getting started guide
- Authentication setup
- Common use cases
- Troubleshooting guide

### Migration Guide

Guide for API version migration:
- v2 to v3 migration
- Breaking changes
- Feature mapping
- Code examples

## Additional Resources

- Python Requests: https://requests.readthedocs.io/
- OAuth 1.0a: https://oauth.net/core/1.0a/
- MAAS API Documentation: https://maas.io/docs/api
- `AGENTS.md`: General coding guidelines