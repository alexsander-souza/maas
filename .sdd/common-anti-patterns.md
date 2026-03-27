# Common Anti-Patterns

## Purpose

This document lists the top anti-patterns that apply across all MAAS code. These are the most common mistakes that appear in multiple contexts and should always be avoided.

For domain-specific anti-patterns, see the relevant skill or subsystem documentation.

## When to Reference

- During code reviews
- Before submitting code
- When refactoring legacy code
- As a quick reference checklist

## Top 15 Common Anti-Patterns

### ❌ 1. Hardcoded Secrets

Never hardcode credentials, API keys, or any sensitive data in source code.

```python
# WRONG
DATABASE_PASSWORD = "mypassword123"
API_KEY = "sk_live_abc123def456"
SECRET_KEY = "django-insecure-hardcoded"

# Correct
DATABASE_PASSWORD = os.environ["DB_PASSWORD"]
API_KEY = os.environ["API_KEY"]
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
```

**Why**: Secrets in source code are exposed in version control, logs, and error messages.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 2. String Concatenation in SQL

Never use string formatting or concatenation to build SQL queries.

```python
# WRONG - SQL Injection vulnerability
query = f"SELECT * FROM machines WHERE id = {machine_id}"
query = "SELECT * FROM machines WHERE name = '" + name + "'"

# Correct - Use parameterized queries
stmt = select(MachineTable).where(MachineTable.c.id == machine_id)
# Or with raw SQL
cursor.execute("SELECT * FROM machines WHERE id = %s", [machine_id])
```

**Why**: Enables SQL injection attacks that can compromise your entire database.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 3. Ignoring Errors

Never silently catch and ignore exceptions or error conditions.

```python
# WRONG
try:
    result = risky_operation()
except:
    pass  # Silent failure

# WRONG
if err != nil {
    // Ignore error
}

# Correct
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise
```

**Why**: Hidden errors make debugging impossible and can cause data corruption.

**See**: [python-patterns.md](skills/languages/python-patterns.md), [go-patterns.md](skills/languages/go-patterns.md)

---

### ❌ 4. Single-Letter Variables (Except Loops)

Avoid cryptic single-letter variable names outside of loop counters.

```python
# WRONG
m = get_machine()
d = datetime.now()
c = calculate_cost(m)

# Correct
machine = get_machine()
current_time = datetime.now()
deployment_cost = calculate_cost(machine)

# Exception: Loop counters are okay
for i in range(10):  # OK
    for j in range(5):  # OK
```

**Why**: Makes code difficult to understand and maintain.

**See**: [naming-conventions.md](skills/techniques/naming-conventions.md)

---

### ❌ 5. Logging Secrets

Never log passwords, API keys, tokens, or other sensitive data.

```python
# WRONG
logger.info(f"Using API key: {api_key}")
logger.debug(f"Password: {password}")
print(f"Token: {token}")

# Correct
logger.info("API key loaded successfully")
logger.info(f"API key length: {len(api_key)}")
logger.info(f"API key prefix: {api_key[:4]}...")  # First 4 chars only
```

**Why**: Logs are often stored insecurely and accessible to many people.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 6. Trusting User Input

Never trust user input without validation and sanitization.

```python
# WRONG
filename = user_input  # Could be "../../../../etc/passwd"
os.remove(filename)

command = f"ls {user_input}"  # Command injection
subprocess.run(command, shell=True)

# Correct
safe_path = safe_file_access(base_dir, user_input)
subprocess.run(["ls", user_input], shell=False)
```

**Why**: Enables path traversal, command injection, and other attacks.

