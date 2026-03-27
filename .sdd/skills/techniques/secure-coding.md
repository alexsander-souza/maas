# Secure Coding

## Purpose

Define security-focused coding practices to prevent common vulnerabilities in MAAS code, including input validation, secure database access, credential management, and cryptographic operations.

## When to Use

- Writing any code that handles user input
- Implementing authentication or authorization
- Accessing databases or external systems
- Working with cryptographic operations
- Handling credentials or secrets
- Processing network requests

## Pattern Examples

### Never Hardcode Credentials

**Python - Use Environment Variables**:

```python
import os

# Never hardcode
# DB_PASSWORD = "secret123"  # WRONG

# Correct: Use environment variables
DB_PASSWORD = os.environ.get("MAAS_DB_PASSWORD")
if not DB_PASSWORD:
    raise ValueError("MAAS_DB_PASSWORD environment variable not set")

# Or use configuration files with proper permissions
from maasserver.config import get_secret
api_key = get_secret("temporal_api_key")
```

**Go - Environment Variables**:

```go
import "os"

// Never hardcode
// const apiKey = "secret123"  // WRONG

// Correct
apiKey := os.Getenv("MAAS_API_KEY")
if apiKey == "" {
    return errors.New("MAAS_API_KEY not set")
}
```

### Parameterized Database Queries

**Python - SQLAlchemy Core (Always Parameterized)**:

```python
from sqlalchemy import select

# Correct: SQLAlchemy automatically parameterizes
stmt = select(MachineTable).where(MachineTable.c.hostname == user_input)
result = await connection.execute(stmt)

# Never do this
# query = f"SELECT * FROM machines WHERE hostname = '{user_input}'"  # SQL INJECTION!
```

**Python - Django ORM (Always Parameterized)**:

```python
# Correct: Django ORM parameterizes automatically
machines = Machine.objects.filter(hostname=user_input)

# Never use raw SQL with string formatting
# Machine.objects.raw(f"SELECT * FROM machine WHERE id = {machine_id}")  # WRONG
# Correct raw SQL
Machine.objects.raw("SELECT * FROM machine WHERE id = %s", [machine_id])
```

**Go - Database Queries**:

```go
// Correct: Use placeholders
row := db.QueryRow("SELECT * FROM machines WHERE hostname = $1", hostname)

// Never use string concatenation
// query := "SELECT * FROM machines WHERE hostname = '" + hostname + "'"  // SQL INJECTION!
```

### Input Validation

**Python - Pydantic Models**:

```python
from pydantic import BaseModel, Field, field_validator
import re

class MachineRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    zone_id: int = Field(gt=0)
    
    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        # Whitelist pattern: only allow valid hostname characters
        pattern = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
        if not re.match(pattern, value.lower()):
            raise ValueError("Invalid hostname format")
        return value.lower()
```

**Go - Request Validation**:

```go
import (
    "errors"
    "regexp"
)

func ValidateHostname(hostname string) error {
    if len(hostname) == 0 || len(hostname) > 255 {
        return errors.New("hostname must be 1-255 characters")
    }
    
    // Whitelist validation
    pattern := regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)
    if !pattern.MatchString(hostname) {
        return errors.New("invalid hostname format")
    }
    
    return nil
}
```

### Sanitize User Input

**Prevent Path Traversal**:

```python
import os
from pathlib import Path

def safe_file_access(base_dir: str, user_filename: str) -> Path:
    """Prevent directory traversal attacks."""
    base = Path(base_dir).resolve()
    target = (base / user_filename).resolve()
    
    # Ensure target is within base directory
    if not target.is_relative_to(base):
        raise ValueError("Invalid file path")
    
    return target

# Usage
safe_path = safe_file_access("/var/lib/maas/images", user_provided_name)
```

**Prevent Command Injection**:

```python
import subprocess
import shlex

# Never use shell=True with user input
# subprocess.run(f"ls {user_input}", shell=True)  # COMMAND INJECTION!

# Correct: Use list of arguments, no shell
subprocess.run(["ls", user_input], shell=False, check=True)

# If shell is absolutely necessary, validate strictly
allowed_commands = {"status", "info", "list"}
if command not in allowed_commands:
    raise ValueError("Invalid command")
```

### Authentication and Authorization

**Check Permissions**:

```python
def delete_machine(request, machine_id: int):
    user = request.user
    machine = get_machine(machine_id)
    
    # Always check authorization before action
    if not user.has_perm("maasserver.delete_machine"):
        raise PermissionDenied("User cannot delete machines")
    
    # Additional ownership checks if needed
    if machine.owner != user and not user.is_admin:
        raise PermissionDenied("Can only delete own machines")
    
    machine.delete()
```

**Session Management**:

```python
# Use secure session settings (in Django settings)
SESSION_COOKIE_SECURE = True  # HTTPS only
SESSION_COOKIE_HTTPONLY = True  # No JavaScript access
SESSION_COOKIE_SAMESITE = 'Strict'  # CSRF protection
CSRF_COOKIE_SECURE = True
```

### Cryptographic Operations

**Use Secure Defaults**:

```python
import secrets
import hashlib

# Generate secure random tokens
token = secrets.token_urlsafe(32)

# Hash passwords (use framework methods)
from django.contrib.auth.hashers import make_password
hashed = make_password(password)  # Uses PBKDF2 by default

# Never use weak hashing
# hash = hashlib.md5(password.encode()).hexdigest()  # WRONG: MD5 is broken
# hash = hashlib.sha1(password.encode()).hexdigest()  # WRONG: SHA1 is weak
```

**Go - Cryptographic Operations**:

```go
import (
    "crypto/rand"
    "crypto/sha256"
    "encoding/base64"
)

// Generate secure random bytes
func GenerateToken(length int) (string, error) {
    bytes := make([]byte, length)
    if _, err := rand.Read(bytes); err != nil {
        return "", err
    }
    return base64.URLEncoding.EncodeToString(bytes), nil
}

// Use strong hashing
hash := sha256.Sum256([]byte(data))
```

### Avoid Insecure Defaults

**Python - Disable Debug in Production**:

```python
# settings.py
DEBUG = False  # Never True in production
ALLOWED_HOSTS = ['maas.example.com']  # Explicit allowed hosts
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']  # From environment

# Disable insecure features
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
```

**Go - Secure Defaults**:

```go
// Disable TLS verification only for testing
tlsConfig := &tls.Config{
    InsecureSkipVerify: false,  // Never true in production
    MinVersion:         tls.VersionTLS12,
}
```

## Anti-patterns

### ❌ Hardcoded Credentials

```python
# NEVER hardcode secrets
DATABASE_PASSWORD = "mysecretpassword"  # WRONG
API_KEY = "abc123def456"  # WRONG

# Correct: Use environment variables
DATABASE_PASSWORD = os.environ["DB_PASSWORD"]
```

### ❌ String Formatting in SQL

```python
# NEVER use string formatting for SQL
query = f"SELECT * FROM machines WHERE id = {machine_id}"  # SQL INJECTION
query = "SELECT * FROM machines WHERE name = '" + name + "'"  # SQL INJECTION

# Correct: Use parameterized queries (ORM does this automatically)
stmt = select(MachineTable).where(MachineTable.c.id == machine_id)
```

### ❌ Trusting User Input

```python
# NEVER trust user input directly
filename = user_input  # Could be "../../../etc/passwd"
os.remove(filename)  # WRONG

# Correct: Validate and sanitize
safe_path = safe_file_access(base_dir, user_input)
```

### ❌ Weak Cryptography

```python
# NEVER use weak hashing
import hashlib
password_hash = hashlib.md5(password.encode()).hexdigest()  # WRONG
password_hash = hashlib.sha1(password.encode()).hexdigest()  # WRONG

# Correct: Use framework password hashing
from django.contrib.auth.hashers import make_password
password_hash = make_password(password)
```

### ❌ Exposing Sensitive Information

```python
# NEVER expose sensitive data in errors
try:
    authenticate(username, password)
except Exception as e:
    # WRONG: Leaks implementation details
    return {"error": str(e), "sql": query, "password": password}

# Correct: Generic error messages
except AuthenticationError:
    return {"error": "Invalid credentials"}
```

### ❌ Missing Authorization Checks

```python
# NEVER skip permission checks
def delete_machine(machine_id):
    # WRONG: No authorization check
    Machine.objects.get(id=machine_id).delete()

# Correct: Always check permissions
def delete_machine(request, machine_id):
    if not request.user.has_perm("delete_machine"):
        raise PermissionDenied()
    Machine.objects.get(id=machine_id).delete()
```

## Related Skills

- **Secret Management**: [secret-management.md](secret-management.md) - Handling credentials
- **Input Validation**: [input-validation.md](input-validation.md) - Sanitizing user input
- **SQLAlchemy**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md) - Safe database queries
- **Django**: [../languages/django-patterns.md](../languages/django-patterns.md) - Django security
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Secure Python code

## Security Principles

1. **Defense in Depth**: Multiple layers of security controls
2. **Least Privilege**: Minimal permissions necessary
3. **Fail Securely**: Errors should not expose information
4. **Secure by Default**: Safe defaults, explicit opt-in for risky features
5. **Never Trust Input**: Validate and sanitize all external data
6. **Parameterize Queries**: Never concatenate SQL
7. **No Hardcoded Secrets**: Use environment variables or secret management
8. **Use Strong Crypto**: Modern algorithms with secure defaults