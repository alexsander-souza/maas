# Feature Specification: Standardize Python Test Framework (User Story 1)

**Feature Branch**: `6685-single-test-framework`  
**Created**: 2026-03-27  
**Status**: Draft  
**Input**: User description: "As a MAAS developer, I want to maintain only one test framework for each language"

**SCOPE CLARIFICATION** (2026-03-27):
This specification defines a complete 3-story feature, but **current implementation focuses on User Story 1 (Python) only**, targeting MVP delivery in 7 weeks. User Story 2 (Go) and User Story 3 (Documentation/Enforcement) are planned as separate follow-up features (#6686, #6687) for future releases. See "Phased Delivery" section below.

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Consolidate Python Test Framework (Priority: P1)

A MAAS developer working on Python code wants a single, unified test framework so they can write and run tests without confusion about which testing tool to use. Currently, the Python codebase may use multiple test frameworks (pytest, unittest, testtools), causing inconsistency in test structure, syntax, and execution.

**Why this priority**: Python is the primary language for MAAS. Consolidating its test framework improves developer velocity, reduces onboarding friction, and ensures consistent test patterns across all Python modules. This is the foundation for the entire feature.

**Independent Test**: Verify that all Python test files in the codebase use the same framework, and that developers can run the full test suite with a single command without encountering "framework not found" errors or syntax incompatibilities.

**Acceptance Scenarios**:

1. **Given** a Python codebase with tests in multiple frameworks, **When** a developer runs `make test`, **Then** all tests execute using the standardized framework with no failures due to framework incompatibility
2. **Given** a developer writing a new Python test, **When** they follow the project testing guidelines, **Then** they use the standardized framework and the test integrates seamlessly with the existing test suite
3. **Given** legacy test files using non-standard frameworks, **When** the migration is complete, **Then** all legacy tests are converted to the standardized framework or explicitly excluded
4. **Given** CI/CD pipeline running tests, **When** tests execute, **Then** only one test framework binary/command is invoked for Python tests

---

### User Story 2 - Establish Single Go Test Framework (Priority: P2)

A Go developer working on `maasagent` or `host-info` wants consistency in Go testing practices. Currently, multiple testing approaches may coexist (standard `testing` package, table-driven tests, assertion libraries, mocking tools), making it harder to maintain coherent test expectations.

**Why this priority**: Go is an emerging language in MAAS (maasagent, host-info). Establishing a clear testing standard early prevents fragmentation. Secondary to Python due to smaller codebase volume.

**Independent Test**: Verify that all Go test files follow consistent patterns (e.g., table-driven tests), use the same assertion/mocking libraries where needed, and can be executed via standard Go tooling (`go test ./...`) without custom test runners.

**Acceptance Scenarios**:

1. **Given** Go test files across maasagent and host-info, **When** a developer runs `go test ./...`, **Then** all tests execute successfully using consistent patterns
2. **Given** a developer contributing a new Go test, **When** they reference the testing guidelines, **Then** they follow established patterns (e.g., table-driven tests, standard library or approved assertion libraries)
3. **Given** multiple Go modules with tests, **When** tests run, **Then** output format and assertion style are consistent across all modules

---

### User Story 3 - Document and Enforce Framework Standards (Priority: P3)

All MAAS developers want clear, authoritative guidance on which test framework to use for each language. Lack of documentation leads to tool sprawl and inconsistent choices by new contributors.

**Why this priority**: Documentation and enforcement ensure long-term consistency. Lower priority than actual consolidation, but critical for preventing regression.

**Independent Test**: Verify that framework standards are documented in a accessible location (AGENTS.md or equivalent), that new contributors can easily find the guidance, and that CI/CD or review processes flag non-compliant test code.

**Acceptance Scenarios**:

1. **Given** a new contributor starting work on the MAAS project, **When** they read the contributor guidelines, **Then** they find clear direction on which test framework to use for each language
2. **Given** a pull request with tests in a non-standard framework, **When** the PR is reviewed, **Then** a reviewer or automated check identifies the issue and guides the developer to fix it
3. **Given** the testing standards in AGENTS.md or Constitution, **When** a developer follows them, **Then** their code is immediately compatible with the project's testing practices

---

### Edge Cases

- What happens when a large legacy module has thousands of tests in a deprecated framework? (Phased migration with clear timelines)
- How does the project handle test failures during framework migration? (Tests should pass in both old and new framework during transition, or be marked as skipped)
- What if a specific test pattern is impossible to replicate in the standardized framework? (Document exception and seek alternative approach or framework compromise)

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: System MUST have a single, standardized test framework for Python code (either pytest or unittest, not both as primary)
- **FR-002**: System MUST have a single, standardized test framework strategy for Go code (standard `testing` package with approved supplementary libraries)
- **FR-003**: System MUST ensure all existing tests pass under the standardized framework(s)
- **FR-004**: System MUST provide clear, discoverable guidance on which test framework to use for each language
- **FR-005**: System MUST ensure developers can run the complete test suite with a single command (e.g., `make test`)
- **FR-006**: System MUST support running tests for specific modules or layers independently
- **FR-007**: System MUST enforce test framework standards in CI/CD so non-compliant code is caught before merge
- **FR-008**: System MUST document approved libraries and patterns for test utilities (mocking, assertions, fixtures) for each language

### Key Entities

- **Test Framework Configuration**: Rules and guidelines for which testing framework applies to each language (Python, Go)
- **Legacy Test Inventory**: Existing test files mapped to their current frameworks for migration planning
- **Testing Guidelines Document**: Authoritative reference for developers on framework standards and patterns

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: All Python test files in the codebase (100%) use the same primary test framework with zero framework incompatibilities
- **SC-002**: All Go test files (100%) follow consistent testing patterns without contradictions
- **SC-003**: Full test suite execution time does not increase by more than 5% after standardization
- **SC-004**: Zero framework-related test failures in CI/CD after standardization is complete
- **SC-005**: 100% of new test code submitted in PRs after standardization uses the standard framework (measured by PR review feedback)
- **SC-006**: Developer onboarding documentation references the standardized frameworks with clear examples (target: new contributors should identify correct framework within 2 minutes of reading docs)
- **SC-007**: All test invocations in Makefile and CI/CD workflows reference a single, unified test command per language

## Assumptions

- **Feature Scope (2026-03-27)**: This feature is implemented in 3 phases across 2-3 releases:
  - **Phase 1 (Current - Feature #6685)**: Python pytest consolidation (User Story 1) - MVP in 7 weeks
  - **Phase 2 (Future - Feature #6686)**: Go testing standardization (User Story 2) - separate planning cycle
  - **Phase 3 (Future - Feature #6687)**: Documentation/Enforcement (User Story 3) - depends on P1+P2
  
- **Python Framework Selection**: pytest is established as the exclusive standard for all Python testing in MAAS (Feature #6685 scope). All existing unittest and testtools tests will be migrated to pytest during this initiative.
- **Go Testing**: Deferred to Feature #6686. Standard Go `testing` package is mandatory; testify/assert or similar libraries are optional but approved for consistent assertion patterns (to be detailed in #6686 planning)
- **Test Coverage Retention**: Any framework migration will maintain or improve overall test coverage percentages
- **Backward Compatibility**: Existing test infrastructure (CI/CD, Makefile targets) will be updated to support the standardized framework; no breaking changes to the testing experience for developers
- **Phased Migration**: Large legacy test suites may require phased migration; not all tests must be converted on day one
- **Framework Scope**: This feature addresses unit and integration testing frameworks; property-based testing (e.g., hypothesis) and performance testing frameworks are separate concerns
- **CI/CD Integration**: The project's CI/CD system (GitHub Actions, internal runners, etc.) will be configured to use the standardized framework; no additional CI setup required from individual developers
