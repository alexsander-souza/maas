# Input Validation

## Purpose

Define patterns for validating and sanitizing user input across MAAS code to prevent injection attacks, data corruption, and security vulnerabilities.

## When to Use

- Processing data from HTTP requests
- Handling command-line arguments
- Reading configuration files
- Processing file uploads
- Parsing external data sources
- Accepting any untrusted input

## Pattern Examples

### Pydantic Validators (Python)

**Field-Level Validation**:

```python
from pydantic import BaseModel, Field, field_validator
import re

class MachineRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    zone_id: int = Field(gt=0)
    cpu_count: int = Field(ge=1, le=256)
    
    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        # Whitelist approach: only allow valid characters
        if not re.match(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$', value.lower()):
            raise ValueError("Hostname must contain only alphanumeric and hyphen")
        return value.lower()
```

**Model-Level Validation**:

```python
from pydantic import model_validator

class MachineRequest(BaseModel):
    hostname: str
    cpu_count: int
    memory: int
    
    @model_validator(mode="after")
    def validate_resources(self) -> "MachineRequest":
        # Cross-field validation
        if self.cpu_count > 64 and self.memory < 65536:
            raise ValueError("High CPU count requires at least 64GB memory")
        return self
```

**Sanitizing Input**:

```python
@field_validator("hostname", mode="before")
@classmethod
def sanitize_hostname(cls, value: str) -> str:
    # Strip whitespace and normalize
    return value.strip().lower()

@field_validator("description", mode="before")
@classmethod
def sanitize_description(cls, value: str) -> str:
    # Remove potentially dangerous characters
    if value is None:
        return ""
    # Remove control characters
    return "".join(char for char in value if char.isprintable())
```

### Django Form Validation

**Form with Validation**:

```python
from django import forms
from django.core.validators import RegexValidator

class MachineForm(forms.Form):
    hostname = forms.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$',
                message="Invalid hostname format"
            )
        ]
    )
    zone_id = forms.IntegerField(min_value=1)
    
    def clean_hostname(self):
        hostname = self.cleaned_data['hostname']
        # Additional validation
        if hostname.startswith('test-') and not settings.DEBUG:
            raise forms.ValidationError("Test hostnames not allowed in production")
        return hostname.lower()
    
    def clean(self):
        cleaned_data = super().clean()
        # Cross-field validation
        hostname = cleaned_data.get('hostname')
        zone_id = cleaned_data.get('zone_id')
        
        if hostname and zone_id:
            # Check for duplicates
            if Machine.objects.filter(hostname=hostname, zone_id=zone_id).exists():
                raise forms.ValidationError("Machine with this hostname already exists in zone")
        
        return cleaned_data
```

### Go Input Validation

**Struct Validation**:

```go
import (
    "errors"
    "regexp"
    "strings"
)

type MachineRequest struct {
    Hostname string `json:"hostname"`
    ZoneID   int    `json:"zone_id"`
    CPUCount int    `json:"cpu_count"`
}

func (r *MachineRequest) Validate() error {
    // Trim and normalize
    r.Hostname = strings.ToLower(strings.TrimSpace(r.Hostname))
    
    // Validate hostname
    if len(r.Hostname) == 0 || len(r.Hostname) > 255 {
        return errors.New("hostname must be 1-255 characters")
    }
    
    // Whitelist validation
    hostnamePattern := regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)
    if !hostnamePattern.MatchString(r.Hostname) {
        return errors.New("hostname contains invalid characters")
    }
    
    // Validate numeric fields
    if r.ZoneID <= 0 {
        return errors.New("zone_id must be positive")
    }
    
    if r.CPUCount < 1 || r.CPUCount > 256 {
        return errors.New("cpu_count must be between 1 and 256")
    }
    
    return nil
}
```

**Sanitization Functions**:

```go
func SanitizeHostname(input string) (string, error) {
    // Trim whitespace
    cleaned := strings.TrimSpace(input)
    cleaned = strings.ToLower(cleaned)
    
    // Remove invalid characters (whitelist approach)
    validPattern := regexp.MustCompile(`[^a-z0-9-]`)
    cleaned = validPattern.ReplaceAllString(cleaned, "")
    
    if len(cleaned) == 0 {
        return "", errors.New("hostname is empty after sanitization")
    }
    
    return cleaned, nil
}

func SanitizeFilename(input string) (string, error) {
    // Prevent path traversal
    if strings.Contains(input, "..") || strings.Contains(input, "/") {
        return "", errors.New("invalid filename")
    }
    
    // Whitelist: alphanumeric, dash, underscore, dot
    validPattern := regexp.MustCompile(`^[a-zA-Z0-9._-]+$`)
    if !validPattern.MatchString(input) {
        return "", errors.New("filename contains invalid characters")
    }
    
    return input, nil
}
```

### File Path Validation

**Prevent Path Traversal**:

```python
from pathlib import Path

def validate_safe_path(base_dir: str, user_path: str) -> Path:
    """Ensure user-provided path is within base directory."""
    base = Path(base_dir).resolve()
    target = (base / user_path).resolve()
    
    # Ensure target is within base
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path {user_path} is outside base directory")
    
    return target

# Usage
safe_path = validate_safe_path("/var/lib/maas/images", user_filename)
with open(safe_path, 'r') as f:
    content = f.read()
```

**Go Path Validation**:

```go
import (
    "path/filepath"
    "strings"
)

func ValidateSafePath(baseDir, userPath string) (string, error) {
    // Prevent path traversal
    if strings.Contains(userPath, "..") {
        return "", errors.New("path contains directory traversal")
    }
    
    // Join and clean path
    fullPath := filepath.Join(baseDir, userPath)
    cleanPath := filepath.Clean(fullPath)
    
    // Ensure result is within base directory
    if !strings.HasPrefix(cleanPath, baseDir) {
        return "", errors.New("path is outside base directory")
    }
    
    return cleanPath, nil
}
```

### Email and URL Validation

**Python - Email Validation**:

```python
from pydantic import BaseModel, EmailStr, HttpUrl

class UserRequest(BaseModel):
    email: EmailStr  # Validates email format
    website: HttpUrl | None = None  # Validates URL format
```

**Python - Manual Validation**:

```python
import re
from urllib.parse import urlparse

def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except:
        return False
```

### List and Collection Validation

**Python - List Size and Content**:

```python
from pydantic import BaseModel, Field, field_validator

class MachineListRequest(BaseModel):
    machine_ids: list[int] = Field(min_length=1, max_length=100)
    
    @field_validator("machine_ids")
    @classmethod
    def validate_machine_ids(cls, value: list[int]) -> list[int]:
        # Check all IDs are positive
        if any(id <= 0 for id in value):
            raise ValueError("All machine IDs must be positive")
        
        # Check for duplicates
        if len(value) != len(set(value)):
            raise ValueError("Duplicate machine IDs not allowed")
        
        return value
```

**Go - Validate Collections**:

```go
func ValidateMachineIDs(ids []int) error {
    if len(ids) == 0 {
        return errors.New("machine ID list cannot be empty")
    }
    
    if len(ids) > 100 {
        return errors.New("too many machine IDs (max 100)")
    }
    
    // Check for duplicates
    seen := make(map[int]bool)
    for _, id := range ids {
        if id <= 0 {
            return errors.New("all machine IDs must be positive")
        }
        if seen[id] {
            return errors.New("duplicate machine IDs not allowed")
        }
        seen[id] = true
    }
    
    return nil
}
```

## Anti-patterns

### ❌ Blacklist Validation

```python
# NEVER use blacklist approach
def validate_hostname(hostname: str) -> bool:
    # Wrong: Tries to block bad characters
    bad_chars = ['/', '\\', ';', '&', '|']
    return not any(c in hostname for c in bad_chars)
    # Easy to bypass with characters you didn't think of

# Correct: Whitelist approach
def validate_hostname(hostname: str) -> bool:
    # Only allow known-good characters
    return bool(re.match(r'^[a-z0-9-]+$', hostname))
```

### ❌ Client-Side Only Validation

```python
# NEVER trust client-side validation alone
@router.post("/machines")
async def create_machine(request: dict):
    # WRONG: No server-side validation
    # Assumes client validated the data
    machine = Machine(**request)
    
# Correct: Always validate on server
@router.post("/machines")
async def create_machine(request: MachineRequest):
    # Pydantic validates automatically
    machine = await service.create(request)
```

### ❌ Insufficient Validation

```python
# NEVER do minimal validation
def validate_email(email: str) -> bool:
    return '@' in email  # WRONG: Too permissive

# Correct: Comprehensive validation
def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))
```

### ❌ Accepting Any File Upload

```python
# NEVER accept files without validation
def upload_file(file):
    # WRONG: No validation
    file.save(f"/uploads/{file.filename}")

# Correct: Validate type, size, and sanitize filename
def upload_file(file, allowed_types=None, max_size_mb=10):
    if allowed_types is None:
        allowed_types = {'.jpg', '.png', '.pdf'}
    
    # Check file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_types:
        raise ValueError(f"File type {ext} not allowed")
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    size_mb = file.tell() / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ValueError(f"File too large: {size_mb}MB (max {max_size_mb}MB)")
    
    # Sanitize filename
    safe_filename = sanitize_filename(file.filename)
    file.save(f"/uploads/{safe_filename}")
```

## Related Skills

- **Security Practices**: [security-practices.md](security-practices.md) - Comprehensive security guidelines including secrets
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Pydantic validation
- **Go Patterns**: [../languages/go-patterns.md](../languages/go-patterns.md) - Go validation patterns
- **API Endpoint**: [../compositions/api-endpoint.md](../compositions/api-endpoint.md) - Endpoint validation

## Validation Principles

1. **Whitelist Over Blacklist**: Define what IS allowed, not what ISN'T
2. **Validate Early**: Check input at entry points before processing
3. **Fail Securely**: Reject invalid input with clear error messages
4. **Server-Side Always**: Never rely solely on client-side validation
5. **Type Safety**: Use type systems and validation libraries (Pydantic)
6. **Sanitize When Needed**: Clean input that will be displayed or stored
7. **Context-Specific**: Different contexts need different validation rules
8. **Comprehensive**: Check format, length, range, and business rules

## Common Validation Patterns

### Python Quick Reference

```python
from pydantic import BaseModel, Field, field_validator
import re

class ValidatedRequest(BaseModel):
    # Length constraints
    name: str = Field(min_length=1, max_length=255)
    
    # Numeric constraints
    count: int = Field(ge=1, le=1000)
    
    # Pattern matching
    email: str
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, value):
            raise ValueError("Invalid email format")
        return value.lower()
```

### Go Quick Reference

```go
func Validate(input string) error {
    // Length check
    if len(input) == 0 || len(input) > 255 {
        return errors.New("input must be 1-255 characters")
    }
    
    // Pattern check (whitelist)
    pattern := regexp.MustCompile(`^[a-z0-9-]+$`)
    if !pattern.MatchString(input) {
        return errors.New("input contains invalid characters")
    }
    
    return nil
}
```