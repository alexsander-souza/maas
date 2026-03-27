# maascommon Subsystem

## Purpose

Common utilities and shared functionality used across multiple MAAS components. This subsystem provides reusable utilities, helper functions, constants, and common patterns that are needed by multiple parts of the MAAS codebase, ensuring consistency and avoiding code duplication.

**Status**: Active - foundational library for MAAS components.

## Location

`src/maascommon`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Standard Library**: Preferred for most functionality
- **Minimal External Dependencies**: Only essential third-party libraries

### Key Libraries
- **typing**: Type hints and annotations
- **dataclasses**: Data structures
- **enum**: Enumeration types
- Standard library modules (os, sys, re, etc.)

## Architectural Constraints

### Minimal Dependencies

**Critical**: This subsystem MUST maintain minimal external dependencies:
- Prefer standard library over third-party packages
- Any new dependency affects ALL components using maascommon
- Dependencies must be carefully evaluated and justified
- Keep the dependency tree shallow and lean

### Shared by Multiple Components

Changes here impact the entire MAAS ecosystem:
- `maasserver` (Django region controller)
- `maasapiserver` (FastAPI v3 API)
- `maasservicelayer` (Service and repository layers)
- `provisioningserver` (Rack controller)
- `maascli` (Command-line interface)
- `maasagent` (Go agent via Python bindings if needed)

### Pyright Compliance

**Critical**: All code MUST pass Pyright type checking:
- Full type hints on all public functions
- No `Any` types without justification
- Strict type checking enabled
- Generic types properly annotated
- Protocol definitions for duck typing

### Zero Business Logic

This subsystem contains ONLY generic utilities:
- No MAAS-specific business rules
- No database access
- No API endpoints
- No workflow orchestration
- Pure utility functions only

## Key Patterns

### Utility Function Pattern

Well-defined, focused utility functions:

```python
from typing import TypeVar, Iterable, List

T = TypeVar('T')

def chunk_list(items: List[T], chunk_size: int) -> List[List[T]]:
    """
    Split a list into chunks of specified size.
    
    Args:
        items: List to split into chunks
        chunk_size: Maximum size of each chunk
        
    Returns:
        List of chunks
        
    Raises:
        ValueError: If chunk_size <= 0
        
    Example:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    
    return [
        items[i:i + chunk_size]
        for i in range(0, len(items), chunk_size)
    ]
```

### Enum Pattern

Shared enumerations for consistency:

```python
from enum import Enum, auto

class NodeStatus(str, Enum):
    """Machine/node status values used across MAAS."""
    
    NEW = "new"
    COMMISSIONING = "commissioning"
    TESTING = "testing"
    READY = "ready"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    BROKEN = "broken"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def is_terminal(cls, status: "NodeStatus") -> bool:
        """Check if status is a terminal state."""
        return status in {cls.DEPLOYED, cls.FAILED, cls.BROKEN}
```

### Constants Pattern

Centralized constants:

```python
# Network constants
DEFAULT_MTU = 1500
MAX_VLAN_ID = 4094
MIN_VLAN_ID = 1

# Timeout constants
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

# Size constants
KB = 1024
MB = 1024 * KB
GB = 1024 * MB
TB = 1024 * GB
```

### Validation Utilities

Reusable validation functions:

```python
import re
from typing import Optional

def validate_mac_address(mac: str) -> bool:
    """
    Validate MAC address format.
    
    Args:
        mac: MAC address string to validate
        
    Returns:
        True if valid MAC address format
        
    Example:
        >>> validate_mac_address("00:11:22:33:44:55")
        True
        >>> validate_mac_address("invalid")
        False
    """
    pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
    return pattern.match(mac) is not None

def validate_ipv4_address(ip: str) -> bool:
    """
    Validate IPv4 address format.
    
    Args:
        ip: IPv4 address string to validate
        
    Returns:
        True if valid IPv4 address
    """
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False

def validate_hostname(hostname: str) -> bool:
    """
    Validate hostname format according to RFC 1123.
    
    Args:
        hostname: Hostname to validate
        
    Returns:
        True if valid hostname
    """
    if not hostname or len(hostname) > 253:
        return False
    
    # Remove trailing dot if present
    if hostname.endswith('.'):
        hostname = hostname[:-1]
    
    # Check each label
    labels = hostname.split('.')
    pattern = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$', re.IGNORECASE)
    return all(pattern.match(label) for label in labels)
```

