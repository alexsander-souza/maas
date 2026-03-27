# Implementation Plan: Standardize Test Frameworks - Python pytest Migration

**Branch**: `6685-single-test-framework` | **Date**: 2026-03-27 | **Spec**: [specs/6685-single-test-framework/spec.md](../spec.md)

**Input**: Feature specification from `/specs/6685-single-test-framework/spec.md`

## Summary

Consolidate MAAS Python testing to a single framework standard: **pytest**. Current Python codebase uses multiple testing frameworks (pytest, unittest, testtools), causing inconsistency in test structure, syntax, and execution. This initiative standardizes on pytest exclusively, providing a unified developer experience and reducing onboarding friction.

**Scope for this plan**: Focus on Python code migration to pytest (User Story 1 priority). Go testing standardization (P2) and enforcement/documentation (P3) are separate implementation phases.

## Technical Context

**Language/Version**: Python 3.9+ (per pyproject.toml)  
**Primary Dependencies**: pytest (exclusive test framework), existing test infrastructure  
**Storage**: N/A (this is a test framework consolidation, not data-persistence feature)  
**Testing**: pytest (being standardized - the feature itself)  
**Target Platform**: Linux (MAAS runs on Linux; Python tests run on any platform)  
**Project Type**: Large distributed system (MAAS) with multi-module Python codebase  
**Performance Goals**: Test suite execution time must not increase by more than 5% after migration  
**Constraints**: Must maintain backward compatibility with existing test infrastructure; CI/CD should continue working without developer setup changes  
**Scale/Scope**: MAAS has ~50+ Python modules across src/ directory; estimated 5000+ existing test files; phased migration required

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Constitution Principle Alignment

