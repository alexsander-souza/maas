# Task Sizing for MAAS

## Overview

Task sizing is the process of estimating the effort required to complete a task. Appropriate sizing enables accurate planning, effective work distribution, and realistic timeline expectations. In the MAAS context, tasks should be small enough to complete quickly but large enough to deliver meaningful, testable functionality.

## Purpose

- **Enable accurate planning**: Understand how much work exists
- **Facilitate work distribution**: Assign tasks to developers based on capacity
- **Track progress**: Measure velocity and predict completion
- **Identify complexity**: Flag challenging tasks early
- **Set expectations**: Communicate realistic timelines
- **Enable parallelism**: Small tasks are easier to distribute

## Sizing Philosophy

### The Goldilocks Principle

Tasks should be "just right"—not too big, not too small:

**Too Large (> 5 days):**
- Hard to estimate accurately
- Blocks other work
- High merge conflict risk
- Difficult to review
- Unclear progress tracking

**Too Small (< 2 hours):**
- Task overhead exceeds value
- Context switching costs
- Clutters backlog
- Inefficient code reviews

**Just Right (1-5 days):**
- Completable within a week
- Independently testable
- Clear scope and boundaries
- Reviewable in reasonable time
- Measurable progress

### MAAS Target Sizes

**Small Task:** 1-2 days (8-16 hours)
- Single file or simple changes
- Straightforward logic
- Minimal dependencies
- Quick to test and review

**Medium Task:** 2-4 days (16-32 hours)
- Multiple files (2-3)
- Moderate complexity
- Some integration points
- Comprehensive testing needed

**Large Task:** 3-5 days (24-40 hours)
- Complex logic
- Multiple components
- Significant integration
- Extensive testing required

**If > 5 days: Split the task**

## Sizing Factors

### 1. Code Complexity

**Low Complexity (Small):**
- CRUD operations
- Simple data transformations
- Straightforward conditionals
- Well-established patterns

**Medium Complexity (Medium):**
- Business logic with multiple conditions
- Moderate algorithms (sorting, filtering)
- Multiple integration points
- Some error handling branches

**High Complexity (Large):**
- Complex algorithms (graph traversal, optimization)
- Asynchronous coordination (Twisted Deferreds)
- State machine implementations
- Intricate error handling

**Example:**
```
Simple (Small): Create Django model for Region with basic fields
↓
Moderate (Medium): Implement repository with query methods and error handling
↓
Complex (Large): Implement query coordinator with parallel async calls, timeouts, result merging
```

### 2. File Count

**1 file:** Usually Small (unless file is complex)
**2-3 files:** Small to Medium
**4-5 files:** Medium to Large
**6+ files:** Split into multiple tasks

**Note:** Always include test file in count

**Example:**
```
Small (1-2 files):
- src/maasserver/models/region.py
- src/maasserver/tests/test_region.py

Medium (3 files):
- src/maasserver/services/query_service.py
- src/maasserver/tests/test_query_service.py
- src/maasserver/tests/integration/test_query_integration.py

Large (4-5 files):
- Multiple related components
- Multiple test files
- Configuration changes
```

### 3. Testing Effort

**Simple Testing (adds 20-30% to estimate):**
- Unit tests with mocked dependencies
- Clear inputs/outputs
- Few edge cases

**Moderate Testing (adds 40-60% to estimate):**
- Integration tests required
- Multiple scenarios
- Error path testing
- Mock setup complexity

**Complex Testing (adds 80-100% to estimate):**
- End-to-end tests
- Docker environment setup
- Performance testing
- Multiple test environments

**Example:**
```
Code: 1 day
Simple testing: +0.3 days = 1.3 days → Small

Code: 2 days
Moderate testing: +1 day = 3 days → Medium

Code: 2 days
Complex testing: +2 days = 4 days → Large
```

### 4. Integration Points

**No Integration (Small):**
- Self-contained component
- No external dependencies
- Mock all collaborators

**Low Integration (Small-Medium):**
- 1-2 integration points
- Well-defined interfaces
- Clear contracts

