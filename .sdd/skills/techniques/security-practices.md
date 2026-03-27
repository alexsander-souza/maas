# Security Practices

## Purpose

Define comprehensive security practices for MAAS code, including credential management, secure database access, authentication, cryptographic operations, and input handling.

## When to Use

- Handling credentials, API keys, tokens, or secrets
- Accessing databases or external systems
- Implementing authentication or authorization
- Working with cryptographic operations
- Processing user input or network requests
- Storing or transmitting sensitive data

## Pattern Examples

### Credentials Management

#### Environment Variables

**Python - Reading Secrets**:

```python
import os

# Required secret
db_password = os.environ.get("MAAS_DB_PASSWORD")
if not db_password:
    raise ValueError("MAAS_DB_PASSWORD environment variable must be set")

# Multiple related secrets
DATABASE_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "user": os.environ.get("DB_USER", "maas"),
    "password": os.environ["DB_PASSWORD"],  # Required, will raise if missing
    "database": os.environ.get("DB_NAME", "maas"),
}
```

**Go - Environment Variables**:

```go
import (
    "fmt"
    "os"
)

type Config struct {
    DBPassword string
    APIKey     string
}

func LoadConfig() (*Config, error) {
    dbPassword := os.Getenv("MAAS_DB_PASSWORD")
    if dbPassword == "" {
        return nil, fmt.Errorf("MAAS_DB_PASSWORD environment variable not set")
    }
    
    apiKey := os.Getenv("MAAS_API_KEY")
    if apiKey == "" {
        return nil, fmt.Errorf("MAAS_API_KEY environment variable not set")
    }
    
    return &Config{
        DBPassword: dbPassword,
        APIKey:     apiKey,
    }, nil
}
```

#### Configuration Files with Restricted Permissions

```python
import json
from pathlib import Path

def load_secrets(config_path: str = "/etc/maas/secrets.json") -> dict:
    """Load secrets from a file with strict permission checks."""
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {config_path}")
    
    # Check file permissions (should be 0600 or 0400)
    stat_info = path.stat()
    if stat_info.st_mode & 0o077:  # Check if group/other have any permissions
        raise PermissionError(
            f"Secrets file has insecure permissions: {oct(stat_info.st_mode)}"
        )
    
    with path.open("r") as f:
        return json.load(f)

# Usage
secrets = load_secrets()
api_key = secrets["temporal_api_key"]
```

**Setting Secure Permissions**:

```bash
umask 077
echo '{"api_key": "secret"}' > /etc/maas/secrets.json
chmod 600 /etc/maas/secrets.json
chown maas:maas /etc/maas/secrets.json
```

### Secure Database Access

#### Parameterized Queries (Always)

**Python - SQLAlchemy Core**:

```python
from sqlalchemy import select

# Correct: SQLAlchemy automatically parameterizes
stmt = select(MachineTable).where(MachineTable.c.hostname == user_input)
result = await connection.execute(stmt)

# NEVER use string formatting
# query = f"SELECT * FROM machines WHERE hostname = '{user_input}'"  # SQL INJECTION!
```

**Python - Django ORM**:

```python
# Correct: Django ORM parameterizes automatically
machines = Machine.objects.filter(hostname=user_input)

# Correct raw SQL with parameters
Machine.objects.raw("SELECT * FROM machine WHERE id = %s", [machine_id])

# NEVER use string formatting
# Machine.objects.raw(f"SELECT * FROM machine WHERE id = {machine_id}")  # WRONG
```

**Go - Database Queries**:

```go
// Correct: Use placeholders
row := db.QueryRow("SELECT * FROM machines WHERE hostname = $1", hostname)

// NEVER use string concatenation
// query := "SELECT * FROM machines WHERE hostname = '" + hostname + "'"  // SQL INJECTION!
```

#### Database Connection with Credentials

**Python - SQLAlchemy**:

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine
from urllib.parse import quote_plus

def create_db_engine():
    """Create database engine with credentials from environment."""
    db_user = os.environ.get("DB_USER", "maas")
    db_password = os.environ["DB_PASSWORD"]  # Required
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "maas")
    
    # URL encoding handles special characters in password
    password_encoded = quote_plus(db_password)
    
    connection_string = (
        f"postgresql+asyncpg://{db_user}:{password_encoded}"
        f"@{db_host}:{db_port}/{db_name}"
    )
    
    return create_async_engine(connection_string, echo=False)