### Data Structure Utilities

Common data structure helpers:

```python
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class Result:
    """Generic result wrapper for operations that may fail."""
    
    success: bool
    value: Any = None
    error: Optional[str] = None
    
    @classmethod
    def ok(cls, value: Any) -> "Result":
        """Create a successful result."""
        return cls(success=True, value=value)
    
    @classmethod
    def fail(cls, error: str) -> "Result":
        """Create a failed result."""
        return cls(success=False, error=error)

def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries.
    
    Args:
        base: Base dictionary
        override: Dictionary with override values
        
    Returns:
        Merged dictionary (does not modify inputs)
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    
    return result
```

### Type Definitions

Shared type aliases and protocols:

```python
from typing import Protocol, TypeAlias, Union
from pathlib import Path

# Type aliases
StrOrBytes: TypeAlias = Union[str, bytes]
PathLike: TypeAlias = Union[str, Path]

# Protocols for duck typing
class Closeable(Protocol):
    """Protocol for objects that can be closed."""
    
    def close(self) -> None:
        """Close the resource."""
        ...

class Readable(Protocol):
    """Protocol for objects that can be read."""
    
    def read(self, size: int = -1) -> bytes:
        """Read up to size bytes."""
        ...
```

### String Utilities

Common string manipulation:

```python
def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to maximum length with suffix.
    
    Args:
        text: String to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to append if truncated
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix

def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in string.
    
    Collapses multiple whitespace characters into single spaces
    and strips leading/trailing whitespace.
    
    Args:
        text: String to normalize
        
    Returns:
        Normalized string
    """
    return ' '.join(text.split())
```

### Time Utilities

Time and datetime helpers:

```python
from datetime import datetime, timezone, timedelta
from typing import Optional

def utc_now() -> datetime:
    """
    Get current time in UTC with timezone info.
    
    Returns:
        Current UTC datetime
    """
    return datetime.now(timezone.utc)

def parse_iso_timestamp(timestamp: str) -> Optional[datetime]:
    """
    Parse ISO 8601 timestamp string.
    
    Args:
        timestamp: ISO 8601 formatted timestamp
        
    Returns:
        Parsed datetime or None if invalid
    """
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "2h 30m 15s")
    """
    td = timedelta(seconds=int(seconds))
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if td.days:
        parts.append(f"{td.days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    
    return ' '.join(parts)
```

## Testing Requirements

### Comprehensive Test Coverage

**Critical**: maascommon must have >95% test coverage:
- All public functions tested
- Edge cases covered
- Error conditions verified
- Type hints validated

```python
import pytest
from maascommon.utils import chunk_list, validate_mac_address

class TestChunkList:
    """Test chunk_list utility."""
    
    def test_chunk_list_even_division(self):
        """Test chunking with even division."""
        result = chunk_list([1, 2, 3, 4], 2)
        assert result == [[1, 2], [3, 4]]
    
    def test_chunk_list_uneven_division(self):
        """Test chunking with remainder."""
        result = chunk_list([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2], [3, 4], [5]]
    
    def test_chunk_list_empty(self):
        """Test chunking empty list."""
        result = chunk_list([], 5)
        assert result == []
    
    def test_chunk_list_invalid_size(self):
        """Test chunking with invalid size."""
        with pytest.raises(ValueError, match="must be positive"):
            chunk_list([1, 2, 3], 0)

class TestValidateMAC:
    """Test MAC address validation."""
    
    @pytest.mark.parametrize("mac,expected", [
        ("00:11:22:33:44:55", True),
        ("00-11-22-33-44-55", True),
        ("00:11:22:33:44:5G", False),
        ("00:11:22:33:44", False),
        ("", False),
    ])
    def test_validate_mac_address(self, mac, expected):
        """Test MAC address validation with various inputs."""
        assert validate_mac_address(mac) == expected
```

