# Content Reorganization Migration Guide

This document explains the recent reorganization of MAAS development guidelines and helps you find content that has been moved from `AGENTS.md` to the `.sdd/` structure.

## Why We Reorganized

### Previous Structure (AGENTS.md only)
- **500+ lines** in a single file
- Language guidelines mixed with subsystem rules
- Difficult to find specific guidance
- Hard to maintain and update
- No clear separation between "how to code" and "what to build"

### New Structure (.sdd/ + lean AGENTS.md)
- **Organized by concern**: Languages, techniques, subsystems, workflows
- **Discoverable**: Clear navigation and categorization
- **Maintainable**: Each topic in its own file
- **Scalable**: Easy to add new patterns and guidelines
- **SDD-enabled**: Structured methodology for complex features

## What Changed

### AGENTS.md is Now a Router
`AGENTS.md` has been refactored from a 500-line reference document into a **lean entry point (~150 lines)** that:
- Provides quick-start guidance
- States core principles
- Routes to detailed guidance in `.sdd/`
- Keeps critical security reminders visible
- Documents Conventional Commits (still central to all work)

### Detailed Content Moved to .sdd/
All detailed guidelines now live in organized subdirectories:
- **Skills** (`.sdd/skills/`): Reusable patterns and techniques
- **Context** (`.sdd/context/`): MAAS-specific constraints and architecture
- **Workflow** (`.sdd/`): Spec-Driven Development methodology

## Content Location Mapping

### Language Guidelines

| Old Location (AGENTS.md) | New Location | Description |
|--------------------------|--------------|-------------|
| Python Guidelines → Code Style | `.sdd/skills/languages/python-patterns.md` | Python coding standards |
| Python Guidelines → Type Hints | `.sdd/skills/languages/python-patterns.md` | Type annotation guidance |
| Python Guidelines → Pydantic v2 | `.sdd/skills/languages/python-pydantic.md` | Pydantic model patterns |
| Python Guidelines → Async Code | `.sdd/skills/languages/python-async.md` | Async/await patterns |
| Python Guidelines → Database Access | `.sdd/skills/languages/python-sqlalchemy.md` | SQLAlchemy Core usage |
| Python Guidelines → Testing | `.sdd/skills/languages/python-testing.md` | pytest patterns |
| Python Guidelines → Django | `.sdd/skills/languages/django-patterns.md` | Django-specific patterns |
| Go Guidelines | `.sdd/skills/languages/go-patterns.md` | Go coding standards |
| Go Guidelines → microcluster | `.sdd/skills/languages/microcluster-patterns.md` | microcluster architecture |

### Code Quality and Techniques

| Old Location (AGENTS.md) | New Location | Description |
|--------------------------|--------------|-------------|
| Code Quality and Verbosity | `.sdd/skills/techniques/code-quality.md` | Naming, comments, verbosity |
| When to Comment | `.sdd/skills/techniques/comments.md` | Comment guidelines |
| Security Requirements (detailed) | `.sdd/skills/techniques/secure-coding.md` | Security best practices |
| Documentation Standards (detailed) | `.sdd/skills/techniques/documentation.md` | Documentation patterns |
| Testing → Avoid trivial assertions | `.sdd/skills/techniques/testing-principles.md` | Testing philosophy |
| Input Validation | `.sdd/skills/techniques/input-validation.md` | Validation patterns |

### Subsystem-Specific Rules

| Old Location (AGENTS.md) | New Location | Description |
|--------------------------|--------------|-------------|
| `src/maasserver` | `.sdd/context/subsystems/maasserver.md` | Legacy Django region controller |
| `src/maasapiserver` | `.sdd/context/subsystems/maasapiserver.md` | FastAPI v3 API layer |
| `src/maasservicelayer` | `.sdd/context/subsystems/maasservicelayer.md` | Service + Repository layers |
| `src/maastemporalworker` | `.sdd/context/subsystems/maastemporalworker.md` | Temporal workers |
| `src/provisioningserver` | `.sdd/context/subsystems/provisioningserver.md` | Rack controller |
| `src/metadataserver` | `.sdd/context/subsystems/metadataserver.md` | Cloud-init metadata |
| `src/maascli` | `.sdd/context/subsystems/maascli.md` | CLI interface |
| `src/apiclient` | `.sdd/context/subsystems/apiclient.md` | API client library |
| `src/maascommon` | `.sdd/context/subsystems/maascommon.md` | Common utilities |
| `src/maastesting` | `.sdd/context/subsystems/maastesting.md` | Testing utilities |
| `src/maasagent` | `.sdd/context/subsystems/maasagent.md` | Go-based agent |
| `src/host-info` | `.sdd/context/subsystems/host-info.md` | Hardware info collector |
| `src/perftests` | `.sdd/context/subsystems/perftests.md` | Performance testing |
| `src/tests` | `.sdd/context/subsystems/tests.md` | Integration tests |

### Architecture Patterns

| Old Location (AGENTS.md) | New Location | Description |
|--------------------------|--------------|-------------|
| Common Patterns (v3 API) | `.sdd/context/architecture/three-tier-architecture.md` | Repository → Service → API pattern |
| Repository patterns | `.sdd/context/architecture/repository-pattern.md` | Repository implementation |
| API versioning mentions | `.sdd/context/architecture/api-versioning.md` | API versioning strategy |

### Workflow and Methodology

| New Content (Added) | Location | Description |
|---------------------|----------|-------------|
| Spec-Driven Development | `.sdd/README.md` | Full SDD methodology |
| SDD Quick Start | `AGENTS.md` (kept in-file) | When to use SDD |
| Adoption Guide | `.sdd/ADOPTION_GUIDE.md` | Decision tree, integration |
| FAQ | `.sdd/FAQ.md` | Common questions |
| Commands | `.sdd/commands/` | `/specify`, `/plan`, `/tasks`, `/implement` |
| Roles | `.sdd/roles/` | Role definitions per phase |
| Examples | `.sdd/examples/` | End-to-end workflows |

## How to Navigate the New Structure

### Quick Reference by Task Type

**I need to write Python code:**
1. Start with `AGENTS.md` for core principles
2. Consult `.sdd/skills/languages/python-patterns.md`
3. Check subsystem-specific rules in `.sdd/context/subsystems/[your-subsystem].md`

**I need to work on a specific subsystem:**
1. Start with `AGENTS.md` for core principles
2. Go directly to `.sdd/context/subsystems/[subsystem-name].md`
3. Follow links to relevant language and technique skills

**I'm starting a new feature:**
1. Use the decision tree in `.sdd/ADOPTION_GUIDE.md`
2. If complex, follow SDD workflow (`.sdd/README.md`)
3. If simple, follow `AGENTS.md` for direct implementation

**I need to understand MAAS architecture:**
1. Browse `.sdd/context/architecture/` for system-wide patterns
2. Check `.sdd/context/subsystems/` for component-specific constraints

**I have questions:**
1. Check `.sdd/FAQ.md`
2. Consult `AGENTS.md` → Questions and Clarifications section

### Directory Structure Overview

```
.sdd/
├── README.md                          # SDD methodology overview
├── ADOPTION_GUIDE.md                  # When/how to use SDD
├── FAQ.md                             # Common questions
├── MIGRATION.md                       # This file
│
├── commands/                          # SDD phase commands
│   ├── specify.md
│   ├── plan.md
│   ├── tasks.md
│   └── implement.md
│
├── skills/                            # Reusable patterns
│   ├── languages/                    # Python, Go, Django, SQLAlchemy
│   ├── techniques/                   # Security, testing, quality
│   ├── domains/                      # MAAS-specific knowledge
│   └── compositions/                 # Pre-composed skill sets
│
├── context/                           # MAAS-specific constraints
│   ├── architecture/                 # System-wide patterns
│   └── subsystems/                   # Per-component rules
│
├── roles/                             # SDD role definitions
├── templates/                         # Artifact templates
├── validation/                        # Quality checklists
├── examples/                          # End-to-end examples
│
├── specs/                             # Feature specifications
├── plans/                             # Technical plans
└── tasks/                             # Task breakdowns
```

## Transition Period

### What's Staying in AGENTS.md

The following content **remains in AGENTS.md** and is **not moving**:
- ✅ Project overview and purpose
- ✅ General principles (modular, testable, explicit)
- ✅ Core security reminders (never hardcode secrets, validate inputs)
- ✅ SDD quick-start guidance
- ✅ Conventional Commits (complete section)
- ✅ Quick reference to language/subsystem guidelines
- ✅ Running checks and tooling
- ✅ Questions and clarifications section

### What Moved to .sdd/

