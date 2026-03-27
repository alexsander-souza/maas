# Security Validation Checklist

## Purpose

Phase-specific security validation checklist for MAAS development, ensuring critical security controls are verified at each stage of the development lifecycle.

## Planning Phase

### Requirements Review
- [ ] Security requirements identified and documented
- [ ] Authentication and authorization needs defined
- [ ] Data sensitivity classification completed
- [ ] External API security requirements documented
- [ ] Compliance requirements identified (if applicable)

### Threat Modeling
- [ ] Potential attack vectors identified
- [ ] High-risk components flagged for extra scrutiny
- [ ] Data flow diagrams include trust boundaries
- [ ] Privilege escalation paths reviewed

## Development Phase

### Code Review Checklist

#### Credentials and Secrets
- [ ] No hardcoded passwords, API keys, or tokens in code
- [ ] All secrets loaded from environment variables or secure config
- [ ] No secrets in comments or documentation
- [ ] No secrets in test code or fixtures
- [ ] Secret files have restricted permissions (600 or 400)
- [ ] Connection strings use environment variables for credentials

#### Input Validation
- [ ] All user input validated before processing
- [ ] Pydantic validators used for API request models (Python)
- [ ] Whitelist validation patterns used (not blacklist)
- [ ] File paths validated to prevent directory traversal
- [ ] File uploads restricted by type and size
- [ ] Email and URL formats validated before use

#### Database Security
- [ ] All database queries use parameterized queries
- [ ] No string concatenation or f-strings in SQL
- [ ] ORM methods used correctly (Django/SQLAlchemy)
- [ ] No raw SQL with user input without parameters
- [ ] Database credentials not in code or version control
- [ ] Connection pooling configured securely

#### Authentication & Authorization
- [ ] Authentication required for all protected endpoints
- [ ] Authorization checks performed before operations
- [ ] User permissions verified for each action
- [ ] Session management uses secure cookies (HTTPS only, HttpOnly)
- [ ] CSRF protection enabled for state-changing operations
- [ ] Password hashing uses strong algorithms (PBKDF2, bcrypt, argon2)

#### Cryptography
- [ ] Strong algorithms used (SHA-256+, AES-256, RSA-2048+)
- [ ] No weak algorithms (MD5, SHA-1, DES, RC4)
- [ ] Secure random number generation (secrets module, crypto/rand)
- [ ] TLS 1.2+ enforced for external connections
- [ ] Certificate validation enabled (not InsecureSkipVerify)
- [ ] Cryptographic keys stored securely (not in code)

#### Error Handling
- [ ] Error messages don't leak sensitive information
- [ ] Stack traces not exposed to users in production
- [ ] Generic error messages for authentication failures
- [ ] Logging doesn't include passwords, tokens, or keys
- [ ] Debugging features disabled in production

#### Dependency Security
- [ ] No known vulnerable dependencies
- [ ] Dependencies pinned to specific versions
- [ ] Regular dependency updates scheduled
- [ ] Security advisories monitored
- [ ] Deprecated libraries avoided

## Testing Phase

### Security Test Checklist
- [ ] Authentication bypass attempts tested
- [ ] Authorization boundary tests written
- [ ] Input validation tests for common payloads (SQLi, XSS, path traversal)
- [ ] Injection attack vectors tested (SQL, command, LDAP)
- [ ] Rate limiting tested if applicable
- [ ] Session hijacking scenarios tested
- [ ] CSRF protection tested for state-changing operations
- [ ] File upload security tested (type, size, content)

### Automated Security Checks
- [ ] Ruff security rules pass (Python)
- [ ] Static analysis security warnings addressed
- [ ] Dependency vulnerability scan clean
- [ ] No secrets detected in repository (git-secrets, truffleHog)
- [ ] Code coverage includes security-critical paths

## Deployment Phase

### Pre-Deployment Security
- [ ] All secrets configured in production environment
- [ ] Database credentials rotated from defaults
- [ ] TLS certificates valid and properly configured
- [ ] Firewall rules restrict unnecessary access
- [ ] Debug mode disabled
- [ ] Unnecessary services disabled
- [ ] File permissions set correctly (config files 600)

