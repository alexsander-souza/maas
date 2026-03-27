# Testing Framework Contract: pytest for MAAS Python

**Feature**: Standardize Test Frameworks - Python pytest Migration  
**Phase**: Phase 1 Design  
**Date**: 2026-03-27

---

## Contract Overview

This contract establishes the testing framework standard for all Python code in MAAS. It defines obligations for:
1. **Test Writers** - Developers writing or migrating tests
2. **Test Infrastructure** - Framework and fixture maintainers
3. **CI/CD Systems** - Test execution and reporting

---

## Part 1: Obligations for Test Writers

### Framework & Discovery

**O1.1**: All new Python test files MUST use pytest (not unittest, testtools)
- **Applies to**: Any file named `test_*.py` or `*_test.py`
- **Verification**: Codebase grep for `import unittest` in test files (should be 0)
- **Exception**: Legacy migration period (until Phase 5 complete)

**O1.2**: Tests MUST be discoverable by pytest's default discovery mechanism
- **Requirement**: File naming must match `test_*.py` or `*_test.py` pattern
- **Requirement**: Test functions/classes must match discovery pattern (see Configuration)
- **Verification**: `pytest --collect-only src/` must discover all tests without errors

**O1.3**: Test files MUST NOT import unittest.TestCase or testtools
- **Applies to**: All new test files and migrated test files
- **Exception**: During migration transition, existing unittest classes may coexist
- **Final State**: Zero unittest.TestCase subclasses in MAAS codebase

---

### Fixtures & Setup/Teardown

**O2.1**: Test setup/teardown MUST use pytest fixtures, not setUp/tearDown methods
- **Old Pattern (reject)**:
  ```python
  class TestUser(unittest.TestCase):
      def setUp(self): self.user = User()
      def tearDown(self): self.user.delete()
  ```
- **New Pattern (accept)**:
  ```python
  @pytest.fixture
  def user():
      user = User()
      yield user
      user.delete()
  ```
- **Verification**: No setUp/tearDown methods in test files (grep -r "def setUp\|def tearDown")

**O2.2**: Fixtures MUST use `@pytest.fixture` decorator
- **Requirement**: All setup/cleanup code must be in fixtures, not test methods
- **Benefit**: Automatic cleanup, parameterization, scope control
- **Verification**: Fixture definitions must use @pytest.fixture

**O2.3**: Fixtures MUST declare their dependencies explicitly
- **Pattern**:
  ```python
  @pytest.fixture
  def db_connection(settings):  # settings is a dependency
      conn = create_connection(settings)
      yield conn
      conn.close()
  ```
- **Benefit**: Clear execution order; pytest resolves dependencies automatically
- **Verification**: Fixture parameters must reference defined fixtures

**O2.4**: Database-related tests MUST use provided database fixtures
- **Available Fixtures**:
  - `db_connection` - raw database connection (function-scoped, no cleanup)
  - `db_transaction` - transaction-scoped database (auto-rollback after test)
  - `django_client` - Django test client with database access
- **Requirement**: Tests must use fixture rather than manual database setup
- **Verification**: Tests must not call `database.setup()` or `database.teardown()` manually

**O2.5**: Mock/patch operations MUST use pytest-compatible patterns
- **Preferred**: `unittest.mock` (built-in, works in pytest)
- **Alternative**: `pytest-mock` plugin (provides `mocker` fixture)
- **Pattern**:
  ```python
  def test_with_mock(mocker):  # pytest-mock fixture
      mock_func = mocker.patch('module.function')
      # OR
      with unittest.mock.patch('module.function') as mock_func:
          pass
  ```
- **Requirement**: Must not use testtools.mock or mocking patterns specific to unittest
- **Verification**: No testtools imports in test files

---

### Assertions

**O3.1**: Tests MUST use native Python assert statements, not unittest assertion methods
- **Old Pattern (reject)**:
  ```python
  self.assertEqual(actual, expected)
  self.assertTrue(condition)
  self.assertRaises(ValueError, func)
  ```
- **New Pattern (accept)**:
  ```python
  assert actual == expected
  assert condition
  with pytest.raises(ValueError):
      func()
  ```