✅ **I. Code Modularity & Testability**: Migration enables independent test execution per module (pytest's `-k` and `--collect-only` support)

✅ **II. Explicit Over Implicit**: pytest's configuration and test discovery are explicit and transparent (conftest.py, pytest.ini, pyproject.toml)

✅ **III. Code Quality & Naming**: pytest test names map directly to function names; no hidden test discovery like unittest

✅ **IV. Security by Default**: pytest has security-focused plugins for credential detection; no inherent security risks from migration

✅ **VII. Testing Discipline**: pytest enforces meaningful assertions; fixtures are explicit and reusable; no boilerplate required

✅ **VIII. Collaboration & Code Review**: Standard pytest patterns documented in AGENTS.md; code reviews can check for pytest compliance

### Gate Status: ✅ PASSED

**No violations detected**. Migration to pytest aligns with all relevant Constitution principles. No violations require justification.

---

## Project Structure

### Documentation (this feature)

```text
specs/6685-single-test-framework/
├── spec.md                          # Feature specification ✅ COMPLETE
├── plan.md                          # This file (Phase 0-1 deliverable)
├── research.md                      # Phase 0: Resolve clarifications
├── data-model.md                    # Phase 1: Test framework configuration model
├── migration-strategy.md            # Phase 1: Detailed migration approach
├── checklists/
│   └── requirements.md              # Quality validation ✅ COMPLETE
└── contracts/
    └── pytest-framework.md          # Testing framework contract
```

### Source Code (MAAS Repository)

```text
src/
├── maasserver/              # Legacy Django tests (unittest → pytest)
├── maasapiserver/           # FastAPI v3 API tests (pytest → pytest)
├── maasservicelayer/        # Service layer tests (pytest → pytest)
├── maastesting/             # Test utilities (fixtures, helpers)
├── maascommon/              # Common utilities tests
├── provisioningserver/      # Rack controller tests (Twisted + unittest)
├── metadataserver/          # Metadata service tests
├── maascli/                 # CLI tests
├── apiclient/               # API client tests
└── perftests/               # Performance tests

test_configuration/
├── conftest.py              # Shared pytest configuration
├── pytest.ini               # pytest settings
├── fixtures/                # Common fixtures (database, mocks, etc.)
└── plugins/                 # Custom pytest plugins (if needed)

Makefile                      # Updated with unified pytest commands
pyproject.toml               # Updated with pytest configuration
```

---

## Phase 0: Outline & Research

### Clarifications to Resolve

1. **Current test framework inventory**: How many test files use unittest vs. pytest vs. testtools?
   - Research Task: Audit codebase for test framework usage

2. **Legacy module compatibility**: Which modules have deep dependencies on unittest-specific patterns?
   - Research Task: Identify unittest.TestCase usage patterns and refactoring requirements

3. **pytest fixture strategy**: Should common fixtures be centralized in conftest.py or distributed per module?
   - Research Task: Best practices for pytest fixture organization in large projects

4. **Migration sequencing**: Which modules should migrate first (dependencies-first vs. risk-first)?
   - Research Task: Dependency analysis of test modules

5. **CI/CD integration**: How does current CI/CD invoke tests? What changes are needed?
   - Research Task: Current test invocation patterns in GitHub Actions and other runners

6. **Performance baseline**: What is current test suite execution time and how does pytest compare?
   - Research Task: Performance comparison (unittest runner vs. pytest)

### Research Output: research.md

Will contain:
- **Codebase Inventory**: Framework distribution by module
- **Migration Blockers**: unittest patterns that require special handling
- **Fixture Strategy**: Recommended conftest.py and fixture organization
- **Migration Sequence**: Dependency-based ordering of modules
- **CI/CD Changes**: Required updates to test invocation
- **Performance Data**: Baseline metrics and expected improvements

---

## Phase 1: Design & Contracts

### 1. Data Model (data-model.md)

**Test Framework Configuration Model**:

```
TestFrameworkConfig:
  language: "python"
  framework: "pytest"
  version: ">=7.0.0"  # pytest minimum version
  config_files:
    - pytest.ini
    - pyproject.toml
    - conftest.py

ModuleMigrationStatus:
  module_name: string
  current_framework: "pytest" | "unittest" | "testtools"
  target_framework: "pytest"
  test_file_count: integer
  estimated_effort: "low" | "medium" | "high"
  blockers: string[]
  status: "not_started" | "in_progress" | "blocked" | "complete"
  migration_date: date | null

MigrationPhase:
  phase_number: integer
  modules: string[]
  dependencies: integer[]  # preceding phase numbers
  estimated_duration: string
```

### 2. Interface Contracts (contracts/pytest-framework.md)

**Testing Framework Contract** for MAAS Python code:

```
## Contract: pytest-based Testing for MAAS Python

### Purpose
Establish single, unified testing framework for all Python code in MAAS

### Obligations for Test Writers
1. All new tests MUST use pytest (not unittest, testtools)
2. Tests MUST be discoverable by pytest's default discovery (test_*.py or *_test.py)
3. Fixtures MUST use @pytest.fixture decorator
4. Assertions MUST use native Python assert (not unittest.TestCase.assert*)
5. Setup/teardown MUST use pytest fixtures, not setUp/tearDown methods
6. Parametrization MUST use @pytest.mark.parametrize
7. Mocking MUST use unittest.mock or pytest-mock, not testtools
8. Database tests MUST use provided fixtures (db_connection, db_transaction)
9. Configuration MUST be in conftest.py or pytest.ini, not scattered in test files
10. Tests MUST pass with: pytest [module_path] (no custom runners)

### Obligations for Framework/Infrastructure
1. MUST provide shared conftest.py with common fixtures
2. MUST provide database fixtures (connection, transaction, factories)
3. MUST provide mock/patch utilities in conftest.py
4. MUST support running tests per-module: pytest src/module_name/tests/
5. MUST support running full suite: pytest (from repo root)
6. MUST provide clear error messages for framework violations
7. MUST maintain backward compatibility during migration period
8. MUST integrate with CI/CD: `make test` invokes pytest
9. MUST document fixture usage in AGENTS.md

### Breaking Changes During Migration
- unittest.TestCase subclasses will be gradually converted to pytest-style
- Some fixtures may change during centralization phase
- test_*.py naming convention enforced (*.test.py → test_*.py)

### Success Metrics
- 100% of new Python tests use pytest
- 100% of CI/CD test invocations use pytest
- All existing tests pass under pytest
- Test execution time ≤ 5% increase

### Supported Platforms
- Python 3.9, 3.10, 3.11, 3.12+
- Linux (primary), macOS (for development)
```

### 3. Migration Strategy Document (migration-strategy.md)

**High-level migration approach**:

1. **Phase 1a - Foundation** (Week 1)
   - Set up pytest configuration (pytest.ini, pyproject.toml entries)
   - Create shared conftest.py with common fixtures
   - Install pytest and plugins (pytest-cov, pytest-xfail, pytest-timeout)
   - Update Makefile to include pytest commands alongside unittest runner

2. **Phase 1b - Test Coverage Audit** (Week 1-2)
   - Audit all Python test files by module
   - Identify unittest.TestCase subclasses and dependencies
   - Identify testtools usage and migration path
   - Document per-module effort estimates

3. **Phase 2 - Module Migration (Dependency-Ordered)** (Weeks 2-6)
   - Migrate modules with no dependencies on other test modules first
   - For each module:
     - Convert test file structure (class-based → function-based)
     - Replace unittest assertions with assert statements
     - Convert setUp/tearDown to pytest fixtures
     - Run tests: `pytest src/module/tests/` (must pass)
   - Update related documentation and fixtures

4. **Phase 3 - CI/CD Integration** (Week 6)
   - Update GitHub Actions workflows to use pytest
   - Verify all tests pass in CI/CD
   - Remove unittest runner from CI/CD
   - Update Makefile `test` target to use only pytest

5. **Phase 4 - Documentation & Cleanup** (Week 7)
   - Update AGENTS.md with pytest standard
   - Add pytest best practices guide
   - Remove unittest-related docs
   - Archive or remove testtools-related code

### 4. Quickstart Guide (quickstart.md)

**For developers: Writing and Running pytest Tests**

```
## Quick Start: pytest Testing in MAAS

### Writing a Test

```python
import pytest
from mymodule import function_under_test

def test_function_basic():
    """Test basic functionality."""
    result = function_under_test("input")
    assert result == "expected_output"

@pytest.mark.parametrize("input,expected", [
    ("a", "A"),
    ("b", "B"),
])
def test_function_parametrized(input, expected):
    """Test with multiple inputs."""
    assert function_under_test(input) == expected

@pytest.fixture
def setup_data():
    """Fixture for test setup."""
    return {"data": "value"}

def test_with_fixture(setup_data):
    """Test using a fixture."""
    assert setup_data["data"] == "value"
```

### Running Tests

```bash
# All tests
make test

# Specific module
pytest src/maasserver/tests/

# Specific test file
pytest src/maasserver/tests/test_machines.py

# Specific test
pytest src/maasserver/tests/test_machines.py::test_machine_creation

# With coverage
pytest --cov=src src/

# Verbose output
pytest -v src/module/tests/

# Stop on first failure
pytest -x src/
```

### Using Fixtures

Fixtures are defined in `conftest.py` and used as function parameters:

```python
def test_with_database(db_connection):
    """Access database through fixture."""
    result = db_connection.execute("SELECT * FROM users")
    assert len(result) > 0
```

Common fixtures available:
- `db_connection`: Database connection
- `db_transaction`: Transaction-scoped database
- `mock_service`: Mocked service layer
- `api_client`: Test API client

See conftest.py for full list and documentation.
```

### 5. Agent Context Update

Run: `.specify/scripts/bash/update-agent-context.sh copilot`

This updates the AI agent context with:
- pytest as standard Python testing framework
- Configuration locations (pytest.ini, conftest.py, pyproject.toml)
- Testing patterns and fixtures
- Migration approach for legacy code

---

## Phase 2: Validation

### Constitution Re-Check (Post-Design)

✅ **Principles verified post-design**:
- Modularity: pytest fixtures enable module-independent testing
- Explicitness: pytest.ini and conftest.py make framework choices transparent
- Code Quality: pytest's assertion introspection improves debugging
- Testing Discipline: pytest encourages meaningful assertions without boilerplate

✅ **No new violations introduced**

---

## Implementation Timeline

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 0: Research | Week 1 | Codebase audit, migration strategy, dependency analysis |
| Phase 1a: Setup | Week 1 | pytest config, conftest.py, Makefile updates |
| Phase 1b: Audit | Week 1-2 | Module-by-module migration estimates |
| Phase 2: Migration | Weeks 2-6 | Convert modules in dependency order |
| Phase 3: CI/CD | Week 6 | GitHub Actions updates, full test validation |
| Phase 4: Cleanup | Week 7 | Documentation, final validation |

---

## Risks & Mitigation

| Risk | Mitigation |
|------|-----------|
| **Long migration tail**: Some modules may be complex to migrate | Phased approach; migrate low-risk modules first; provide helpers for common patterns |
| **Test failures during migration**: Tests may fail in pytest format | Parallel testing during transition; fixtures ensure compatibility |
| **CI/CD downtime**: Test runner changes may break builds | Maintain both runners in parallel; gradual cutover |
| **Performance regression**: pytest slower than unittest | Benchmark and optimize; pytest typically faster in practice |
| **Developer friction**: Developers unfamiliar with pytest | Comprehensive quickstart; in-repo examples; training materials |

---

## Dependencies & Blockers

**External**: None

**Internal**:
- Fixture library must be finalized before module migration starts
- conftest.py structure must be agreed upon before Phase 2
- CI/CD changes require coordination with DevOps/Platform team

---

## Success Criteria (from spec)

- ✅ All Python test files use pytest (100% compliance)
- ✅ Full test suite execution time ≤ 5% increase
- ✅ Zero framework-related CI/CD failures
- ✅ 100% of new test code uses pytest (post-migration)
- ✅ Developer onboarding documentation updated

---

## Next Steps

1. **Phase 0 Execution**: Run research to resolve clarifications
2. **Stakeholder Review**: Present plan to core team
3. **Phase 1 Execution**: Set up pytest infrastructure
4. **Task Breakdown**: Use `/speckit.tasks` to generate implementation tasks
5. **Implementation**: Execute migration tasks in dependency order

---

## Appendix: pytest Configuration Template

### pytest.ini (or pyproject.toml [tool.pytest.ini_options])

```ini
[pytest]
minversion = 7.0
addopts = -v --strict-markers --tb=short
testpaths = src
python_files = test_*.py *_test.py
python_classes = Test*
python_functions = test_*
markers =
    slow: marks tests as slow
    integration: marks tests as integration tests
    db: marks tests requiring database
    requires_admin: marks tests requiring admin privileges
```

### conftest.py (Root Level)

```python
import pytest
from mymodule.testing import fixtures

@pytest.fixture
def db_connection():
    """Provide database connection for tests."""
    # Implementation

@pytest.fixture
def api_client():
    """Provide API test client."""
    # Implementation
```

---

**Plan Status**: ✅ Ready for Phase 0 Research Execution
