# Spec-Driven Development FAQ

Common questions and answers about using SDD in MAAS development.

## General Questions

### What is Spec-Driven Development?

Spec-Driven Development (SDD) is a structured methodology that transforms requirements into working code through four explicit phases: Specify, Plan, Tasks, and Implement. Each phase produces validated artifacts that serve as living documentation and guide the next phase.

### How is SDD different from traditional development?

Traditional development often mixes "what," "why," and "how" together, leading to:
- Requirements encoded implicitly in code
- Architectural decisions lost to time
- Rework due to misalignment

SDD separates concerns:
- **Specifications** capture stable intent (what/why)
- **Plans** document technical decisions (how)
- **Tasks** organize implementation (execution)
- **Code** reflects validated design

### Is SDD compatible with Agile?

**Yes.** SDD complements Agile rather than replacing it:

- **Agile** governs *when* work happens (sprints, iterations) and *who* does it (team dynamics)
- **SDD** governs *how* work is structured (specify → plan → tasks → implement)

Specifications evolve with each sprint. Tasks map to user stories. SDD artifacts become the "definition of done" for design.

### Isn't this just waterfall?

**No.** Waterfall has sequential phases where you never go back. SDD has:

- **Living documents** that evolve with requirements
- **Iterative validation** at each phase
- **Continuous feedback** between phases
- **Incremental delivery** via task-based implementation

If requirements change, you update the spec and regenerate downstream artifacts. The spec remains the source of truth, not a frozen document.

## When to Use SDD

### When should I use SDD vs direct implementation?

Use SDD for:
- Greenfield features (new capabilities)
- Architectural changes (affecting multiple subsystems)
- Cross-cutting concerns (security, performance, infrastructure)
- Complex refactors (legacy modernization)

Use direct implementation for:
- Bug fixes
- Small enhancements (<200 lines, single module)
- Pattern repetition (applying known solutions)
- Urgent hotfixes