- **Benefit**: Simpler code; pytest provides better assertion introspection
- **Verification**: No `self.assert*` calls in test files (grep -r "self\.assert")

**O3.2**: Complex assertions MUST use pytest.raises() context manager
- **Pattern**:
  ```python
  with pytest.raises(ValueError, match="invalid input"):
      function_that_raises()
  ```
- **Requirement**: Preferred over unittest.TestCase.assertRaises()
- **Verification**: `pytest.raises()` usage in exception test files

**O3.3**: Parametrized tests MUST use @pytest.mark.parametrize
- **Pattern**:
  ```python
  @pytest.mark.parametrize("input,expected", [
      ("a", "A"),
      ("b", "B"),
  ])
  def test_function(input, expected):
      assert function(input) == expected
  ```
- **Benefit**: DRY principle; one test function, multiple data points
- **Verification**: No manual loops in test code; use parametrize instead

---

### Test Markers

**O4.1**: Tests requiring specific resources MUST use appropriate markers
- **Available Markers**:
  - `@pytest.mark.db` - Requires database access
  - `@pytest.mark.slow` - Test takes >5 seconds
  - `@pytest.mark.integration` - Integration test (tests multiple components)
  - `@pytest.mark.requires_admin` - Requires admin privileges
  - `@pytest.mark.django_db` - Django-specific database test
- **Pattern**:
  ```python
  @pytest.mark.db
  def test_database_operation(db_transaction):
      assert db_transaction.execute("SELECT 1") is not None
  ```
- **Benefit**: Tests can be filtered/skipped based on capabilities
- **Verification**: Proper markers on database and slow tests

**O4.2**: Tests MUST NOT be skipped without justification
- **Acceptable Skips**:
  ```python
  @pytest.mark.skip(reason="Feature not yet implemented (MAAS-1234)")
  def test_future_feature(): pass
  
  @pytest.mark.skipif(sys.version_info < (3, 10), reason="Requires Python 3.10+")
  def test_new_syntax(): pass
  ```
- **Requirement**: Skip reason MUST reference issue tracker or version constraint
- **Verification**: All skipped tests have documented reasons

---

### Configuration & Organization

**O5.1**: Test configuration MUST be in conftest.py, pytest.ini, or pyproject.toml
- **Locations**:
  - Root `conftest.py` - Shared fixtures for all modules
  - Module `conftest.py` - Module-specific fixtures
  - `pytest.ini` - pytest settings (deprecated in favor of pyproject.toml)
  - `pyproject.toml [tool.pytest.ini_options]` - Modern configuration
- **Requirement**: No test configuration in individual test files
- **Verification**: No `pytest.ini` or `[tool.pytest]` sections in test_*.py files

**O5.2**: Test helpers and utilities MUST be in src/maastesting or module-specific utilities
- **Pattern**:
  ```python
  # In src/maastesting/fixtures.py
  @pytest.fixture
  def api_client():
      return TestClient(app)
  
  # In conftest.py
  from maastesting.fixtures import api_client
  ```
- **Requirement**: Test utilities should be reusable across modules
- **Verification**: No duplicate fixture definitions across modules

**O5.3**: Test files MUST NOT have relative imports; use absolute imports
- **Old (reject)**:
  ```python
  from ..module import function
  ```
- **New (accept)**:
  ```python
  from maasserver.module import function
  ```
- **Benefit**: Clearer imports; easier to refactor
- **Verification**: No relative imports starting with `..` in test files

---

## Part 2: Obligations for Test Infrastructure Maintainers

### Framework Maintenance

**I1.1**: The test framework MUST support all Python versions specified in pyproject.toml
- **Current**: Python 3.9+
- **Requirement**: pytest configuration must work on all supported versions
- **Verification**: CI/CD matrix tests all versions

**I1.2**: Fixture library MUST be documented and versioned
- **Location**: `src/maastesting/fixtures/`
- **Documentation**: Docstrings for every fixture with examples
- **Versioning**: Fixture breaking changes require migration guide
- **Verification**: `pytest --fixtures` should show all fixtures with full documentation

