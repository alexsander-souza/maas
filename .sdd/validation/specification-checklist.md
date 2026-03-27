# Specification Validation Checklist

**Specification:** [Feature Name]  
**Specifier:** [Your Name]  
**Date:** YYYY-MM-DD  
**Status:** Draft | Review | Approved

---

**Reference:** See [Shared Quality Criteria](./_shared-criteria.md) for common standards (documentation quality, security requirements)

---

## Instructions

This checklist validates that a specification is complete and ready for technical planning. Answer each question honestly with Yes or No. A "No" answer indicates an area that needs work before proceeding.

**Target:** All questions should be "Yes" before marking specification as "Approved"

---

## Problem Statement

### Clarity

- [ ] **Is the current problem clearly described?**
  - Can someone unfamiliar with MAAS understand what's wrong?
  - Is it obvious why this is a problem?

- [ ] **Is the user perspective evident?**
  - Is this written from the user's point of view?
  - Does it explain what users experience?

- [ ] **Is the "why now" explained?**
  - Is the urgency or timing justified?
  - Is it clear why this matters?

### Impact

- [ ] **Is the impact quantified?**
  - Are specific metrics provided (time, cost, frequency)?
  - Can you point to concrete numbers?

- [ ] **Is evidence provided?**
  - Are there references to user research, tickets, or data?
  - Is this backed by facts, not assumptions?

- [ ] **Is the scope of impact clear?**
  - Is it clear how many users are affected?
  - Is the severity/frequency stated?

---

## Target Users

### User Identification

- [ ] **Are primary users clearly identified?**
  - Can you name specific user roles?
  - Is it clear who will use this directly?

- [ ] **Are secondary users identified?**
  - Are indirect beneficiaries listed?
  - Is their relationship to the feature clear?

- [ ] **Are user characteristics documented?**
  - Skill levels described?
  - Work environments specified?
  - Tools/constraints noted?

### User Understanding

- [ ] **Is user context explained?**
  - Why do these users need this feature?
  - What problems do they face?
  - How does MAAS fit into their workflow?

- [ ] **Are user constraints identified?**
  - Access limitations (network, permissions)?
  - Time pressures?
  - Technical skill boundaries?

---

## User Journeys

### Journey Completeness

- [ ] **Is at least one complete user journey documented?**
  - From trigger to outcome?
  - With specific steps?

- [ ] **Are journey steps concrete and specific?**
  - No vague statements like "user does something"?
  - Each step describes actual action?

- [ ] **Is system response documented for each step?**
  - What does the system do?
  - What does the user see/receive?

- [ ] **Are decision points identified?**
  - Where do users make choices?
  - What options are available?

- [ ] **Is the outcome clear?**
  - What has been accomplished?
  - What state change occurred?

### Journey Quality

- [ ] **Are pain points explicitly called out?**
  - Where does the workflow break down today?
  - What frustrates users?
  - What takes too long?

- [ ] **Is the improved workflow (to-be) described?**
  - How will this feature change the workflow?
  - What will be better/faster/easier?

- [ ] **Are journeys realistic and based on research?**
  - Derived from actual user observation or interview?
  - Not just imagined or assumed?

- [ ] **Do journeys represent common scenarios?**
  - Not just edge cases?
  - Typical user experiences?

---

## Success Criteria

### Measurability

- [ ] **Are user success criteria measurable?**
  - Can you observe these behaviors?
  - Are they verifiable?

- [ ] **Are business success criteria quantified?**
  - Specific numbers or percentages?
  - Timeline for achievement stated?

- [ ] **Are operational success criteria defined?**
  - Performance targets?
  - Reliability measures?
  - Operational impact stated?

### Clarity

- [ ] **Is it clear what "success" looks like?**
  - Could you determine if this feature succeeded?
  - Are criteria specific, not vague?

- [ ] **Are success criteria achievable?**
  - Realistic given constraints?
  - Not impossible standards?

- [ ] **Are success criteria relevant to the problem?**
  - Do they actually measure problem resolution?
  - Not just vanity metrics?

---

## Acceptance Criteria

### Completeness

- [ ] **Are must-have criteria clearly defined?**
  - MVP requirements identified?
  - Clear boundary of minimum useful feature?

- [ ] **Are should-have criteria identified?**
  - Important but deferrable items listed?
  - Distinction from must-have is clear?

- [ ] **Are could-have criteria listed?**
  - Future enhancements captured?
  - Helps set expectations?

### Quality

- [ ] **Is each criterion testable?**
  - Can you verify with yes/no test?
  - Observable and verifiable?

- [ ] **Is each criterion specific and unambiguous?**
  - No vague statements like "works well"?
  - Clear, concrete requirements?

- [ ] **Do criteria focus on behavior, not implementation?**
  - Describe what, not how?
  - No technical prescriptions?

- [ ] **Are criteria prioritized correctly?**
  - Must-haves are truly essential?
  - Could-haves are truly optional?

### Coverage