Detailed content that moved (with links from AGENTS.md):
- ❌ Detailed Python guidelines → `.sdd/skills/languages/`
- ❌ Detailed Go guidelines → `.sdd/skills/languages/`
- ❌ Detailed security practices → `.sdd/skills/techniques/`
- ❌ Detailed code quality rules → `.sdd/skills/techniques/`
- ❌ Subsystem-specific patterns → `.sdd/context/subsystems/`
- ❌ Architectural patterns → `.sdd/context/architecture/`

### No Breaking Changes

**Important**: The reorganization is **additive and backward-compatible**:
- All detailed content still exists, just in better locations
- AGENTS.md provides clear links to migrated content
- No information was removed, only reorganized
- Existing workflows continue to work

## Finding Migrated Content

### Search Strategy

**1. Start with AGENTS.md**
The new lean AGENTS.md has a clear navigation section that routes you to the right place.

**2. Use grep/find for keywords**
All content is in `.md` files:
```bash
# Find content by keyword
grep -r "Pydantic" .sdd/skills/

# Find subsystem rules
ls .sdd/context/subsystems/
```

**3. Browse the README files**
Each major directory has a README.md explaining its contents:
- `.sdd/README.md` - Overall SDD methodology
- `.sdd/skills/README.md` - Skills catalog
- `.sdd/context/README.md` - Context catalog

**4. Check the mapping table above**
Use the tables in this document to quickly locate specific content.

## Benefits of the New Structure

### For AI Agents
- **Faster context loading**: Load only relevant skills/context
- **Better composition**: Combine multiple skills for complex tasks
- **Clearer guidance**: Know which rules apply to which subsystem
- **SDD support**: Structured workflow for complex features

### For Human Developers
- **Easier discovery**: Find guidance by language, subsystem, or technique
- **Focused reading**: Read only what's relevant to your task
- **Better maintainability**: Update patterns in dedicated files
- **Onboarding**: New team members can navigate by topic

### For the Project
- **Scalability**: Easy to add new patterns without bloating AGENTS.md
- **Consistency**: Centralized patterns that multiple files can reference
- **Living documentation**: Skills and context evolve with the codebase
- **Knowledge retention**: Architectural decisions documented in context/

## Validation Approach

### How We Ensure Nothing Was Lost

1. **Content audit**: All AGENTS.md sections mapped to new locations
2. **Link validation**: AGENTS.md links verified to point to correct files
3. **Coverage check**: Every subsystem has corresponding context file
4. **Backward compatibility**: Old patterns still work, new patterns added

### If You Find Missing Content

If you discover content that was in the old AGENTS.md but isn't in the new structure:

1. Check this mapping table first
2. Search `.sdd/` for the topic using `grep -r "keyword" .sdd/`
3. File an issue or update the appropriate `.sdd/` file

## Examples of Using the New Structure

### Example 1: Adding a New FastAPI Endpoint

**Old workflow:**
1. Read all of AGENTS.md (500+ lines)
2. Find Python Guidelines section
3. Find Subdirectory-Specific Rules → maasapiserver
4. Keep entire context in mind

**New workflow:**
1. Read AGENTS.md (~150 lines, 2 minutes)
2. Navigate to `.sdd/context/subsystems/maasapiserver.md`
3. Follow links to `.sdd/skills/languages/python-patterns.md` if needed
4. Load only relevant context

### Example 2: Implementing a Security Fix

**Old workflow:**
1. Read Security Requirements section (generic)
2. Find subsystem rules
3. Infer security patterns

**New workflow:**
1. Read AGENTS.md core security principles
2. Consult `.sdd/skills/techniques/secure-coding.md` for detailed patterns
3. Check subsystem context for specific constraints
4. Reference `.sdd/skills/techniques/input-validation.md` if needed

### Example 3: Starting a New Feature

**Old workflow:**
1. Start coding immediately
2. Discover requirements are unclear
3. Rewrite code multiple times

**New workflow:**
1. Consult `.sdd/ADOPTION_GUIDE.md` decision tree
2. Use SDD if complex: `/specify` → `/plan` → `/tasks` → `/implement`
3. Use direct implementation if simple
4. Follow AGENTS.md standards during implementation

## Getting Help

- **Migration questions**: This document
- **Content location**: Mapping tables above
- **SDD methodology**: [.sdd/README.md](.sdd/README.md)
- **General questions**: [.sdd/FAQ.md](.sdd/FAQ.md)
- **Can't find something**: Search `.sdd/` or ask maintainers

---

**Summary**: Content was reorganized for better discoverability and maintainability. Nothing was removed—everything is now better organized. Use AGENTS.md as your entry point, then navigate to detailed guidance in `.sdd/`.