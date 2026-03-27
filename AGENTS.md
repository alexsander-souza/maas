# AI Coding Agent Guidelines

📍 **Content Reorganization Notice**: Detailed guidelines have been reorganized into `.sdd/` for better discoverability. See [MIGRATION.md](.sdd/MIGRATION.md) for the complete mapping of where content moved.

This document is the entry point for AI coding agents working on MAAS. It provides core principles and routes to detailed guidance.

---

## Quick Start

1. **Read this file** (~5 minutes) for core principles
2. **Check your task type**:
   - New complex feature? → Use [Spec-Driven Development](.sdd/README.md)
   - Simple bug fix or enhancement? → Follow guidelines below + subsystem rules
3. **Load relevant context**:
   - Language patterns → [.sdd/skills/languages/](.sdd/skills/languages/)
   - Subsystem rules → [.sdd/context/subsystems/](.sdd/context/subsystems/)
   - Techniques → [.sdd/skills/techniques/](.sdd/skills/techniques/)
4. **Write code** following Conventional Commits

---

## Core Principles

These principles apply to **all MAAS code**:

- **Write modular, testable code** - Functions and classes should have single, clear responsibilities
- **Prefer explicit over implicit** - Make code intentions clear through naming and structure
- **Follow established patterns** - Check existing code in the same module before introducing new patterns
- **Better naming over comments** - Use descriptive names; comment only the "why," not the "what"
- **Validate all inputs** - Never trust user input; validate and sanitize at boundaries
- **Never hardcode secrets** - Use environment variables or secure credential stores
- **Keep changes focused** - Reasonable PR sizes with clear, single purposes

---

## Security Requirements (Critical)

🔒 **Non-negotiable security rules for all code**:

- Never hardcode credentials, secrets, tokens, or API keys
- Validate and sanitize all user inputs at system boundaries
- Use parameterized queries for all database access (never string concatenation)
- Avoid deprecated or insecure libraries; check for CVEs
- Use secure defaults for cryptographic operations
- Be extra careful with authentication and authorization logic
- Follow principle of least privilege

**Detailed security patterns**: [.sdd/skills/techniques/secure-coding.md](.sdd/skills/techniques/secure-coding.md)

---

## Conventional Commits

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/) specification.

### Format
```
<type>[scope][!]: <description>

[body]

[footer(s)]
```

### Allowed Types

| Type | Purpose |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix (reference the bug) |
| `refactor` | Code change that doesn't fix bugs or add features |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `build` | Build, packaging, or dependency changes |
| `chore` | Changes that don't fit other types |
| `docs` | Documentation-only changes |

### Allowed Scopes

`bootresources`, `dhcp`, `dns`, `network`, `power`, `security`, `storage`, `tftp`, `deps`, `ci`

### Guidelines

- Use scope when applicable to categorize commits
- For breaking changes: add `!` before colon AND `BREAKING CHANGE:` footer
- Always reference bugs: `Resolves LP:2066936` or `Resolves GH:123`
- Keep titles concise (<72 chars); use body for detailed reasoning
- Explain **why** a change was made, not just what changed

### Examples

**Breaking change:**
```
feat(bootresources)!: replace tcpdump with maas-netmon

New binary `maas-netmon` introduced for ARP network discovery.

BREAKING CHANGE: Binary doesn't read PCAP format, thus it is not 
possible to pass in stdin or file as an argument anymore.
```

**Bug fix:**
```
fix(network): correct VLAN configuration parsing

Parser incorrectly handled tagged VLANs with non-standard MTU values.

Resolves LP:2066936
```

---

## Navigation: Find Detailed Guidance

### By Language

- **Python**: [.sdd/skills/languages/python-patterns.md](.sdd/skills/languages/python-patterns.md)
  - Pydantic: [python-pydantic.md](.sdd/skills/languages/python-pydantic.md)
  - Async: [python-async.md](.sdd/skills/languages/python-async.md)
  - Testing: [python-testing.md](.sdd/skills/languages/python-testing.md)
  - SQLAlchemy: [python-sqlalchemy.md](.sdd/skills/languages/python-sqlalchemy.md)
  - Django: [django-patterns.md](.sdd/skills/languages/django-patterns.md)