```

**Go - Database Connection**:

```go
import (
    "database/sql"
    "fmt"
    "net/url"
    "os"
)

func CreateDBConnection() (*sql.DB, error) {
    user := os.Getenv("DB_USER")
    password := os.Getenv("DB_PASSWORD")
    if password == "" {
        return nil, fmt.Errorf("DB_PASSWORD not set")
    }
    
    host := os.Getenv("DB_HOST")
    dbname := os.Getenv("DB_NAME")
    
    // URL encode password to handle special characters
    dsn := fmt.Sprintf(
        "postgres://%s:%s@%s/%s?sslmode=require",
        user,
        url.QueryEscape(password),
        host,
        dbname,
    )
    
    return sql.Open("postgres", dsn)
}
```

### Authentication and Authorization

#### Check Permissions Before Actions

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

#### Secure Session Configuration

```python
# Django settings.py
SESSION_COOKIE_SECURE = True  # HTTPS only
SESSION_COOKIE_HTTPONLY = True  # No JavaScript access
SESSION_COOKIE_SAMESITE = 'Strict'  # CSRF protection
CSRF_COOKIE_SECURE = True
```

#### HTTP Client with API Key

**Python**:

```python
import httpx
import os

class TemporalClient:
    def __init__(self):
        self.base_url = os.environ.get("TEMPORAL_URL", "http://localhost:7233")
        self.api_key = os.environ.get("TEMPORAL_API_KEY")
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )
```

**Go**:

```go
type APIClient struct {
    baseURL string
    apiKey  string
    client  *http.Client
}

func NewAPIClient() (*APIClient, error) {
    apiKey := os.Getenv("API_KEY")
    if apiKey == "" {
        return nil, fmt.Errorf("API_KEY not set")
    }
    
    return &APIClient{
        baseURL: os.Getenv("API_URL"),
        apiKey:  apiKey,
        client:  &http.Client{},
    }, nil
}

func (c *APIClient) Do(req *http.Request) (*http.Response, error) {
    req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", c.apiKey))
    return c.client.Do(req)
}
```

### Cryptography

#### Use Secure Random Generation

**Python**:

```python
import secrets

# Generate URL-safe token (32 bytes = 256 bits)
token = secrets.token_urlsafe(32)

# Generate hex token
token_hex = secrets.token_hex(32)

# Generate random bytes for key
key_bytes = secrets.token_bytes(32)

# NEVER use random module for security
# import random
# token = ''.join(random.choices('0123456789', k=16))  # WRONG: Predictable
```

**Go**:

```go
import (
    "crypto/rand"
    "encoding/base64"
)

func GenerateToken(byteLength int) (string, error) {
    bytes := make([]byte, byteLength)
    if _, err := rand.Read(bytes); err != nil {
        return "", err
    }
    return base64.URLEncoding.EncodeToString(bytes), nil
}
```

#### Password Hashing

```python
# Use framework methods with strong algorithms
from django.contrib.auth.hashers import make_password, check_password

hashed = make_password(password)  # Uses PBKDF2 by default

# Verify password
is_valid = check_password(password, hashed)

# NEVER use weak hashing
# import hashlib
# hash = hashlib.md5(password.encode()).hexdigest()  # WRONG: MD5 is broken
# hash = hashlib.sha1(password.encode()).hexdigest()  # WRONG: SHA1 is weak
```

#### Use Strong Defaults

```python
# Disable debug in production
DEBUG = False
ALLOWED_HOSTS = ['maas.example.com']  # Explicit allowed hosts
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

# Security headers
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
```

### Input Validation

> **See**: [input-validation.md](input-validation.md) for comprehensive input validation patterns.

#### Sanitize File Paths

```python
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

#### Prevent Command Injection

