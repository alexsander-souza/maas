# maascommon Subsystem

## Purpose

Shared utility functions, constants, enumerations, and type definitions used across all MAAS components. This subsystem provides common functionality without business logic, ensuring consistency and reducing duplication across Python codebases.

**Status**: Stable - foundational utilities for all Python components.

## Location

`src/maascommon`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **No external dependencies** (standard library only)

### Key Libraries
- **typing**: Type hints and generics
- **enum**: Enumeration support
- **dataclasses**: Data structure definitions

## Architectural Constraints

### Minimal Dependencies

**Critical**: maascommon must have **zero external dependencies** outside Python's standard library.

**Why**: This subsystem is imported by all other MAAS components. External dependencies would create circular dependency issues and bloat all components.

```python
# ✅ Allowed
import re
from typing import Optional
from dataclasses import dataclass

# ❌ Not allowed
import pydantic  # External dependency
import requests  # External dependency
```

### Shared by Multiple Components

This subsystem is imported by:
- `maasserver` (Django application)
- `maasservicelayer` (Service/Repository layers)
- `maasapiserver` (FastAPI application)
- `maastemporalworker` (Temporal workers)
- `provisioningserver` (Legacy rack controller)

Changes here impact **all** components - test thoroughly.

### Pyright Compliance

All code must be fully type-hinted and pass Pyright strict mode:
- No `Any` types without justification
- Complete type coverage
- Generic types properly specified
- Protocol definitions where appropriate

### Zero Business Logic

**Absolute rule**: No business logic, domain models, or application-specific code in maascommon.

This is for **utilities only**: string manipulation, validation helpers, constants, basic data structures.

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) for common Python patterns.

### Utility Function Pattern

Pure functions with clear, single responsibilities:

```python
from typing import TypeVar, Sequence

T = TypeVar('T')

def chunk_list(items: Sequence[T], chunk_size: int) -> list[list[T]]:
    """Split list into chunks of specified size.
    
    Args:
        items: List to chunk
        chunk_size: Size of each chunk
        
    Returns:
        List of chunks
        
    Raises:
        ValueError: If chunk_size < 1
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    
    return [list(items[i:i + chunk_size]) for i in range(0, len(items), chunk_size)]
```

### Enum Pattern

Use Enums for constants with behavior:

```python
from enum import Enum, auto

class NodeStatus(str, Enum):
    """Machine status enumeration."""
    NEW = "new"
    READY = "ready"
    ALLOCATED = "allocated"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    
    def is_terminal(self) -> bool:
        """Check if status is terminal (no further transitions)."""
        return self in (NodeStatus.DEPLOYED, NodeStatus.FAILED)
```

### Constants Pattern

Group related constants:

```python
# Network constants
DEFAULT_MTU = 1500
MAX_HOSTNAME_LENGTH = 255
MAC_ADDRESS_PATTERN = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'

# Timeout constants
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 3

# Size constants
MB = 1024 * 1024
GB = 1024 * MB
```

### Validation Utilities

Reusable validation functions:

```python
import re
from typing import Optional

def validate_mac_address(mac: str) -> bool:
    """Validate MAC address format."""
    pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return bool(re.match(pattern, mac))

def validate_ipv4_address(ip: str) -> bool:
    """Validate IPv4 address format."""
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    return all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)

def validate_hostname(hostname: str) -> Optional[str]:
    """Validate hostname, return error message if invalid."""
    if not hostname:
        return "Hostname cannot be empty"
    if len(hostname) > 255:
        return "Hostname too long (max 255 characters)"
    if not re.match(r'^[a-z0-9-]+$', hostname):
        return "Hostname contains invalid characters"
    return None
```

### Type Definitions

Common Protocol and TypeVar definitions:

```python
from typing import Protocol, TypeVar

class Closeable(Protocol):
    """Protocol for objects that can be closed."""
    def close(self) -> None:
        ...

class Readable(Protocol):
    """Protocol for objects that can be read."""
    def read(self, size: int = -1) -> bytes:
        ...

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.
> **See**: [python-testing.md](../../skills/languages/python-testing.md) for Python-specific testing.

### Comprehensive Test Coverage

All utilities must have 100% test coverage:

```python
import pytest

class TestChunkList:
    def test_chunk_list_even_division(self):
        result = chunk_list([1, 2, 3, 4], 2)
        assert result == [[1, 2], [3, 4]]
    
    def test_chunk_list_empty(self):
        result = chunk_list([], 5)
        assert result == []
    
    def test_chunk_list_invalid_size(self):
        with pytest.raises(ValueError):
            chunk_list([1, 2, 3], 0)
```

### Doctest Integration

Use doctests for simple examples:

```python
def fibonacci(n: int) -> int:
    """Calculate nth Fibonacci number.
    
    >>> fibonacci(0)
    0
    >>> fibonacci(1)
    1
    >>> fibonacci(10)
    55
    """
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
```

### Running Tests

```bash
# All tests
pytest src/maascommon/tests/

