<!-- 
Sync Impact Report for Constitution v1.0.0 (2026-03-27)
- Version: v1.0.0 (initial from AGENTS.md)
- Principles Added: 8 core principles extracted from AGENTS.md
- Sections Added: Code Quality, Security, Documentation, Collaboration, Version Control
- Ratified: 2025-06-13 (project inception, approximated)
- Dependencies Updated: None (first constitution iteration)
-->

# MAAS Project Constitution

## Core Principles

### I. Code Modularity & Testability

Write code that is modular, testable, and self-contained. Every component MUST be independently testable, with clear separation of concerns. Avoid monolithic code structures. Code duplication is a signal to refactor into reusable modules. Always check existing patterns in the same module before introducing new ones.

### II. Explicit Over Implicit

Prefer explicit, clear code that is easily understood. Avoid clever or implicit patterns unless they are widely established in the codebase. Use clear, descriptive names for variables, functions, classes, and tests. Avoid abbreviations unless widely understood. Code should speak for itself without requiring detailed explanation.

### III. Code Quality & Naming

Better naming over comments. Use descriptive identifiers and clear function signatures instead of complex code requiring verbose comments. Comments should explain *why* something is done, not *what*. Avoid trivial comments on obvious logic. Keep documentation concise and straightforward. Test code must be clean, self-documenting, and free of verbose docstrings.

### IV. Security by Default

Security is non-negotiable. Never hardcode credentials, secrets, or tokens. All user inputs MUST be validated and sanitized. All database access MUST use parameterized queries—never construct SQL with string concatenation. Avoid deprecated or insecure libraries. Follow security best practices for the technology stack. Authentication and authorization code requires extra scrutiny. Always use secure defaults for cryptographic operations.

### V. Documentation Synchronization

Keep documentation synchronized with code. Update README and API documentation when functionality changes. Document architectural changes immediately. Keep inline comments focused on *why*, not *what*. Avoid redundancy and obvious statements in documentation. Include type hints where applicable. Architecture documentation is a living artifact that must stay current.

### VI. Conventional Commits & History

All commits MUST follow Conventional Commits specification (feat, fix, refactor, perf, test, build, chore, docs). Use meaningful scope tags for MAAS components (bootresources, dhcp, dns, network, power, security, storage, tftp, deps, ci). Include `BREAKING CHANGE:` footer for breaking changes with `!` in commit type. Always reference related issues (LP: for Launchpad, GH: for GitHub) in commit bodies. Commit messages explain *why*, not just *what* changed.

### VII. Testing Discipline

Write meaningful tests with pytest for new Python code. Avoid trivial assertions that test framework behavior. Keep tests minimal—only test behavior that matters. Test code should be clean and self-explanatory. Mock external dependencies appropriately. Follow existing test patterns in each subdirectory. For integration-heavy code, focus integration tests on actual cross-component communication, not on mocked boundaries.

### VIII. Collaboration & Code Review

Follow the project's code review and pull request process. Tag relevant team members for specialized reviews. Reference related issues in PRs. Link to relevant documentation when making architectural changes. Ensure code is compatible with current dependency versions. When in doubt, check existing patterns in the same subdirectory, review the subdirectory README, or consult project maintainers.

## Technology Standards

### Python Guidelines

- **Line Length**: Maximum 79 characters (per `pyproject.toml`)
- **Formatting**: Use Ruff formatter and follow Ruff linting rules (pycodestyle, pyflakes, isort, flake8-bugbear)
- **Type Hints**: MUST use type hints for all function signatures. Ensure Pyright compliance in new code in `maascommon`, `maasservicelayer`, `maasapiserver`, and `maastemporalworker`
- **Async/Await**: Prefer async patterns in v3 API code; use `deferToDatabase` in legacy Django code
- **Database**: New code MUST use SQLAlchemy Core (not ORM) in service layer. Legacy code continues using Django ORM. Always use parameterized queries
- **Target Version**: Python 3.9+ (verify in `pyproject.toml`)

### Go Guidelines

- Follow standard Go formatting (`gofmt` / `go fmt`)
- Check `go.mod` for version requirements (Go 1.24.4 for `maasagent`, Go 1.18 for `host-info`)
- Use table-driven tests where appropriate
- Follow microcluster patterns in `maasagent`

### Architecture Decisions

- **v3 API**: Use three-tier architecture (Repository → Service → API handler). Repositories use SQLAlchemy Core, services contain business logic
- **Legacy Code**: Django ORM and Twisted patterns remain in place for `maasserver`, `provisioningserver`, `metadataserver`
- **Data Validation**: Use Pydantic models for validation in new code
- **Shared Utilities**: Keep `maascommon` dependencies minimal with Pyright compliance
- **Database Migrations**: Use Alembic for schema migrations in service layer

## Code Quality Gates

### Before Submitting Changes

1. **Linting**: Run `make lint` for Python code
2. **Testing**: Run `make test` for affected components; Go tests run per-directory with `make test` or `go test ./...`
3. **Conventional Commits**: Verify commit messages follow the specification
4. **Documentation**: Update README or architecture docs if functionality changes
5. **Type Compliance**: Ensure new code in key modules passes Pyright checks

### Code Review Standards

- Verify compliance with this Constitution in all PRs
- Challenge code that violates established patterns without justification
- Ensure security practices are followed (no hardcoded secrets, parameterized queries, validated inputs)
- Confirm tests are meaningful and focused on actual behavior
- Check that documentation is current and accurate

## Governance

### Constitution Authority

This Constitution supersedes all other development guidelines and practices. It establishes non-negotiable principles for code quality, security, and consistency across the MAAS project. When conflicts arise between this document and other guidelines, the Constitution takes precedence.

### Amendment Procedure

Amendments to this Constitution require:

1. **Ratification**: Changes MUST be documented and approved by the MAAS core team
2. **Migration Plan**: Breaking changes require a clear migration path for existing code
3. **Version Bump**: Changes trigger semantic versioning updates to this document
4. **Template Updates**: Any amendment affecting development process MUST update dependent templates in `.specify/templates/`
5. **Communication**: All team members MUST be notified of Constitution changes

### Compliance Review

- Code review gates MUST verify Constitution compliance for all PRs
- Deviations from principles require explicit justification in commit messages or PR descriptions
- Regular audits of the codebase SHOULD identify patterns that contradict established principles
- AI agents working on this project MUST reference this Constitution as the authoritative development guide

### Guidance File Location

This Constitution is the source of truth. Additional context is available in:
- `AGENTS.md` - AI coding agent guidelines with module-specific rules
- `go-style-guide.md` - Go language style guide
- `src/maasservicelayer/README.md` - Service layer architecture details
- `pyproject.toml` - Python tooling and version configuration
- Individual module READMEs for subdirectory-specific patterns

**Version**: 1.0.0 | **Ratified**: 2025-06-13 | **Last Amended**: 2026-03-27