```python
import subprocess

# Correct: Use list of arguments, no shell
subprocess.run(["ls", user_input], shell=False, check=True)

# NEVER use shell=True with user input
# subprocess.run(f"ls {user_input}", shell=True)  # COMMAND INJECTION!

# If shell is absolutely necessary, validate strictly
allowed_commands = {"status", "info", "list"}
if command not in allowed_commands:
    raise ValueError("Invalid command")
```

### Safe Logging

#### Never Log Secrets

```python
import logging

logger = logging.getLogger(__name__)

# NEVER log secrets
api_key = os.environ["API_KEY"]

# WRONG
# logger.info(f"Using API key: {api_key}")

# Correct: Log without exposing secret
logger.info("API key loaded successfully")
logger.info(f"API key length: {len(api_key)}")
logger.info(f"API key prefix: {api_key[:4]}...")  # First 4 chars only

# Redact secrets in structured logging
def redact_secrets(data: dict) -> dict:
    """Redact sensitive fields from log data."""
    sensitive_fields = {"password", "api_key", "token", "secret"}
    return {
        k: "***REDACTED***" if k.lower() in sensitive_fields else v
        for k, v in data.items()
    }
```

## Anti-patterns

### ❌ Hardcoded Secrets

```python
# NEVER hardcode secrets in code
DATABASE_PASSWORD = "mypassword123"  # WRONG
API_KEY = "sk_live_abc123def456"  # WRONG

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

### ❌ Secrets in URLs or Logs

```python
# NEVER put secrets in URLs
url = f"https://api.example.com/data?api_key={api_key}"  # WRONG: Logged

# Correct: Use headers
headers = {"Authorization": f"Bearer {api_key}"}
requests.get("https://api.example.com/data", headers=headers)

# NEVER log secrets
logger.info(f"Connecting with password: {password}")  # WRONG
```

### ❌ Missing Authorization Checks

```python
# NEVER skip permission checks
def delete_machine(machine_id):
    Machine.objects.get(id=machine_id).delete()  # WRONG: No check

# Correct: Always check permissions
def delete_machine(request, machine_id):
    if not request.user.has_perm("delete_machine"):
        raise PermissionDenied()
    Machine.objects.get(id=machine_id).delete()
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
# NEVER use weak hashing for passwords
import hashlib
password_hash = hashlib.md5(password.encode()).hexdigest()  # WRONG
password_hash = hashlib.sha1(password.encode()).hexdigest()  # WRONG

# Correct: Use framework password hashing
from django.contrib.auth.hashers import make_password
password_hash = make_password(password)
```

### ❌ Insecure File Permissions

```python
# NEVER store secrets in world-readable files
with open("/tmp/secrets.txt", "w") as f:  # WRONG: /tmp is world-readable
    f.write(api_key)

# Correct: Use restricted permissions
import os
fd = os.open("/etc/maas/secrets.txt", os.O_CREAT | os.O_WRONLY, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(api_key)
```

### ❌ Exposing Sensitive Information in Errors

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

### ❌ No Timeout on Network Requests

```python
# NEVER omit timeouts
response = requests.get(url)  # WRONG: Can hang indefinitely

# Correct: Always set timeout
response = requests.get(url, timeout=30)
```

### ❌ Using Same Secrets Across Environments

```python
# NEVER use the same secret in dev and production
# PROD_DB_PASSWORD = DEV_DB_PASSWORD  # WRONG

# Correct: Each environment has unique secrets
prod_password = os.environ["PROD_DB_PASSWORD"]
dev_password = os.environ["DEV_DB_PASSWORD"]
```

## Related Skills

- **Input Validation**: [input-validation.md](input-validation.md) - Sanitizing user input
- **SQLAlchemy Patterns**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md) - Safe database queries
- **Django Patterns**: [../languages/django-patterns.md](../languages/django-patterns.md) - Django security
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
9. **Unique Secrets Per Environment**: Different secrets for dev/staging/prod
10. **Audit Logging**: Log security events (not secret values)

## MAAS Secret Locations

- **Environment Variables**: Primary method (`/etc/environment`, systemd unit files)
- **Config Files**: `/etc/maas/` with mode 600
- **Database Credentials**: PostgreSQL connection string from env
- **API Keys**: External service credentials from env or secure config
- **TLS Certificates**: `/var/lib/maas/certificates/` with restricted permissions