# With coverage
pytest --cov=maascommon src/maascommon/tests/

# Doctests
pytest --doctest-modules src/maascommon/
```

## Development Guidelines

### Adding New Utilities

**Checklist before adding**:
1. Is this truly shared across multiple components?
2. Does it have zero external dependencies?
3. Is it pure utility code (no business logic)?
4. Is it fully type-hinted?
5. Does it have comprehensive tests?

If all answers are "yes", proceed. Otherwise, put it in the component that needs it.

### Type Hints Requirements

All functions must have complete type hints:

```python
# ❌ Missing type hints
def process_items(items, limit):
    return items[:limit]

# ✅ Complete type hints
from typing import Sequence, TypeVar

T = TypeVar('T')

def process_items(items: Sequence[T], limit: int) -> list[T]:
    """Process items with limit."""
    return list(items[:limit])
```

### Documentation Requirements

Every public function needs:
- One-line summary
- Args documentation
- Returns documentation
- Raises documentation (if applicable)
- Examples (via doctest when possible)

```python
def example_function(value: str, max_length: int = 100) -> str:
    """Truncate string to maximum length.
    
    Args:
        value: String to truncate
        max_length: Maximum allowed length (default: 100)
        
    Returns:
        Truncated string with ellipsis if needed
        
    Raises:
        ValueError: If max_length < 1
        
    Examples:
        >>> example_function("hello", 10)
        'hello'
        >>> example_function("hello world", 8)
        'hello...'
    """
    if max_length < 1:
        raise ValueError("max_length must be at least 1")
    if len(value) <= max_length:
        return value
    return value[:max_length - 3] + "..."
```

### Avoiding Business Logic

❌ **Don't** add domain-specific logic:
```python
# WRONG - Business logic
def can_deploy_machine(machine_status: str, pool_available: bool) -> bool:
    return machine_status == "ready" and pool_available
```

✅ **Do** add generic utilities:
```python
# Correct - Generic utility
def all_conditions_met(conditions: list[bool]) -> bool:
    """Check if all conditions are true."""
    return all(conditions)
```

## Integration Points

### Used By All Components

All Python components import from maascommon:
- `maasserver`
- `maasservicelayer`
- `maasapiserver`
- `maastemporalworker`
- `provisioningserver`

### Versioning Considerations

Changes to maascommon affect all components:
- Breaking changes require coordination
- Deprecate before removing functions
- Use versioned names for major changes (e.g., `parse_datetime_v2`)

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Adding Business Logic

❌ **Don't** add domain-specific logic:
```python
# WRONG - This is business logic
def calculate_machine_priority(machine: dict) -> int:
    return machine["cpu_count"] * machine["memory"]
```

✅ **Do** keep it generic:
```python
# Correct - Generic utility
def calculate_priority(values: list[int], weights: list[int]) -> int:
    """Calculate weighted priority."""
    return sum(v * w for v, w in zip(values, weights))
```

### Heavy Dependencies

❌ **Don't** add external dependencies:
```python
# WRONG - External dependency
import pandas as pd

def calculate_average(values: list[float]) -> float:
    return pd.Series(values).mean()
```

✅ **Do** use standard library:
```python
# Correct - Standard library only
def calculate_average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
```

### Missing Type Hints

❌ **Don't** omit type hints:
```python
# WRONG - No type hints
def process_data(data, flag):
    return [x for x in data if flag]
```

✅ **Do** add complete type hints:
```python
# Correct - Full type hints
def process_data(data: list[int], flag: bool) -> list[int]:
    return [x for x in data if flag]
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Input Validation

Validation utilities must be robust:
- Handle edge cases (empty strings, None, extreme values)
- Return clear error messages
- Never raise unexpected exceptions
- See [input-validation.md](../../skills/techniques/input-validation.md)

### No Secrets

Never include sensitive data in maascommon:
- No default passwords
- No API keys
- No cryptographic keys
- No connection strings

### Safe Defaults

Use safe defaults for all utilities:
- Fail closed on security checks
- Conservative timeouts
- Strict validation by default

## Performance Considerations

### Optimization Focus

Only optimize utilities that are:
- Called in hot paths
- Processing large datasets
- Identified as bottlenecks via profiling

Don't prematurely optimize - measure first.

### Lazy Evaluation

Use generators for large sequences:

```python
def lazy_process(items: list[int]) -> Generator[int, None, None]:
    """Process items lazily."""
    for item in items:
        yield item * 2

# Better than loading all into memory
def eager_process(items: list[int]) -> list[int]:
    return [item * 2 for item in items]
```

### Caching

Use `functools.lru_cache` for expensive pure functions:

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_computation(n: int) -> int:
    """Expensive pure function."""
    # ... complex calculation
    return result
```

## Additional Resources

- **Python Docs**: https://docs.python.org/3/
- **Typing**: https://docs.python.org/3/library/typing.html
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [naming-conventions.md](../../skills/techniques/naming-conventions.md)