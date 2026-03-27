# Secret Management

## Purpose

Define patterns for securely handling credentials, API keys, tokens, and other sensitive data in MAAS code, including storage, access, rotation, and best practices.

## When to Use

- Storing database credentials
- Managing API keys and tokens
- Handling cryptographic keys
- Configuring external service credentials
- Implementing service-to-service authentication
- Rotating secrets and credentials

## Pattern Examples

### Environment Variables

**Python - Reading Secrets**:

```python
import os

# Required secret
db_password = os.environ.get("MAAS_DB_PASSWORD")
if not db_password:
    raise ValueError("MAAS_DB_PASSWORD environment variable must be set")

# Optional secret with default
api_timeout = int(os.environ.get("API_TIMEOUT", "30"))

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
    TLSCert    string
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
        TLSCert:    os.Getenv("TLS_CERT_PATH"),
    }, nil
}
```

### Configuration Files with Restricted Permissions

**Python - Secure Config File**:

```python
import os
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
db_password = secrets["database_password"]
```

**Setting Secure File Permissions**:

```bash
# Create secrets file with restricted permissions
umask 077
echo '{"api_key": "secret"}' > /etc/maas/secrets.json
chmod 600 /etc/maas/secrets.json
chown maas:maas /etc/maas/secrets.json
```

### Secrets in Database Connections

**Python - SQLAlchemy Connection**:

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine

def create_db_engine():
    """Create database engine with credentials from environment."""
    db_user = os.environ.get("DB_USER", "maas")
    db_password = os.environ["DB_PASSWORD"]  # Required
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "maas")
    
    # URL encoding handles special characters in password
    from urllib.parse import quote_plus
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

### API Keys and Tokens

**Python - HTTP Client with Token**:

```python
import httpx
import os

class TemporalClient:
    def __init__(self):
        self.base_url = os.environ.get("TEMPORAL_URL", "http://localhost:7233")
        self.api_key = os.environ.get("TEMPORAL_API_KEY")
        
        # Create client with auth header
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
        )
    
    async def close(self):
        await self.client.aclose()
```

**Go - HTTP Client with API Key**:

```go
import (
    "fmt"
    "net/http"
    "os"
)

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
    // Add API key to request
    req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", c.apiKey))
    return c.client.Do(req)
}
```

### Generating Secure Tokens

**Python - Token Generation**:

```python
import secrets

# Generate URL-safe token (32 bytes = 256 bits)
token = secrets.token_urlsafe(32)

# Generate hex token
token_hex = secrets.token_hex(32)

# Generate random bytes for key
key_bytes = secrets.token_bytes(32)

# Generate secure random integers
random_id = secrets.randbelow(1000000)
```

**Go - Token Generation**:

```go
import (
    "crypto/rand"
    "encoding/base64"
    "encoding/hex"
)

func GenerateToken(byteLength int) (string, error) {
    bytes := make([]byte, byteLength)
    if _, err := rand.Read(bytes); err != nil {
        return "", err
    }
    return base64.URLEncoding.EncodeToString(bytes), nil
}

func GenerateHexToken(byteLength int) (string, error) {
    bytes := make([]byte, byteLength)
    if _, err := rand.Read(bytes); err != nil {
        return "", err
    }
    return hex.EncodeToString(bytes), nil
}
```

### Secret Rotation

**Python - Token Expiration**:

```python
from datetime import datetime, timedelta

class APIToken:
    def __init__(self, token: str, expires_at: datetime):
        self.token = token
        self.expires_at = expires_at
    
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at
    
    def needs_rotation(self, days_before: int = 7) -> bool:
        """Check if token should be rotated soon."""
        rotation_threshold = self.expires_at - timedelta(days=days_before)
        return datetime.utcnow() >= rotation_threshold

# Usage
if api_token.needs_rotation():
    new_token = generate_new_token()
    update_token_in_storage(new_token)
```

### Logging Without Secrets

**Python - Safe Logging**:

```python
import logging

logger = logging.getLogger(__name__)

# Never log secrets
api_key = os.environ["API_KEY"]

# WRONG: Logs the secret
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

logger.info("Request data", extra=redact_secrets(request_data))
```

**Go - Safe Logging**:

```go
import "log"

func SafeLog(apiKey string) {
    // Never log the full secret
    // log.Printf("API key: %s", apiKey)  // WRONG
    
    // Correct: Log without exposing
    log.Println("API key loaded successfully")
    if len(apiKey) > 4 {
        log.Printf("API key prefix: %s...", apiKey[:4])
    }
}
```

## Anti-patterns

### ❌ Hardcoded Secrets

```python
# NEVER hardcode secrets in code
DATABASE_PASSWORD = "mypassword123"  # WRONG
API_KEY = "sk_live_abc123def456"  # WRONG
SECRET_KEY = "django-insecure-hardcoded"  # WRONG

# NEVER commit secrets to version control
# Even in test code or comments
```

### ❌ Secrets in URLs or Logs

```python
# NEVER put secrets in URLs
url = f"https://api.example.com/data?api_key={api_key}"  # WRONG: Logged in access logs

# Correct: Use headers
headers = {"Authorization": f"Bearer {api_key}"}
requests.get("https://api.example.com/data", headers=headers)

# NEVER log secrets
logger.info(f"Connecting with password: {password}")  # WRONG
```

### ❌ Insecure Storage

```python
# NEVER store secrets in world-readable files
with open("/tmp/secrets.txt", "w") as f:  # WRONG: /tmp is often world-readable
    f.write(api_key)

# NEVER store secrets in code comments
# API_KEY = "abc123"  # WRONG: Still in version control

# NEVER store secrets in database without encryption
# INSERT INTO config VALUES ('api_key', 'secret123')  # WRONG
```

### ❌ Weak Secret Generation

```python
import random

# NEVER use random module for secrets
token = ''.join(random.choices('0123456789', k=16))  # WRONG: Predictable

# Correct: Use secrets module
import secrets
token = secrets.token_urlsafe(32)
```

### ❌ Sharing Secrets Across Environments

```python
# NEVER use the same secret in dev and production
# PROD_DB_PASSWORD = DEV_DB_PASSWORD  # WRONG

# Each environment should have unique secrets
prod_password = os.environ["PROD_DB_PASSWORD"]
dev_password = os.environ["DEV_DB_PASSWORD"]
```

## Related Skills

- **Secure Coding**: [secure-coding.md](secure-coding.md) - General security practices
- **Input Validation**: [input-validation.md](input-validation.md) - Validating secret formats
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Configuration management
- **Go Patterns**: [../languages/go-patterns.md](../languages/go-patterns.md) - Go configuration

## Secret Management Principles

1. **Never Hardcode**: Secrets should never be in source code
2. **Environment Variables**: Primary method for secret injection
3. **Restricted Permissions**: Config files must be 600 or 400
4. **Encryption at Rest**: Encrypt secrets stored in databases
5. **Rotation**: Regularly rotate secrets and tokens
6. **Least Privilege**: Each service gets only the secrets it needs
7. **Audit Logging**: Log secret access (not values)
8. **Secure Deletion**: Overwrite secrets when no longer needed
9. **No Logs**: Never log secret values
10. **Unique Per Environment**: Different secrets for dev/staging/prod

## MAAS Secret Locations

- **Environment Variables**: Primary method (`/etc/environment`, systemd unit files)
- **Config Files**: `/etc/maas/` with mode 600
- **Database Credentials**: PostgreSQL connection string from env
- **API Keys**: External service credentials from env or secure config
- **TLS Certificates**: `/var/lib/maas/certificates/` with restricted permissions