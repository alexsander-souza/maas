# Implementation Checklist

**Task ID:** [TASK-XXX]  
**Task Name:** [Brief description]  
**Implementer:** [Your Name]  
**Date Started:** YYYY-MM-DD  
**Date Completed:** YYYY-MM-DD

---

## Pre-Implementation Checklist

### Understanding the Task

- [ ] **Read complete task specification**
  - Understand what needs to be built
  - Know why it's needed (context from technical plan)
  - Clear on scope boundaries

- [ ] **Review all acceptance criteria**
  - List all criteria (copy from task spec)
  - Understand what each criterion means
  - Know how to verify each criterion

- [ ] **Identify files to modify**
  - List: [file1.py, file2.py, test_file.py]
  - Understand why each file is included
  - Confirm files exist (or will be created)

- [ ] **Check task dependencies**
  - Prerequisite tasks completed: [TASK-XXX, TASK-YYY]
  - Required interfaces/APIs available
  - Test infrastructure ready

- [ ] **Review technical plan sections**
  - Read relevant architecture sections
  - Understand component being built
  - Know integration points
  - Review API contracts or interfaces

### Environment Setup

- [ ] **Create feature branch**
  - Branch name: `feature/<task-id>-short-description`
  - Branch from: `main` (or appropriate base branch)
  - Verify clean working directory

- [ ] **Update dependencies**
  - Pull latest changes from main
  - Run: `pip install -r requirements.txt` (backend)
  - Run: `npm install` (frontend, if applicable)
  - Verify development environment works

- [ ] **Run existing tests**
  - Backend: `make test` or `pytest`
  - Frontend: `npm test`
  - All tests pass before starting work
  - Baseline established

- [ ] **Set up local environment**
  - Database migrations applied
  - Services running (if needed)
  - Can run MAAS locally
  - Test data created (if needed)

### Knowledge Gathering

- [ ] **Read AGENTS.md relevant sections**
  - Code style guidelines
  - Testing standards
  - Git workflow
  - Review process

- [ ] **Study similar code**
  - Find analogous implementations in codebase
  - Understand patterns used
  - Note naming conventions
  - Identify reusable components

- [ ] **Clarify ambiguities**
  - List unclear requirements
  - Ask questions to task decomposer/planner
  - Document answers
  - Update task understanding

---

## During Implementation Checklist

### Test-Driven Development

- [ ] **Write first failing test**
  - Test file created: `test_<module>.py`
  - Test follows naming convention: `test_<feature>_<behavior>`
  - Test is clear and focused
  - Test fails for right reason (not implemented)

- [ ] **Implement minimal code to pass test**
  - Write simplest implementation
  - Avoid premature optimization
  - Focus on making test pass

- [ ] **Refactor if needed**
  - Improve code quality
  - Extract functions/methods
  - Add docstrings
  - Tests still pass

- [ ] **Repeat red-green-refactor**
  - Continue TDD cycle for all functionality
  - Write test → Make it pass → Refactor
  - Commit small, logical chunks

### Code Quality

- [ ] **Follow MAAS conventions**
  - Python: PEP 8, black formatting
  - JavaScript: ES6+, Prettier formatting
  - Naming matches codebase patterns
  - Structure matches MAAS patterns

- [ ] **Write docstrings**
  - Module docstring (if new file)
  - Class docstrings
  - Public method/function docstrings
  - Google style format

- [ ] **Add inline comments**
  - Explain complex logic
  - Clarify non-obvious decisions
  - Document edge cases
  - Avoid obvious comments

- [ ] **Handle errors properly**
  - Catch specific exceptions
  - Provide useful error messages
  - Log errors appropriately
  - Fail gracefully

- [ ] **Make minimal changes**
  - Modify only task files
  - Don't refactor unrelated code
  - Don't fix unrelated bugs
  - Stay within scope

### Testing

- [ ] **Unit tests comprehensive**
  - Test happy path (expected behavior)
  - Test edge cases (empty, null, boundary)
  - Test error cases (invalid input, failures)
  - Mock external dependencies

- [ ] **Integration tests (if applicable)**
  - Test component interactions
  - Test with real dependencies (where appropriate)
  - Test data flow
  - Verify end-to-end behavior