See the [decision tree in ADOPTION_GUIDE.md](ADOPTION_GUIDE.md#decision-tree-should-i-use-sdd) for detailed guidance.

### Can I use SDD for part of a project?

**Yes.** You can use partial SDD:

- **Specify only**: For RFCs or exploratory design
- **Specify + Plan**: For features where implementation is straightforward
- **Plan + Tasks**: When requirements are crystal clear but technical approach needs documentation

Tailor the process to the complexity of your work.

### What if I'm not sure if SDD is appropriate?

Start with `/specify`. Writing a 1-page specification takes 15 minutes and clarifies:
- Whether the problem is well-understood
- If technical decisions need explicit documentation
- Whether the full SDD workflow is justified

If the spec reveals low complexity, proceed with direct implementation. If it reveals high ambiguity, continue with `/plan`.

## Overhead and Efficiency

### Doesn't SDD slow down development?

**Short-term**: Writing specs and plans adds 1-2 hours upfront.  
**Long-term**: Prevents days/weeks of rework from misalignment.

Studies show:
- 60% of defects originate from requirements/design phase
- Fixing a defect in production costs 100x more than fixing it in design

SDD catches issues early when they're cheap to fix.

### How much overhead does SDD add?

Typical breakdown for a medium feature (500 lines):
- Specification: 30-60 minutes
- Plan: 1-2 hours
- Task breakdown: 30-60 minutes
- Implementation: (unchanged, but more focused)

**Total overhead: 2-4 hours**  
**Rework prevented: 4-20 hours** (based on avoiding false starts, architectural pivots, and misaligned code)

### We move fast—do we have time for this?

**Fast ≠ Frantic.** Moving fast means:
- Delivering value quickly
- Not wasting time on rework
- Making informed decisions

SDD enables speed by eliminating thrashing. You move fast *because* you know where you're going.

## Specifications

### How detailed should specifications be?

**Just enough to eliminate ambiguity.** A specification should:
- Define success criteria clearly
- Outline user journeys
- Specify constraints and non-functional requirements

**Avoid**:
- Implementation details (that's the plan's job)
- Over-specification of UI/UX (unless it's critical)
- Exhaustive edge case enumeration (capture major cases)

Aim for 2-5 pages for most features.

### What if requirements change after I write the spec?

**Update the spec.** Specifications are living documents:

1. Modify the spec to reflect new requirements
2. Regenerate or update the plan
3. Adjust task breakdowns
4. Continue implementation

The spec is always the source of truth. Code and docs should match the current spec.

### Who writes the specification?

- **AI agents** can draft based on user input
- **Product managers** can write directly
- **Developers** can write for technical features
- **Collaborative authoring** between stakeholders

What matters: The spec is validated before moving to planning.

## Plans

### How is a plan different from a spec?

| Specification | Plan |
|--------------|------|
| User-focused | Developer-focused |
| What and why | How |
| Technology-agnostic | Technology-specific |
| Stable | May evolve with tech landscape |
| Defines success | Defines architecture |

Example:
- **Spec**: "Users can export audit logs in JSON or CSV format"
- **Plan**: "Add `/api/v3/audit/export` endpoint using Django REST framework serializers with streaming response for large datasets"

### Can I have multiple plans for one spec?

**Yes.** For complex features, you might have:
- **Plan A**: Minimal viable implementation
- **Plan B**: Full-featured approach
- **Plan C**: Refactor-first approach

Evaluate trade-offs and choose one plan to implement. Document rejected alternatives for future reference.

### What if the plan is wrong?

If during implementation you discover a better approach:

1. **Update the plan** with new approach and rationale
2. Review updated plan with team (if applicable)
3. Adjust tasks if needed
4. Continue implementation

Don't blindly follow a flawed plan. SDD is iterative, not rigid.

## Tasks

### How small should tasks be?

Each task should:
- Affect 1-3 files (or a single module)
- Be implementable in <4 hours
- Have clear, testable acceptance criteria
- Be independently reviewable

**Too small**: "Add import statement to database.py"  
**Just right**: "Add `export_audit_logs()` function to database layer with tests"  
**Too large**: "Implement entire audit export feature"

### Should tasks map to commits or PRs?

**Flexible.** Common patterns:

- **1 task = 1 PR**: Best for clear separation and focused review
- **Multiple tasks = 1 PR**: Acceptable if tasks are tightly coupled
- **1 task = multiple commits**: Fine for iterative development

Use Conventional Commits for all commits. Reference task numbers in PR descriptions.

### What if tasks have dependencies?

Document them explicitly in the task list:

```markdown
## Task 3: Implement CSV serializer
**Depends on**: Task 1 (database layer), Task 2 (export endpoint)
```

Implement in dependency order. If you discover new dependencies during implementation, update the task list.

## Implementation

### Does implementation follow AGENTS.md or SDD?

**Both.** SDD provides:
- What to build (from spec)
- How to architect it (from plan)
- What to implement (from tasks)

AGENTS.md provides:
- How to write the code (style, patterns, standards)
- Language-specific guidelines (Python, Go)
- Subsystem-specific rules

During implementation, follow AGENTS.md for code quality while satisfying SDD task requirements.

### Can I deviate from the plan during implementation?

**Yes, with documentation.** If you discover:
- A better approach
- An incorrect assumption
- A technical limitation

Then:
1. Update the plan with new approach
2. Update affected tasks
3. Document why the change was necessary
4. Continue implementation

Never silently diverge. Keep artifacts synchronized.

### What if I need to make an urgent fix?

**Fix first, document later.** For production hotfixes:

1. Implement and deploy the fix immediately
2. Write a retrospective spec explaining what was built and why
3. Update relevant plans and subsystem context if architectural changes were made
4. File a follow-up task for proper implementation if the hotfix was a workaround

Urgency doesn't eliminate the need for documentation—it just changes the order.

## AI Agent Usage

### How do AI agents use SDD?

AI agents follow the same four phases:

1. **Specify**: AI drafts spec based on user input → user validates
2. **Plan**: AI designs architecture using `.sdd/context/` → user reviews
3. **Tasks**: AI breaks down work → user approves
4. **Implement**: AI writes code following AGENTS.md → user tests

Validation checkpoints ensure AI output is correct before proceeding.

### Can AI agents validate their own work?

**Partially.** AI agents can:
- Check syntax and completeness (using validation checklists)
- Verify references (specs → plans → tasks → code)
- Run automated tests

But humans should validate:
- Requirement correctness (does the spec solve the real problem?)
- Architectural soundness (is the plan the right approach?)
- Business logic (does the code do what users need?)

### What if the AI generates a bad spec/plan?

Use the validation checklists:
- [Specification Checklist](validation/specification-checklist.md)
- [Plan Checklist](validation/plan-checklist.md)

If validation fails, regenerate or manually correct. Don't proceed with flawed artifacts—garbage in, garbage out.

## Integration and Workflow

### How does SDD integrate with code review?

SDD enhances code review:

**Traditional review**: "Is this code correct?"  
**SDD review**:
1. Spec review: "Is this the right feature?"
2. Plan review: "Is this the right architecture?"
3. Task review: "Is this properly broken down?"
4. Code review: "Does this implement the task correctly?"

Earlier reviews catch issues before code is written.

### Can I use SDD with existing projects?

**Yes.** Two approaches:

**Retroactive SDD**: Write specs and plans for existing features to document current state  
**Forward SDD**: Use SDD for new features while maintaining existing code as-is

Over time, the documented features will be the well-understood ones.

### How do I organize specs/plans/tasks in version control?

All SDD artifacts live in `.sdd/` and are committed:

```
.sdd/
├── specs/
│   ├── audit-export.md
│   └── rbac-v2.md
├── plans/
│   ├── audit-export.md
│   └── rbac-v2.md
└── tasks/
    ├── audit-export.md
    └── rbac-v2.md
```

Archive completed work periodically:
```bash
mv .sdd/specs/shipped-feature.md .sdd/archive/v3.2/specs/
```

## Common Mistakes

### Mistake 1: Skipping validation

**Problem**: Moving to next phase without validating current phase  
**Solution**: Use validation checklists explicitly. Don't proceed until validation passes.

### Mistake 2: Over-specifying implementation

**Problem**: Putting code-level details in specifications  
**Solution**: Keep specs technology-agnostic. Move technical details to plans.

### Mistake 3: Creating static documents

**Problem**: Never updating specs when requirements change  
**Solution**: Treat specs as living documents. Update them first when requirements evolve.

### Mistake 4: Using SDD for everything

**Problem**: Writing specs for trivial bug fixes  
**Solution**: Use the decision tree. SDD is for complex work only.

### Mistake 5: Ignoring subsystem context

**Problem**: Plans that violate MAAS architectural constraints  
**Solution**: Always reference `.sdd/context/subsystems/` during planning.

### Mistake 6: Monolithic tasks

**Problem**: Tasks affecting 10+ files or taking days to implement  
**Solution**: Break down further. Each task should be <4 hours and <3 files.

## Advanced Topics

### Can I compose skills from multiple domains?

**Yes.** See `.sdd/skills/compositions/` for pre-composed skill sets. You can also compose manually:

```markdown
Relevant skills for this task:
- [Python async patterns](skills/languages/python/async-patterns.md)
- [PostgreSQL transactions](skills/techniques/database/postgresql-transactions.md)
- [MAAS API conventions](skills/domains/maas/api-conventions.md)
```

### How do I add new skills or context?

Skills and context are living knowledge bases:

1. Identify a reusable pattern or constraint
2. Document it in the appropriate directory
3. Reference it in future plans and tasks
4. Update when patterns evolve

See [skills/README.md](skills/README.md) and [context/README.md](context/README.md) for organization.

### Can SDD be automated further?

**Future enhancements**:
- Automated spec validation (syntax, completeness)
- Plan generation from specs (AI-assisted)
- Task generation from plans (AI-assisted)
- Code scaffolding from tasks (boilerplate generation)
- Continuous validation in CI/CD

The infrastructure is designed to support these automations as the team matures in SDD usage.

## Troubleshooting

### "My spec keeps changing—is this normal?"

**Yes, in early iterations.** Specifications often evolve during:
- Initial drafting (understanding the problem)
- Stakeholder review (aligning on goals)
- Planning (discovering constraints)

Once validated and implementation starts, specs should stabilize. Frequent changes during implementation suggest insufficient upfront validation.

### "The plan is too detailed—should I simplify?"

**Probably.** Plans should document architectural decisions, not implementation details. If your plan includes:
- Line-by-line pseudocode → Too detailed
- Specific variable names → Too detailed
- High-level architecture and key patterns → Just right

### "My tasks don't fit the 1-3 file guideline"

Some tasks naturally span more files:
- Database migrations + model + API layer = 5+ files

This is acceptable if the task is still:
- Cohesive (one logical change)
- Independently testable
- <4 hours to implement

Guidelines are guidelines, not laws.

## Getting Help

- **Process questions**: This FAQ
- **Adoption strategy**: [ADOPTION_GUIDE.md](ADOPTION_GUIDE.md)
- **Methodology overview**: [README.md](README.md)
- **Command reference**: [commands/](commands/)
- **Examples**: [examples/](examples/)

---

**Still have questions?** Add them to this FAQ via pull request or discuss with the team.