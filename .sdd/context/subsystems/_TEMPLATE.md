# [Subsystem Name] Subsystem

## Purpose

[2-3 sentences describing what this subsystem does and why it exists. Focus on the core responsibility and its role in the MAAS architecture.]

**Status**: [If applicable: "Active development" / "Maintenance mode" / "Deprecated"]

## Location

`[path/to/subsystem]`

## Technology Stack

### Core Technologies
- **[Language]**: [Version]
- **[Framework]**: [Brief description]
- **[Database/Service]**: [Brief description]

### Key Libraries
- **[Library]**: [Purpose in this subsystem]
- **[Library]**: [Purpose in this subsystem]

## Architectural Constraints

[Only include if there are specific architectural constraints unique to this subsystem]

### [Constraint Name]
[Brief explanation of why this constraint exists and what it means for development]

### [Constraint Name]
[Brief explanation]

## Key Patterns

> **Note**: Only include patterns that are unique to or especially important for this subsystem.
> For common patterns, link to the relevant skill documentation.

### [Unique Pattern Name]

[Brief explanation of when and why to use this pattern]

```[language]
// Minimal example showing the pattern
// Focus on the key concept, not exhaustive details
```

### [Unique Pattern Name]

[Explanation]

```[language]
// Example
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

[Only include subsystem-specific testing considerations that are unique, such as:]
- Special test fixtures or setup required for this subsystem
- Integration test requirements specific to external dependencies
- Performance testing considerations unique to this subsystem

## Development Guidelines

### Code Organization
[Subsystem-specific organization patterns - keep brief]

### Dependency Management
[Only if there are unique dependency concerns]

### Error Handling
[Only subsystem-specific error handling patterns]

## Integration Points

### [External System/Subsystem Name]
- **Purpose**: [Why this integration exists]
- **Interface**: [API/Protocol used]
- **Key Considerations**: [Important details for developers]

### [External System/Subsystem Name]
- **Purpose**: 
- **Interface**: 
- **Key Considerations**: 

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

[Only include pitfalls that are specific to this subsystem]

### [Subsystem-Specific Pitfall]
[What to avoid and why]

```[language]
// WRONG: 
// [Bad example]

// Correct:
// [Good example]
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md) for comprehensive security guidelines.

[Only include security considerations unique to this subsystem, such as:]
- Specific authentication/authorization requirements
- Data sensitivity concerns
- Network exposure considerations
- Subsystem-specific security constraints

## Performance Considerations

[Only include if there are significant performance concerns unique to this subsystem]

### [Performance Concern]
[Brief explanation and guidance]

## Additional Resources

- [Link to design documents]
- [Link to architecture diagrams]
- [Link to external documentation]

---

## Instructions for Using This Template

1. **Keep It Concise**: Target 300-400 lines maximum
2. **Link, Don't Duplicate**: Reference common patterns rather than repeating them
3. **Focus on Uniqueness**: Only document what makes this subsystem different
4. **Remove Boilerplate**: Delete any template sections that don't apply
5. **Be Specific**: Use concrete examples, not abstract descriptions
6. **No "Related Skills" Section**: Use inline links instead
7. **Minimal Configuration**: Only document non-obvious configuration concerns