- [ ] **Test coverage adequate**
  - Run coverage tool: `coverage run -m pytest`
  - Check coverage: `coverage report`
  - New code >= 80% coverage
  - Critical paths 100% covered

- [ ] **Tests are clear and maintainable**
  - Test names describe behavior
  - Arrange-Act-Assert pattern
  - No test interdependencies
  - Tests run quickly

### Continuous Validation

- [ ] **Run tests frequently**
  - Run tests every 5-10 minutes
  - Run affected tests after each change
  - Fix failing tests immediately
  - Don't commit broken tests

- [ ] **Run linters regularly**
  - Python: `flake8 <files>`, `black --check <files>`
  - JavaScript: `eslint <files>`, `prettier --check <files>`
  - Fix issues as they arise
  - Don't accumulate linting debt

- [ ] **Commit logical chunks**
  - Commit after each TDD cycle
  - Commit message format: `[TASK-XXX] Clear description`
  - Commits are small and focused
  - Each commit leaves code in working state

- [ ] **Self-review changes**
  - Read your own diff
  - Check for debugging code left in
  - Verify no unintended changes
  - Ensure changes make sense

---

## Post-Implementation Checklist

### Acceptance Criteria Verification

**Task Acceptance Criteria:**
[Copy each criterion from task spec and check off]

- [ ] **AC1:** [Criterion text]
  - Verification: [How you verified this]
  
- [ ] **AC2:** [Criterion text]
  - Verification: [How you verified this]
  
- [ ] **AC3:** [Criterion text]
  - Verification: [How you verified this]

- [ ] **All unit tests pass**
  - Command: `pytest src/maasserver/tests/test_<module>.py`
  - Result: X/X tests passed
  
- [ ] **Code passes linting**
  - Python: `flake8` and `black --check` pass
  - JavaScript: `eslint` and `prettier --check` pass
  - No warnings or errors

- [ ] **Documentation updated**
  - Docstrings added for new code
  - Relevant docs files updated (if applicable)
  - Comments added for complex logic

### Code Quality Verification

- [ ] **Test coverage meets target**
  - Coverage report generated
  - New code >= 80% covered
  - Critical paths 100% covered
  - Coverage report: [X%]

- [ ] **No code smells**
  - No copy-paste duplication
  - No overly long functions (>50 lines)
  - No deeply nested conditionals (>3 levels)
  - No magic numbers (use named constants)

- [ ] **Error handling complete**
  - All exceptions caught appropriately
  - Error messages are helpful
  - Logging added where appropriate
  - No silent failures

- [ ] **Security considerations addressed**
  - No hardcoded credentials
  - Input validation present
  - SQL injection prevented (use ORM)
  - XSS prevented (React escapes by default)

- [ ] **Performance is acceptable**
  - No obvious performance issues
  - Queries are optimized (no N+1)
  - Large loops are efficient
  - Profiled if performance-critical

### Integration Verification

- [ ] **Changes integrate correctly**
  - New code works with existing code
  - No breaking changes to APIs (unless intended)
  - Dependencies are satisfied
  - Imports resolve correctly

- [ ] **Manual testing completed**
  - Tested in local development environment
  - Verified UI changes visually (if applicable)
  - Tested error scenarios manually
  - Checked logs for errors

- [ ] **Database migrations (if applicable)**
  - Migration created: `./manage.py makemigrations`
  - Migration tested forward: `./manage.py migrate`
  - Migration tested backward: `./manage.py migrate <app> <previous>`
  - Migration is reversible

- [ ] **No unintended side effects**
  - Existing tests still pass
  - No new warnings in logs
  - No performance degradation
  - No broken functionality

### Documentation

- [ ] **Code is self-documenting**
  - Clear variable names
  - Clear function names
  - Logical structure
  - Minimal mental load

- [ ] **API documentation (if applicable)**
  - Endpoint documented (OpenAPI/Swagger)
  - Request/response examples provided
  - Error codes documented
  - Authentication requirements noted

- [ ] **User documentation (if applicable)**
  - User-facing docs updated
  - New features explained
  - Examples provided
  - Linked from main docs

