# Tasks: Standardize Test Frameworks - Python pytest Migration

**Input**: Design documents from `/specs/6685-single-test-framework/`  
**Prerequisites**: plan.md (✓), spec.md (✓), data-model.md (✓), research.md (✓), contracts/ (✓)

**Tests**: Test tasks OPTIONAL - only included for contract validation (NOT requested in spec)

**Organization**: Tasks grouped by user story to enable independent implementation and testing of each story.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3) or foundational component
- Include exact file paths in all descriptions

---

## Phase 1: Setup & Infrastructure (Foundation)

**Purpose**: Project initialization and pytest configuration baseline

- [ ] T001 Create pytest configuration file `pyproject.toml [tool.pytest.ini_options]` section with:
  - minversion = 7.0
  - testpaths = src
  - python_files = test_*.py
  - python_classes = Test*
  - python_functions = test_*
  - markers for: db, slow, integration, requires_admin, django_db

- [ ] T002 Create root `conftest.py` with imports from maastesting.fixtures

- [ ] T003 Create `src/maastesting/fixtures/__init__.py` (empty module file)

- [ ] T004 [P] Create `src/maastesting/fixtures/database.py` with fixtures:
  - `@pytest.fixture` def db_connection(settings) → raw database connection
  - `@pytest.fixture` def db_transaction(db_connection) → transaction-scoped, auto-rollback
  - Docstrings with usage examples

- [ ] T005 [P] Create `src/maastesting/fixtures/api.py` with fixtures:
  - `@pytest.fixture` def api_client() → FastAPI TestClient instance
  - `@pytest.fixture` def django_client(db_transaction) → Django test client
  - Docstrings with usage examples

- [ ] T006 [P] Create `src/maastesting/fixtures/mocking.py` with fixtures:
  - `@pytest.fixture` def mock_service(mocker) → Mocked service layer
  - `@pytest.fixture` def settings() → Test configuration object
  - Docstrings with usage examples

- [ ] T007 [P] Create `src/maastesting/fixtures/utilities.py` with fixtures:
  - `@pytest.fixture` def tmp_directory(tmp_path) → Temporary directory fixture
  - `@pytest.fixture` def logged_in_user(db_transaction) → Test user object with auth
  - Docstrings with usage examples

- [ ] T008 Create `src/maastesting/conftest.py` importing and re-exporting all fixtures from fixtures/ submodules

- [ ] T009 Update `Makefile` with pytest-based test targets:
  ```makefile
  .PHONY: test
  test:
      pytest src/ --cov=src --cov-report=xml --tb=short -v
  
  .PHONY: test-quick
  test-quick:
      pytest src/ -v --tb=line
  
  .PHONY: test-module
  test-module:  # pytest src/<module>/tests/
      pytest $(TARGET) -v
  ```

- [ ] T010 Update `pyproject.toml` [build-system] and [tool.pytest] to reference pytest:
  - Ensure pytest >=7.0.0 in test dependencies
  - Configure test discovery paths
  - Enable coverage tracking

---

## Phase 2: Foundational Baseline (Blocking Prerequisites)

**Purpose**: Establish pytest infrastructure that all user stories depend on

- [ ] T011 Audit codebase for test framework usage (output to `migration-inventory.txt`):
  - Count unittest.TestCase files: `find src -name "test_*.py" -exec grep -l "unittest.TestCase" {} \;`
  - Count pytest files: `find src -name "test_*.py" -exec grep -l "import pytest" {} \;`
  - Count testtools usage: `find src -name "test_*.py" -exec grep -l "testtools" {} \;`
  - Document per-module counts and complexity estimates

- [ ] T012 Create migration strategy document `specs/6685-single-test-framework/migration-strategy.md`:
  - Summarize inventory from T011
  - List modules by migration priority (dependency order)
  - Identify complex patterns requiring special handling
  - Document Django TestCase migration approach
  - Reference pytest-django plugin integration

- [ ] T013 Create pytest documentation `docs/testing/pytest-migration.md`:
  - Writing pytest tests (basic example)
  - Using fixtures (with examples)
  - Running tests (make test, module-specific, pattern matching)
  - Common patterns and best practices
  - Migration guide for unittest → pytest