**High Integration (Medium-Large):**
- 3+ integration points
- Complex data flow
- Synchronization challenges
- Multiple systems

**Example:**
```
Low: Repository calling Django ORM (1 integration point)
Medium: Service calling repository + external API (2 points)
High: Coordinator calling 5 regional APIs + repository + event bus (7 points)
```

### 5. Risk and Unknowns

**Low Risk (estimate as-is):**
- Well-understood problem
- Established patterns
- Team has expertise
- Clear requirements

**Medium Risk (add 30-50% buffer):**
- Some unknowns
- New but similar to past work
- Requires research
- Unclear requirements

**High Risk (add 100%+ buffer or spike):**
- Unfamiliar technology
- Significant unknowns
- No precedent
- Dependencies outside control

**Example:**
```
Low Risk: Implement CRUD endpoint (done many times before)
Estimate: 2 days

Medium Risk: Integrate with new BMC API version (documented but untested)
Base: 2 days → With buffer: 3 days

High Risk: Implement custom protocol parser (never done before)
Base: 2 days → Spike first: 1 day exploration → Re-estimate after spike
```

### 6. Knowledge and Experience

**Team Expert (estimate as-is):**
- Developer has done this before
- Deep domain knowledge
- Familiar with codebase

**Team Familiar (add 20-30%):**
- Team has general knowledge
- Some learning required
- Can reference similar code

**Team Learning (add 50-100%):**
- New area for team
- Significant learning curve
- May need mentoring

**Example:**
```
Expert in Twisted async: 2 days
Familiar with async concepts: 2.5 days
Learning Twisted for first time: 4 days
```

## Sizing Techniques

### Technique 1: Reference Class Estimation

**Compare to similar past tasks:**

1. Find analogous completed task
2. Note how long it actually took
3. Adjust for differences
4. Use as baseline

**Example:**
```
Past: "Implement BMC power control adapter" took 3 days
Current: "Implement network configuration adapter"

Similarity analysis:
- Same adapter pattern ✓
- Similar API complexity ✓
- Different domain (networking vs power) ~

Estimate: 3 days (Medium)
```

### Technique 2: Decomposition and Aggregation

**Break task into sub-activities, estimate each:**

1. List all sub-activities
2. Estimate each in hours
3. Sum estimates
4. Add integration buffer (20%)
5. Convert to task size

**Example:**
```
Task: Implement Query Coordinator Service

Sub-activities:
- Create QueryCoordinator class: 4 hours
- Implement parallel query logic (DeferredList): 8 hours
- Handle timeouts and errors: 4 hours
- Write unit tests (with mocks): 6 hours
- Write integration tests: 4 hours
- Code review and fixes: 2 hours

Subtotal: 28 hours
Integration buffer (20%): +6 hours
Total: 34 hours = 4.25 days → Large task
```

### Technique 3: T-Shirt Sizing (Relative)

**Compare tasks to each other:**

**XS (< 0.5 day):** Trivial change, combine with other tasks
**S (1-2 days):** Single file, simple logic
**M (2-4 days):** Multiple files, moderate complexity
**L (3-5 days):** Complex logic, multiple integrations
**XL (> 5 days):** Split into smaller tasks

**Calibration:**
Use a known "Small" task as baseline, compare others relatively.

**Example:**
```
Baseline (S): "Create Django model" = 1 day

Other tasks:
"Implement repository" is 1.5x as complex → S/M (1.5 days)
"Implement service with 3 integrations" is 3x as complex → M/L (3 days)
"Full feature end-to-end" is 10x as complex → Split it
```

### Technique 4: Story Points (Fibonacci)

**Use relative complexity scoring:**

**1 point:** Trivial (few hours)
**2 points:** Small (1 day)
**3 points:** Small-Medium (1-2 days)
**5 points:** Medium (2-3 days)
**8 points:** Large (3-5 days)
**13 points:** Too large, split

**Benefits:**
- Relative, not absolute time
- Accounts for complexity, not just hours
- Team-calibrated

