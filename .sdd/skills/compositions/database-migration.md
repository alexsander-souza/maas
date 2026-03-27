# Database Migration

## Purpose

Complete workflow for creating, testing, and deploying database migrations in MAAS, covering both Django migrations (legacy) and SQLAlchemy schema changes (v3 API), with focus on data integrity and zero-downtime deployments.

## When to Use

- Adding new tables or columns to the database
- Modifying existing schema (rename, change type, add constraints)
- Migrating data between schema versions
- Removing deprecated tables or columns
- Creating indexes for performance

## Combined Skills

- **Django Patterns**: [../languages/django-patterns.md](../languages/django-patterns.md) - Django migration system
- **SQLAlchemy Patterns**: [../languages/sqlalchemy-patterns.md](../languages/sqlalchemy-patterns.md) - Schema definition
- **Python Patterns**: [../languages/python-patterns.md](../languages/python-patterns.md) - Code organization
- **Secure Coding**: [../techniques/secure-coding.md](../techniques/secure-coding.md) - Safe data handling
- **Testing**: [../languages/python-testing.md](../languages/python-testing.md) - Migration testing

## Workflow Steps

### 1. Plan the Migration

**Identify Changes Needed**:

```python
# Example: Add description field to Machine model

# Current state (Django model)
class Machine(models.Model):
    hostname = models.CharField(max_length=255)
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT)
    status = models.CharField(max_length=50)

# Desired state
class Machine(models.Model):
    hostname = models.CharField(max_length=255)
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT)
    status = models.CharField(max_length=50)
    description = models.TextField(blank=True, default="")  # NEW
```

**Consider Backward Compatibility**:

- Can old code run with new schema?
- Can new code run with old schema?
- Do you need a multi-step migration?

### 2. Create Django Migration (Legacy Code)

**Generate Migration**:

```bash
cd src
python3 manage.py makemigrations maasserver --name add_machine_description
```

**Review Generated Migration**:

```python
# src/maasserver/migrations/0123_add_machine_description.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("maasserver", "0122_previous_migration"),
    ]
    
    operations = [
        migrations.AddField(
            model_name="machine",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
```

**For Complex Changes - Manual Migration**:

```python
# Data migration example
from django.db import migrations

def populate_machine_descriptions(apps, schema_editor):
    """Populate descriptions from machine tags."""
    Machine = apps.get_model("maasserver", "Machine")
    Tag = apps.get_model("maasserver", "Tag")
    
    for machine in Machine.objects.all():
        tags = Tag.objects.filter(machine=machine)
        machine.description = ", ".join(tag.name for tag in tags)
        machine.save()

def reverse_migration(apps, schema_editor):
    """Clear descriptions on rollback."""
    Machine = apps.get_model("maasserver", "Machine")
    Machine.objects.update(description="")

class Migration(migrations.Migration):
    dependencies = [
        ("maasserver", "0123_add_machine_description"),
    ]
    
    operations = [
        migrations.RunPython(
            populate_machine_descriptions,
            reverse_migration,
        ),
    ]
```

### 3. Update SQLAlchemy Table Definitions (V3 API)

**Update Table Definition**:

```python
# src/maasservicelayer/db/tables.py
from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, MetaData

metadata = MetaData()

MachineTable = Table(
    "maasserver_machine",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hostname", String(255), nullable=False),
    Column("zone_id", Integer, ForeignKey("maasserver_zone.id"), nullable=False),
    Column("status", String(50), nullable=False),
    Column("description", Text, nullable=False, server_default=""),  # NEW
)
```

**Update Pydantic Models**:

```python
# src/maasservicelayer/models/machines.py
from pydantic import BaseModel, Field

class Machine(BaseModel):
    id: int
    hostname: str
    zone_id: int
    status: str
    description: str = ""  # NEW

class MachineRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    zone_id: int = Field(gt=0)
    description: str = ""  # NEW - optional
```

### 4. Handle Multi-Step Migrations

**For Breaking Changes - Three-Step Process**:

```python
# Step 1: Add new column (nullable or with default)
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name="machine",
            name="cpu_count_new",
            field=models.IntegerField(null=True),
        ),
    ]

# Step 2: Migrate data
class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(copy_cpu_count_to_new_column),
    ]

# Step 3: Remove old column, rename new column
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(model_name="machine", name="cpu_count"),
        migrations.RenameField(
            model_name="machine",
            old_name="cpu_count_new",
            new_name="cpu_count",
        ),
        migrations.AlterField(
            model_name="machine",
            name="cpu_count",
            field=models.IntegerField(null=False),
        ),
    ]
```

### 5. Add Indexes and Constraints

**Performance Indexes**:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.AddIndex(
            model_name="machine",
            index=models.Index(
                fields=["zone", "status"],
                name="machine_zone_status_idx",
            ),
        ),
    ]
```

**Data Integrity Constraints**:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.AddConstraint(
            model_name="machine",
            constraint=models.CheckConstraint(
                check=models.Q(cpu_count__gte=1),
                name="machine_cpu_count_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="machine",
            constraint=models.UniqueConstraint(
                fields=["hostname", "zone"],
                name="unique_hostname_per_zone",
            ),
        ),
    ]
```

### 6. Test Migrations

**Test Migration Applies Cleanly**:

```python
# tests/test_migrations.py
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

def test_migration_0123_applies_successfully():
    """Test that migration applies without errors."""
    executor = MigrationExecutor(connection)
    
    # Start from previous migration
    executor.migrate([("maasserver", "0122_previous_migration")])
    
    # Apply new migration
    executor.migrate([("maasserver", "0123_add_machine_description")])
    
    # Verify column exists
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'maasserver_machine' 
            AND column_name = 'description'
        """)
        assert cursor.fetchone() is not None

def test_migration_0123_is_reversible():
    """Test that migration can be rolled back."""
    executor = MigrationExecutor(connection)
    
    # Apply migration
    executor.migrate([("maasserver", "0123_add_machine_description")])
    
    # Reverse it
    executor.migrate([("maasserver", "0122_previous_migration")])
    
    # Verify column removed
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'maasserver_machine' 
            AND column_name = 'description'
        """)
        assert cursor.fetchone() is None
```

**Test Data Migration**:

```python
def test_data_migration_populates_descriptions():
    """Test that data migration correctly populates descriptions."""
    from django.apps import apps
    
    # Setup test data
    Machine = apps.get_model("maasserver", "Machine")
    machine = Machine.objects.create(hostname="test", zone_id=1)
    
    # Run data migration
    populate_machine_descriptions(apps, None)
    
    # Verify result
    machine.refresh_from_db()
    assert machine.description != ""
```

### 7. Handle Large Tables

**For Tables with Millions of Rows**:

```python
# Use batched updates to avoid locking table
def migrate_large_table(apps, schema_editor):
    Machine = apps.get_model("maasserver", "Machine")
    
    batch_size = 1000
    total = Machine.objects.count()
    
    for offset in range(0, total, batch_size):
        machines = Machine.objects.all()[offset:offset + batch_size]
        for machine in machines:
            machine.description = f"Machine {machine.hostname}"
        Machine.objects.bulk_update(machines, ["description"])
        
        # Commit batch to avoid long-running transaction
        schema_editor.connection.commit()
```

**Add Index Concurrently (PostgreSQL)**:

```python
class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation
    
    operations = [
        migrations.RunSQL(
            """
            CREATE INDEX CONCURRENTLY machine_status_idx 
            ON maasserver_machine (status)
            """,
            reverse_sql="DROP INDEX machine_status_idx",
        ),
    ]
```

### 8. Deployment Checklist

**Pre-Deployment**:

- [ ] Migration tested on copy of production database
- [ ] Migration is reversible (has reverse operation)
- [ ] Backward compatible with currently deployed code
- [ ] Large table migrations use batching
- [ ] Indexes created concurrently if needed
- [ ] Data migration has been reviewed for correctness

**Deployment**:

```bash
# Stop services (if downtime required)
sudo systemctl stop maas-apiserver

# Run migration
cd /path/to/maas
sudo -u maas python3 manage.py migrate

# Restart services
sudo systemctl start maas-apiserver
```

**Zero-Downtime Deployment**:

1. Deploy code that works with old and new schema
2. Run migration
3. Deploy code that uses new schema
4. (Optional) Clean up compatibility code later

