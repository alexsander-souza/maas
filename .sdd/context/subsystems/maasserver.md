# maasserver Subsystem

## Purpose

Legacy Django-based region controller server that provides the v2 REST API and web UI for MAAS. This subsystem handles the core MAAS functionality including machine management, network configuration, and deployment orchestration through a monolithic Django application.

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
This is a monolithic Django application that predates the modern three-tier architecture. It combines presentation, business logic, and data access in a traditional Django MVC pattern.

### Database Access
- **Django ORM**: Primary data access method
- **Transitioning**: Moving to SQLAlchemy Core in v3 API
- **deferToDatabase**: Required for database operations in Twisted async contexts

### Async Patterns
Uses Twisted's deferred-based async model, which differs from modern Python async/await:

```python
from twisted.internet import defer
from maasserver.utils.orm import transactional

@transactional
def get_machine(machine_id):
    """Synchronous function wrapped for transaction."""
    return Machine.objects.get(id=machine_id)

@defer.inlineCallbacks
def async_operation():
    """Async operation using Twisted deferreds."""
    machine = yield deferToDatabase(get_machine, machine_id=123)
    defer.returnValue(machine)
```

### Backward Compatibility
Must maintain backward compatibility with:
- Existing v2 API clients
- Django model structure
- Database schema (shared with v3)
- Legacy authentication methods

## Key Patterns

### deferToDatabase Pattern

When calling database operations from Twisted async contexts, always use `deferToDatabase`:

```python
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase

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
        db_table = "maasserver_node"
```

**Do NOT**:
- Change existing model field names
- Modify model inheritance hierarchy
- Alter Meta class settings without careful review
- Break existing migrations

### Transactional Decorator

Use `@transactional` for database operations:

```python
from maasserver.utils.orm import transactional

@transactional
def create_machine(hostname, architecture):
    """Create machine in transaction."""
    machine = Machine.objects.create(
        hostname=hostname,
        architecture=architecture
    )
    return machine
```

### Django Signal Handlers

Use signals for side effects and cross-cutting concerns:

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Machine)
def machine_created(sender, instance, created, **kwargs):
    """Handle machine creation event."""
    if created:
        notify_machine_created(instance)
```

## Testing Requirements

### Test Framework

Use Django's test framework with `testtools`:

```python
from maasserver.testing.testcase import MAASServerTestCase

class TestMachine(MAASServerTestCase):
    """Test machine operations."""
    
    def test_create_machine(self):
        """Test machine creation."""
        machine = Machine.objects.create(hostname="test-machine")
        self.assertEqual(machine.hostname, "test-machine")
```

### Test Fixtures

Use Django fixtures and factory patterns:

```python
from maasserver.testing.factory import factory

class TestMachineAPI(MAASServerTestCase):
    def test_list_machines(self):
        """Test machine listing."""
        # Use factory to create test data
        machine = factory.make_Machine(hostname="test")
        
        response = self.client.get("/MAAS/api/2.0/machines/")
        self.assertEqual(response.status_code, 200)
```

### Running Tests

```bash
# Run all maasserver tests
bin/test.region

# Run specific test file
bin/test.region src/maasserver/tests/test_machine.py

# Run specific test case
bin/test.region src/maasserver/tests/test_machine.py::TestMachine::test_create_machine
```

### Test Database

Tests use a separate test database:
- Automatically created and destroyed
- Isolated from development database
- Migrations applied automatically

## Development Guidelines

### Adding New Features

**Prefer v3 API**: New features should be implemented in the v3 API (`src/maasapiserver` + `src/maasservicelayer`) unless there's a specific requirement for v2 support.

**If must add to v2**:
1. Keep changes minimal
2. Maintain backward compatibility
3. Document in v2 API deprecation notes
4. Plan migration path to v3

### Modifying Existing Code

When modifying legacy code:

1. **Preserve Structure**: Don't refactor unless necessary
2. **Test Coverage**: Ensure existing tests pass
3. **Backward Compatibility**: Don't break existing API contracts
4. **Document Changes**: Update docstrings and comments

### Database Migrations

Use Django migrations:

```bash
# Create migration
./manage.py makemigrations maasserver