**I1.3**: Common fixtures MUST be available and working across all modules
- **Required Fixtures**:
  - `db_connection` - Database connection
  - `db_transaction` - Transaction-scoped database
  - `api_client` - FastAPI/REST test client
  - `mock_service` - Mocked service layer
  - `settings` - Test configuration
  - `tmp_directory` - Temporary directory
- **Verification**: All fixtures pass in multiple modules (cross-module integration test)

**I1.4**: Fixture scope MUST match test requirements
- **Scopes**:
  - `function` - Reset before/after each test (default)
  - `class` - Shared across test class methods
  - `module` - Shared across module tests
  - `session` - Shared across entire test run
- **Requirement**: Database fixtures MUST be function-scoped with cleanup
- **Verification**: Fixture scope correctly specified; no state leakage between tests

---

### Configuration & CI/CD

**I2.1**: pytest configuration MUST support both full suite and module-specific execution
- **Pattern**:
  ```bash
  pytest                              # Full suite
  pytest src/maasserver/tests/        # Single module
  pytest src/ -m db                   # Only database tests
  pytest src/ -k test_machine         # Only tests matching pattern
  ```
- **Verification**: All invocation patterns work without errors

**I2.2**: Test discovery MUST NOT have conflicts or surprises
- **Requirement**: Default pytest discovery must find all tests
- **Requirement**: No slow test discovery (must complete in <10 seconds for test collection)
- **Verification**: `pytest --collect-only` completes in <10s with no conflicts

**I2.3**: pytest output MUST be clear and actionable
- **Requirements**:
  - Failed tests clearly show assertion details
  - Skipped tests show reason for skip
  - Collection errors are immediately visible
  - Coverage reports are generated with `--cov` flag
- **Verification**: Pytest output is readable and helpful (not noise)

**I2.4**: CI/CD MUST invoke pytest consistently
- **Pattern** (in GitHub Actions, Makefile, etc.):
  ```bash
  make test               # Invokes pytest with standard options
  pytest --cov=src       # With coverage
  pytest -x src/         # Stop on first failure
  pytest --tb=short src/ # Short traceback format
  ```
- **Requirement**: Single source of truth for test invocation (Makefile)
- **Verification**: `make test` and CI/CD use identical pytest command

**I2.5**: Performance MUST NOT regress significantly
- **Baseline**: Current test suite execution time (to be measured)
- **Target**: ≤5% increase in execution time after migration
- **Optimization**: Enable pytest-xdist for parallel execution if needed
- **Verification**: Performance benchmarks tracked in CI/CD

---

### Migration Support

**I3.1**: Migration helpers MUST be provided for common patterns
- **Example Helpers**:
  ```python
  # In src/maastesting/migration.py
  def convert_unittest_to_pytest(test_class):
      """Convert unittest.TestCase to pytest functions."""
      # Conversion logic
  ```
- **Requirement**: Clear examples for common conversions
- **Verification**: Migration guide includes runnable examples

**I3.2**: Backward compatibility fixtures MUST be provided during transition
- **Pattern**:
  ```python
  # conftest.py - for backward compatibility during migration
  @pytest.fixture
  def unittest_test_case():
      """Compatibility fixture for unittest.TestCase."""
      return FakeTestCase()
  ```
- **Duration**: Phase 5 completion (end of complex module migration)
- **Verification**: Hybrid unittest+pytest tests pass during transition

---

## Part 3: Obligations for CI/CD Systems

### Test Execution

**C1.1**: Tests MUST be invoked via `make test` command
- **Implementation**:
  ```makefile
  test:
      pytest src/ --cov=src --cov-report=xml --tb=short
  ```
- **Requirement**: Makefile target is single source of truth
- **Verification**: GitHub Actions calls `make test`

**C1.2**: Test failures MUST prevent merge to main branch
- **GitHub Actions**: Status check "Tests" required before merge
- **Requirement**: CI/CD must pass before PR merge
- **Verification**: GitHub branch protection rules enforce this

**C1.3**: Coverage reports MUST be generated and tracked
- **Configuration**:
  ```bash
  pytest --cov=src --cov-report=html --cov-report=xml
  ```
- **Requirement**: Coverage ≥80% (or project standard)
- **Verification**: Coverage badge or report uploaded to PR