- [ ] T014 Set up GitHub Actions workflow (if not already configured):
  - `.github/workflows/test.yml` runs `make test`
  - Separate coverage report upload
  - Matrix testing for Python 3.9, 3.10, 3.11, 3.12
  - Set required status check "Tests" before merge

- [ ] T015 Document fixture contracts in `src/maastesting/README.md`:
  - Describe available fixtures (db_connection, api_client, mock_service, etc.)
  - Usage patterns and scopes
  - When to use each fixture
  - Examples for common test patterns
  - Link to pytest documentation

---

## Phase 3: User Story 1 - Consolidate Python Test Framework (Priority: P1)

**Goal**: Migrate Python tests to pytest exclusively; establish pytest as sole testing standard

**Independent Test**: All Python test files use pytest syntax; `make test` executes all tests with 0 framework-related failures

### Tests for User Story 1 (Not requested - skipped per spec)

### Implementation for User Story 1

**Low Risk Module 1: maascommon**

- [ ] T016 [P] [US1] Audit test files in `src/maascommon/tests/`:
  - Count test_*.py files
  - Identify unittest/testtools usage
  - Document assertions to convert
  - Estimated effort for module

- [ ] T017 [P] [US1] Convert `src/maascommon/tests/` to pytest:
  - Rename Test*.py → test_*.py (if needed)
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Replace setUp/tearDown → @pytest.fixture
  - Verify imports (no relative imports)
  - Run: `pytest src/maascommon/tests/ -v` (must pass)

- [ ] T018 [P] [US1] Update imports in migrated maascommon tests:
  - Replace `from unittest import ...` with pytest equivalents
  - Replace `from testtools import ...` with pytest or unittest.mock
  - Verify all imports work with pytest

- [ ] T019 [US1] Validate maascommon test migration:
  - `pytest src/maascommon/tests/ --cov=src/maascommon`
  - Coverage must not decrease
  - All tests pass
  - No collection errors
  - Document completion in migration-inventory.txt

**Low Risk Module 2: maascli**

- [ ] T020 [P] [US1] Audit test files in `src/maascli/tests/`:
  - Count test_*.py files
  - Identify unittest/testtools usage
  - Document assertions to convert
  - Estimated effort for module

- [ ] T021 [P] [US1] Convert `src/maascli/tests/` to pytest:
  - Rename Test*.py → test_*.py (if needed)
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Replace setUp/tearDown → @pytest.fixture
  - Verify imports (no relative imports)
  - Run: `pytest src/maascli/tests/ -v` (must pass)

- [ ] T022 [P] [US1] Update imports in migrated maascli tests:
  - Replace `from unittest import ...` with pytest equivalents
  - Replace `from testtools import ...` with pytest or unittest.mock
  - Verify all imports work with pytest

- [ ] T023 [US1] Validate maascli test migration:
  - `pytest src/maascli/tests/ --cov=src/maascli`
  - Coverage must not decrease
  - All tests pass
  - No collection errors
  - Document completion in migration-inventory.txt

**Low Risk Module 3: apiclient**

- [ ] T024 [P] [US1] Audit test files in `src/apiclient/tests/`:
  - Count test_*.py files
  - Identify unittest/testtools usage
  - Document assertions to convert
  - Estimated effort for module

- [ ] T025 [P] [US1] Convert `src/apiclient/tests/` to pytest:
  - Rename Test*.py → test_*.py (if needed)
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Replace setUp/tearDown → @pytest.fixture
  - Verify imports (no relative imports)
  - Run: `pytest src/apiclient/tests/ -v` (must pass)

- [ ] T026 [P] [US1] Update imports in migrated apiclient tests:
  - Replace `from unittest import ...` with pytest equivalents
  - Replace `from testtools import ...` with pytest or unittest.mock
  - Verify all imports work with pytest

- [ ] T027 [US1] Validate apiclient test migration:
  - `pytest src/apiclient/tests/ --cov=src/apiclient`
  - Coverage must not decrease
  - All tests pass
  - No collection errors
  - Document completion in migration-inventory.txt

**Checkpoint**: User Story 1 - Low Risk Phase Complete
- All 3 low-risk modules migrated to pytest
- `pytest src/ -k "maascommon or maascli or apiclient"` passes
- Foundation fixtures verified working with migrated modules

