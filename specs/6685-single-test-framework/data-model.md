# Data Model: Test Framework Configuration & Migration State

**Feature**: Standardize Test Frameworks - Python pytest Migration  
**Phase**: Phase 1 Design  
**Date**: 2026-03-27

---

## Core Entities

### 1. TestFrameworkConfiguration

**Purpose**: Define the pytest configuration and requirements for MAAS Python testing

**Attributes**:
```
id: UUID
language: "python"
framework: "pytest"
minimum_version: "7.0.0"
python_version: "3.9+"
configuration_source: ["pytest.ini", "pyproject.toml", "conftest.py"]
created_at: timestamp
updated_at: timestamp
status: "active" | "deprecated"
```

**Validation Rules**:
- framework MUST be "pytest" (no other values allowed)
- minimum_version MUST be ≥7.0.0 (supports modern pytest features)
- python_version MUST match pyproject.toml specification (3.9+)
- configuration_source MUST include at least one valid config file

**Relationships**:
- Has many: MigrationPhases
- Has many: TestModuleConfigs
- References: FixtureLibrary

---

### 2. TestModuleConfig

**Purpose**: Track pytest configuration for individual Python modules

**Attributes**:
```
id: UUID
module_path: string (e.g., "src/maasserver")
module_name: string (e.g., "maasserver")
test_framework: "pytest" | "unittest" | "testtools" | "mixed"
test_file_count: integer ≥ 0
test_class_count: integer ≥ 0
test_function_count: integer ≥ 0
fixture_dependencies: string[] (fixture names)
external_dependencies: string[] (pytest plugins: pytest-django, pytest-asyncio, etc.)
migration_status: "not_started" | "in_progress" | "blocked" | "complete" | "verified"
estimated_effort: "low" (0-2 days) | "medium" (2-5 days) | "high" (5+ days)
blockers: string[] (descriptions of blocking issues)
migration_start_date: date | null
migration_complete_date: date | null
owner: string (developer assigned)
notes: string
```

**Validation Rules**:
- module_path MUST exist in repository
- test_file_count MUST be ≥ 0
- migration_status progression: not_started → in_progress → [blocked OR complete] → verified
- If status is "blocked", blockers array MUST not be empty
- If status is "complete", migration_complete_date MUST be set
- estimated_effort MUST be calculated based on test_file_count:
  - low: 1-10 files
  - medium: 11-50 files
  - high: 51+ files

**Relationships**:
- Belongs to: MigrationPhase
- Has many: TestFileConfigs
- References: TestFrameworkConfiguration

---

### 3. TestFileConfig

**Purpose**: Track pytest configuration for individual test files

**Attributes**:
```
id: UUID
file_path: string (e.g., "src/maasserver/tests/test_machines.py")
file_name: string (e.g., "test_machines.py")
current_framework: "pytest" | "unittest" | "testtools"
target_framework: "pytest"
test_count: integer
class_count: integer (for unittest.TestCase subclasses)
uses_fixtures: boolean
uses_parametrize: boolean
uses_mock: boolean
needs_conversion: boolean
conversion_blockers: string[] (e.g., "uses_asyncio_TestCase", "custom_test_runner")
migration_status: "not_started" | "in_progress" | "review" | "complete"
migration_date: date | null
reviewer: string | null
notes: string
```

**Validation Rules**:
- file_path MUST end in `test_*.py` or `*_test.py`
- test_count MUST be ≥ 1 (empty test files should not exist)
- If current_framework is "unittest", needs_conversion MUST be true
- If needs_conversion is true, conversion_blockers MUST be populated

**Relationships**:
- Belongs to: TestModuleConfig
- Has many: TestAssertionConversions (for assertion migration)

---

### 4. FixtureLibrary

**Purpose**: Define shared pytest fixtures available to all test modules

**Attributes**:
```
id: UUID
name: string (e.g., "database_fixtures", "api_fixtures")
fixture_definitions: FixtureDefinition[]
location: string (e.g., "src/maastesting/fixtures/database.py")
version: string (semver)
created_at: timestamp
updated_at: timestamp
documentation: string (sphinx-compatible docstring)
```

**Relationships**:
- Has many: FixtureDefinitions
- References: TestFrameworkConfiguration

---

### 5. FixtureDefinition

**Purpose**: Define individual pytest fixtures and their contracts

**Attributes**:
```
id: UUID
name: string (e.g., "db_connection", "api_client")
scope: "function" | "class" | "module" | "session"
fixture_type: "database" | "mock" | "api" | "configuration" | "utility"
parameters: Parameter[] (other fixtures it depends on)
return_type: string (e.g., "Connection", "TestClient")
documentation: string
example_usage: string (code example)
deprecation_status: "active" | "deprecated" | "planned"
deprecation_replacement: FixtureDefinition | null
created_at: timestamp
updated_at: timestamp
```

**Validation Rules**:
- name MUST be unique within FixtureLibrary
- scope MUST be valid pytest scope
- return_type MUST be documented for IDE autocomplete
- If deprecation_status is "deprecated", deprecation_replacement MUST reference valid fixture

**Common Fixtures** (pre-defined):

| Name | Scope | Type | Returns | Purpose |
|------|-------|------|---------|---------|
| `db_connection` | function | database | Connection | Raw database connection |
| `db_transaction` | function | database | Transaction | Transaction-scoped DB (auto-rollback) |
| `django_client` | function | api | Client | Django test client |
| `api_client` | function | api | TestClient | FastAPI test client |
| `mock_service` | function | mock | MagicMock | Mocked service layer |
| `settings` | session | configuration | Settings | Test configuration |
| `tmp_dir` | function | utility | Path | Temporary directory |
| `logged_in_user` | function | database | User | Test user object |

**Relationships**:
- Belongs to: FixtureLibrary
- Has many: FixtureParameters (dependencies)

---

### 6. MigrationPhase

**Purpose**: Define phases of test framework migration

**Attributes**:
```
id: UUID
phase_number: integer (1, 2, 3, ...)
phase_name: string (e.g., "Phase 1 - Low Risk Foundation")
modules: TestModuleConfig[] (modules to migrate)
start_date: date
estimated_end_date: date
actual_end_date: date | null
status: "planned" | "in_progress" | "complete"
dependencies_on_phases: integer[] (prior phase numbers)
estimated_duration_days: integer
notes: string
```

**Validation Rules**:
- phase_number MUST be sequential (1, 2, 3, not 1, 3, 5)
- dependencies_on_phases MUST reference valid prior phase numbers
- estimated_duration_days MUST be > 0
- If status is "complete", actual_end_date MUST be set

**Predefined Phases**:

| Phase | Name | Modules | Duration | Dependencies |
|-------|------|---------|----------|--------------|
| 1 | Foundation & Setup | pytest config, conftest.py, fixture library | 1 week | - |
| 2 | Low Risk Modules | maascommon, maascli, apiclient | 1 week | Phase 1 |
| 3 | Medium Risk | maastesting, maasservicelayer, maasapiserver | 1 week | Phase 2 |
| 4 | High Risk | provisioningserver, metadataserver | 2 weeks | Phase 3 |
| 5 | Complex Legacy | maasserver | 2 weeks | Phase 4 |
| 6 | CI/CD Integration | Test runner updates, GitHub Actions | 1 week | Phase 5 |
| 7 | Cleanup & Docs | Remove unittest references, finalize docs | 1 week | Phase 6 |

**Relationships**:
- Has many: TestModuleConfigs
- Has many: MigrationTaskGroups (for task tracking)

---

### 7. TestAssertionConversion

**Purpose**: Track conversion of unittest assertions to pytest assert statements

**Attributes**:
```
id: UUID
test_file_id: UUID (TestFileConfig)
old_assertion: string (e.g., "self.assertEqual(a, b)")
new_assertion: string (e.g., "assert a == b")
count_in_file: integer
complexity: "simple" | "moderate" | "complex"
automated_conversion_possible: boolean
conversion_script: string | null (e.g., "lib2to3 fixer name")
notes: string
```

**Validation Rules**:
- old_assertion MUST be valid unittest assertion syntax
- new_assertion MUST be valid pytest assertion syntax
- count_in_file MUST be ≥ 1

**Supported Conversions**:

| unittest | pytest | Type |
|----------|--------|------|
| `self.assertEqual(a, b)` | `assert a == b` | Simple |
| `self.assertNotEqual(a, b)` | `assert a != b` | Simple |
| `self.assertTrue(a)` | `assert a` | Simple |
| `self.assertFalse(a)` | `assert not a` | Simple |
| `self.assertIn(a, b)` | `assert a in b` | Simple |
| `self.assertRaises(exc, fn, *args)` | `pytest.raises(exc)` | Moderate |
| `self.assertIsNone(a)` | `assert a is None` | Simple |
| `self.assertIsNotNone(a)` | `assert a is not None` | Simple |
| Custom assertions (test base classes) | @pytest.fixture or helper functions | Complex |

**Relationships**:
- Belongs to: TestFileConfig

---

## State Transitions

### TestModuleConfig State Machine

```
┌─────────────────┐
│  not_started    │ (Initial state)
│                 │
└────────┬────────┘
         │
         ├─ (Developer starts work)
         ▼
┌─────────────────┐
│  in_progress    │
│                 │
└────────┬────────┘
         │
         ├─ (Blocker encountered)
         │─► (blocked) ──┐
         │               │
         │ (No blocker)  │
         ▼               │
┌─────────────────┐     │
│  complete       │     │
│                 │     │
└────────┬────────┘     │
         │              │
         ├─ (Tests pass) │
         │              │
         │ (Tests fail)  │
         ├──────────────┘
         │
         ▼
┌─────────────────┐
│   verified      │ (Final state)
│                 │
└─────────────────┘
```

---

## Relationships Summary

```
TestFrameworkConfiguration
├── Has many MigrationPhases
├── Has many TestModuleConfigs
└── References FixtureLibrary

MigrationPhase
├── Has many TestModuleConfigs
└── Has many MigrationTaskGroups

TestModuleConfig
├── Belongs to MigrationPhase
├── Has many TestFileConfigs
└── References TestFrameworkConfiguration

TestFileConfig
├── Belongs to TestModuleConfig
└── Has many TestAssertionConversions

FixtureLibrary
├── Has many FixtureDefinitions
└── References TestFrameworkConfiguration

FixtureDefinition
├── Belongs to FixtureLibrary
└── Has many FixtureParameters
```

---

## Key Validations & Constraints

1. **Referential Integrity**:
   - TestModuleConfig references must exist
   - MigrationPhase dependencies must be satisfied
   - FixtureDefinition parameters must reference valid fixtures

2. **Status Consistency**:
   - If any TestModuleConfig is "not_started", parent MigrationPhase cannot be "complete"
   - If MigrationPhase is "complete", all TestModuleConfigs must be at least "complete"

3. **Temporal Constraints**:
   - actual_end_date ≥ start_date
   - estimated_end_date ≥ start_date
   - TestModuleConfig migration_complete_date ≤ MigrationPhase actual_end_date

4. **Phase Dependencies**:
   - Phase N cannot start until Phase N-1 is complete
   - Dependency cycles are not allowed

---

## Queries & Reporting

**Migration Progress**:
```
SELECT 
    phase_number,
    COUNT(CASE WHEN status = 'complete' THEN 1 END) as completed,
    COUNT(*) as total,
    ROUND(100.0 * COUNT(CASE WHEN status = 'complete' THEN 1 END) / COUNT(*), 2) as pct_complete
FROM TestModuleConfig
GROUP BY phase_number
ORDER BY phase_number;
```

**Blocker Status**:
```
SELECT 
    module_name,
    blockers
FROM TestModuleConfig
WHERE migration_status = 'blocked'
ORDER BY module_name;
```

**Fixture Adoption**:
```
SELECT 
    name,
    COUNT(DISTINCT module_id) as modules_using,
    fixture_type
FROM FixtureDefinition
JOIN TestModuleConfig ON fixture_dependencies CONTAINS FixtureDefinition.name
GROUP BY name
ORDER BY modules_using DESC;
```

---

**Data Model Status**: ✅ COMPLETE - Ready for Phase 1 implementation