- [ ] **Do acceptance criteria cover all user journeys?**
  - Each journey step has corresponding criteria?
  - No gaps in coverage?

- [ ] **Are error/edge cases addressed?**
  - What happens when things go wrong?
  - Failure scenarios considered?

- [ ] **Are performance requirements stated?**
  - Response time targets?
  - Scale/load expectations?

- [ ] **Are integration points covered?**
  - How this works with existing MAAS features?
  - External system interactions?

---

## Out of Scope

### Boundary Definition

- [ ] **Are explicitly excluded items listed?**
  - Features that might be expected but aren't included?
  - Clearly stated what this won't do?

- [ ] **Are deferred items identified?**
  - Valuable features postponed to future?
  - Distinction between out-of-scope and deferred clear?

- [ ] **Are constraints and boundaries documented?**
  - Technical limitations noted?
  - Business constraints stated?

### Clarity

- [ ] **Is the scope boundary clear?**
  - No ambiguity about what's in/out?
  - Could implementers tell what's included?

- [ ] **Are scope decisions justified?**
  - Reason for exclusions explained?
  - Context for deferrals provided?

---

## Assumptions and Dependencies

### Assumptions

- [ ] **Are assumptions explicitly stated?**
  - What are we taking for granted?
  - Environmental assumptions?
  - User capability assumptions?

- [ ] **Are assumptions reasonable?**
  - Not making wild assumptions?
  - Based on known facts?

- [ ] **Are assumption risks identified?**
  - What if assumption is wrong?
  - How would that affect the specification?

### Dependencies

- [ ] **Are external dependencies identified?**
  - Other systems, services, teams?
  - Required infrastructure?

- [ ] **Are prerequisite features/capabilities listed?**
  - What must exist first?
  - Other MAAS features required?

- [ ] **Is dependency status noted?**
  - Are dependencies available now?
  - Timeline for dependency availability?

### Risks

- [ ] **Are risks identified and documented?**
  - What could block or delay this?
  - Technical risks?
  - Business risks?

- [ ] **Are mitigation strategies mentioned?**
  - How to reduce risk likelihood?
  - Fallback plans?

---

## Open Questions

### Completeness

- [ ] **Are open questions documented?**
  - Unanswered items captured?
  - Ambiguities noted?

- [ ] **Is question status tracked?**
  - Who needs to answer?
  - Timeline for resolution?

- [ ] **Are there no critical unanswered questions?**
  - Major unknowns resolved before approval?
  - Only minor clarifications pending?

---

## Documentation Quality

### Writing Quality

- [ ] **Is the specification well-written?**
  - Clear language?
  - No jargon without explanation?
  - Good grammar and spelling?

- [ ] **Is the specification well-organized?**
  - Logical flow?
  - Easy to navigate?
  - Sections complete?

- [ ] **Are examples provided where helpful?**
  - Concrete illustrations?
  - Real scenarios shown?

### Technical Neutrality

- [ ] **Does the specification avoid technical prescriptions?**
  - No implementation details specified?
  - No technology choices mandated?
  - No architectural decisions made?

- [ ] **Does it focus on "what" and "why," not "how"?**
  - Problem and needs, not solutions?
  - User perspective maintained?

- [ ] **Are technical terms used correctly?**
  - MAAS terminology accurate?
  - Consistent with MAAS documentation?

---

## Stakeholder Review

### Validation

- [ ] **Has this been reviewed with actual users?**
  - User feedback incorporated?
  - User needs validated?

- [ ] **Has this been reviewed by relevant stakeholders?**
  - Product, engineering, operations consulted?
  - Business alignment confirmed?

- [ ] **Have reviewers approved the specification?**
  - Sign-offs obtained?
  - Comments addressed?

### Readiness

- [ ] **Is the specification ready for technical planning?**
  - Complete enough for planner to work with?
  - No major ambiguities remaining?
  - Scope is clear?

- [ ] **Are you confident this solves the right problem?**
  - Validated with users?
  - Addresses root cause?
  - Worth the investment?

---

## Summary

**Total Questions:** 88  
**Yes Answers:** [ ]  
**No Answers:** [ ]  
**Percentage Complete:** [ ]%

**Areas Needing Work:**
[List any sections with "No" answers that need attention]

**Readiness Assessment:**
- [ ] **Ready for Approval** (All critical questions are "Yes")
- [ ] **Needs Minor Revisions** (Few "No" answers, non-critical areas)
- [ ] **Needs Major Revisions** (Many "No" answers, critical gaps)
- [ ] **Not Ready** (Substantial work required)

---

## Sign-off

**Specifier:** [Name]  
**Self-Review Date:** YYYY-MM-DD  
**Peer Reviewer:** [Name]  
**Peer Review Date:** YYYY-MM-DD  
**Status:** Draft | Ready for Approval | Approved  
**Approver:** [Name]  
**Approval Date:** YYYY-MM-DD

---

## Notes

[Any additional notes, context, or follow-up items]