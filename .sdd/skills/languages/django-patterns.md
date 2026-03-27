# Django Patterns

## Purpose

Define Django ORM patterns for legacy MAAS code (primarily `maasserver`), including model design, QuerySet usage, migrations, and integration with the existing Django-based codebase.

## When to Use

Maintaining existing Django-based code in `maasserver`, legacy v2 API, and Django migrations. **Note**: New v3 API code uses SQLAlchemy Core.

## Pattern Examples

### Django Model Design

**Basic Model**:

```python
from django.db import models

class Machine(models.Model):
    hostname = models.CharField(max_length=255, unique=True)
    zone = models.ForeignKey(
        "Zone",
        on_delete=models.PROTECT,
        related_name="machines",
    )
    cpu_count = models.IntegerField(default=1)
    memory = models.IntegerField(default=0)  # MB
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "maasserver_machine"
        ordering = ["hostname"]
        
    def __str__(self):
        return self.hostname
```

### QuerySet Patterns

**Basic Queries**:

```python
# Get single object
machine = Machine.objects.get(id=1)
machine = Machine.objects.get(hostname="node1")

# Get or 404
from django.shortcuts import get_object_or_404
machine = get_object_or_404(Machine, id=1)

# Get with default
machine = Machine.objects.filter(hostname="node1").first()  # None if not found

# Filter
ready_machines = Machine.objects.filter(status="ready")
zone_machines = Machine.objects.filter(zone_id=1)

# Exclude
non_ready = Machine.objects.exclude(status="ready")

# Multiple conditions
machines = Machine.objects.filter(
    status="ready",
    zone_id=1,
    cpu_count__gte=4,
)
```

**Complex Queries with Q Objects**:

```python
from django.db.models import Q, F

# OR conditions
machines = Machine.objects.filter(
    Q(status="ready") | Q(status="allocated")
)

# Field comparisons
machines = Machine.objects.filter(cpu_count__gt=F("memory") / 1024)
```

**Select Related / Prefetch Related**:

```python
# select_related for ForeignKey/OneToOne (SQL JOIN)
machines = Machine.objects.select_related("zone", "owner")
for machine in machines:
    print(machine.zone.name)  # No additional query

# prefetch_related for ManyToMany/Reverse ForeignKey
zones = Zone.objects.prefetch_related("machines")
for zone in zones:
    for machine in zone.machines.all():  # No N+1 queries
        print(machine.hostname)

```

### Transactions

```python
from django.db import transaction

# Atomic decorator
@transaction.atomic
def create_machine_with_interfaces(hostname, zone_id):
    machine = Machine.objects.create(hostname=hostname, zone_id=zone_id)
    Interface.objects.create(machine=machine, name="eth0")
    Interface.objects.create(machine=machine, name="eth1")
    return machine

# Atomic context manager
def update_machine_status(machine_id, new_status):
    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(id=machine_id)
        machine.status = new_status
        machine.save()
        StatusHistory.objects.create(machine=machine, status=new_status)

```

### Migrations

**Creating Migrations**:

```python
# In migration file: 0042_add_machine_description.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("maasserver", "0041_previous_migration"),
    ]
    
    operations = [
        migrations.AddField(
            model_name="machine",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
```

**Data Migrations**:

```python
from django.db import migrations

def populate_default_zone(apps, schema_editor):
    Machine = apps.get_model("maasserver", "Machine")
    Zone = apps.get_model("maasserver", "Zone")
    
    default_zone = Zone.objects.get(name="default")
    Machine.objects.filter(zone__isnull=True).update(zone=default_zone)

def reverse_populate_default_zone(apps, schema_editor):
    # Optional: define reverse operation
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("maasserver", "0042_add_zone_field"),
    ]
    
    operations = [
        migrations.RunPython(
            populate_default_zone,
            reverse_populate_default_zone,
        ),
    ]
```

### Django in Async Contexts (deferToDatabase)

```python
from twisted.internet.defer import inlineCallbacks
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase

@inlineCallbacks
def async_handler():
    # Call synchronous Django ORM code from async context
    machines = yield deferToDatabase(get_ready_machines)
    return machines

@transactional
def get_ready_machines():
    """Synchronous function that uses Django ORM."""
    return list(Machine.objects.filter(status="ready"))

# With parameters
@inlineCallbacks
def update_machine_async(machine_id, new_status):
    result = yield deferToDatabase(
        update_machine_status,
        machine_id,
        new_status,
    )
    return result

@transactional
def update_machine_status(machine_id, new_status):
    machine = Machine.objects.get(id=machine_id)
    machine.status = new_status
    machine.save()
    return machine
```

## Anti-patterns

### ❌ Using Django ORM in V3 API

```python
# NEVER use Django ORM in new v3 API code
from maasserver.models import Machine  # Wrong layer

@router.get("/api/v3/machines")
async def list_machines():
    machines = Machine.objects.all()  # Wrong: Use SQLAlchemy Core
```

### ❌ N+1 Query Problem

```python
# NEVER iterate without select_related/prefetch_related
machines = Machine.objects.all()
for machine in machines:
    print(machine.zone.name)  # N+1 queries!
    
# Correct
machines = Machine.objects.select_related("zone")
for machine in machines:
    print(machine.zone.name)  # Single query
```

### ❌ Raw SQL String Interpolation

```python
# NEVER use string formatting for SQL
Machine.objects.raw(f"SELECT * FROM machine WHERE id = {machine_id}")  # SQL injection!

# Correct: Use parameterized queries
Machine.objects.raw("SELECT * FROM machine WHERE id = %s", [machine_id])
```

### ❌ Fetching All Objects When You Need One

```python
# NEVER fetch all when you need one
all_machines = Machine.objects.all()
machine = [m for m in all_machines if m.id == target_id][0]  # Wasteful!

# Correct
machine = Machine.objects.get(id=target_id)
```

### ❌ Not Using Transactions for Multi-Step Operations

```python
# NEVER skip transactions for related operations
def create_machine_with_interfaces(data):
    machine = Machine.objects.create(**data)
    Interface.objects.create(machine=machine, name="eth0")  # Could fail, leaving orphan

# Correct
@transaction.atomic
def create_machine_with_interfaces(data):
    machine = Machine.objects.create(**data)
    Interface.objects.create(machine=machine, name="eth0")
```

### ❌ Using .count() When You Need Existence Check

```python
# NEVER use count() just to check existence
if Machine.objects.filter(hostname="test").count() > 0:  # Wasteful
    do_something()

# Correct
if Machine.objects.filter(hostname="test").exists():  # Efficient EXISTS query
    do_something()
```

## When to Use Django vs SQLAlchemy

| Context | Use Django ORM | Use SQLAlchemy Core |
|---------|---------------|---------------------|
| New v3 API code | ❌ No | ✅ Yes |
| Legacy maasserver | ✅ Yes | ❌ No |
| New service layer | ❌ No | ✅ Yes |
| Existing Django models | ✅ Yes | ❌ No |
| Migrations | ✅ Django migrations | ❌ No |
| Legacy v2 API | ✅ Yes | ❌ No |

## Configuration

- **Migration path**: `src/maasserver/migrations/`
- **Models location**: `src/maasserver/models/`
- **Database**: PostgreSQL
- **Transaction isolation**: Read Committed (default)