---

## Phase 4: User Story 1 - Medium Risk Modules (Continuation)

**Goal**: Extend pytest consolidation to medium-complexity modules

**Medium Risk Module 1: maastesting (Test Framework Itself)**

- [ ] T028 [P] [US1] Audit test files in `src/maastesting/tests/`:
  - Count test_*.py files
  - Identify unittest/testtools usage in test utilities
  - Document assertions to convert
  - Estimated effort for module

- [ ] T029 [P] [US1] Convert `src/maastesting/tests/` to pytest:
  - Rename Test*.py → test_*.py (if needed)
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Replace setUp/tearDown → @pytest.fixture
  - Verify imports (no relative imports)
  - Run: `pytest src/maastesting/tests/ -v` (must pass)

- [ ] T030 [P] [US1] Update imports in migrated maastesting tests:
  - Replace `from unittest import ...` with pytest equivalents
  - Verify fixture imports work with updated conftest.py
  - Verify all imports work with pytest

- [ ] T031 [US1] Validate maastesting test migration:
  - `pytest src/maastesting/tests/ --cov=src/maastesting`
  - Coverage must not decrease
  - All tests pass
  - No collection errors
  - Verify fixtures themselves work correctly

**Medium Risk Module 2: maasservicelayer**

- [ ] T032 [P] [US1] Audit test files in `src/maasservicelayer/tests/`:
  - Count test_*.py files
  - Identify unittest/testtools usage
  - Document SQLAlchemy-specific test patterns
  - Estimated effort for module

- [ ] T033 [P] [US1] Migrate maasservicelayer tests to pytest (SQLAlchemy context):
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Replace setUp/tearDown → @pytest.fixture with db_connection/db_transaction
  - Update database setup to use fixture approach
  - Run: `pytest src/maasservicelayer/tests/ -v` (must pass)

- [ ] T034 [P] [US1] Update imports in migrated maasservicelayer tests:
  - Replace `from unittest import ...` with pytest equivalents
  - Import db_transaction fixture from maastesting
  - Verify SQLAlchemy engine/session fixtures work with pytest

- [ ] T035 [US1] Validate maasservicelayer test migration:
  - `pytest src/maasservicelayer/tests/ --cov=src/maasservicelayer`
  - Coverage must not decrease
  - All tests pass
  - Database fixture cleanup works correctly
  - No collection errors

**Medium Risk Module 3: maasapiserver (FastAPI/pytest-ready)**

- [ ] T036 [P] [US1] Audit test files in `src/maasapiserver/tests/`:
  - Count test_*.py files
  - Most likely already pytest-based; verify
  - Check for any unittest remnants
  - Identified migration effort (likely minimal)

- [ ] T037 [P] [US1] Update maasapiserver tests to use standardized fixtures:
  - Update to use maastesting.fixtures.api_client instead of custom client setup
  - Replace any custom mock_service with maastesting.fixtures.mock_service
  - Align with pytest standards from contract
  - Run: `pytest src/maasapiserver/tests/ -v` (must pass)

- [ ] T038 [P] [US1] Verify FastAPI TestClient fixture works:
  - Ensure api_client fixture in src/maastesting/fixtures/api.py is compatible
  - Update fixture if needed for FastAPI specifics
  - Test with sample FastAPI test

- [ ] T039 [US1] Validate maasapiserver test consistency:
  - `pytest src/maasapiserver/tests/ --cov=src/maasapiserver`
  - Coverage must not decrease
  - All tests pass
  - No collection errors
  - Fixture compatibility verified

**Checkpoint**: User Story 1 - Medium Risk Phase Complete
- All 3 medium-risk modules migrated/aligned to pytest
- `pytest src/ -k "maastesting or maasservicelayer or maasapiserver"` passes
- Fixture compatibility verified across modules

---

## Phase 5: User Story 1 - High Risk Modules (Complex Legacy)

**Goal**: Migrate complex modules with extensive unittest patterns

**High Risk Module 1: provisioningserver (Twisted + unittest)**

- [ ] T040 [P] [US1] Audit test files in `src/provisioningserver/tests/`:
  - Count test_*.py files
  - Identify Twisted async test patterns
  - Document unittest.TestCase + Twisted integration
  - Identify deferToDatabase patterns
  - Estimated effort for module (high complexity)

