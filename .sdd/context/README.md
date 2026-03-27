# MAAS Context System

This directory contains structured contextual information about MAAS architecture, subsystems, and design patterns. The context system provides AI coding agents and developers with detailed guidance on specific areas of the codebase.

## Directory Structure

```
.sdd/context/
├── README.md                    # This file
├── architecture/                # Architectural patterns and design principles
│   ├── three-tier-architecture.md
│   ├── repository-pattern.md
│   └── api-versioning.md
└── subsystems/                  # Subsystem-specific guidelines
    ├── maasapiserver.md
    ├── maasservicelayer.md
    ├── maasagent.md
    └── ...
```

## Purpose

The context system serves multiple purposes:

1. **Architectural Guidance**: Explains high-level design patterns and architectural decisions used throughout MAAS
2. **Subsystem Documentation**: Provides detailed information about each major subsystem, including technology stack, patterns, and constraints
3. **Integration Points**: Documents how different subsystems interact and integrate with each other
4. **Testing Requirements**: Specifies testing approaches and requirements for each subsystem
5. **Reference Material**: Links to related skills, templates, and examples

## Navigation

### By Architecture Pattern

If you need to understand a specific architectural pattern or design principle used in MAAS:

- **Three-tier architecture**: See `architecture/three-tier-architecture.md`
- **Repository pattern**: See `architecture/repository-pattern.md`
- **API versioning**: See `architecture/api-versioning.md`

### By Subsystem

If you're working in a specific directory or subsystem, consult the corresponding file in `subsystems/`:

- `src/maasapiserver` → `subsystems/maasapiserver.md`
- `src/maasservicelayer` → `subsystems/maasservicelayer.md`
- `src/maasagent` → `subsystems/maasagent.md`
- `src/host-info` → `subsystems/host-info.md`
- And others...

### By Technology

Each subsystem file lists its technology stack. Search for the technology you're using:

- **Python + FastAPI**: See `maasapiserver.md`
- **Python + SQLAlchemy**: See `maasservicelayer.md`
- **Go + microcluster**: See `maasagent.md`
- **Django (legacy)**: See `maasserver.md`

## Relationship to Other .sdd Components

The context system works alongside other .sdd directories:

- **`.sdd/skills/`**: Context files reference specific skills needed for each subsystem
- **`.sdd/templates/`**: Architecture patterns may reference code templates
- **`.sdd/examples/`**: Subsystem files may point to relevant examples
- **`.sdd/specs/`**: Technical specifications for features and APIs

## When to Consult Context

Use context files when:

- Starting work in a new subsystem
- Understanding architectural constraints
- Choosing appropriate patterns for new features
- Determining testing requirements
- Understanding integration between subsystems
- Making architectural decisions

## Maintenance

Context files should be updated when:

- Architectural patterns change
- New subsystems are added
- Technology stacks are upgraded
- Testing approaches evolve
- Integration points change

Keep context files synchronized with `AGENTS.md` and actual codebase practices.