# Apply migrations
./manage.py migrate
```

**Coordination**: Database is shared with v3 API. Coordinate migrations with `src/maasservicelayer` Alembic migrations.

## Integration Points

### v3 API Integration

The v3 API shares the same database:
- **Shared Schema**: Both use same PostgreSQL database
- **Shared Models**: Some data models overlap
- **Migration Coordination**: Schema changes require coordination

### Provisioning Server

Communicates with rack controllers via RPC:

```python
from provisioningserver.rpc.region import ProvisioningRPC

# RPC calls to rack controllers
client.call(GetBootConfig, system_id=machine.system_id)
```

### Metadata Server

Provides cloud-init metadata during machine deployment:
- Boot configuration
- User data
- Network configuration

### Web UI

Django templates and views for the web interface:
- Machine management UI
- Network configuration UI
- Settings and administration

### MAAS CLI

CLI communicates with v2 API endpoints:
- OAuth authentication
- REST API calls
- JSON responses

## Migration Strategy

### From v2 to v3

Gradual migration approach:

1. **Identify Feature**: Feature to migrate from v2 to v3
2. **Implement in v3**: Build feature in v3 API with three-tier architecture
3. **Test Parity**: Ensure v3 feature matches v2 behavior
4. **Update Clients**: Migrate clients to v3 endpoint
5. **Deprecate v2**: Mark v2 endpoint as deprecated
6. **Monitor Usage**: Track v2 endpoint usage
7. **Remove v2**: After sufficient transition period

### Shared Components

Some components remain shared:
- Database schema
- Django models (until fully migrated)
- Authentication backends
- Permission systems

## Common Pitfalls

### Threading Issues

❌ **Don't**: Call Django ORM directly from Twisted async code
```python
@defer.inlineCallbacks
def bad_example():
    machine = Machine.objects.get(id=123)  # WRONG: Not thread-safe
```

✅ **Do**: Use deferToDatabase
```python
@defer.inlineCallbacks
def good_example():
    machine = yield deferToDatabase(lambda: Machine.objects.get(id=123))
```

### Transaction Management

❌ **Don't**: Manually manage transactions
```python
from django.db import transaction

def bad_example():
    with transaction.atomic():  # Avoid manual transaction management
        Machine.objects.create(...)
```

✅ **Do**: Use @transactional decorator
```python
@transactional
def good_example():
    Machine.objects.create(...)  # Transaction handled automatically
```

### Breaking Changes

❌ **Don't**: Change existing API behavior
```python
def get_machines(request):
    # Don't change response format
    return {"machines": [...]}  # Breaking change
```

✅ **Do**: Maintain backward compatibility
```python
def get_machines(request):
    # Preserve existing response format
    return [...]  # Original format maintained
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Python Development**: General Python best practices
- **Django Development**: Django-specific patterns
- **Twisted Async**: Asynchronous programming with Twisted
- **Database Migrations**: Django migration management
- **API Development**: REST API design and implementation
- **Testing**: Unit and integration testing strategies

## Security Considerations

### Authentication
- OAuth 1.0a for API access
- Django session authentication for web UI
- Macaroon-based authentication for specialized use cases

### Authorization
- Django permission system
- Role-based access control
- Resource-level permissions

### Input Validation
- Django form validation
- Manual validation in API handlers
- SQL injection prevention via ORM

## Performance Considerations

### Database Optimization
- Use `select_related()` and `prefetch_related()` to avoid N+1 queries
- Index frequently queried fields
- Use database-level constraints

### Caching
- Django cache framework
- Per-request caching
- Memcached backend

### Async Operations
- Use deferToDatabase for blocking operations
- Avoid blocking the Twisted reactor
- Use thread pools appropriately

## Documentation

### Code Documentation
- Docstrings for all public functions and classes
- Inline comments for complex logic
- Type hints where beneficial (gradually adding)

### API Documentation
- v2 API reference maintained separately
- Endpoint documentation in code
- Example requests/responses

## Maintenance Status

**Current State**: Legacy codebase in maintenance mode

**Changes Allowed**:
- ✅ Bug fixes
- ✅ Security patches
- ✅ Critical feature updates
- ⚠️ New features (justify v2 requirement)
- ❌ Major refactoring
- ❌ Architecture changes

**Future Direction**: Gradual feature migration to v3 API

## Additional Resources

- Django Documentation: https://docs.djangoproject.com/
- Twisted Documentation: https://docs.twisted.org/
- MAAS v2 API Reference: https://maas.io/docs/api
- `AGENTS.md`: General coding guidelines
- `src/maasservicelayer/README.md`: v3 architecture guide