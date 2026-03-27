# apiclient Subsystem

## Purpose

Python API client library for interacting with the MAAS REST API. Provides a programmatic interface for external tools, scripts, and integrations to communicate with MAAS.

## Location

`src/apiclient`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **HTTP Client**: Requests library or httpx
- **OAuth**: OAuth 1.0a authentication

### Key Libraries
- **requests/httpx**: HTTP client library
- **oauthlib**: OAuth authentication
- **urllib3**: Low-level HTTP handling

## Architectural Constraints

### Client Library Pattern
This is a library, not a service:
- No server components or database access
- Consumed by external applications
- Stateless request/response model

### Authentication Support
Must support multiple MAAS authentication methods:
- **OAuth 1.0a**: Primary authentication for v2 API
- **Bearer tokens**: For v3 API
- **API keys**: User-specific credentials

### Backward Compatibility
Maintain compatibility across MAAS versions:
- Support both v2 and v3 API endpoints
- Handle API version differences gracefully
- Clear error messages for version mismatches

## Key Patterns

### Client Initialization

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
        return MachinesResource(self)
    
    @property
    def devices(self) -> DevicesResource:
        return DevicesResource(self)
```

### Resource Class Pattern

Each resource type implements CRUD operations:

```python
class MachinesResource:
    """Machine resource operations."""
    
    def __init__(self, client: Client):
        self.client = client
    
    def list(self, **filters) -> list[Machine]:
        response = self.client.get("machines/", params=filters)
        return [Machine(data) for data in response.json()]
    
    def get(self, system_id: str) -> Machine:
        response = self.client.get(f"machines/{system_id}/")
        return Machine(response.json())
    
    def create(self, **kwargs) -> Machine:
        response = self.client.post("machines/", json=kwargs)
        return Machine(response.json())
    
    def update(self, system_id: str, **kwargs) -> Machine:
        response = self.client.put(f"machines/{system_id}/", json=kwargs)
        return Machine(response.json())
    
    def delete(self, system_id: str) -> None:
        self.client.delete(f"machines/{system_id}/")
```

### HTTP Request Handling

Centralized request handling with authentication:

```python
import requests
from requests_oauthlib import OAuth1

class Client:
    def _create_session(self) -> requests.Session:
        """Create authenticated session."""
        session = requests.Session()
        
        if self.api_key:
            # OAuth 1.0a
            consumer, token, secret = self.api_key.split(':')
            session.auth = OAuth1(
                consumer,
                client_secret="",
                resource_owner_key=token,
                resource_owner_secret=secret,
                signature_method="PLAINTEXT"
            )
        elif self.bearer_token:
            # Bearer token
            session.headers['Authorization'] = f'Bearer {self.bearer_token}'
        
        session.headers['Accept'] = 'application/json'
        return session
    
    def get(self, path: str, **kwargs):
        url = self._build_url(path)
        response = self._session.get(url, timeout=30, **kwargs)
        self._raise_for_status(response)
        return response
    
    def post(self, path: str, **kwargs):
        url = self._build_url(path)
        response = self._session.post(url, timeout=30, **kwargs)
        self._raise_for_status(response)
        return response
```

### Error Handling

Custom exception hierarchy for API errors:

```python
class MAASClientError(Exception):
    """Base exception for MAAS client errors."""
    
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code
    
    @classmethod
    def from_response(cls, response: requests.Response):
        """Create exception from HTTP response."""
        try:
            error_data = response.json()
            message = error_data.get("error", response.text)
        except ValueError:
            message = response.text
        
        status_code = response.status_code
        
        if status_code == 404:
            return ResourceNotFoundError(message, status_code)
        elif status_code == 400:
            return ValidationError(message, status_code)
        elif status_code == 401:
            return AuthenticationError(message, status_code)
        elif status_code == 403:
            return PermissionError(message, status_code)
        else:
            return cls(message, status_code)

class ResourceNotFoundError(MAASClientError):
    """Resource not found (404)."""

class ValidationError(MAASClientError):
    """Request validation failed (400)."""

class AuthenticationError(MAASClientError):
    """Authentication failed (401)."""
```

### Model Objects

Represent API resources as Python objects:

```python
from dataclasses import dataclass
from typing import List
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
    ip_addresses: List[str]
    created: datetime
    
    def __init__(self, data: dict):
        self.system_id = data["system_id"]
        self.hostname = data["hostname"]
        self.status = data["status"]
        self.architecture = data["architecture"]
        self.memory = data.get("memory", 0)
        self.cpu_count = data.get("cpu_count", 0)
        self.ip_addresses = data.get("ip_addresses", [])
        self.created = self._parse_datetime(data.get("created"))
    
    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
```

### API Version Support

Support both v2 and v3 APIs:

```python
class Client:
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

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### HTTP Mocking
Mock HTTP responses using pytest-mock:

```python
def test_list_machines(mocker):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"system_id": "abc123", "hostname": "machine-1", "status": "ready"}
    ]
    
    mocker.patch.object(Client, 'get', return_value=mock_response)
    
    client = Client(api_url="http://test.example.com/MAAS/api/2.0/")
    machines = client.machines.list()
    
    assert len(machines) == 1
    assert machines[0].hostname == "machine-1"
```

### Integration Tests
Integration tests require a real MAAS instance and should be marked with `@pytest.mark.integration`.

## Integration Points

### MAAS CLI
- **Purpose**: CLI commands use this client library for API communication
- **Interface**: Direct Python imports
- **Key Considerations**: Shared authentication and error handling

### External Tools
- **Purpose**: Third-party integrations (Terraform, Ansible, custom scripts)
- **Interface**: Public Python API
- **Key Considerations**: Backward compatibility across versions

### Python Applications
- **Purpose**: Infrastructure automation and deployment orchestration
- **Interface**: Imported as Python package
- **Key Considerations**: Thread-safe session handling, connection pooling

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Hardcoded URLs

```python
# WRONG
client = Client(api_url="http://localhost:5240/MAAS/api/2.0/")

# Correct
client = Client(api_url=os.getenv("MAAS_API_URL"))
```

### No Timeout

```python
# WRONG
response = session.get(url)

# Correct
response = session.get(url, timeout=30)
```

### Poor Error Messages

```python
# WRONG
except ResourceNotFoundError:
    raise Exception("Not found")

# Correct
except ResourceNotFoundError:
    raise ResourceNotFoundError(
        f"Machine '{system_id}' not found. "
        f"Use client.machines.list() to see available machines."
    )
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Client-Specific Security
- Never log API keys or tokens
- Use environment variables for credentials
- Prefer HTTPS and validate certificates
- Support custom CA certificates for enterprise environments
- Clear sensitive data from memory when done

## Performance Considerations

### Connection Pooling
Reuse HTTP connections via single session per client:
- Connection pool configuration
- Keep-alive support
- Configurable pool size

### Request Batching
Batch requests where possible for bulk operations and parallel requests for independent resources.

## Additional Resources

- Python Requests: https://requests.readthedocs.io/
- OAuth 1.0a: https://oauth.net/core/1.0a/
- MAAS API Documentation: https://maas.io/docs/api