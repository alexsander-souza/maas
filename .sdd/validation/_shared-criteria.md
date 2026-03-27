# Shared Quality Criteria

## Purpose

Common quality standards referenced by all validation checklists (specification, plan, task, implementation). Use this as a reference to avoid duplication across phase-specific checklists.

---

## Documentation Quality Standards

**Applies to:** All phases (specification, plan, task, implementation)

### Clarity
- Written in clear, concise language
- No jargon without explanation
- Technical terms used correctly and consistently
- Obvious to unfamiliar readers

### Organization
- Logical structure and flow
- Easy to navigate
- All required sections complete
- Consistent formatting

### Completeness
- All necessary information present
- No critical gaps or unknowns
- References and links provided
- Context adequately explained

### Accuracy
- Information is factually correct
- No conflicting statements
- Up-to-date with current codebase
- Validated by relevant stakeholders

---

## MAAS Architectural Standards

**Applies to:** Plan, task, implementation

### Three-Tier Architecture (v3 API)
- API layer handles HTTP interface only
- Service layer contains business logic
- Repository layer handles data access
- Clear separation maintained
- No layer bypassing

### Repository-Service Pattern
- Repositories use SQLAlchemy Core (not ORM)
- QuerySpec used for all list methods
- ClauseFactory for reusable filters
- Services orchestrate business logic
- Services manage transactions

### Legacy Code (Django)
- Django ORM only in maasserver
- deferToDatabase for async contexts
- Proper transaction management
- No Django ORM in v3 API

### Technology Alignment
- **Python**: v3 API, service layer, repositories (asyncio, Pydantic v2, SQLAlchemy Core)
- **Django**: Legacy maasserver only
- **Go**: maasagent, host-info (microcluster, Temporal)
- **Database**: PostgreSQL via asyncpg

---

## Testing Standards

**Applies to:** Task, implementation

### Coverage Requirements
- >90% coverage for new code
- All public interfaces tested
- Happy path, error cases, edge cases
- Critical paths fully covered

### Test Quality
- One behavior per test
- Descriptive test names (no verbose docstrings)
- Tests are independent and can run in any order
- Proper cleanup (no test pollution)
- Mock only external dependencies

### Test-Driven Development
- Tests written before implementation (RED-GREEN-REFACTOR)
- Tests drive design decisions
- Acceptance criteria map to tests

### Test Organization
- **Python**: pytest, fixtures, parametrize, async tests
- **Go**: table-driven tests, testify assertions, subtests with t.Run()
- Integration tests use real dependencies where appropriate
- Unit tests mock external services

---

## Code Quality Standards

**Applies to:** Implementation

### Readability
- Self-documenting code with clear names
- Functions/methods appropriately sized (<50 lines)
- Complex logic explained with comments (explain "why", not "what")
- Consistent formatting (Ruff for Python, gofmt for Go)

### Design Principles
- DRY (Don't Repeat Yourself)
- Single Responsibility Principle
- Loose coupling, high cohesion
- No magic numbers (use named constants)

### Type Safety
- Type hints on all Python functions/methods (Python 3.10+ union syntax)
- Go types properly defined
- Pydantic models for validation

### Error Handling
- Expected errors handled gracefully
- Meaningful error messages
- Resources cleaned up properly (context managers, defer)
- No silent failures

### Code Style
- **Python**: 79 char lines, double quotes, 4-space indent, isort import order
- **Go**: gofmt formatting, exported vs unexported naming, defer for cleanup

---

## Security Standards

**Applies to:** All phases (specification identifies requirements, implementation enforces)

### Critical Security Items
- No hardcoded secrets (passwords, API keys, tokens)
- All database queries use parameterized queries (never string concatenation)
- Input validation on all user inputs
- Authentication required for protected resources
- Authorization checked before actions
- Error messages don't leak sensitive information
- Debug mode off in production

### Input Validation
- User input validated before processing
- Pydantic validators for API requests (Python)
- Whitelist validation (not blacklist)
- File paths validated (no directory traversal)

### Data Protection
- Sensitive data not logged
- Passwords hashed with strong algorithms
- TLS enforced for external connections
- API keys from environment variables

---

## Performance Standards

**Applies to:** Plan, implementation

### Query Optimization
- No N+1 query problems
- Proper use of select_related/prefetch_related (Django)
- QuerySpec for composable filters (SQLAlchemy)
- Appropriate indexes on database tables
- Aggregations done in database when possible

### Resource Efficiency
- Memory usage reasonable
- No resource leaks (connections, file handles)
- Proper cleanup with context managers/defer
- Async operations for I/O-bound tasks

### Scalability
- Code handles expected data volumes
- Performance degrades gracefully
- No hardcoded limits that don't scale

---

## Minimal Change Integration

**Applies to:** Implementation

### Code Preservation
- Preserve existing code structure
- Match existing patterns and style
- Minimal, surgical changes only
- No "while I'm here" changes

### Integration Approach
- Add to existing code rather than rewriting
- Preserve working functionality
- Use existing utilities and patterns
- No breaking changes to public APIs

### Scope Discipline
- Only change files specified in task
- No unrelated refactoring
- No fixing unrelated bugs
- No style cleanup of untouched code

---

## Usage by Phase

### Specification Validation
- Documentation Quality Standards
- Security Standards (identify requirements)

### Plan Validation
- Documentation Quality Standards
- MAAS Architectural Standards
- Security Standards (design for security)
- Performance Standards (design for performance)

### Task Validation
- Documentation Quality Standards
- MAAS Architectural Standards
- Testing Standards (define test requirements)

### Implementation Validation
- All sections apply
- Most comprehensive validation phase

---

## Reference

For detailed patterns and examples, see:
- **[Python Patterns](../skills/languages/python-patterns.md)** - Python code standards
- **[Go Patterns](../skills/languages/go-patterns.md)** - Go code standards
- **[Python Testing](../skills/languages/python-testing.md)** - Python test patterns
- **[Go Testing](../skills/languages/go-testing.md)** - Go test patterns
- **[Security Checklist](./security-checklist.md)** - Detailed security validation
- **[Test Code Quality](../skills/techniques/test-code-quality.md)** - Test quality principles