**See**: [input-validation.md](skills/techniques/input-validation.md), [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 7. Weak Cryptography

Never use broken or weak cryptographic algorithms.

```python
# WRONG - Broken algorithms
import hashlib
password_hash = hashlib.md5(password.encode()).hexdigest()  # MD5 is broken
password_hash = hashlib.sha1(password.encode()).hexdigest()  # SHA1 is weak

import random
token = ''.join(random.choices('0123456789', k=16))  # Predictable

# Correct - Use strong, modern algorithms
from django.contrib.auth.hashers import make_password
password_hash = make_password(password)  # PBKDF2 by default

import secrets
token = secrets.token_urlsafe(32)  # Cryptographically secure
```

**Why**: Weak crypto can be easily broken, compromising security.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 8. Functions That Do Too Much

Avoid functions with multiple responsibilities or excessive complexity.

```python
# WRONG - Function does too much
def process_machine(machine_id):
    machine = Machine.objects.get(id=machine_id)
    if machine.status == "ready":
        machine.status = "deploying"
        machine.save()
        send_notification(machine.owner)
        log_deployment(machine)
        update_metrics(machine)
        start_workflow(machine)
        return True
    return False

# Correct - Single responsibility
def deploy_machine(machine_id):
    machine = get_machine(machine_id)
    validate_deployment_ready(machine)
    update_machine_status(machine, "deploying")
    trigger_deployment_workflow(machine)
```

**Why**: Hard to test, maintain, and understand. Violates single responsibility principle.

**See**: [code-clarity.md](skills/techniques/code-clarity.md)

---

### ❌ 9. Missing Authorization Checks

Never perform privileged operations without checking permissions.

```python
# WRONG - No authorization check
def delete_machine(machine_id):
    Machine.objects.get(id=machine_id).delete()

# Correct - Check permissions first
def delete_machine(request, machine_id):
    if not request.user.has_perm("maasserver.delete_machine"):
        raise PermissionDenied("User cannot delete machines")
    
    machine = Machine.objects.get(id=machine_id)
    if machine.owner != request.user and not request.user.is_admin:
        raise PermissionDenied("Can only delete own machines")
    
    machine.delete()
```

**Why**: Security vulnerability allowing unauthorized access to sensitive operations.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 10. Client-Side Only Validation

Never rely solely on client-side validation for security.

```python
# WRONG - Only JavaScript validation
# form.html: <input type="text" pattern="[A-Za-z]+" required>
# No server-side validation

# Correct - Always validate server-side
def create_machine(request):
    data = request.POST
    
    # Server-side validation is mandatory
    if not data.get("hostname"):
        raise ValidationError("Hostname is required")
    
    if not re.match(r'^[a-z0-9-]+$', data["hostname"]):
        raise ValidationError("Invalid hostname format")
    
    # Process validated data
```

**Why**: Client-side validation can be easily bypassed by attackers.

**See**: [input-validation.md](skills/techniques/input-validation.md)

---

### ❌ 11. Commented-Out Code

Never leave commented-out code in the codebase.

```python
# WRONG
def process_data(data):
    result = new_algorithm(data)
    # old_result = legacy_algorithm(data)
    # if needs_migration:
    #     migrate_data(old_result)
    return result

# Correct - Delete it (it's in version control)
def process_data(data):
    result = new_algorithm(data)
    return result
```

**Why**: Creates confusion, clutters code, and version control already preserves history.

**See**: [minimal-comments.md](skills/techniques/minimal-comments.md)

---

### ❌ 12. Exposing Sensitive Information in Errors

Never expose implementation details or sensitive data in error messages.

```python
# WRONG - Leaks sensitive information
try:
    authenticate(username, password)
except Exception as e:
    return {
        "error": str(e),
        "sql": query,
        "password": password,
        "stack_trace": traceback.format_exc()
    }

# Correct - Generic error messages
try:
    authenticate(username, password)
except AuthenticationError:
    logger.error(f"Authentication failed for user {username}")
    return {"error": "Invalid credentials"}
except Exception as e:
    logger.exception("Unexpected authentication error")
    return {"error": "Authentication failed"}
```

**Why**: Exposes internal details that help attackers, violates security best practices.

**See**: [security-practices.md](skills/techniques/security-practices.md)

---

### ❌ 13. Clever Code Over Clear Code

Avoid overly clever or obscure code patterns.

```python
# WRONG - Too clever
result = [x for x in (y for y in data if y) if x.valid]

# WRONG - Obscure one-liner
value = (lambda x: x[0] if x else None)(sorted(filter(None, items)))

# Correct - Clear and explicit
valid_items = []
for item in data:
    if item and item.valid:
        valid_items.append(item)
result = valid_items

# Correct - Clear one-liner alternative
non_empty_items = [item for item in items if item]
value = sorted(non_empty_items)[0] if non_empty_items else None
```

**Why**: Reduces readability and maintainability for minimal benefit.

**See**: [code-clarity.md](skills/techniques/code-clarity.md)

---

### ❌ 14. No Input Validation

Never process user input without validation.

```python
# WRONG - No validation
def update_machine(machine_id, hostname):
    machine = Machine.objects.get(id=machine_id)
    machine.hostname = hostname  # Could be anything!
    machine.save()

# Correct - Validate input
def update_machine(machine_id, hostname):
    if not re.match(r'^[a-z0-9-]{1,63}$', hostname):
        raise ValidationError("Invalid hostname format")
    
    machine = Machine.objects.get(id=machine_id)
    machine.hostname = hostname
    machine.save()
```

**Why**: Opens door to injection attacks, data corruption, and security issues.

**See**: [input-validation.md](skills/techniques/input-validation.md)

---

### ❌ 15. Inconsistent Naming Patterns

Maintain consistent naming conventions throughout the codebase.

```python
# WRONG - Inconsistent patterns
def getMachine(id):  # camelCase in Python
    pass

def process_Data(val):  # Mixed case
    pass

def FetchUser(userId):  # Multiple inconsistencies
    pass

# Correct - Consistent Python conventions
def get_machine(machine_id):
    pass

def process_data(value):
    pass

def fetch_user(user_id):
    pass
```

**Why**: Inconsistency makes code harder to read and navigate.

**See**: [naming-conventions.md](skills/techniques/naming-conventions.md)

---

## Quick Checklist

Before submitting code, verify:

- [ ] No hardcoded secrets or credentials
- [ ] All SQL queries use parameters, not string concatenation
- [ ] All errors are handled and logged appropriately
- [ ] Variable names are descriptive (no single letters except loops)
- [ ] No secrets appear in logs or error messages
- [ ] All user input is validated and sanitized
- [ ] Strong cryptographic algorithms used (no MD5/SHA1 for passwords)
- [ ] Functions have single, clear responsibilities
- [ ] Authorization checks before privileged operations
- [ ] Server-side validation present (not just client-side)
- [ ] No commented-out code
- [ ] Error messages don't expose sensitive information
- [ ] Code is clear and straightforward (not overly clever)
- [ ] Input validation is comprehensive
- [ ] Naming conventions are consistent with codebase style

## Related Documentation

- **Security**: [security-practices.md](skills/techniques/security-practices.md)
- **Input Validation**: [input-validation.md](skills/techniques/input-validation.md)
- **Code Clarity**: [code-clarity.md](skills/techniques/code-clarity.md)
- **Naming**: [naming-conventions.md](skills/techniques/naming-conventions.md)
- **Python Patterns**: [python-patterns.md](skills/languages/python-patterns.md)
- **Go Patterns**: [go-patterns.md](skills/languages/go-patterns.md)