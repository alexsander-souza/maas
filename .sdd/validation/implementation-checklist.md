# Implementation Validation Checklist

**Task ID:** [TASK-XXX]  
**Task Title:** [Task Title]  
**Developer:** [Your Name]  
**Date:** YYYY-MM-DD  
**Status:** In Progress | Ready for Review | Approved

---

**Reference:** See [Shared Quality Criteria](./_shared-criteria.md) for all common standards (documentation, architecture, testing, code quality, security, performance, minimal change integration)

---

## Instructions

This checklist validates that implementation work is complete, high-quality, and ready for code review. Use this before submitting a pull request to ensure all quality standards are met.

**Target:** All questions should be "Yes" before requesting code review

---

## Test-Driven Development

### Test-First Approach

- [ ] **Were tests written before implementation code?**
  - Followed RED-GREEN-REFACTOR cycle?
  - Not writing tests after the fact?

- [ ] **Does every new function/method have tests?**
  - No untested code?
  - Coverage for all public interfaces?

- [ ] **Were tests used to drive design?**
  - Design decisions influenced by testability?
  - Interfaces shaped by test needs?

### Test Coverage

- [ ] **Do tests cover happy path scenarios?**
  - Normal operation validated?
  - Expected behavior tested?

- [ ] **Do tests cover error cases?**
  - Exception handling tested?
  - Invalid inputs handled?
  - Failure scenarios validated?

- [ ] **Do tests cover edge cases?**
  - Boundary conditions tested?
  - Empty inputs, nulls, max values?
  - Unusual but valid inputs?

- [ ] **Is code coverage adequate (>90% for new code)?**
  - Critical paths fully covered?
  - No significant gaps?

### Test Quality

- [ ] **Are tests clear and focused?**
  - One behavior per test?
  - Test names describe what's being tested?

- [ ] **Do tests follow Arrange-Act-Assert pattern?**
  - Setup, execution, verification clearly separated?
  - Easy to understand test flow?

- [ ] **Are tests independent?**
  - Tests don't depend on each other?
  - Can run in any order?
  - No shared state between tests?

- [ ] **Do tests use appropriate mocking?**
  - External dependencies mocked?
  - Not mocking implementation details?
  - Integration tests use real dependencies where appropriate?

- [ ] **Are test assertions meaningful?**
  - Testing actual behavior, not just "not null"?
  - Specific, verifiable outcomes?

---

## Acceptance Criteria Validation

### Criteria Coverage

- [ ] **Are all task acceptance criteria met?**
  - Every criterion has passing test?
  - All functionality implemented?

- [ ] **Can you demonstrate each criterion is met?**
  - Clear proof of completion?
  - Tests validate each requirement?

- [ ] **Have acceptance criteria been verified, not just assumed?**
  - Actually ran tests to confirm?
  - Manually tested where appropriate?

### Requirements Traceability

- [ ] **Does implementation address spec requirements?**
  - Contributes to user stories?
  - Supports user journeys?

- [ ] **Does implementation follow technical plan?**
  - Matches planned architecture?
  - Uses specified technologies?
  - Follows design decisions?

---

## Task Boundary Compliance

### Scope Adherence

- [ ] **Did you only change what the task specified?**
  - No scope creep?
  - Stayed within task boundaries?

- [ ] **Are file changes limited to those listed in task?**
  - No additional files modified?
  - Only specified files touched?

- [ ] **Did you avoid "while I'm here" changes?**
  - No unrelated refactoring?
  - No fixing unrelated bugs?
  - No style cleanup of untouched code?

### Focus

- [ ] **Is implementation focused on single responsibility?**
  - Does one thing well?
  - Not mixing multiple concerns?

- [ ] **Did you resist adding "nice to have" features?**
  - Only implemented what's required?
  - Deferred enhancements to future tasks?

---

## Minimal-Change Integration

### Code Preservation

- [ ] **Did you preserve existing code structure?**
  - Existing organization maintained?
  - No unnecessary restructuring?

- [ ] **Did you match existing patterns?**
  - New code looks like existing code?
  - Consistent style and approach?

- [ ] **Are changes minimal and surgical?**
  - Smallest possible modifications?
  - Only touched necessary lines?

### Integration Quality

- [ ] **Did you integrate rather than replace?**
  - Added to existing code rather than rewriting?
  - Preserved working functionality?

- [ ] **Are existing interfaces preserved?**
  - No breaking changes to public APIs?
  - Backward compatibility maintained?

- [ ] **Did you use existing utilities and patterns?**
  - Leveraged existing MAAS code?
  - Didn't reinvent wheels?

---

## Code Quality

### Readability

- [ ] **Is code easy to read and understand?**
  - Clear logic flow?
  - Self-documenting where possible?

- [ ] **Are variable and function names descriptive?**
  - Names reveal intent?
  - No cryptic abbreviations?
  - No misleading names?

- [ ] **Is code properly formatted?**
  - Consistent indentation?
  - Proper spacing?
  - Linter passes without errors?

- [ ] **Is complex logic explained with comments?**
  - Non-obvious code has explanatory comments?
  - Comments explain "why," not "what"?

### Design Quality

- [ ] **Is code DRY (Don't Repeat Yourself)?**
  - No duplicated logic?
  - Common code extracted to helpers?

- [ ] **Are functions/methods appropriately sized?**
  - Not too long (< 50 lines generally)?
  - Single responsibility?

- [ ] **Is coupling loose and cohesion high?**
  - Components minimally dependent?
  - Related functionality grouped?

- [ ] **Are magic numbers replaced with constants?**
  - Named constants used?
  - Intent clear?

### Error Handling

- [ ] **Are errors handled appropriately?**
  - Expected errors caught and handled?
  - Meaningful error messages?

- [ ] **Are resources cleaned up properly?**
  - Context managers used?
  - No resource leaks?

- [ ] **Are edge cases handled?**
  - Null checks where needed?
  - Boundary conditions addressed?

---

## AGENTS.md Compliance

### Code Standards

- [ ] **Does code follow AGENTS.md quality standards?**
  - Meets documented code quality requirements?
  - Follows team conventions?

- [ ] **Is code maintainable and extensible?**
  - Future changes will be easy?
  - No technical debt introduced?

- [ ] **Does code follow SOLID principles?**
  - Single Responsibility?
  - Open/Closed?
  - Liskov Substitution?
  - Interface Segregation?
  - Dependency Inversion?

### Best Practices

- [ ] **Are security best practices followed?**
  - Input validation?
  - No SQL injection vulnerabilities?
  - No XSS vulnerabilities?
  - Sensitive data protected?

- [ ] **Are performance considerations addressed?**
  - No obvious performance issues?
  - Efficient algorithms used?
  - Database queries optimized?

- [ ] **Is error handling robust?**
  - Fails gracefully?
  - User-friendly error messages?
  - Appropriate logging?

---

## MAAS-Specific Patterns

### Architectural Patterns

- [ ] **Does code follow MAAS repository-service pattern?**
  - Repositories for data access?
  - Services for business logic?
  - Proper layering?

- [ ] **Are Django patterns followed correctly?**
  - Models, managers, migrations done right?
  - Django best practices observed?

- [ ] **Is Twisted async code handled properly?**
  - Deferreds used correctly?
  - inlineCallbacks where appropriate?
  - Proper error handling in async code?

### MAAS Conventions

- [ ] **Are MAAS naming conventions followed?**
  - File names match conventions?
  - Class/function names consistent?

- [ ] **Is code organized according to MAAS structure?**
  - Files in correct directories?
  - Module organization follows project standards?

- [ ] **Are MAAS testing patterns used?**
  - Factory fixtures used appropriately?
  - MAASTestCase base classes?
  - Test organization follows conventions?

### Domain Appropriateness

- [ ] **Is code appropriate for infrastructure management domain?**
  - Handles scale requirements?
  - Multi-region awareness if relevant?
  - Machine lifecycle considerations if relevant?

---

## Documentation

### Code Documentation

- [ ] **Are all public functions/methods documented?**
  - Docstrings present?
  - Parameters described?
  - Return values documented?
  - Exceptions documented?

- [ ] **Are docstrings clear and helpful?**
  - Explain purpose?
  - Provide usage examples if complex?
  - Follow project docstring conventions?

- [ ] **Are complex algorithms explained?**
  - Comments clarify approach?
  - References to resources if needed?

### External Documentation

- [ ] **Are README updates made if needed?**
  - Public API changes documented?
  - New features explained?

- [ ] **Are API docs updated if applicable?**
  - Endpoint documentation current?
  - Request/response formats documented?

- [ ] **Are migration guides created if needed?**
  - Breaking changes documented?
  - Upgrade path explained?

---

## Testing Execution

### Test Results

- [ ] **Do all new tests pass?**
  - 100% of new tests green?
  - No flaky tests?

- [ ] **Do all existing tests still pass?**
  - No regressions introduced?
  - Full test suite run and passing?

- [ ] **Have tests been run multiple times?**
  - Consistent results?
  - No race conditions?

### Test Environments

- [ ] **Have tests been run locally?**
  - Passed on your development machine?

- [ ] **Have integration tests been run?**
  - Real database tests passing?
  - External integrations working?

- [ ] **Will tests pass in CI/CD?**
  - No dependencies on local environment?
  - Reproducible in clean environment?

---

## Code Review Readiness

### Self-Review

- [ ] **Have you reviewed your own code?**
  - Read through all changes?
  - Caught obvious issues?

- [ ] **Are there no debug artifacts?**
  - No console.log or print statements?
  - No commented-out code?
  - No TODO comments without tickets?

- [ ] **Is code consistent throughout?**
  - Consistent style in all files?
  - Consistent naming?
  - Consistent patterns?

### Pull Request Quality

- [ ] **Is PR description clear and complete?**
  - Summary of changes?
  - References to task, spec, plan?
  - Testing notes?

- [ ] **Are commit messages meaningful?**
  - Describe what and why?
  - Reference task IDs?

- [ ] **Is diff reviewable?**
  - Changes are focused?
  - No massive files?
  - Easy to understand what changed?

---

## Integration Verification

### Component Integration

- [ ] **Does code integrate correctly with dependencies?**
  - Calls to other components work?
  - Data flows correctly?

- [ ] **Have integration points been tested?**
  - Integration tests pass?
  - Manual integration testing done?

- [ ] **Are interfaces used correctly?**
  - API contracts followed?
  - Expected parameters provided?
  - Return values handled properly?

### System Integration

- [ ] **Does feature work end-to-end?**
  - Complete user journey tested?
  - All layers working together?

- [ ] **Are external integrations working?**
  - Third-party APIs called correctly?
  - Database operations successful?
  - Event publishing/consuming works?

---

## Database Changes (if applicable)

### Migrations

- [ ] **Are database migrations created correctly?**
  - Migration files generated?
  - Migration tested locally?
  - Rollback tested?

- [ ] **Are migrations safe for production?**
  - No data loss?
  - Can run with minimal downtime?
  - Backwards compatible if needed?

- [ ] **Are indexes created where needed?**
  - Query performance considered?
  - Proper indexes for lookups?

### Data Integrity

- [ ] **Is data integrity maintained?**
  - Constraints enforced?
  - Referential integrity preserved?

- [ ] **Is data validation in place?**
  - Invalid data rejected?
  - Validation at appropriate layers?

---

## UI Changes (if applicable)

### Functionality

- [ ] **Does UI work as expected?**
  - User interactions functional?
  - State management correct?
  - Error states handled?

- [ ] **Is UI responsive?**
  - Works on different screen sizes?
  - Mobile-friendly if required?

### Accessibility

- [ ] **Is UI accessible?**
  - Keyboard navigation works?
  - Screen reader friendly?
  - ARIA labels present?
  - Color contrast adequate?

### Testing

- [ ] **Are component tests comprehensive?**
  - User interactions tested?
  - State changes validated?
  - Error scenarios covered?

---

## Performance

### Efficiency

- [ ] **Is code performant?**
  - No obvious performance issues?
  - Meets performance requirements from spec?

- [ ] **Are queries optimized?**
  - No N+1 queries?
  - Proper use of select_related/prefetch_related?
  - Indexes utilized?

- [ ] **Are resources used efficiently?**
  - Memory usage reasonable?
  - No resource leaks?
  - Proper cleanup of connections?

### Scalability

- [ ] **Will code scale appropriately?**
  - Handles expected data volumes?
  - Performance degrades gracefully?

---

## Security

### Input Validation

- [ ] **Are all inputs validated?**
  - User inputs sanitized?
  - Type checking in place?
  - Range validation where appropriate?

- [ ] **Are security vulnerabilities addressed?**
  - No SQL injection risks?
  - No XSS vulnerabilities?
  - No CSRF issues?

### Authentication and Authorization

- [ ] **Are auth checks in place?**
  - Authentication required where needed?
  - Authorization enforced?
  - Permissions checked?

### Data Protection

- [ ] **Is sensitive data protected?**
  - Passwords hashed?
  - Secrets not in code?
  - PII handled appropriately?

---

## Deployment Readiness

### Configuration

- [ ] **Are configuration needs documented?**
  - New settings identified?
  - Defaults appropriate?
  - Environment-specific config handled?

- [ ] **Are deployment steps clear?**
  - Migration order specified?
  - Deployment dependencies noted?

### Monitoring

- [ ] **Is appropriate logging in place?**
  - Important events logged?
  - Log levels appropriate?
  - No sensitive data in logs?

- [ ] **Are errors properly reported?**
  - Exceptions logged with context?
  - User-facing errors helpful?

---

## Final Checks

### Completeness

- [ ] **Is implementation actually complete?**
  - All acceptance criteria met?
  - All tests passing?
  - All files created/modified?
  - All documentation updated?

- [ ] **Is nothing missing?**
  - No TODOs left unaddressed?
  - No placeholder code?
  - No "to be implemented" stubs?

### Quality Confidence

- [ ] **Are you confident in this code?**
  - Would you approve this in code review?
  - Would you deploy this to production?
  - Would you maintain this code?

- [ ] **Is this your best work?**
  - Code quality meets your standards?
  - Nothing you're embarrassed about?
  - Ready for team scrutiny?

---

## Summary

**Total Questions:** 189  
**Yes Answers:** [ ]  
**No Answers:** [ ]  
**Percentage Complete:** [ ]%

**Issues to Fix Before Review:**
[List any "No" answers that need to be addressed]

**Critical Issues:**
[Any blocking quality problems]

**Readiness Assessment:**
- [ ] **Ready for Code Review** (All critical questions are "Yes")
- [ ] **Needs Minor Fixes** (Few "No" answers, quick to address)
- [ ] **Needs Significant Work** (Many "No" answers or critical gaps)
- [ ] **Not Ready** (Major quality issues present)

---

## Pre-Review Actions

**Before requesting review:**
1. [ ] Run full test suite locally
2. [ ] Run linter and fix all issues
3. [ ] Self-review all changes
4. [ ] Update task document with completion status
5. [ ] Create pull request with complete description
6. [ ] Request reviewers

---

## Code Review Notes

**For Reviewers:**
- Focus areas: [Specific areas needing extra attention]
- Known limitations: [Any deliberate trade-offs or limitations]
- Testing notes: [How to test/verify changes]
- Deployment notes: [Any special deployment considerations]

---

## Sign-off

**Developer:** [Name]  
**Self-Review Date:** YYYY-MM-DD  
**Self-Review Status:** [ ] Pass [ ] Needs Work  

**Code Reviewer:** [Name]  
**Review Date:** YYYY-MM-DD  
**Review Status:** [ ] Approved [ ] Needs Changes [ ] Rejected  

**Merge Date:** YYYY-MM-DD  
**Deployed:** YYYY-MM-DD

---

## Post-Implementation Notes

**Lessons Learned:**
[What went well, what could be improved]

**Technical Debt:**
[Any technical debt incurred, with tickets for future cleanup]

**Future Improvements:**
[Ideas for future enhancements]