### Type Checking Tests

Validate Pyright compliance:

```bash
# Run Pyright type checker
pyright src/maascommon/

# Run mypy as additional validation
mypy --strict src/maascommon/
```

### Doctest Integration

Use doctests in docstrings:

```python
def fibonacci(n: int) -> int:
    """
    Calculate nth Fibonacci number.
    
    Args:
        n: Position in Fibonacci sequence (0-indexed)
        
    Returns:
        Fibonacci number at position n
        
    Raises:
        ValueError: If n is negative
        
    Examples:
        >>> fibonacci(0)
        0
        >>> fibonacci(1)
        1
        >>> fibonacci(5)
        5
        >>> fibonacci(10)
        55
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    
    if n <= 1:
        return n
    
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    
    return b
```

### Running Tests

```bash
# Run all maascommon tests
pytest src/maascommon/tests/

# Run with coverage
pytest --cov=maascommon --cov-report=html src/maascommon/tests/

# Run doctests
pytest --doctest-modules src/maascommon/

# Run type checks
pyright src/maascommon/
```

## Development Guidelines

### Adding New Utilities

Before adding to maascommon:

1. **Check if it already exists**: Search existing utilities first
2. **Evaluate generality**: Is it truly reusable across components?
3. **Consider dependencies**: Will it introduce new dependencies?
4. **Type safety**: Can it be fully type-annotated?
5. **Test coverage**: Can it be comprehensively tested?

### Dependency Addition Process

Adding a new dependency requires:

1. **Justification**: Document why standard library is insufficient
2. **Impact Analysis**: Which components will be affected?
3. **Alternatives Evaluation**: Consider all alternatives
4. **Team Review**: Requires approval from multiple maintainers
5. **Documentation**: Update dependency documentation

### Type Hints Requirements

All public functions MUST have complete type hints:

```python
# ✅ Good: Complete type hints
def process_items(
    items: List[str],
    transform: Callable[[str], str],
    filter_fn: Optional[Callable[[str], bool]] = None
) -> List[str]:
    """Process items with transformation and optional filtering."""
    result = [transform(item) for item in items]
    if filter_fn:
        result = [item for item in result if filter_fn(item)]
    return result

# ❌ Bad: Missing type hints
def process_items(items, transform, filter_fn=None):
    """Process items with transformation and optional filtering."""
    result = [transform(item) for item in items]
    if filter_fn:
        result = [item for item in result if filter_fn(item)]
    return result
```

### Documentation Requirements

Every public function requires:

```python
def example_function(param1: str, param2: int = 10) -> bool:
    """
    One-line summary of what the function does.
    
    More detailed explanation if needed. Can span multiple paragraphs
    and include implementation details, algorithm descriptions, etc.
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter with default value
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When parameter validation fails
        TypeError: When parameter types are incorrect
        
    Examples:
        >>> example_function("test", 5)
        True
        >>> example_function("", 0)
        False
        
    Notes:
        Any important notes about behavior, performance, or usage.
    """
    pass
```

### Avoiding Business Logic

❌ **Don't** add MAAS-specific business logic:
```python
# WRONG: Business logic belongs in services
def can_deploy_machine(machine: Machine) -> bool:
    """Check if machine can be deployed."""  # Business rule!
    return machine.status == "ready" and machine.power_state == "off"
```

✅ **Do** provide generic utilities:
```python
# CORRECT: Generic utility
def all_conditions_met(conditions: List[Callable[[], bool]]) -> bool:
    """Check if all condition functions return True."""
    return all(condition() for condition in conditions)
```