- [ ] T041 [P] [US1] Create migration guide for Twisted tests → pytest:
  - Document how to handle Deferred results in pytest
  - Pytest-asyncio or pytest-twisted compatibility
  - Deferring and callbacks in pytest fixtures
  - Example conversions for 3 common Twisted patterns

- [ ] T042 [US1] Migrate provisioningserver tests with Twisted support:
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Handle Deferred.inlineCallbacks with pytest-twisted or async/await
  - Update setUp/tearDown to use @pytest.fixture
  - Run: `pytest src/provisioningserver/tests/ -v` (must pass, may need pytest-twisted plugin)

- [ ] T043 [P] [US1] Update imports in provisioningserver tests:
  - Replace unittest imports with pytest equivalents
  - Add pytest-twisted plugin if Twisted async patterns detected
  - Update reactor/Twisted fixture imports

- [ ] T044 [US1] Validate provisioningserver test migration:
  - `pytest src/provisioningserver/tests/ --cov=src/provisioningserver`
  - Coverage must not decrease
  - All Twisted tests pass with async handling
  - No collection errors
  - Performance acceptable (Twisted tests may be slow)

**High Risk Module 2: metadataserver (Django TestCase)**

- [ ] T045 [P] [US1] Audit test files in `src/metadataserver/tests/`:
  - Count test_*.py files
  - Identify Django TestCase usage
  - Document database setup patterns
  - Identify transaction handling patterns
  - Estimated effort for module

- [ ] T046 [P] [US1] Create migration guide for Django tests → pytest:
  - Document django.test.TestCase → pytest-django @pytest.mark.django_db
  - Database transaction handling in pytest vs Django TestCase
  - Fixture approach for Django models and ORM
  - Example conversions for 3 common Django test patterns

- [ ] T047 [US1] Migrate metadataserver tests with Django support:
  - Convert unittest.TestCase classes → pytest functions
  - Replace self.assert* with assert statements
  - Update setUp/tearDown to use @pytest.fixture with db_transaction
  - Add @pytest.mark.django_db to database tests
  - Use pytest-django plugin for Django compatibility
  - Run: `pytest src/metadataserver/tests/ -v` (must pass)

- [ ] T048 [P] [US1] Update imports in metadataserver tests:
  - Replace django.test.TestCase with pytest-django
  - Replace unittest imports with pytest equivalents
  - Import db_transaction from maastesting.fixtures

- [ ] T049 [US1] Validate metadataserver test migration:
  - `pytest src/metadataserver/tests/ --cov=src/metadataserver`
  - Coverage must not decrease
  - All Django tests pass with ORM functionality
  - Database cleanup works correctly
  - No collection errors

**Checkpoint**: User Story 1 - High Risk Phase Complete
- Both high-risk modules migrated to pytest
- Twisted and Django TestCase patterns handled
- `pytest src/ -k "provisioningserver or metadataserver"` passes

---

## Phase 6: User Story 1 - Most Complex Legacy (maasserver)

**Goal**: Migrate the largest, most complex module with heavy Django dependency

**High Risk Module 3: maasserver (Most Complex - Heavy Django)**

- [ ] T050 [P] [US1] Audit test files in `src/maasserver/tests/`:
  - Count test_*.py files (largest module, 100+ files expected)
  - Identify Django TestCase usage (extensive)
  - Identify custom test base classes
  - Document database fixture usage patterns
  - Identify test fixtures and factories
  - Estimated effort for module (very high complexity, may require phased migration)

- [ ] T051 [US1] Create comprehensive migration guide for maasserver:
  - Document all custom test base classes → pytest equivalent fixtures
  - Factory pattern (if used) → pytest parametrize + fixtures
  - Database setup complexity → fixture approach with db_transaction
  - Test isolation patterns → pytest scope control
  - Example conversions for 10 common patterns in maasserver

- [ ] T052 [P] [US1] Create test helpers in `src/maastesting/maasserver_helpers.py`:
  - Custom fixtures for maasserver-specific patterns
  - Factory fixtures for common Django models
  - Helper functions for test setup
  - Assertion helpers (if using custom assertions)
  - Document with examples

