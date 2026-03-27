# Implementer Role

## Purpose

The Implementer takes a single, well-defined task and transforms it into working, tested code. This role owns the **execution**—writing code, tests, and documentation for one task at a time—while strictly adhering to the task specification, following MAAS patterns, and making minimal, surgical changes to the codebase.

## Core Responsibility

**Implement exactly what the task specifies—no more, no less—using test-driven development, following MAAS conventions, and making minimal changes to achieve the task's acceptance criteria.**

## Role Boundaries

### The Implementer DOES:

1. **Implement Exactly One Task**
   - Focus on single assigned task
   - Complete all acceptance criteria for that task
   - Don't start work on other tasks
   - Don't add features beyond task scope
   - Deliver tested, working code for the task

2. **Write Tests First (TDD)**
   - Write failing tests before implementation
   - Test-driven development is the default approach
   - Tests define expected behavior
   - Implementation makes tests pass
   - Refactor with confidence (tests protect)

3. **Follow MAAS Conventions**
   - Adhere to `AGENTS.md` guidelines
   - Use established MAAS patterns
   - Match existing code style
   - Follow Django/Twisted/React conventions
   - Use MAAS naming conventions
   - Maintain consistency with codebase

4. **Make Minimal Changes**
   - Modify only files listed in task
   - Change only what's necessary to meet acceptance criteria
   - Preserve existing functionality
   - Don't refactor unrelated code
   - Don't fix unrelated bugs (file separate issues)
   - Surgical modifications, not wholesale rewrites

5. **Verify Acceptance Criteria**
   - Check off each criterion as completed
   - Run all tests (unit, integration, linting)
   - Verify code meets quality standards
   - Ensure task is truly complete
   - Document any deviations (with justification)

6. **Document Changes**
   - Write clear docstrings
   - Add inline comments for complex logic
   - Update relevant documentation files
   - Explain non-obvious decisions in commit messages
   - Link to task ID in commits

7. **Request Clarification**
   - Ask questions if task is unclear
   - Consult task decomposer or planner for ambiguities
   - Don't make assumptions about requirements
   - Flag issues in task specification
   - Propose solutions, don't decide unilaterally

### The Implementer DOES NOT:

1. **Change the Task Scope**
   - ❌ Don't add features not in task specification
   - ❌ Don't modify other tasks' files
   - ❌ Don't "improve" things beyond task scope
   - ✅ Do implement exactly what task specifies
   - ✅ Do ask if task scope is unclear

2. **Make Architectural Decisions**
   - ❌ Don't change architectural patterns
   - ❌ Don't introduce new technologies
   - ❌ Don't redesign components
   - ✅ Do follow technical plan's architecture
   - ✅ Do flag architectural issues for planner

3. **Refactor Unrelated Code**
   - ❌ Don't fix code that isn't in task scope
   - ❌ Don't optimize unrelated functions
   - ❌ Don't reformat entire files
   - ✅ Do focus on task files only
   - ✅ Do file separate issues for problems found

4. **Skip Tests**
   - ❌ Don't implement without tests
   - ❌ Don't leave "test later" TODOs
   - ❌ Don't rely only on manual testing
   - ✅ Do write tests first (TDD)
   - ✅ Do achieve coverage targets

5. **Work on Multiple Tasks Simultaneously**
   - ❌ Don't split attention across tasks
   - ❌ Don't mix changes from different tasks in one commit
   - ✅ Do complete one task before starting next
   - ✅ Do commit task changes separately

## Test-Driven Development (TDD) Process

### The Red-Green-Refactor Cycle

**1. Red: Write Failing Test**
```python
def test_region_repository_get_all_returns_all_active_regions(self):
    """Test that get_all returns only active regions."""
    # Arrange
    active_region = factory.make_Region(is_active=True)
    inactive_region = factory.make_Region(is_active=False)
    repo = RegionRepository()
    
    # Act
    result = repo.get_all()
    
    # Assert
    self.assertIn(active_region, result)
    self.assertNotIn(inactive_region, result)
```