**Example:**
```
Reference task (3 points): "Implement repository with 4 methods"

New task: "Implement async query coordinator"
- More complex logic → +2 points
- More integration points → +2 points
- More testing needed → +1 point

Estimate: 3 + 2 + 2 + 1 = 8 points (Large)
```

### Technique 5: Three-Point Estimation

**Consider best, likely, and worst cases:**

**Formula:** Expected = (Best + 4×Likely + Worst) / 6

**Example:**
```
Task: Implement Regional API Client

Best case (everything goes smoothly): 1.5 days
Likely case (some minor issues): 2.5 days
Worst case (API changes, debugging needed): 4 days

Expected = (1.5 + 4×2.5 + 4) / 6 = 2.75 days

Round to: 3 days (Medium)
```

### Technique 6: Planning Poker (Team-Based)

**Team estimates together:**

1. Present task
2. Each person estimates independently
3. Reveal estimates simultaneously
4. Discuss differences
5. Re-estimate until consensus

**Benefits:**
- Surfaces different perspectives
- Identifies hidden complexity
- Team buy-in

**Example:**
```
Task: "Implement result merger"

Estimates: 2, 2, 3, 5

Discussion:
- Why 5? "Didn't consider duplicate detection complexity"
- Why 2? "Thought it was just list concatenation"

After discussion:
- Team agrees duplicates are edge case, add to acceptance criteria
- Consensus: 3 days (Medium)
```

## MAAS-Specific Sizing Guidelines

### Database Tasks

**Django Model (Small: 1 day):**
- Create model class
- Write migration
- Basic tests

**Repository (Small-Medium: 1-2 days):**
- Implement 3-5 methods
- Error handling
- Mock-based tests

**Complex Query (Medium: 2-3 days):**
- Optimize query performance
- Multiple joins
- Index creation
- Performance tests

### API Tasks

**Simple CRUD Endpoint (Small: 1-2 days):**
- Single endpoint
- Basic validation
- Standard tests

**Complex Endpoint (Medium: 2-3 days):**
- Multiple operations
- Authorization checks
- Complex validation
- Comprehensive tests

**Multi-Endpoint Feature (Large: 3-5 days):**
- Multiple related endpoints
- Shared logic
- Integration tests
- API documentation

### UI Tasks

**Simple Component (Small: 1 day):**
- Presentational component
- Few props
- Basic interactions
- Component tests

**Complex Component (Medium: 2-3 days):**
- Stateful component
- Multiple child components
- Complex interactions
- Redux integration
- Comprehensive tests

**Feature with Multiple Components (Large: 3-5 days):**
- Multiple components
- Routing
- State management
- Integration tests
- Accessibility

### Service/Business Logic Tasks

**Simple Service (Medium: 2-3 days):**
- Single responsibility
- 2-3 methods
- Clear dependencies
- Unit tests

**Complex Service (Large: 3-5 days):**
- Multiple responsibilities
- Complex orchestration
- Error handling
- Integration tests
- Documentation

### Testing Tasks

**Unit Tests for Existing Code (Small: 1 day per component)**

**Integration Test (Medium: 2-3 days):**
- Set up test environment
- Write scenarios
- Mock external dependencies

**E2E Test with Docker (Large: 3-5 days):**
- Docker environment
- Multiple services
- Full workflow tests
- CI integration

## Adjustment Factors

### Velocity Tracking

**After completing several tasks, calculate team velocity:**

```
Sprint 1: Estimated 30 points, completed 20 points
Sprint 2: Estimated 30 points, completed 22 points
Sprint 3: Estimated 30 points, completed 24 points

Average velocity: ~22 points per sprint
Velocity factor: 22/30 = 0.73

For future estimates, multiply by 1/0.73 = 1.37
(Or reduce commitment to match velocity)
```

### Historical Accuracy

**Track estimation accuracy:**

