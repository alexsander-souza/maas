# Task Validation Checklist

**Task ID:** [TASK-XXX]  
**Task Title:** [Task Title]  
**Reviewer:** [Your Name]  
**Date:** YYYY-MM-DD  
**Status:** Draft | Review | Approved

---

**Reference:** See [Shared Quality Criteria](./_shared-criteria.md) for common standards (documentation quality, MAAS architectural standards, testing standards)

---

## Instructions

This checklist validates that an individual task is well-defined, properly sized, and ready for implementation. Answer each question honestly with Yes or No. A "No" answer indicates an area that needs work before the task can be assigned.

**Target:** All questions should be "Yes" before assigning task to developer

---

## Task Definition

### Clarity

- [ ] **Is the task title clear and descriptive?**
  - Describes what will be built/changed?
  - Specific, not vague?

- [ ] **Is the task description complete?**
  - Clear explanation of what needs to be done?
  - Context provided?
  - Responsibility of component explained?

- [ ] **Is it obvious what "done" looks like?**
  - Clear completion criteria?
  - No ambiguity about scope?

### Purpose

- [ ] **Does the task have clear value?**
  - Contributes to specification requirements?
  - Implements part of technical plan?

- [ ] **Is the task's relationship to the feature clear?**
  - Obvious how this fits into overall feature?
  - Links to spec and plan provided?

---

## Scope and Sizing

### Appropriate Size

- [ ] **Is the task properly sized (1-5 days)?**
  - Not too large (> 5 days)?
  - Not too small (< 0.5 days)?

- [ ] **Does the task modify 1-3 files (or create 1-2)?**
  - Not touching too many files?
  - Not artificially split across multiple tasks?

- [ ] **Is the complexity appropriate for task size?**
  - Complex tasks sized larger?
  - Simple tasks sized smaller?

### Scope Boundaries

- [ ] **Is the task scope well-defined?**
  - Clear what's included?
  - Clear what's excluded?

- [ ] **Is the task focused on single responsibility?**
  - Does one thing well?
  - Not mixing unrelated concerns?

- [ ] **Can the task be completed independently?**
  - Doesn't require simultaneous changes elsewhere?
  - Self-contained unit of work?

### Decomposition Quality

- [ ] **If task is large, should it be split?**
  - Could it be broken into smaller tasks?
  - Would splitting improve parallelization?

- [ ] **If task is small, should it be combined?**
  - Is it too granular?
  - Would combining reduce overhead?

---

## Acceptance Criteria

### Completeness

- [ ] **Are acceptance criteria defined?**
  - At least 3 criteria provided?
  - Cover all aspects of the task?

- [ ] **Are all acceptance criteria testable?**
  - Can verify with yes/no test?
  - Observable and measurable?

- [ ] **Do acceptance criteria cover happy path?**
  - Normal operation validated?
  - Expected behavior tested?

- [ ] **Do acceptance criteria cover error cases?**
  - Failure scenarios identified?
  - Error handling validated?

- [ ] **Do acceptance criteria cover edge cases?**
  - Boundary conditions?
  - Empty inputs, max values, etc.?

### Quality

- [ ] **Is each criterion specific and unambiguous?**
  - No vague statements like "works well"?
  - Concrete, measurable outcomes?

- [ ] **Is each criterion independently verifiable?**
  - Can test each separately?
  - Not dependent on other criteria?

- [ ] **Are acceptance criteria achievable within task scope?**
  - Not requiring work outside task boundaries?
  - Realistic given estimate?

---

## Files and Changes

### File Specification

- [ ] **Are all files to create/modify listed?**
  - Implementation files?
  - Test files?
  - Migration files (if applicable)?

- [ ] **Are file paths accurate and complete?**
  - Full path from project root?
  - No ambiguous file references?

- [ ] **Is the change type specified for each file?**
  - Create vs modify clearly indicated?
  - Expected changes described?

### Change Scope

- [ ] **Are file changes minimal and focused?**
  - Only touching files necessary for task?
  - Not modifying unrelated files?

- [ ] **Is test file count appropriate?**
  - Unit test file included?
  - Integration test file if needed?

- [ ] **Are configuration/migration files identified if needed?**
  - Database migrations?
  - Config file updates?

---

## Testing Requirements

### Test Coverage

- [ ] **Are testing requirements clearly specified?**
  - Types of tests needed (unit, integration, E2E)?
  - What functionality to test?

- [ ] **Is unit testing approach defined?**
  - What to mock?
  - Test scenarios identified?

- [ ] **Are integration testing needs identified?**
  - What to test with real dependencies?
  - Integration points validated?

- [ ] **Are test coverage expectations set?**
  - Coverage targets specified?
  - Critical paths identified?

### Test Strategy

- [ ] **Is testing strategy appropriate for component type?**
  - Models, services, APIs, UI tested appropriately?
  - MAAS testing patterns followed?

- [ ] **Are test dependencies identified?**
  - Test fixtures needed?
  - Test data requirements?
  - Mock/stub requirements?

- [ ] **Can tests be written first (TDD)?**
  - Tests can drive implementation?
  - Test-first approach feasible?

---

## Dependencies

### Task Dependencies

- [ ] **Are prerequisite tasks identified?**
  - Tasks that must complete first?
  - Dependencies on other work?

- [ ] **Are dependencies accurate and minimal?**
  - Only true dependencies listed?
  - No unnecessary dependencies?

- [ ] **Is dependency status known?**
  - Are prerequisite tasks complete?
  - Timeline for dependency completion clear?

### Technical Dependencies

- [ ] **Are code dependencies identified?**
  - Which existing components will be used?
  - Required interfaces/APIs documented?

- [ ] **Are external dependencies noted?**
  - Third-party libraries?
  - External services?
  - Database schemas?

- [ ] **Are dependency interfaces stable?**
  - APIs won't change during implementation?
  - Safe to depend on?

---

## Implementation Guidance

### Technical Direction

- [ ] **Is implementation approach suggested?**
  - General strategy provided?
  - Key technical decisions made?

- [ ] **Are integration points clear?**
  - How to integrate with existing code?
  - Which existing patterns to follow?

- [ ] **Are potential pitfalls identified?**
  - Common mistakes to avoid?
  - Tricky areas highlighted?

### Code Quality

- [ ] **Are code quality expectations clear?**
  - Style guide to follow?
  - Standards to maintain?

- [ ] **Is minimal-change integration expected?**
  - Preserve existing code structure?
  - Surgical modifications only?

- [ ] **Are refactoring boundaries set?**
  - What can/can't be refactored?
  - Scope limits clear?

---

## Alignment with Plan and Spec

### Technical Plan Alignment

- [ ] **Does task implement component from technical plan?**
  - Clear mapping to plan component?
  - Implements planned architecture?

- [ ] **Does task follow planned design?**
  - Matches architectural decisions?
  - Uses specified technologies?

- [ ] **Is task consistent with overall architecture?**
  - Fits into system design?
  - No architectural conflicts?

### Specification Alignment

- [ ] **Does task contribute to spec requirements?**
  - Addresses at least one acceptance criterion from spec?
  - Supports user journeys?

- [ ] **Is task necessary for feature completion?**
  - Required for MVP?
  - Not gold-plating?

- [ ] **Does task respect spec boundaries?**
  - Not implementing out-of-scope features?
  - Stays within defined limits?

---

## Independent Testability

### Isolation

- [ ] **Can task be tested independently?**
  - Doesn't require other incomplete tasks?
  - Self-contained validation?

- [ ] **Can task be developed in isolation?**
  - Doesn't block other developers?
  - Can work in parallel with other tasks?

- [ ] **Can task be reviewed independently?**
  - Standalone code review possible?
  - Doesn't require reviewing other tasks?

### Integration

- [ ] **Are integration test points identified?**
  - How to verify integration with dependencies?
  - Integration test scenarios defined?

- [ ] **Can integration be validated incrementally?**
  - Don't need all components complete?
  - Can mock missing pieces?

---

## Estimation

### Effort Estimate

- [ ] **Is effort estimate provided?**
  - Days or story points specified?
  - Estimate size category clear (S/M/L)?

- [ ] **Is estimate realistic?**
  - Based on actual complexity?
  - Includes testing time?
  - Includes review time?

- [ ] **Does estimate account for all work?**
  - Implementation time?
  - Testing time?
  - Documentation time?
  - Code review cycles?

### Estimate Validation

- [ ] **Is estimate based on similar past work?**
  - Reference tasks identified?
  - Historical data considered?

- [ ] **Are estimation risks acknowledged?**
  - Unknowns identified?
  - Buffer included if needed?

- [ ] **Does estimate align with task size?**
  - Small tasks = 1-2 days?
  - Medium tasks = 2-4 days?
  - Large tasks = 3-5 days?

---

## Assignment Readiness

### Developer Assignment

- [ ] **Is task ready to be assigned?**
  - All information available?
  - No blocking unknowns?

- [ ] **Are skill requirements identified?**
  - What expertise needed?
  - Which developer(s) can take this?

- [ ] **Is task at right level for team?**
  - Not too junior?
  - Not too senior?
  - Good learning opportunity?

### Prerequisites

- [ ] **Are all prerequisites met?**
  - Dependency tasks complete?
  - Required approvals obtained?
  - Resources available?

- [ ] **Is development environment ready?**
  - Tools available?
  - Access granted?
  - Infrastructure provisioned?

---

## Documentation

### Task Documentation Quality

- [ ] **Is task well-written?**
  - Clear language?
  - No jargon without explanation?
  - Good grammar?

- [ ] **Is task well-organized?**
  - Logical structure?
  - Easy to scan?
  - All sections complete?

- [ ] **Are examples provided where helpful?**
  - Code snippets?
  - Mockups?
  - Sample data?

### References

- [ ] **Are references to spec and plan included?**
  - Links provided?
  - Section references specific?

- [ ] **Are related tasks referenced?**
  - Dependencies linked?
  - Related work identified?

- [ ] **Are relevant docs/resources linked?**
  - API documentation?
  - Design documents?
  - Existing similar code?

---

## Risk Assessment

### Technical Risks

- [ ] **Are technical risks identified?**
  - Complexity challenges?
  - Integration challenges?
  - Unknown factors?

- [ ] **Are mitigation strategies provided?**
  - How to reduce risk?
  - Fallback options?

- [ ] **Are unknowns acknowledged?**
  - What needs investigation?
  - When to ask for help?

### Schedule Risks

- [ ] **Are schedule risks identified?**
  - What could delay task?
  - Dependency delays possible?

- [ ] **Is there a backup plan?**
  - Alternative approaches?
  - Scope reduction options?

---

## MAAS-Specific Validation

### MAAS Patterns

- [ ] **Does task follow MAAS architectural patterns?**
  - Repository-Service-API pattern?
  - Event-driven where appropriate?

- [ ] **Does task use MAAS conventions?**
  - Naming conventions?
  - File organization?
  - Testing patterns?

- [ ] **Does task leverage existing MAAS code?**
  - Using existing utilities?
  - Following existing examples?
  - Not reinventing wheels?

### MAAS Integration

- [ ] **Is MAAS context considered?**
  - Infrastructure management domain?
  - Multi-region awareness?
  - Scale requirements?

- [ ] **Are MAAS-specific concerns addressed?**
  - BMC/power management if relevant?
  - Network configuration if relevant?
  - Machine lifecycle if relevant?

---

## Quality Gates

### Definition of Ready

- [ ] **Does task meet "Definition of Ready"?**
  - All information complete?
  - Dependencies resolved?
  - Acceptance criteria clear?
  - Ready to start implementation?

### Definition of Done

- [ ] **Is "Definition of Done" clear?**
  - Acceptance criteria met?
  - Tests passing?
  - Code reviewed?
  - Documentation updated?

---

## Summary

**Total Questions:** 127  
**Yes Answers:** [ ]  
**No Answers:** [ ]  
**Percentage Complete:** [ ]%

**Issues to Address:**
[List any sections with "No" answers]

**Blocking Issues:**
[Any critical "No" answers that prevent task assignment]

**Recommendations:**
- [ ] **Ready for Assignment** (All critical questions are "Yes")
- [ ] **Needs Minor Clarification** (Few "No" answers, non-blocking)
- [ ] **Needs Revision** (Several "No" answers, important gaps)
- [ ] **Not Ready** (Many "No" answers or blocking issues)

---

## Action Items

**Before Assignment:**
1. [Action item 1]
2. [Action item 2]
3. [Action item 3]

**During Implementation:**
- [Guidance or warnings for developer]

**During Review:**
- [Specific review focus areas]

---

## Sign-off

**Task Author:** [Name]  
**Author Sign-off Date:** YYYY-MM-DD  

**Reviewer:** [Name]  
**Review Date:** YYYY-MM-DD  
**Review Status:** [ ] Approved [ ] Needs Revision  

**Tech Lead:** [Name]  
**Approval Date:** YYYY-MM-DD  

**Assigned To:** [Developer Name]  
**Assignment Date:** YYYY-MM-DD  

---

## Notes

[Any additional context, warnings, or guidance for the developer]