### Configuration Review
- [ ] `DEBUG = False` in production (Python/Django)
- [ ] `ALLOWED_HOSTS` properly configured
- [ ] `SECRET_KEY` unique and from environment
- [ ] `SESSION_COOKIE_SECURE = True`
- [ ] `CSRF_COOKIE_SECURE = True`
- [ ] CORS settings restrictive (if applicable)
- [ ] Rate limiting configured for public APIs

## Post-Deployment Phase

### Monitoring
- [ ] Authentication failures monitored
- [ ] Unusual access patterns alerted
- [ ] Failed authorization attempts logged
- [ ] Security logs reviewed regularly
- [ ] Anomaly detection configured

### Incident Response
- [ ] Security incident response plan documented
- [ ] Contact information for security team available
- [ ] Procedure for credential rotation documented
- [ ] Backup and recovery tested

## Quick Security Audit

Use this condensed checklist for rapid security review:

### Critical Items (Must Fix)
- [ ] No hardcoded secrets
- [ ] All database queries parameterized
- [ ] Input validation on all user inputs
- [ ] Authentication required for protected resources
- [ ] Authorization checked before actions
- [ ] Error messages don't leak information
- [ ] Debug mode off in production

### High Priority (Should Fix)
- [ ] Strong password hashing
- [ ] TLS enforced for connections
- [ ] CSRF protection enabled
- [ ] Secure session configuration
- [ ] Dependencies up to date
- [ ] Logging doesn't expose secrets

### Medium Priority (Review)
- [ ] Rate limiting on public endpoints
- [ ] File upload restrictions
- [ ] Security headers configured
- [ ] Audit logging for sensitive operations

## Language-Specific Checklists

### Python Security
- [ ] `secrets` module used for random tokens (not `random`)
- [ ] Pydantic models validate all input
- [ ] SQLAlchemy/Django ORM used correctly
- [ ] No `shell=True` in subprocess calls
- [ ] No `eval()` or `exec()` with user input
- [ ] `pickle` avoided for untrusted data
- [ ] Path operations use `Path.resolve()` and validation

### Go Security
- [ ] `crypto/rand` used for random generation (not `math/rand`)
- [ ] SQL queries use placeholders (`$1`, `?`)
- [ ] HTTP client validates TLS certificates
- [ ] Input validated before processing
- [ ] Error wrapping preserves security (doesn't leak details)
- [ ] Context timeout/cancellation used for operations

## Common Vulnerabilities to Check

### SQL Injection
- [ ] No string formatting in queries: `f"SELECT * FROM table WHERE id={user_id}"`
- [ ] No concatenation: `"SELECT * FROM table WHERE name='" + name + "'"`
- [ ] Parameterized queries used: `stmt.where(Table.c.id == user_id)`

### Path Traversal
- [ ] User input not directly used in file paths
- [ ] `../` sequences blocked or validated
- [ ] Path resolved and checked within allowed directory
- [ ] Symbolic links considered in path validation

### Command Injection
- [ ] No `subprocess.run(..., shell=True)` with user input
- [ ] Command arguments passed as list, not string
- [ ] User input validated against whitelist before commands

### Authentication Issues
- [ ] Weak password policies not allowed
- [ ] Password reset tokens random and time-limited
- [ ] Account lockout after failed attempts
- [ ] Multi-factor authentication considered for admin

### Authorization Issues
- [ ] Horizontal privilege escalation prevented (user can't access other users' data)
- [ ] Vertical privilege escalation prevented (user can't perform admin actions)
- [ ] Direct object references checked (can't change ID in URL to access others' resources)

## Security Review Sign-Off

**Component**: ___________________________

**Reviewer**: ___________________________

**Date**: ___________________________

**Checklist Completion**: _____ / _____ items verified

**Critical Issues Found**: ___________________________

**Issues Resolved**: [ ] Yes [ ] No [ ] N/A

**Approved for Deployment**: [ ] Yes [ ] No

**Notes**: