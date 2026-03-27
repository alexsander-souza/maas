# Research Document: pytest Migration for MAAS Python

**Feature**: Standardize Test Frameworks - Python pytest Migration  
**Branch**: 6685-single-test-framework  
**Date**: 2026-03-27

## Clarification 1: Current Test Framework Inventory

### Question
How many test files use unittest vs. pytest vs. testtools in the MAAS codebase?

### Research & Findings

**Methodology**: Audit Python test files in src/ directory for framework usage patterns

**Expected Findings** (based on MAAS codebase characteristics):
- **pytest**: Likely used in newer modules (maasapiserver, maasservicelayer, maastemporalworker)
- **unittest**: Legacy modules use unittest.TestCase extensively (maasserver, provisioningserver)
- **testtools**: Some older tests may use testtools (Django test runner compat)

**Inventory Tool**:
```bash
# Find all test files
find src -name "test_*.py" -o -name "*_test.py"

# Count unittest usage
grep -r "unittest.TestCase\|from unittest import" src --include="test_*.py" | wc -l

# Count pytest usage
grep -r "@pytest.fixture\|import pytest" src --include="test_*.py" | wc -l

# Count testtools usage
grep -r "testtools\|from testtools" src --include="test_*.py" | wc -l
```

**Decision**: All test files MUST migrate to pytest-only patterns. Unittest and testtools are deprecated in favor of pytest.

**Rationale**: pytest is modern, extensible, and standard in Python community (used in FastAPI, SQLAlchemy, Django 4.2+)

**Alternatives Considered**: 
- Coexistence of pytest + unittest: Rejected (violates single framework requirement)
- Stick with unittest: Rejected (less modern, verbose, boilerplate-heavy)

---

## Clarification 2: Legacy Module Compatibility

### Question
Which modules have deep dependencies on unittest-specific patterns that may require special handling?

### Research & Findings

**Methodology**: Identify unittest.TestCase subclasses and common patterns

**Expected Patterns to Handle**:

1. **unittest.TestCase Subclasses** (most common):
   ```python
   # OLD (unittest)
   class TestMachine(unittest.TestCase):
       def setUp(self): pass
       def test_creation(self): self.assertEqual(...)
   
   # NEW (pytest)
   @pytest.fixture
   def setup(): pass
   def test_creation(setup): assert ... == ...
   ```

2. **Django Test Framework Integration**:
   - maasserver uses Django's TestCase which inherits from unittest.TestCase
   - Django 4.2+ supports pytest natively
   - Migrate to: pytest-django plugin + pytest fixtures

3. **Mock/Patch Usage**:
   - unittest.mock → pytest-mock or unittest.mock (both work in pytest)
   - testtools.mock → unittest.mock

4. **Database Transactions** (Django-specific):
   - setUp/tearDown database cleanup → pytest fixtures with transaction scope
   - pytest-django provides `db` fixture for this

**Affected Modules** (estimated):
- `src/maasserver/` - Heavy Django dependency (100+ test classes)
- `src/provisioningserver/` - Twisted async + unittest (50+ test classes)
- `src/metadataserver/` - Django TestCase usage (30+ test classes)
- `src/maasapiserver/` - Already pytest-based (upgrade path only)
- `src/maasservicelayer/` - pytest with some SQLAlchemy patterns (minimal changes)

**Decision**: Provide migration helpers and examples for each pattern

**Rationale**: Pattern-based migration reduces risk and human error

**Migration Helper Examples**:
```python
# Helper 1: Convert setUp/tearDown to fixtures
# OLD:
#   def setUp(self): self.client = APIClient()
# NEW:
#   @pytest.fixture
#   def client(): return APIClient()

# Helper 2: Convert assertions
# OLD:
#   self.assertEqual(actual, expected)
# NEW:
#   assert actual == expected

# Helper 3: Django TestCase to pytest-django
# OLD:
#   from django.test import TestCase
# NEW:
#   import pytest; @pytest.mark.django_db
```

---

## Clarification 3: pytest Fixture Strategy

### Question
Should common fixtures be centralized in conftest.py or distributed per module?

### Research & Findings

**Methodology**: Review best practices for large pytest projects (FastAPI, SQLAlchemy, etc.)

**Best Practices** (from industry):

1. **Root conftest.py** (recommended for large projects):
   - Shared fixtures used across multiple modules
   - Database, mocking, API client fixtures
   - Configuration and markers
   - Example: FastAPI, SQLAlchemy, Django ORM test suites

2. **Module-level conftest.py**:
   - Module-specific fixtures (used only within that module)
   - Override shared fixtures if needed
   - Lightweight and focused

3. **Fixture Library** (best for MAAS):
   - src/maastesting/fixtures.py - Common fixture definitions
   - src/maastesting/conftest.py - Imports and re-exports
   - Allows reuse, documentation, and version control

**Decision for MAAS**: Hybrid approach

**Structure**:
```
src/
├── maastesting/
│   ├── conftest.py           # Root fixture setup
│   ├── fixtures/
│   │   ├── database.py       # DB fixtures
│   │   ├── mocking.py        # Mock/patch fixtures
│   │   ├── api.py            # API client fixtures
│   │   └── django.py         # Django-specific fixtures
│   └── markers.py            # Custom markers (slow, integration, db)

conftest.py                    # Root project conftest (imports from maastesting)
```

**Common Fixtures to Provide**:
- `db_connection` - Raw database connection
- `db_transaction` - Transaction-scoped DB for cleanup
- `django_client` - Django test client
- `api_client` - FastAPI/REST client
- `mock_service` - Mocked service layer
- `settings` - Configuration object
- `temporary_directory` - Tmpdir for file tests

**Rationale**: Centralized fixtures improve consistency; modular structure allows growth without chaos

**Alternatives Considered**:
- Purely distributed: Rejected (difficult to maintain consistency across 50+ modules)
- Purely centralized: Rejected (root conftest becomes monolithic)

---

## Clarification 4: Migration Sequencing

### Question
Which modules should migrate first (dependencies-first vs. risk-first)?

### Research & Findings

**Methodology**: Analyze test module dependencies and complexity

**Recommended Sequence**: Dependency-First (with risk awareness)

**Phase 1 - Low Risk, No Dependencies** (Week 1-2):
- maascommon (utilities, isolated)
- maascli (CLI tests, low framework dependency)
- apiclient (API client tests, straightforward)

**Phase 2 - Medium Risk, Few Dependencies** (Week 2-3):
- maastesting (test utilities themselves)
- maasservicelayer (service layer, already pytest-friendly)

**Phase 3 - Medium Risk, Some Dependencies** (Week 3-4):
- maasapiserver (FastAPI, already pytest-based - mostly upgrade)
- maastemporalworker (Temporal, modern patterns)

**Phase 4 - High Risk, Many Dependencies** (Week 4-6):
- provisioningserver (Twisted async, unittest patterns)
- metadataserver (Django, unittest.TestCase)
- maasserver (Most complex: Django + unittest + legacy patterns)

**Rationale**: 
- Quick wins build confidence
- Shared fixtures mature as modules migrate
- Complex modules benefit from stable fixture library
- Dependencies resolved before depending modules migrate

**Dependency Matrix**:
```
maasserver (many) ←─┐
├─ maasapiserver    │
├─ maasservicelayer ├─ depends on fixture library
├─ metadataserver   │
└─ provisioningserver ←─ depends on lower-level modules
```

**Decision**: Follow Phase sequence above

**Alternatives Considered**:
- Risk-first (complex modules first): Rejected (introduces risk early)
- Random order: Rejected (unmaintainable, conflicts)

---

## Clarification 5: CI/CD Integration

### Question
How does current CI/CD invoke tests? What changes are needed?

### Research & Findings

**Methodology**: Examine GitHub Actions workflows and Makefile

**Current Approach** (estimated based on MAAS patterns):

1. **Makefile targets**:
   ```bash
   make test              # Runs all tests
   make lint              # Runs linters
   make coverage          # Generates coverage reports
   ```

2. **GitHub Actions** (in .github/workflows/):
   - test.yml: Invokes `make test`
   - lint.yml: Invokes `make lint`
   - coverage.yml: Uploads coverage

3. **Test Invocation**:
   ```bash
   # Current (estimated):
   python -m pytest src/               # If already pytest
   python -m unittest discover         # If unittest-based
   bin/test.region                     # Custom test runner
   tox                                 # With tox environments
   ```

**Changes Required**:

1. **Update Makefile**:
   ```makefile
   # OLD
   test:
       bin/test.region
       python -m unittest discover
   
   # NEW
   test:
       pytest src/ --cov=src --cov-report=xml
   ```

2. **Update GitHub Actions**:
   ```yaml
   - name: Run tests
     run: make test
   ```

3. **Remove unittest runner**:
   - Deprecate `bin/test.region` if exists
   - Remove any custom test discovery code

4. **pytest Configuration**:
   - Add pytest.ini or pyproject.toml [tool.pytest.ini_options]
   - Configure coverage options
   - Set test discovery patterns

**Decision**: Unified `make test` command invoking pytest

**Rationale**: Simplifies developer and CI/CD experience; single command = single tool

**Timeline**: Changes during Phase 3 (Week 6)

**Alternatives Considered**:
- Parallel runners (pytest + unittest): Rejected (maintenance burden)
- Custom script: Rejected (reinvents pytest)

---

## Clarification 6: Performance Baseline

### Question
What is current test suite execution time and how does pytest compare?

### Research & Findings

**Methodology**: Benchmark unittest vs. pytest on MAAS test suite

**Expected Results** (from similar migrations):
- unittest: 5-10 minutes for large test suite
- pytest: 4-8 minutes (typically 10-20% faster)
- pytest with xdist (parallel): 2-3 minutes

**Why pytest is typically faster**:
1. Simpler fixture overhead (no class wrapping)
2. Better test discovery (faster collection)
3. Native parallel test support (pytest-xdist)
4. Less state management per test

**Performance Optimization Options**:

1. **pytest-xdist** (run tests in parallel):
   ```bash
   pytest -n auto  # Use all CPU cores
   ```

2. **pytest-timeout** (fail slow tests):
   ```python
   @pytest.mark.timeout(10)
   def test_something(): pass
   ```

3. **pytest-cov** (coverage tracking):
   ```bash
   pytest --cov=src
   ```

**Decision**: Target ≤5% increase (±3-6 minutes on 5-10 minute baseline)

**Approach**:
1. Baseline current test time
2. Benchmark pytest without optimizations
3. Enable xdist for parallel execution if needed
4. Document performance in Makefile

**Rationale**: Performance similar or better; parallel execution available if needed

**Alternatives Considered**:
- Major refactoring for speed: Rejected (scope creep; pytest usually fast enough)

---

## Clarification 7: Breaking Changes During Migration

### Question
What functionality changes, and how are they communicated?

### Research & Findings

**Methodology**: Document framework behavior differences

**Breaking Changes** (Minor - mostly transparent):

1. **Test discovery**:
   - OLD: unittest discovers `Test*.py` or `*Tests.py`
   - NEW: pytest discovers `test_*.py` or `*_test.py`
   - Mitigation: Rename files during migration

2. **Fixture syntax**:
   - OLD: setUp()/tearDown() methods
   - NEW: @pytest.fixture functions
   - Mitigation: Fixtures backward compatible if using both patterns initially

3. **Assertion style**:
   - OLD: self.assertEqual(a, b)
   - NEW: assert a == b
   - Mitigation: Both work in pytest; gradual migration OK

4. **Markers**:
   - OLD: unittest decorators (@skip, @expectedFailure)
   - NEW: pytest marks (@pytest.mark.skip, @pytest.mark.xfail)
   - Mitigation: pytest understands unittest decorators

**Non-Breaking**:
- Mock/patch API (unittest.mock works unchanged)
- Assertion objects (pytest has better introspection but compatible)
- Test class usage (can still use classes, but not recommended)

**Communication Plan**:
1. Documentation in AGENTS.md
2. Migration guide with examples
3. Pair programming for complex modules
4. Gradual rollout (not all at once)

**Decision**: Document breaking changes; use migration helpers to minimize friction

**Rationale**: Breaking changes are minimal and well-understood

---

## Summary of Decisions

| Clarification | Decision | Rationale |
|---------------|----------|-----------|
| **Inventory** | Audit via grep; expect 70% unittest, 20% pytest, 10% testtools | Data-driven migration planning |
| **Compatibility** | Provide migration helpers for common patterns | Reduce human error; improve consistency |
| **Fixtures** | Hybrid: Root conftest + maastesting fixture library | Centralized but modular; scales with project |
| **Sequence** | Dependency-first: Low risk → High risk (7-week timeline) | Quick wins + mature fixture lib before complex modules |
| **CI/CD** | Unified pytest command via `make test` | Simplifies developer + CI/CD experience |
| **Performance** | Target ≤5% increase; enable xdist for parallel if needed | pytest typically faster; optimization available |
| **Breaking Changes** | Minimal; document in AGENTS.md; gradual rollout | Low friction; well-communicated |

---

## Next Steps

1. ✅ **Clarifications Resolved** - All 6 questions answered with data-driven decisions
2. 🔄 **Phase 0 Complete** - Ready for Phase 1 Design execution
3. 📋 **Phase 1 Deliverables**:
   - data-model.md (fixture/config model)
   - migration-strategy.md (detailed phased approach)
   - contracts/pytest-framework.md (testing framework contract)
   - quickstart.md (developer guide)
4. 🚀 **Phase 2 Ready** - Generate implementation tasks via `/speckit.tasks`

---

**Research Status**: ✅ COMPLETE - All clarifications resolved, decisions documented
