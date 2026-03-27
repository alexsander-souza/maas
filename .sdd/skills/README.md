# Skills Catalog

This directory contains reusable, actionable skill modules for MAAS development. Each skill defines specific patterns, practices, and guidelines that agents can apply when working on code.

## Structure

```
.sdd/skills/
├── languages/        # Language-specific patterns and idioms
├── techniques/       # Cross-cutting practices (security, testing, naming)
├── domains/          # Domain-specific knowledge (not yet populated)
└── compositions/     # Combined skills for complete workflows
```

## Quick Reference by Task

### Writing Python Code
- **General patterns**: [python-patterns.md](languages/python-patterns.md)
- **Testing**: [python-testing.md](languages/python-testing.md)
- **Django ORM**: [django-patterns.md](languages/django-patterns.md)
- **SQLAlchemy**: [sqlalchemy-patterns.md](languages/sqlalchemy-patterns.md)

### Writing Go Code
- **General patterns**: [go-patterns.md](languages/go-patterns.md)
- **Testing**: [go-testing.md](languages/go-testing.md)
- **Microcluster**: [microcluster-patterns.md](languages/microcluster-patterns.md)

### Security & Quality
- **Secure coding**: [secure-coding.md](techniques/secure-coding.md)
- **Secret management**: [secret-management.md](techniques/secret-management.md)
- **Input validation**: [input-validation.md](techniques/input-validation.md)
- **Naming conventions**: [naming-conventions.md](techniques/naming-conventions.md)
- **Code clarity**: [code-clarity.md](techniques/code-clarity.md)
- **Comments**: [minimal-comments.md](techniques/minimal-comments.md)
- **Test quality**: [test-code-quality.md](techniques/test-code-quality.md)

### Complete Workflows
- **Backend feature**: [backend-feature.md](compositions/backend-feature.md)
- **API endpoint**: [api-endpoint.md](compositions/api-endpoint.md)
- **Database migration**: [database-migration.md](compositions/database-migration.md)
- **Testing suite**: [testing-suite.md](compositions/testing-suite.md)

## Searchable Index

### By Technology
- **Python 3.9+**: python-patterns, python-testing, django-patterns, sqlalchemy-patterns
- **Go 1.18+**: go-patterns, go-testing, microcluster-patterns
- **Pydantic v2**: python-patterns
- **SQLAlchemy Core**: sqlalchemy-patterns
- **Django ORM**: django-patterns
- **Pytest**: python-testing
- **Microcluster**: microcluster-patterns

### By Activity
- **Creating new endpoints**: api-endpoint, python-patterns, sqlalchemy-patterns, input-validation
- **Writing tests**: python-testing, go-testing, test-code-quality, testing-suite
- **Database work**: sqlalchemy-patterns, django-patterns, database-migration
- **Refactoring**: code-clarity, naming-conventions, python-patterns
- **Security review**: secure-coding, secret-management, input-validation
- **Code review**: All techniques/, test-code-quality

### By Concern
- **Performance**: sqlalchemy-patterns (efficient queries), python-patterns (async)
- **Security**: secure-coding, secret-management, input-validation
- **Maintainability**: naming-conventions, code-clarity, minimal-comments
- **Testing**: python-testing, go-testing, test-code-quality, testing-suite
- **Architecture**: python-patterns (three-tier), backend-feature, api-endpoint

## How to Use Skills

Each skill document follows this structure:

1. **Purpose**: What problem this skill solves
2. **When to Use**: Conditions that trigger this skill
3. **Pattern Examples**: Concrete, actionable code patterns
4. **Anti-patterns**: What to avoid
5. **Related Skills**: Other skills commonly used together

### For Agents
When assigned a task:
1. Identify the primary technology (Python/Go)
2. Identify the type of work (new feature, test, refactor, security)
3. Select relevant skills from the index above
4. Apply patterns from selected skills
5. Check anti-patterns to avoid common mistakes
6. Use composition guides for multi-step workflows

### For Humans
Use this catalog to:
- Understand project conventions quickly
- Review code against established patterns
- Onboard new team members
- Document architectural decisions
- Ensure consistency across the codebase

## Skill Catalog Principles

1. **Actionable**: Every skill contains concrete, copy-paste-ready patterns
2. **Minimal**: Focus on essential patterns, not exhaustive documentation
3. **Current**: Extracted from actual MAAS codebase (AGENTS.md)
4. **Composable**: Skills combine to handle complex workflows
5. **Searchable**: Multiple entry points (task, technology, concern)

## Maintenance

Skills are derived from:
- `AGENTS.md` (primary source)
- `go-style-guide.md` (Go-specific)
- Actual codebase patterns
- Team code review feedback

When patterns change in AGENTS.md, update the corresponding skill modules.