- **Go**: [.sdd/skills/languages/go-patterns.md](.sdd/skills/languages/go-patterns.md)
  - Microcluster: [microcluster-patterns.md](.sdd/skills/languages/microcluster-patterns.md)

### By Subsystem

All subsystem-specific rules are in [.sdd/context/subsystems/](.sdd/context/subsystems/):

- [maasapiserver.md](.sdd/context/subsystems/maasapiserver.md) - FastAPI v3 REST API
- [maasservicelayer.md](.sdd/context/subsystems/maasservicelayer.md) - Business logic & repositories
- [maasserver.md](.sdd/context/subsystems/maasserver.md) - Legacy Django region controller
- [maasagent.md](.sdd/context/subsystems/maasagent.md) - Go-based agent (microcluster)
- [provisioningserver.md](.sdd/context/subsystems/provisioningserver.md) - Rack controller
- [maastemporalworker.md](.sdd/context/subsystems/maastemporalworker.md) - Temporal workflows
- [Other subsystems...](.sdd/context/subsystems/)

### By Technique

- **Code Quality**: [.sdd/skills/techniques/code-quality.md](.sdd/skills/techniques/code-quality.md)
- **Secure Coding**: [.sdd/skills/techniques/secure-coding.md](.sdd/skills/techniques/secure-coding.md)
- **Testing Principles**: [.sdd/skills/techniques/testing-principles.md](.sdd/skills/techniques/testing-principles.md)
- **Input Validation**: [.sdd/skills/techniques/input-validation.md](.sdd/skills/techniques/input-validation.md)
- **Documentation**: [.sdd/skills/techniques/documentation.md](.sdd/skills/techniques/documentation.md)
- **Comments**: [.sdd/skills/techniques/comments.md](.sdd/skills/techniques/comments.md)

### SDD Workflow (Complex Features)

For greenfield features, architectural changes, or cross-cutting concerns:

- **Methodology**: [.sdd/README.md](.sdd/README.md)
- **When to use SDD**: [.sdd/ADOPTION_GUIDE.md](.sdd/ADOPTION_GUIDE.md) (includes decision tree)
- **FAQ**: [.sdd/FAQ.md](.sdd/FAQ.md)
- **Commands**: [.sdd/commands/](.sdd/commands/) (`/specify`, `/plan`, `/tasks`, `/implement`)
- **Examples**: [.sdd/examples/](.sdd/examples/)

---

## Running Checks

Before submitting code:

```bash
# Python linting and formatting
make lint

# Python tests
make test

# Go tests (in respective directories)
cd src/maasagent && make test
cd src/host-info && go test ./...
```

---

## Architecture Overview

MAAS uses a **three-tier architecture** for the v3 API:

- **API Layer** (`maasapiserver`): FastAPI endpoints, Pydantic models
- **Service Layer** (`maasservicelayer`): Business logic
- **Repository Layer** (`maasservicelayer`): SQLAlchemy Core database access

**Legacy components** use Django + Twisted patterns.

**Details**: [.sdd/context/architecture/three-tier-architecture.md](.sdd/context/architecture/three-tier-architecture.md)

---

## Additional Resources

- **Python config**: `pyproject.toml`
- **Go config**: `src/maasagent/go.mod`, `src/host-info/go.mod`
- **Service layer details**: `src/maasservicelayer/README.md`
- **Database migrations**: `src/maasservicelayer/db/alembic/`
- **Skills catalog**: [.sdd/skills/README.md](.sdd/skills/README.md)
- **Context catalog**: [.sdd/context/README.md](.sdd/context/README.md)

---

## Questions and Clarifications

When in doubt:

1. Check existing code in the same subdirectory for patterns
2. Review the subsystem's context file in [.sdd/context/subsystems/](.sdd/context/subsystems/)
3. Consult relevant skills in [.sdd/skills/](.sdd/skills/)
4. Check `pyproject.toml` or `go.mod` for configuration
5. Ask the human reviewer for clarification on architectural decisions

---

## Excluded Directories

Ignore these directories:

- `src/maas-offline-docs` - Documentation artifacts
- `src/maasui` - UI components (separate frontend codebase)

---

**Remember**: This file provides the foundation. Load specific guidance from `.sdd/` based on your task. All detailed patterns, rules, and methodologies are one click away.