## Integration Points

### Used By All Components

Every MAAS component depends on maascommon:

```python
# In maasserver
from maascommon.enums import NodeStatus
from maascommon.utils import validate_mac_address

# In maasapiserver
from maascommon.constants import DEFAULT_TIMEOUT_SECONDS
from maascommon.validators import validate_hostname

# In maasservicelayer
from maascommon.types import Result
from maascommon.time import utc_now
```

### Versioning Considerations

Changes must maintain backward compatibility:
- Deprecate before removing
- Version new functionality when breaking
- Document migration paths
- Maintain changelog

## Common Pitfalls

### Adding Business Logic

❌ **Don't**:
```python
# Business logic in common utilities - WRONG!
def calculate_machine_priority(machine: Machine) -> int:
    if machine.pool == "critical":
        return 10
    return 5
```

✅ **Do**:
```python
# Generic utility
def calculate_priority(
    value: T,
    priority_map: Dict[T, int],
    default_priority: int = 0
) -> int:
    return priority_map.get(value, default_priority)
```

### Heavy Dependencies

❌ **Don't**:
```python
# Adding heavy dependencies - WRONG!
import pandas as pd  # Heavy dependency for simple utility
import numpy as np

def calculate_average(numbers: List[float]) -> float:
    return np.mean(numbers)
```

✅ **Do**:
```python
# Use standard library
from statistics import mean

def calculate_average(numbers: List[float]) -> float:
    return mean(numbers)
```

### Missing Type Hints

❌ **Don't**:
```python
def process_data(data):  # No type hints - WRONG!
    return [item.upper() for item in data]
```

✅ **Do**:
```python
def process_data(data: List[str]) -> List[str]:
    return [item.upper() for item in data]
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Python Best Practices**: General Python patterns
- **Type Hints**: Advanced typing patterns
- **Testing**: Comprehensive test strategies
- **Documentation**: Docstring and API documentation
- **Standard Library**: Effective use of Python stdlib

## Security Considerations

### Input Validation

Provide validation utilities but don't enforce:
- Validate format, not business rules
- Document validation behavior
- Handle edge cases safely
- Prevent injection in string utilities

### No Secrets

Never include secrets or credentials:
- No API keys
- No passwords
- No tokens
- Use environment variables in calling code

### Safe Defaults

Default values should be secure:
- Conservative timeout values
- Safe file permissions
- Secure random number generation

## Performance Considerations

### Optimization Focus

Optimize commonly-used utilities:
- Profile before optimizing
- Avoid premature optimization
- Document performance characteristics
- Provide complexity analysis

### Lazy Evaluation

Use lazy evaluation where appropriate:

```python
from typing import Iterator

def lazy_process(items: List[T]) -> Iterator[T]:
    """Process items lazily for memory efficiency."""
    for item in items:
        yield process_item(item)

# vs eager evaluation
def eager_process(items: List[T]) -> List[T]:
    """Process all items immediately."""
    return [process_item(item) for item in items]
```

### Caching

Provide caching utilities but don't enforce:

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_computation(value: int) -> int:
    """Cache results of expensive computation."""
    # Complex calculation...
    return result
```

## Documentation

### Module Documentation

Each module requires comprehensive docs:
- Purpose and scope
- Usage examples
- Public API reference
- Version history

### API Reference

Maintain API reference documentation:
- Auto-generated from docstrings
- Examples for all public functions
- Type signatures visible
- Links to related utilities

### Migration Guides

Document breaking changes:
- What changed and why
- Migration steps
- Deprecation timeline
- Example code updates

## Additional Resources

- Python Type Hints: https://docs.python.org/3/library/typing.html
- Pyright: https://github.com/microsoft/pyright
- Python Standard Library: https://docs.python.org/3/library/
- `AGENTS.md`: General coding guidelines
- PEP 8: https://pep8.org/