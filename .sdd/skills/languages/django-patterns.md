# Django Patterns

## Purpose

Define Django ORM patterns for legacy MAAS code (primarily `maasserver`), including model design, QuerySet usage, migrations, and integration with the existing Django-based codebase.

## When to Use

- Maintaining existing Django-based code in `maasserver`
- Working with Django models in legacy endpoints
- Creating or modifying Django migrations
- Accessing Django ORM from legacy v2 API
- Using `deferToDatabase` in async contexts with Django

**Note**: New v3 API code should use SQLAlchemy Core, not Django ORM. See [sqlalchemy-patterns.md](sqlalchemy-patterns.md).

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

**Model with Validators**:

```python
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

class Machine(models.Model):
    cpu_count = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(256)]
    )
    
    def clean(self):
        super().clean()
        if self.hostname.startswith("_"):
            raise ValidationError("Hostname cannot start with underscore")
    
    def save(self, *args, **kwargs):
        self.full_clean()  # Run validators
        super().save(*args, **kwargs)
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

**Complex Queries**:

```python
from django.db.models import Q, F, Count, Sum

# OR conditions
machines = Machine.objects.filter(
    Q(status="ready") | Q(status="allocated")
)

# Complex boolean logic
machines = Machine.objects.filter(
    Q(status="ready") & (Q(zone_id=1) | Q(zone_id=2))
)

# Field comparisons
machines = Machine.objects.filter(cpu_count__gt=F("memory") / 1024)

# Aggregation
from django.db.models import Count, Avg
zone_stats = Zone.objects.annotate(
    machine_count=Count("machines"),
    avg_cpu=Avg("machines__cpu_count"),
)

# Distinct
unique_zones = Machine.objects.values("zone_id").distinct()
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

# Complex prefetch
from django.db.models import Prefetch
zones = Zone.objects.prefetch_related(
    Prefetch(
        "machines",
        queryset=Machine.objects.filter(status="ready"),
        to_attr="ready_machines",
    )
)
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

# Savepoints for partial rollback
with transaction.atomic():
    create_machine("machine1")
    
    sid = transaction.savepoint()
    try:
        create_machine("invalid")
    except Exception:
        transaction.savepoint_rollback(sid)
    
    create_machine("machine2")  # This still succeeds
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

**Complex Schema Changes**:

```python
class Migration(migrations.Migration):
    operations = [
        # Add index
        migrations.AddIndex(
            model_name="machine",
            index=models.Index(fields=["zone", "status"], name="machine_zone_status_idx"),
        ),
        
        # Add constraint
        migrations.AddConstraint(
            model_name="machine",
            constraint=models.CheckConstraint(
                check=models.Q(cpu_count__gte=1),
                name="machine_cpu_count_positive",
            ),
        ),
        
        # Rename field
        migrations.RenameField(
            model_name="machine",
            old_name="cores",
            new_name="cpu_count",
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

### Manager and QuerySet Custom Methods

```python
class MachineQuerySet(models.QuerySet):
    def ready(self):
        return self.filter(status="ready")
    
    def in_zone(self, zone_id):
        return self.filter(zone_id=zone_id)
    
    def with_min_resources(self, min_cpu, min_memory):
        return self.filter(
            cpu_count__gte=min_cpu,
            memory__gte=min_memory,
        )

class MachineManager(models.Manager):
    def get_queryset(self):
        return MachineQuerySet(self.model, using=self._db)
    
    def ready(self):
        return self.get_queryset().ready()
    
    def in_zone(self, zone_id):
        return self.get_queryset().in_zone(zone_id)

class Machine(models.Model):
    # fields...
    
    objects = MachineManager()

# Usage
ready_machines = Machine.objects.ready()
zone_ready = Machine.objects.ready().in_zone(1)
```

### Model Properties and Methods

```python
class Machine(models.Model):
    cpu_count = models.IntegerField()
    memory = models.IntegerField()  # MB
    
    @property
    def memory_gb(self):
        """Memory in gigabytes."""
        return self.memory / 1024
    
    @property
    def is_high_spec(self):
        return self.cpu_count >= 16 and self.memory >= 32768
    
    def allocate_to(self, user):
        """Business logic method."""
        if self.status != "ready":
            raise ValueError(f"Machine {self.hostname} is not ready")
        
        self.status = "allocated"
        self.owner = user
        self.save()
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

### ❌ Multiple Database Hits in Loop

```python
# NEVER query in a loop
for machine_id in machine_ids:
    machine = Machine.objects.get(id=machine_id)  # N queries!
    process(machine)

# Correct: Fetch once
machines = Machine.objects.filter(id__in=machine_ids)
for machine in machines:
    process(machine)
```

### ❌ Not Using Transactions for Multi-Step Operations

```python
# NEVER skip transactions for related operations
def create_machine_with_interfaces(data):
    machine = Machine.objects.create(**data)
    Interface.objects.create(machine=machine, name="eth0")  # Could fail, leaving orphan
    Interface.objects.create(machine=machine, name="eth1")

# Correct
@transaction.atomic
def create_machine_with_interfaces(data):
    machine = Machine.objects.create(**data)
    Interface.objects.create(machine=machine, name="eth0")
    Interface.objects.create(machine=machine, name="eth1")
```

### ❌ Modifying QuerySets After Evaluation

```python
# NEVER modify queryset after it's evaluated
machines = Machine.objects.filter(status="ready")
list(machines)  # Evaluates queryset
machines = machines.filter(zone_id=1)  # New query, previous evaluation wasted
```

### ❌ Using .count() When You Need Existence Check

```python
# NEVER use count() just to check existence
if Machine.objects.filter(hostname="test").count() > 0:  # Counts all matching rows
    do_something()

# Correct
if Machine.objects.filter(hostname="test").exists():  # Efficient EXISTS query
    do_something()
```

## Related Skills

- **SQLAlchemy**: [sqlalchemy-patterns.md](sqlalchemy-patterns.md) - Patterns for new v3 API code
- **Python Patterns**: [python-patterns.md](python-patterns.md) - General Python conventions
- **Database Migration**: [../compositions/database-migration.md](../compositions/database-migration.md) - Migration workflows
- **Testing**: [python-testing.md](python-testing.md) - Testing Django code
- **Security**: [../techniques/input-validation.md](../techniques/input-validation.md) - Secure database access

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