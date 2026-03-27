# maasserver Subsystem

## Purpose

Legacy Django-based region controller server that provides the v2 REST API and web UI for MAAS. Handles core MAAS functionality including machine management, network configuration, and deployment orchestration through a monolithic Django application.

**Status**: Maintenance mode - new features should be added to v3 API when feasible.

## Location

`src/maasserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Django**: Web framework and ORM
- **Twisted**: Asynchronous networking and event-driven programming
- **PostgreSQL**: Database via Django ORM

### Key Libraries
- **django-piston3**: REST framework for v2 API
- **testtools**: Testing framework
- **Twisted**: Deferred execution and async operations

## Architectural Constraints

### Legacy Architecture
Monolithic Django application that predates the modern three-tier architecture. Combines presentation, business logic, and data access in traditional Django MVC pattern.

### Database Access
- **Django ORM**: Primary data access method
- **Transitioning**: Moving to SQLAlchemy Core in v3 API
- **deferToDatabase**: Required for database operations in Twisted async contexts

### Async Patterns
Uses Twisted's deferred-based async model, which differs from modern Python async/await.

### Backward Compatibility
Must maintain compatibility with existing v2 API clients, Django model structure, and legacy authentication methods.

## Key Patterns

### deferToDatabase Pattern

When calling database operations from Twisted async contexts, always use `deferToDatabase`:

```python
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from twisted.internet import defer

@transactional
def _get_machine_sync(machine_id):
    """Synchronous database operation."""
    return Machine.objects.get(system_id=machine_id)

@defer.inlineCallbacks
def get_machine_async(machine_id):
    """Async wrapper."""
    machine = yield deferToDatabase(_get_machine_sync, machine_id)
    defer.returnValue(machine)
```

**Why**: Django ORM is not thread-safe. `deferToDatabase` executes database operations in a separate thread pool to prevent conflicts with Twisted's reactor.

### Django Model Conventions

Follow established Django model patterns:

```python
from django.db import models

class Machine(models.Model):
    """Existing Django model - maintain conventions."""
    
    system_id = models.CharField(max_length=41, unique=True)
    hostname = models.CharField(max_length=255)
    status = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'maasserver_node'
        ordering = ['hostname']
    
    def __str__(self):
        return f"{self.hostname} ({self.system_id})"
```

### Django Signal Handlers

Use Django signals for decoupled event handling:

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Machine)
def handle_machine_save(sender, instance, created, **kwargs):
    """Handle machine creation/update events."""
    if created:
        logger.info(f"Machine created: {instance.system_id}")
        trigger_commissioning(instance)
    else:
        logger.info(f"Machine updated: {instance.system_id}")
```

### Twisted Deferred Pattern

Handle async operations with Twisted deferreds:

```python
from twisted.internet import defer

@defer.inlineCallbacks
def deploy_machine(machine_id, distro_series):
    """Deploy machine using Twisted async pattern."""
    # Get machine from database
    machine = yield deferToDatabase(get_machine, machine_id)
    
    # Validate machine status
    if machine.status != NODE_STATUS.READY:
        raise MachineNotReady(f"Machine {machine_id} not ready")
    
    # Update status
    yield deferToDatabase(update_machine_status, machine_id, NODE_STATUS.DEPLOYING)
    
    # Trigger deployment workflow
    result = yield trigger_deployment_workflow(machine, distro_series)
    
    defer.returnValue(result)
```

### Django REST API (Piston3)

Legacy v2 API uses django-piston3:

```python
from piston3.handler import BaseHandler
from piston3.utils import rc

class MachinesHandler(BaseHandler):
    """Handler for /api/2.0/machines/ endpoint."""
    
    allowed_methods = ('GET', 'POST')
    model = Machine
    
    def read(self, request):
        """List machines."""
        machines = Machine.objects.all()
        return machines
    
    def create(self, request):
        """Create new machine."""
        hostname = request.POST.get('hostname')
        architecture = request.POST.get('architecture')
        
        machine = Machine.objects.create(
            hostname=hostname,
            architecture=architecture
        )
        return machine
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Django Test Conventions
Use Django's `TestCase` for database tests:

```python
from django.test import TestCase
from maasserver.models import Machine

class TestMachineModel(TestCase):
    def test_create_machine(self):
        machine = Machine.objects.create(
            hostname="test-machine",
            architecture="amd64/generic"
        )
        self.assertEqual(machine.hostname, "test-machine")