## Security Considerations

### Protect Sensitive Data

```python
# NEVER log sensitive data during migration
def migrate_passwords(apps, schema_editor):
    User = apps.get_model("auth", "User")
    
    for user in User.objects.all():
        # WRONG: Logs password
        # print(f"Migrating user {user.username}: {user.password}")
        
        # Correct: No sensitive data in logs
        logger.info(f"Migrating user {user.id}")
        
        # Migrate password hash
        user.password_hash_new = hash_password(user.password_old)
        user.save()
```

### Validate Data

```python
def validate_before_migration(apps, schema_editor):
    """Validate data integrity before migration."""
    Machine = apps.get_model("maasserver", "Machine")
    
    # Check for invalid data
    invalid_machines = Machine.objects.filter(
        hostname__isnull=True
    ) | Machine.objects.filter(
        zone_id__lte=0
    )
    
    if invalid_machines.exists():
        raise ValueError(
            f"Found {invalid_machines.count()} machines with invalid data. "
            "Fix data before running migration."
        )
```

## Common Patterns

### Rename Column

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RenameField(
            model_name="machine",
            old_name="cores",
            new_name="cpu_count",
        ),
    ]
```

### Change Column Type

```python
# Multi-step for safety
# Step 1: Add new column
migrations.AddField(
    model_name="machine",
    name="cpu_count_int",
    field=models.IntegerField(null=True),
)

# Step 2: Copy data with conversion
migrations.RunPython(convert_cpu_count)

# Step 3: Remove old, rename new
migrations.RemoveField(model_name="machine", name="cpu_count")
migrations.RenameField(
    model_name="machine",
    old_name="cpu_count_int",
    new_name="cpu_count",
)
```

### Add Foreign Key

```python
class Migration(migrations.Migration):
    operations = [
        # Step 1: Add column without constraint (nullable)
        migrations.AddField(
            model_name="machine",
            name="owner",
            field=models.ForeignKey(
                "auth.User",
                null=True,
                on_delete=models.SET_NULL,
            ),
        ),
        # Step 2: Populate data
        migrations.RunPython(assign_default_owners),
        # Step 3: Add constraint if needed (separate migration)
    ]
```

## Anti-patterns

### ❌ Non-Reversible Migrations

```python
# NEVER create non-reversible migrations
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            "DROP TABLE old_table",
            # WRONG: No reverse operation
        ),
    ]

# Correct: Always provide reverse
class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            "DROP TABLE old_table",
            reverse_sql="CREATE TABLE old_table (...)",
        ),
    ]
```

### ❌ Breaking Backward Compatibility

```python
# NEVER remove columns that current code uses
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(
            model_name="machine",
            name="hostname",  # WRONG: Code still uses this!
        ),
    ]

# Correct: Multi-step deployment
# 1. Deploy code that doesn't use hostname
# 2. Then remove column in next release
```

### ❌ Long-Running Transactions

```python
# NEVER update millions of rows in single transaction
def migrate_all_machines(apps, schema_editor):
    Machine = apps.get_model("maasserver", "Machine")
    
    # WRONG: Locks table for hours
    for machine in Machine.objects.all():
        machine.description = f"Machine {machine.hostname}"
        machine.save()

# Correct: Batch updates
def migrate_all_machines(apps, schema_editor):
    Machine = apps.get_model("maasserver", "Machine")
    batch_size = 1000
    
    for offset in range(0, Machine.objects.count(), batch_size):
        batch = Machine.objects.all()[offset:offset + batch_size]
        Machine.objects.bulk_update(batch, ["description"])
```

## Related Compositions

- **Backend Feature**: [backend-feature.md](backend-feature.md) - Complete feature workflow
- **Testing Suite**: [testing-suite.md](testing-suite.md) - Testing migrations

## Checklist

- [ ] Migration file created and reviewed
- [ ] SQLAlchemy tables updated (if v3 API)
- [ ] Pydantic models updated
- [ ] Migration is reversible
- [ ] Backward compatible (or multi-step plan)
- [ ] Tested on copy of production data
- [ ] Large table handling considered
- [ ] Indexes created concurrently if needed
- [ ] Security: No sensitive data logged
- [ ] Documentation updated