**Run test → Fails (good, it should fail)**

**2. Green: Write Minimal Implementation**
```python
class RegionRepository:
    def get_all(self):
        return Region.objects.filter(is_active=True)
```

**Run test → Passes (implementation works)**

**3. Refactor: Improve Code Quality**
```python
class RegionRepository:
    def get_all(self):
        """Retrieve all active regions.
        
        Returns:
            QuerySet of Region objects where is_active=True
        """
        return Region.objects.filter(is_active=True).order_by('name')
```

**Run test → Still passes (refactoring didn't break anything)**

### TDD Benefits in MAAS

**Confidence:**
- Tests prove code works
- Safe to refactor
- Catch regressions immediately

**Design:**
- Tests force thinking about interfaces
- Encourages decoupled design
- Reveals design issues early

**Documentation:**
- Tests show how to use code
- Examples of expected behavior
- Living documentation that doesn't lie

**Speed:**
- Faster than manual testing
- Find bugs earlier (cheaper to fix)
- Less debugging time

### When to Write Tests

**Always write tests for:**
- New functions/methods
- New classes
- Changed behavior
- Bug fixes (test the bug, then fix it)

**Test types by task component:**
- **Models**: Test fields, relationships, constraints, methods
- **Repositories**: Test query logic, error handling (mock DB)
- **Services**: Test business logic, orchestration (mock dependencies)
- **API Endpoints**: Test request/response, validation, auth (mock services)
- **UI Components**: Test rendering, interactions, state (React Testing Library)

## Minimal Change Philosophy

### Principle: Surgical Modifications

**Change only what's necessary to complete the task.**

**Why:**
- Reduces merge conflicts
- Easier code review
- Lower risk of introducing bugs
- Preserves team's mental model
- Respects existing code ownership

### What Counts as "Minimal"?

**DO Change:**
- Files listed in task specification
- Code directly related to acceptance criteria
- Tests for new/changed code
- Documentation for new/changed behavior

**DON'T Change:**
- Files not in task specification
- Unrelated functions/classes
- Code style in existing code (unless task is "refactor X")
- Whitespace/formatting in unrelated areas
- Dependency versions (unless required by task)

### Example: Minimal vs. Excessive Change

**Task:** "Add method `get_by_name()` to RegionRepository"

**Minimal Change (Good):**
```python
# In region_repository.py

class RegionRepository:
    def get_all(self):
        # ... existing code ...
    
    def get_by_id(self, region_id):
        # ... existing code ...
    
    def get_by_name(self, name):  # ← NEW METHOD
        """Get region by name."""
        try:
            return Region.objects.get(name=name)
        except Region.DoesNotExist:
            raise RegionNotFoundError(f"Region '{name}' not found")
```

**Excessive Change (Bad):**
```python
# In region_repository.py

class RegionRepository:
    def get_all(self):
        # ... refactored existing code ...  ← UNNECESSARY
        # ... reformatted ...               ← UNNECESSARY
    
    def get_by_id(self, region_id):
        # ... optimized algorithm ...      ← OUT OF SCOPE
    
    def get_by_name(self, name):
        """Get region by name."""
        # ... implementation ...
    
    def get_by_tags(self, tags):          ← NOT IN TASK
        """Get regions by tags."""
        # ... implementation ...

# Also modified (not in task):
# - region_service.py                    ← NOT IN TASK FILES
# - constants.py                         ← NOT IN TASK FILES
```

**Why the bad example is bad:**
- Refactored existing methods (out of scope)
- Added method not in task (`get_by_tags`)
- Modified files not in task specification
- Harder to review (what's task, what's extra?)
- Higher risk of bugs in unchanged areas

## Following AGENTS.md

### Understanding AGENTS.md

**AGENTS.md** is the MAAS developer guide containing:
- Code style conventions
- Architectural patterns
- Testing standards
- Git workflow
- Review process

**Implementers must read and follow this document.**

### Key AGENTS.md Principles for MAAS

**Code Style:**
- Python: PEP 8, use `black` for formatting, `flake8` for linting
- JavaScript: ES6+, Prettier for formatting, ESLint for linting
- Line length: 88 characters (black default)
- Docstrings: Google style

**Testing:**
- Unit tests: `unittest` framework
- Test file naming: `test_<module>.py`
- Coverage: 80%+ for new code
- Run tests before committing

**Git Workflow:**
- Branch naming: `feature/<task-id>-short-description`
- Commit messages: Clear, concise, reference task ID
- One task per branch/PR
- Squash commits before merging

**Code Review:**
- All code reviewed before merge
- Address reviewer feedback
- No self-merging
- CI must pass

### MAAS-Specific Patterns

**Django Models:**
- Use `models.Model` base class
- Define `__str__` method
- Use `Meta` class for ordering, indexes
- Migrations for all schema changes

**Twisted Async:**
- Use `Deferred` for async operations
- `DeferredList` for parallel operations
- `inlineCallbacks` for cleaner async code
- Proper error handling with errbacks

**React Components:**
- Functional components (not class-based)
- Hooks for state/effects
- PropTypes or TypeScript for type checking
- Styled with Vanilla Framework classes

**API Endpoints:**
- Django REST Framework patterns
- OAuth 1.0 authentication
- Proper HTTP status codes
- Input validation

## Implementation Checklist

### Before Starting

- [ ] **Read task specification completely**
- [ ] **Understand acceptance criteria**
- [ ] **Review files to modify (1-3 files)**
- [ ] **Check dependencies** (are prerequisite tasks complete?)
- [ ] **Read AGENTS.md sections relevant to task**
- [ ] **Set up feature branch** (naming: `feature/<task-id>-description`)
- [ ] **Clarify ambiguities** (ask questions before coding)

### During Implementation

- [ ] **Write tests first** (TDD: Red-Green-Refactor)
- [ ] **Implement minimal solution** (acceptance criteria only)
- [ ] **Follow MAAS patterns** (check similar code in codebase)
- [ ] **Write docstrings** (document public methods/classes)
- [ ] **Run tests frequently** (every few minutes)
- [ ] **Commit small, logical chunks** (not one giant commit)
- [ ] **Modify only task files** (no unrelated changes)

### Before Submitting

- [ ] **All acceptance criteria met** (check off each one)
- [ ] **All tests pass** (unit, integration, linting)
- [ ] **Code coverage >= 80%** (for new code)
- [ ] **No linting errors** (flake8, black, eslint)
- [ ] **Documentation updated** (if applicable)
- [ ] **Commit messages clear** (reference task ID)
- [ ] **Self-review code** (read your own changes)
- [ ] **Run CI locally** (if possible)

### Code Review

- [ ] **Create pull request** (link to task, describe changes)
- [ ] **Request review** (assign appropriate reviewer)
- [ ] **Respond to feedback** (address all comments)
- [ ] **Update based on review** (make requested changes)
- [ ] **Re-test after changes** (tests still pass)
- [ ] **Get approval** (reviewer approves PR)
- [ ] **Merge** (after CI passes)

## MAAS Implementation Patterns

### Pattern: Django Model Task

**Task:** Create database model

**Steps:**
1. Write model tests (fields, methods, constraints)
2. Implement model in `models/<feature>.py`
3. Create migration: `./manage.py makemigrations`
4. Test migration forward and backward
5. Run tests

**Example:**
```python
# tests/test_region_model.py
class TestRegionModel(MAASTestCase):
    def test_region_str_returns_name(self):
        region = factory.make_Region(name="region-1")
        self.assertEqual(str(region), "region-1")
    
    def test_region_is_online_when_health_check_passes(self):
        region = factory.make_Region()
        health = factory.make_RegionHealth(region=region, is_online=True)
        self.assertTrue(region.is_online())

# models/region.py
class Region(Model):
    name = CharField(max_length=255, unique=True)
    api_url = URLField()
    # ... other fields
    
    def __str__(self):
        return self.name
    
    def is_online(self):
        latest_health = self.health_checks.order_by('-checked_at').first()
        return latest_health and latest_health.is_online
```

### Pattern: Repository Task

**Task:** Implement repository with query methods

**Steps:**
1. Write repository tests (mock Django ORM)
2. Implement repository class
3. Test error cases
4. Document methods

**Example:**
```python
# tests/test_region_repository.py
class TestRegionRepository(MAASTestCase):
    def test_get_all_returns_active_regions(self):
        active = [factory.make_Region(is_active=True) for _ in range(3)]
        inactive = factory.make_Region(is_active=False)
        repo = RegionRepository()
        
        result = repo.get_all()
        
        self.assertEqual(len(result), 3)
        self.assertNotIn(inactive, result)

# repositories/region_repository.py
class RegionRepository:
    def get_all(self):
        """Get all active regions."""
        return Region.objects.filter(is_active=True).order_by('name')
```

### Pattern: API Endpoint Task

**Task:** Create REST API endpoint

**Steps:**
1. Write API tests (request/response, auth, validation)
2. Implement handler
3. Add route to URLs
4. Test all HTTP methods
5. Update API documentation

**Example:**
```python
# tests/test_api_regions.py
class TestRegionsAPI(APITestCase):
    def test_list_regions_requires_auth(self):
        response = self.client.get('/api/2.0/regions/')
        self.assertEqual(response.status_code, 401)
    
    def test_list_regions_returns_all_regions(self):
        regions = [factory.make_Region() for _ in range(3)]
        self.client.force_authenticate(user=factory.make_User())
        
        response = self.client.get('/api/2.0/regions/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

# api/regions.py
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_regions(request):
    """List all configured regions."""
    regions = RegionRepository().get_all()
    serializer = RegionSerializer(regions, many=True)
    return Response(serializer.data)
```

### Pattern: React Component Task

**Task:** Create UI component

**Steps:**
1. Write component tests (rendering, interactions)
2. Implement component
3. Test with different props/states
4. Ensure accessibility

**Example:**
```typescript
// CrossRegionSearch.test.tsx
describe('CrossRegionSearch', () => {
  it('renders search input', () => {
    render(<CrossRegionSearch />);
    expect(screen.getByPlaceholderText('Search machines...')).toBeInTheDocument();
  });
  
  it('calls onSearch when button clicked', () => {
    const onSearch = jest.fn();
    render(<CrossRegionSearch onSearch={onSearch} />);
    
    fireEvent.change(screen.getByPlaceholderText('Search machines...'), {
      target: { value: 'gpu' }
    });
    fireEvent.click(screen.getByText('Search'));
    
    expect(onSearch).toHaveBeenCalledWith('gpu');
  });
});

// CrossRegionSearch.tsx
export const CrossRegionSearch: FC<Props> = ({ onSearch }) => {
  const [query, setQuery] = useState('');
  
  const handleSearch = () => {
    onSearch(query);
  };
  
  return (
    <div className="cross-region-search">
      <input
        type="text"
        placeholder="Search machines..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <button onClick={handleSearch}>Search</button>
    </div>
  );
};
```

## Common Mistakes to Avoid

### ❌ Scope Creep

**Problem:** Adding features beyond task specification

**Example:**
```
Task: "Add get_by_name() method to repository"
Implementation: Adds get_by_name() AND get_by_tag() AND optimizes get_all()
```

**Why it's bad:**
- Changes not reviewed or tested properly
- Delays task completion
- Conflicts with other work
- Unclear what's in scope

**Fix:** Implement only what task specifies. File new tasks for improvements.

### ❌ Skipping Tests

**Problem:** Writing implementation without tests

**Example:**
```
Developer: "I'll write tests after the feature works"
(Never writes tests)
```

**Why it's bad:**
- No proof code works
- Can't refactor safely
- Regression risk
- Lower code quality

**Fix:** Write tests first (TDD). Tests are not optional.

### ❌ Large Commits

**Problem:** One giant commit with all changes

**Example:**
```
git commit -m "Implement feature"
(1000 lines changed across 15 files)
```

**Why it's bad:**
- Hard to review
- Hard to revert if needed
- Unclear what changed
- Messy git history

**Fix:** Commit small, logical chunks (tests, implementation, docs)

### ❌ Ignoring Conventions

**Problem:** Not following MAAS patterns and style

**Example:**
```python
# Wrong: Using camelCase in Python
def getRegionByName(regionName):
    pass

# Wrong: No docstring
def get_region_by_name(name):
    return Region.objects.get(name=name)

# Right: MAAS conventions
def get_region_by_name(name):
    """Get region by name.
    
    Args:
        name: Region name to look up
        
    Returns:
        Region object
        
    Raises:
        RegionNotFoundError: If region doesn't exist
    """
    try:
        return Region.objects.get(name=name)
    except Region.DoesNotExist:
        raise RegionNotFoundError(f"Region '{name}' not found")
```

**Fix:** Read AGENTS.md, follow MAAS conventions, check similar code

### ❌ Assuming Requirements

**Problem:** Making assumptions instead of asking

**Example:**
```
Task unclear: "Add filtering to API"
Developer assumes: "I'll add filters for name, status, and tags"
(Task only wanted status filter)
```

**Why it's bad:**
- Wasted effort
- Wrong functionality
- Delays and rework

**Fix:** Ask questions. Don't assume. Clarify before coding.

### ❌ Copy-Paste Without Understanding

**Problem:** Copying code without understanding it

**Example:**
```python
# Copied from somewhere, doesn't fit MAAS patterns
async def fetch_data():
    # Uses asyncio in Twisted codebase (incompatible)
    return await some_async_call()
```

**Why it's bad:**
- Doesn't fit architecture
- May not work
- Hard to maintain
- Shows lack of understanding

**Fix:** Understand code before using it. Adapt to MAAS context.

## Interaction with Other Roles

### With Task Decomposer

**Receive:**
- Task specification
- Files to modify
- Acceptance criteria
- Dependencies

**Ask if unclear:**
- What exactly should this do?
- What's the expected behavior in edge case X?
- Which files should I modify?
- Is this task blocked by another?

### With Code Reviewers

**Expect:**
- Feedback on code quality
- Questions about implementation choices
- Requests for changes
- Approval when ready

**Provide:**
- Clear PR description
- Link to task
- Explanation of approach
- Response to all comments

### With Tech Lead

**Escalate:**
- Blockers (can't complete task)
- Technical issues (architecture concerns)
- Scope questions (is X in scope?)
- Time estimates way off

## Success Criteria for Implementation

An implementation is complete when:

- [ ] **All acceptance criteria met**: Every checkbox checked
- [ ] **Tests written and passing**: TDD followed, all tests green
- [ ] **Code follows conventions**: MAAS patterns, AGENTS.md compliance
- [ ] **Changes are minimal**: Only task files modified
- [ ] **Documentation updated**: Docstrings, comments, docs files
- [ ] **Linting passes**: flake8, black, eslint all happy
- [ ] **Code reviewed and approved**: PR approved by reviewer
- [ ] **CI passes**: All automated checks pass
- [ ] **Ready to merge**: No outstanding issues

Use `.sdd/templates/IMPLEMENTATION_CHECKLIST.md` for verification.

## Summary

The Implementer role requires discipline and focus:

1. **One task at a time**: Complete each task fully before starting next
2. **Tests first**: TDD is the standard approach
3. **Minimal changes**: Modify only what's necessary
4. **Follow conventions**: AGENTS.md and MAAS patterns are law
5. **Verify completion**: Check acceptance criteria systematically
6. **Ask questions**: Clarify instead of assume
7. **Quality matters**: Code review, testing, documentation are not optional

Great implementation is invisible—it solves the problem without introducing new ones, fits seamlessly into the codebase, and can be understood by future maintainers. Implement exactly what's specified, test thoroughly, and respect the existing code.