```

### Twisted Test Pattern
Use `MAASServerTestCase` for Twisted tests:

```python
from maasserver.testing.testcase import MAASServerTestCase

class TestAsyncOperation(MAASServerTestCase):
    @defer.inlineCallbacks
    def test_deploy_machine(self):
        machine = yield deferToDatabase(create_test_machine)
        result = yield deploy_machine(machine.system_id, "ubuntu/jammy")
        self.assertEqual(result.status, "deploying")
```

## Integration Points

### v3 API Server (maasapiserver)
- **Purpose**: Gradual migration from v2 to v3 API
- **Interface**: Shared database schema
- **Key Considerations**: Maintain schema compatibility during transition

### Provisioning Server (provisioningserver)
- **Purpose**: Rack controller services and DHCP/DNS/PXE
- **Interface**: RPC over message queue
- **Key Considerations**: Maintain protocol compatibility

### Metadata Server (metadataserver)
- **Purpose**: Cloud-init metadata for deploying machines
- **Interface**: Django URL routing and shared models
- **Key Considerations**: Part of same Django application

### Temporal Workflows
- **Purpose**: Orchestration of long-running operations
- **Interface**: Temporal client via deferToDatabase
- **Key Considerations**: Async operations must use deferToDatabase

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Calling Django ORM Directly from Twisted

```python
# WRONG: Direct ORM call in async context
@defer.inlineCallbacks
def get_machine(machine_id):
    machine = Machine.objects.get(id=machine_id)  # Thread safety issue!
    defer.returnValue(machine)

# Correct: Use deferToDatabase
@transactional
def _get_machine(machine_id):
    return Machine.objects.get(id=machine_id)

@defer.inlineCallbacks
def get_machine(machine_id):
    machine = yield deferToDatabase(_get_machine, machine_id)
    defer.returnValue(machine)
```

### Blocking Operations in Twisted

```python
# WRONG: Blocking call in Twisted context
@defer.inlineCallbacks
def process_machine(machine_id):
    result = requests.get("http://external-api.com")  # Blocks reactor!
    defer.returnValue(result)

# Correct: Use Twisted's HTTP client or deferToThread
from twisted.web.client import getPage

@defer.inlineCallbacks
def process_machine(machine_id):
    result = yield getPage(b"http://external-api.com")
    defer.returnValue(result)
```

### Mixing async/await with Twisted

```python
# WRONG: Can't mix modern async/await with Twisted
@defer.inlineCallbacks
async def deploy_machine(machine_id):  # Syntax error!
    machine = await get_machine(machine_id)
    return machine

# Correct: Stick to Twisted patterns in this subsystem
@defer.inlineCallbacks
def deploy_machine(machine_id):
    machine = yield deferToDatabase(get_machine, machine_id)
    defer.returnValue(machine)
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

### Legacy-Specific Security
- Django's built-in security features (CSRF, XSS protection)
- OAuth 1.0a for v2 API authentication
- Session-based authentication for web UI
- SQL injection protection via Django ORM (never use raw SQL with string formatting)

## Performance Considerations

### Database Query Optimization
Use `select_related` and `prefetch_related` to avoid N+1 queries:

```python
# Optimize queries for related objects
machines = Machine.objects.select_related('zone', 'owner').prefetch_related('interfaces')
```

### Caching
Use Django's cache framework for frequently accessed data:

```python
from django.core.cache import cache

def get_machine_count():
    count = cache.get('machine_count')
    if count is None:
        count = Machine.objects.count()
        cache.set('machine_count', count, 300)  # 5 minutes
    return count
```

## Migration Notes

When adding new features:
1. **Prefer v3 API**: Add to `maasapiserver` when possible
2. **Database changes**: Coordinate with v3 API team for schema changes
3. **Testing**: Ensure backward compatibility with existing clients
4. **Documentation**: Mark v2-specific features as legacy

## Additional Resources

- Django Documentation: https://docs.djangoproject.com/
- Twisted Documentation: https://twisted.org/documents/current/
- Django ORM Best Practices: [sqlalchemy-patterns.md](../../skills/languages/sqlalchemy-patterns.md) (principles apply)
- [AGENTS.md](../../AGENTS.md): Core coding guidelines