- [ ] **Developer documentation (if applicable)**
  - Architecture docs updated
  - Component diagrams updated
  - Integration points documented
  - Testing guide updated

### Pre-Submission Checks

- [ ] **All files included**
  - All task files modified/created
  - Test files included
  - No missing files
  - No extra files

- [ ] **Branch is clean**
  - No uncommitted changes
  - No untracked files (except intentional ignores)
  - Branch rebased on latest main (if needed)
  - No merge conflicts

- [ ] **Commits are clean**
  - Commit messages are clear
  - Commits reference task ID
  - No "WIP" or "fix" commits (squash if needed)
  - Logical commit sequence

- [ ] **CI checks pass locally (if possible)**
  - Run: `make ci` or equivalent
  - All tests pass
  - Linting passes
  - Build succeeds

### Pull Request Preparation

- [ ] **PR description complete**
  - Title: `[TASK-XXX] Brief description`
  - Links to task specification
  - Summarizes changes
  - Notes any deviations or decisions
  - Screenshots included (if UI changes)

- [ ] **Changes are reviewable**
  - Diff is reasonable size (<500 lines preferred)
  - Changes are focused on task
  - No unnecessary whitespace changes
  - Code is readable

- [ ] **Review checklist for reviewer**
  - Acceptance criteria listed
  - Test coverage shown
  - Breaking changes noted (if any)
  - Deployment notes included (if any)

- [ ] **Request appropriate reviewer**
  - Assign to tech lead or designated reviewer
  - Tag relevant people for context
  - Set appropriate labels (task-id, component)

---

## Code Review Checklist

### During Review

- [ ] **Respond to all comments**
  - Address every review comment
  - Explain decisions if different from suggestion
  - Mark resolved when addressed
  - Thank reviewer for feedback

- [ ] **Make requested changes**
  - Implement suggested improvements
  - Fix identified issues
  - Add requested tests
  - Update documentation

- [ ] **Re-test after changes**
  - Run all tests again
  - Verify acceptance criteria still met
  - Check linting again
  - Ensure CI still passes

- [ ] **Keep discussion focused**
  - Keep comments on topic
  - Move scope discussions elsewhere
  - File follow-up tasks if needed
  - Resolve disagreements constructively

### After Approval

- [ ] **Final checks before merge**
  - Approval received from reviewer
  - CI is green (all checks pass)
  - Branch is up-to-date with main
  - No outstanding comments

- [ ] **Merge cleanly**
  - Use appropriate merge strategy (squash, rebase, merge)
  - Ensure merge commit message is clear
  - Verify merge succeeded
  - Delete feature branch after merge

- [ ] **Verify in main branch**
  - Pull latest main
  - Run tests locally
  - Verify feature works
  - Monitor CI on main

---

## Deviations and Notes

### Deviations from Task Specification

[Document any deviations from the original task spec]

**Deviation:** [What was changed]  
**Reason:** [Why the deviation was necessary]  
**Approved by:** [Who approved the change]

### Implementation Decisions

[Document significant implementation decisions]

**Decision:** [What was decided]  
**Alternatives:** [What else was considered]  
**Rationale:** [Why this was chosen]

### Known Issues or Limitations

[Document any known issues or limitations]

**Issue:** [Description]  
**Impact:** [How this affects functionality]  
**Follow-up:** [Reference to follow-up task, if any]

---

## Time Tracking

**Estimated Effort:** [From task spec]  
**Actual Effort:** [Hours/days spent]  
**Variance:** [Difference and reason if significant]

**Time Breakdown:**
- Understanding task: [hours]
- Writing tests: [hours]
- Implementation: [hours]
- Debugging: [hours]
- Code review iterations: [hours]
- Documentation: [hours]

---

## Sign-off

**Implementer:** [Name]  
**Date Completed:** YYYY-MM-DD  
**Reviewer:** [Name]  
**Date Approved:** YYYY-MM-DD  
**Merged by:** [Name]  
**Merge Date:** YYYY-MM-DD

---

## Retrospective Notes

[After task completion, note learnings for future tasks]

**What went well:**
- [Item]
- [Item]

**What could be improved:**
- [Item]
- [Item]

**Lessons learned:**
- [Item]
- [Item]