- [ ] T053 [US1] Migrate maasserver tests in batches (by subdirectory):
  - **Batch 1**: `src/maasserver/tests/test_models.py` (models and model tests)
    - Convert unittest.TestCase → pytest functions
    - Replace self.assert* with assert
    - Update setUp/tearDown → @pytest.fixture
    - Run: `pytest src/maasserver/tests/test_models.py -v` (must pass)
  
  - **Batch 2**: `src/maasserver/tests/test_forms.py` (form tests)
    - Same conversion approach
    - Run: `pytest src/maasserver/tests/test_forms.py -v` (must pass)
  
  - **Batch 3**: `src/maasserver/tests/test_api/` (API tests)
    - Use api_client fixture from maastesting
    - Update response assertions to pytest style
    - Run: `pytest src/maasserver/tests/test_api/ -v` (must pass)
  
  - **Batch 4**: Remaining test files (repeat pattern)
    - Group similar tests
    - Convert each batch
    - Run batch validation

- [ ] T054 [P] [US1] Update imports across maasserver tests:
  - Replace django.test.TestCase with pytest-django
  - Replace unittest imports with pytest
  - Import helpers from maastesting.maasserver_helpers
  - Verify all Django ORM imports work

- [ ] T055 [US1] Validate complete maasserver migration:
  - `pytest src/maasserver/tests/ --cov=src/maasserver -v`
  - Coverage must not decrease from baseline
  - All tests pass (100% pass rate)
  - No collection errors or warnings
  - Performance benchmark (may take 10+ minutes, acceptable if within 5%)
  - Document completion with completion timestamp

**Checkpoint**: User Story 1 Complete - All Python Tests Migrated to pytest
- All modules (low, medium, high risk) migrated to pytest
- Full test suite: `pytest src/` passes with 0 framework-related failures
- All 50+ modules have pytest-compatible test files
- Coverage metrics maintained or improved
- Ready for CI/CD transition

---

## Phase 7: CI/CD Integration & Testing

**Purpose**: Transition CI/CD and local testing to pytest exclusively

- [ ] T056 Update `.github/workflows/test.yml` to use pytest:
  - Change test invocation from custom runner to `make test`
  - Set up pytest-cov for coverage reporting
  - Upload coverage to codecov or similar (if used)
  - Ensure all Python versions (3.9-3.12) tested

- [ ] T057 Update `.github/workflows/lint.yml` (if exists):
  - Verify no references to unittest runner
  - If linting includes import sorting, verify pytest imports correct

- [ ] T058 Verify GitHub branch protection rules:
  - "Tests" status check required before merge
  - Coverage threshold (if applicable)
  - Test results posting to PRs

- [ ] T059 Run full integration test locally:
  - `pytest src/ --cov=src --cov-report=xml`
  - Verify all tests pass on main development machine
  - Document baseline execution time
  - Compare with performance target (≤5% increase from original)

- [ ] T060 Test parallel execution (optional optimization):
  - Install pytest-xdist: `pip install pytest-xdist`
  - Run: `pytest src/ -n auto` (parallel execution)
  - Measure execution time improvement
  - Document if worth enabling by default

- [ ] T061 Verify CI/CD test runs on actual GitHub Actions:
  - Push feature branch to remote
  - Verify workflow runs and passes
  - Check coverage report uploaded
  - Verify status check shows "Tests passed"

---

## Phase 8: Documentation & Finalization

**Purpose**: Update project documentation and close out pytest standardization

- [ ] T062 Update `AGENTS.md` with pytest testing standard:
  - Add pytest testing section under Python Guidelines
  - Document required testing patterns
  - Link to `docs/testing/pytest-migration.md`
  - Add example test file
  - Reference fixtures and markers

- [ ] T063 Create pytest quick reference guide `docs/testing/pytest-quick-ref.md`:
  - Common commands (make test, pytest -k, pytest -m)
  - Fixture usage patterns
  - Assertion styles
  - Marker usage
  - One-page reference

- [ ] T064 Archive deprecated unittest documentation:
  - Move any unittest-specific docs to `docs/archived/unittest-migration/`
  - Create README explaining old patterns (for historical reference only)
  - Note that these docs are deprecated