```
Task A: Estimated 2 days, actual 3 days (1.5x)
Task B: Estimated 3 days, actual 4 days (1.33x)
Task C: Estimated 1 day, actual 1.5 days (1.5x)

Average multiplier: 1.44x

Apply to future estimates:
Estimated 2 days × 1.44 = 2.9 days → Round to 3 days
```

### Context Switching

**Add overhead for task switching:**

If developer works on multiple tasks simultaneously:
- 1 task: 0% overhead
- 2 tasks: +10% overhead each
- 3+ tasks: +20% overhead each

**Example:**
```
Single task: 2 days
Same task split across sprint with other work: 2.4 days
```

## Common Sizing Mistakes

### ❌ Mistake 1: Forgetting Testing

**Problem:** Estimating only implementation, forgetting test effort

**Example:**
```
Wrong: "Repository implementation: 1 day"
Right: "Repository implementation + tests: 1.5 days"
```

**Fix:** Always include testing in estimate (typically adds 30-50%)

### ❌ Mistake 2: Ignoring Integration

**Problem:** Treating integrated task as sum of parts

**Example:**
```
Wrong: Component A (2 days) + Component B (2 days) = 4 days
Right: A (2 days) + B (2 days) + Integration (1 day) = 5 days
```

**Fix:** Add 20-30% integration buffer for multi-component tasks

### ❌ Mistake 3: Assuming Perfect Knowledge

**Problem:** Estimating as if requirements are crystal clear

**Reality:** Requirements clarification takes time

**Fix:** Add 10-20% buffer for requirements refinement

### ❌ Mistake 4: Ignoring Code Review

**Problem:** Not accounting for review feedback cycles

**Example:**
```
Wrong: "Implementation: 2 days"
Right: "Implementation: 2 days + Review cycles: 0.5 days = 2.5 days"
```

**Fix:** Add time for review, feedback, and revisions

### ❌ Mistake 5: Over-Precision

**Problem:** Estimating to the hour (e.g., "2.37 days")

**Reality:** Estimates are inherently uncertain

**Fix:** Use half-day increments maximum (0.5, 1, 1.5, 2, 2.5, etc.)

### ❌ Mistake 6: Anchoring Bias

**Problem:** Being influenced by initial estimate

**Example:**
"Manager suggests 1 day" → Team estimates 1 day (even if it's 3 days)

**Fix:** Estimate independently before discussing

## Sizing Decision Tree

```
Start: Estimate task size

1. How many files? 
   1-2 → Small (go to 2)
   3-4 → Medium (go to 3)
   5+ → Split task

2. Is logic complex?
   No → Small (1-2 days)
   Yes → Medium (go to 3)

3. Are tests complex?
   No → Use base estimate
   Yes → Add 1-2 days

4. Are there unknowns/risks?
   No → Use current estimate
   Yes → Add 50% buffer or spike first

5. Final size:
   < 2 days → Small
   2-4 days → Medium
   3-5 days → Large
   > 5 days → Split task
```

## Validation and Calibration

### Before Starting Sprint

Review task sizes:
- [ ] Are any tasks > 5 days? Split them
- [ ] Are tasks testable? Add test estimates
- [ ] Are unknowns identified? Add buffers
- [ ] Does estimate include code review time?
- [ ] Have similar past tasks been referenced?

### During Sprint

Track actuals:
- Log actual hours spent
- Note reasons for deviations
- Update team velocity

### After Sprint

Retrospective:
- Which estimates were accurate?
- Which were off? Why?
- What factors were missed?
- How to improve future estimates?

## Summary

Effective task sizing requires:

1. **Understand factors**: Complexity, files, testing, integration, risk
2. **Use multiple techniques**: Reference class, decomposition, planning poker
3. **Account for everything**: Testing, integration, review, unknowns
4. **Track and adjust**: Measure velocity, learn from actuals
5. **Be realistic**: Add buffers for uncertainty
6. **Stay humble**: Estimates are predictions, not commitments
7. **Iterate**: Improve estimation accuracy over time

Good sizing enables better planning, more accurate forecasts, and realistic expectations. Size conservatively, track actuals, and refine your estimation skills with each iteration.