**C1.4**: Test execution time MUST be monitored
- **Baseline**: Measure before migration (estimated 5-10 minutes)
- **Target**: ≤5% increase post-migration
- **Optimization**: Optional pytest-xdist for parallel execution
- **Verification**: Execution time logged in CI/CD

---

### Reporting & Notifications

**C2.1**: Test failure reports MUST be clear and actionable
- **Information**:
  - Failed test name
  - Assertion that failed
  - Expected vs. actual values
  - Stack trace (short format recommended)
- **Notification**: Comments on PR with failure details
- **Verification**: Developers can fix failures from CI/CD report

**C2.2**: Flaky tests MUST be identified and tracked
- **Detection**: Re-run failed tests automatically
- **Tracking**: Log flaky tests for investigation
- **Requirement**: Flaky tests MUST be fixed or skipped with reason
- **Verification**: No persistent flaky tests in CI/CD

---

## Migration Transition Period

### Overlap Support (Phases 1-5)

During migration (approximately 7 weeks), the following compatibility is maintained:

**Allowed Coexistence**:
- ✅ pytest tests (new standard)
- ✅ unittest.TestCase subclasses (being migrated)
- ✅ Mixed conftest.py + setUp/tearDown (during transition)
- ❌ testtools patterns (should be eliminated immediately)

**CI/CD Behavior**:
- Pytest runs all tests (pytest understands unittest.TestCase)
- Custom test runner (if exists) gradually deprecated
- Coverage maintained across both patterns

**Migration Completion**:
- Phase 5 End: All unittest.TestCase converted or removed
- Phase 6: unittest references removed from codebase
- Phase 7: Legacy documentation archived

---

## Breaking Changes Summary

| Change | Old Behavior | New Behavior | Timeline | Mitigation |
|--------|--------------|--------------|----------|-----------|
| **Test Discovery** | Test*.py pattern | test_*.py pattern | Phase 2-5 | Rename files during migration |
| **Setup/Teardown** | setUp/tearDown methods | @pytest.fixture | Phase 2-5 | Migration helpers provided |
| **Assertions** | self.assertEqual(...) | assert ... == ... | Phase 2-5 | Code examples provided |
| **Markers** | @unittest.skip | @pytest.mark.skip | Phase 2-5 | Both understood by pytest |
| **Mocking** | unittest.mock or testtools | unittest.mock | Phase 2-5 | Module swap straightforward |
| **Test Runner** | python -m unittest or custom | pytest | Phase 6 | Simple CLI change |

---

## Contract Compliance Verification

### Automated Checks

**Code Quality Gates**:
```bash
# 1. Framework consistency check
find src -name "test_*.py" -exec grep -l "import unittest" {} \; | wc -l
# Output: 0 (except during Phase 1-5 migration)

# 2. Fixture discovery
pytest --fixtures src/ | grep "fixtures:" | wc -l
# Output: >= 20 (expected shared fixtures)

# 3. Test collection
pytest --collect-only src/ | grep "error" | wc -l
# Output: 0 (no collection errors)

# 4. Performance benchmark
pytest src/ --durations=10
# Output: <5% variance from baseline
```

### Manual Review Checklist (for Code Review)

- [ ] Test file uses `test_*.py` naming
- [ ] Tests use `assert` statements, not `self.assert*`
- [ ] Setup uses `@pytest.fixture`, not `setUp/tearDown`
- [ ] Database tests use `db_transaction` or `db_connection` fixture
- [ ] Mocking uses `unittest.mock` or `pytest-mock`
- [ ] No relative imports (use absolute imports)
- [ ] Slow tests have `@pytest.mark.slow`
- [ ] Database tests have `@pytest.mark.db`
- [ ] Parametrized tests use `@pytest.mark.parametrize`
- [ ] Skipped tests have documented reason

---

## Contract Status

**Effective Date**: 2026-03-27 (Start of Phase 1)  
**Enforcement Timeline**: Phased (7-week migration period)  
**Final Compliance Date**: End of Phase 5 (approximately Week 7)

**Status**: ✅ ACTIVE - Approved and ready for implementation

---

**Contract Maintained By**: MAAS Core Team  
**Questions/Clarifications**: See AGENTS.md Testing section or Constitution Section VII (Testing Discipline)