- [ ] T065 Update README.rst with testing information:
  - Point to pytest as the standard testing framework
  - Link to testing documentation
  - Include `make test` as standard command

- [ ] T066 Create migration summary document `specs/6685-single-test-framework/migration-completion-report.md`:
  - Modules migrated (all 50+)
  - Metrics: tests converted, assertions updated, fixtures created
  - Performance comparison (old vs. new)
  - Issues encountered and resolutions
  - Team learnings and recommendations

- [ ] T067 Final validation of entire codebase:
  - Grep for "unittest.TestCase" in src/ tests (should be 0 results)
  - Grep for "self.assert" in src/ tests (should be 0 results)
  - Grep for relative imports in src/ tests (should be 0 results)
  - Run full test suite: `pytest src/` (100% pass)
  - Verify documentation is complete

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements affecting multiple modules and long-term maintenance

- [ ] [P] T068 Review and optimize pytest configuration in `pyproject.toml`:
  - Verify markers are complete and well-organized
  - Check test discovery patterns are optimal
  - Review coverage thresholds
  - Document any customizations

- [ ] [P] T069 Create pytest plugin for custom assertions (if applicable):
  - If custom assertions appear across tests, create helper module
  - Implement as pytest plugin (optional)
  - Document plugin usage

- [ ] [P] T070 Performance optimization (if needed):
  - If test suite ≤5% slower, nothing required
  - If >5% slower, implement optimizations:
    - Use pytest-xdist for parallel execution
    - Identify slow tests with `pytest --durations=10`
    - Optimize database fixture setup
    - Consider session-scoped fixtures where appropriate

- [ ] T071 Create test maintenance guide `docs/testing/test-maintenance.md`:
  - How to add new tests following pytest patterns
  - Fixture reuse and extension guidelines
  - Test naming conventions
  - When to use different fixture scopes
  - Common pitfalls and how to avoid them

- [ ] T072 Set up pre-commit hook for test checks (optional):
  - Create `.pre-commit-config.yaml` entry (if not present)
  - Run `pytest --collect-only` on changed test files
  - Run linting on tests (flake8, isort, etc.)
  - Document in contributor guide

- [ ] T073 Create or update CONTRIBUTING.md with testing section:
  - Link to pytest documentation
  - Testing requirements for PRs
  - How to run tests locally
  - Common testing patterns to follow
  - Performance expectations

- [ ] T074 Team training & documentation review:
  - Schedule optional team session on pytest patterns
  - Review migration guide with interested developers
  - Answer questions on new testing approach
  - Document FAQ in `docs/testing/pytest-faq.md`

- [ ] T075 Final sign-off and project closure:
  - Verify all success criteria from spec.md are met
  - Conduct final team review
  - Document lessons learned
  - Close feature branch or merge to main
  - Create summary PR with all changes

**Final Checkpoint**: Pytest Migration Complete & Tested
- ✅ All Python tests migrated to pytest (100%)
- ✅ Zero unittest.TestCase in codebase
- ✅ All fixtures working and documented
- ✅ CI/CD fully integrated with pytest
- ✅ Performance within 5% target
- ✅ Documentation complete and updated
- ✅ Team trained and ready for future testing

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 complete - BLOCKS all user stories
- **Phase 3-6 (User Story 1 Modules)**: All depend on Phase 2 complete
  - Low Risk (T016-T027): Can start after Phase 2
  - Medium Risk (T028-T039): Can start after Phase 2 (parallel with Low Risk)
  - High Risk (T040-T049): Can start after Phase 2 (parallel with Medium Risk)
  - Complex Legacy (T050-T055): Can start after Phase 2 (parallel with others)
  - All phases must complete before proceeding to CI/CD
- **Phase 7 (CI/CD)**: Depends on Phase 6 complete
- **Phase 8 (Documentation)**: Depends on Phase 7 complete
- **Phase 9 (Polish)**: Depends on Phase 8 complete

### Module Dependencies (within User Story 1)

```
Phase 2: Foundation
    ↓
Phase 3: Low Risk (maascommon, maascli, apiclient) - Can run in parallel
    ↓
Phase 4: Medium Risk (maastesting, maasservicelayer, maasapiserver) - Can run in parallel
    ↓
Phase 5: High Risk (provisioningserver, metadataserver) - Can run in parallel
    ↓
Phase 6: Complex Legacy (maasserver) - Must wait for earlier phases
    ↓
Phase 7: CI/CD Integration (only after all modules migrated)
    ↓
Phase 8: Documentation & Finalization
    ↓
Phase 9: Polish & Optimization
```

### Within Each User Story Phase

- Tests (if included) MUST be written and FAIL before implementation
- Models/Data before Services
- Services before API/Endpoints
- Core implementation before Integration
- Story complete before moving to next priority

### Parallel Opportunities

All Phase 3 low-risk module tasks marked [P] can run in parallel (different files, no dependencies)

All Phase 4 medium-risk module tasks marked [P] can run in parallel

All Phase 5 high-risk module tasks can start simultaneously (different modules)

Phases can **NOT** run in parallel due to foundation dependencies

---

## Implementation Strategy

### MVP First (User Story 1 Only - Pytest for Python)

**Recommended**: Since User Story 1 is P1 and foundation for the project:

1. Complete Phase 1: Setup (1 week)
2. Complete Phase 2: Foundational (1 week)
3. Complete Phase 3-6: User Story 1 module migration (4 weeks)
4. **STOP and VALIDATE**: All pytest tests passing
5. Complete Phase 7: CI/CD Integration (1 week)
6. Complete Phase 8: Documentation (1 week)
7. Deploy/Demo pytest as sole Python testing standard

**Total MVP Timeline**: 7 weeks to pytest consolidation

**Deployment Strategy**: After Phase 7, new feature code MUST use pytest. Old unittest/testtools removed completely.

### Incremental Delivery (Phase by Phase)

1. Phase 1 (Setup) → Demo: pytest configuration ready, fixtures available
2. Phase 2 (Foundation) → Demo: baseline tests migrated, audits complete
3. Phase 3 (Low Risk) → Demo: 3 small modules migrated, proof of concept
4. Phase 4 (Medium Risk) → Demo: 3 more modules + pytest ecosystem verified
5. Phase 5 (High Risk) → Demo: Complex patterns (Twisted, Django) handled
6. Phase 6 (Complex Legacy) → Demo: maasserver (largest module) migrated
7. Phase 7 (CI/CD) → Demo: full automation working
8. Phase 8 (Docs) → Demo: team can start using pytest
9. Phase 9 (Polish) → Production-ready pytest framework

### Parallel Team Strategy (If Multiple Developers Available)

With 4 developers:

1. **Developer A**: Phases 1 & 2 (Setup + Foundation) - MUST complete first
2. Once Phase 2 complete:
   - **Developer A**: Phase 3 (Low Risk)
   - **Developer B**: Phase 4 (Medium Risk)  
   - **Developer C**: Phase 5 (High Risk)
   - **Developer D**: Phase 6 (Complex Legacy)
3. Once all modules done:
   - **Developer A**: Phase 7 (CI/CD)
   - **Developers B, C, D**: Phase 8 (Documentation & Training)
4. **All**: Phase 9 (Review & Polish)

**Total Parallel Timeline**: 4 weeks (vs. 7 weeks sequential)

---

## Notes

- [P] tasks = different files, no inter-task dependencies
- [US1] label = User Story 1 (P1 - Consolidate Python Framework)
- All exact file paths included for clarity
- Each task independently executable by developer or LLM agent
- Stop at any checkpoint to validate story independently
- Performance benchmarking critical (≤5% increase target)
- Team training recommended before general feature development

---

**Tasks Status**: ✅ COMPLETE - 75 actionable tasks broken down by phase and story

**Total Tasks**: 75  
**Phase 1 (Setup)**: 15 tasks  
**Phase 2 (Foundation)**: 5 tasks  
**Phase 3 (US1 - Low Risk)**: 12 tasks  
**Phase 4 (US1 - Medium Risk)**: 12 tasks  
**Phase 5 (US1 - High Risk)**: 10 tasks  
**Phase 6 (US1 - Complex Legacy)**: 8 tasks  
**Phase 7 (CI/CD Integration)**: 6 tasks  
**Phase 8 (Documentation)**: 6 tasks  
**Phase 9 (Polish & Optimization)**: 8 tasks  

**Ready for**: Team assignment → Sprint planning → Task execution
