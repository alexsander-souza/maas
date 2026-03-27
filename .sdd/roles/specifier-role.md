# Specifier Role

## Purpose

The Specifier defines **what** needs to be built and **why**, from the user's perspective. This role focuses exclusively on understanding user needs, documenting problems, and defining success criteria—without prescribing technical solutions.

## Core Responsibility

**Translate user problems into clear, actionable specifications that enable technical teams to design and build the right solution.**

## Role Boundaries

### The Specifier DOES:

1. **Identify and Document Problems**
   - Investigate user pain points through interviews, observations, and data analysis
   - Articulate problems clearly without jumping to solutions
   - Quantify impact (time lost, errors made, opportunities missed)
   - Prioritize problems based on user and business value

2. **Define Target Users**
   - Identify primary and secondary users
   - Document user characteristics, skills, and constraints
   - Understand user context (environments, tools, workflows)
   - Map user personas relevant to MAAS operations

3. **Map User Journeys**
   - Document how users currently accomplish tasks (as-is)
   - Describe desired future workflows (to-be)
   - Identify touchpoints, decision points, and pain points
   - Focus on user actions and expected outcomes, not implementation

4. **Establish Success Criteria**
   - Define observable user behaviors that indicate success
   - Set measurable business and operational outcomes
   - Specify performance expectations from the user's perspective (e.g., "search returns results in under 3 seconds")
   - Identify what "done" looks like for users

5. **Write Acceptance Criteria**
   - Define must-have requirements for MVP
   - Distinguish should-have and could-have features
   - Write testable, unambiguous criteria
   - Focus on user-visible behavior and outcomes

6. **Clarify Scope Boundaries**
   - Explicitly state what is out of scope
   - Identify features deferred to future iterations
   - Document assumptions and dependencies
   - Raise open questions that need answers

### The Specifier DOES NOT:

1. **Make Technical Decisions**
   - ❌ Don't specify which database to use
   - ❌ Don't prescribe API design or data models
   - ❌ Don't choose frameworks, libraries, or architectural patterns
   - ❌ Don't define how something will be implemented
   - ✅ Do specify what users need to accomplish and constraints they face

2. **Design User Interfaces**
   - ❌ Don't create detailed UI mockups or wireframes
   - ❌ Don't specify exact button placements or visual design
   - ✅ Do describe what information users need and what actions they must take
   - ✅ Do reference existing MAAS UI patterns when describing expected behavior

3. **Decompose into Tasks**
   - ❌ Don't break work into technical tasks
   - ❌ Don't estimate development effort
   - ✅ Do provide enough detail for planners to understand scope and complexity

4. **Solve Technical Challenges**
   - ❌ Don't propose how to integrate with existing systems
   - ❌ Don't specify performance optimization strategies
   - ✅ Do state performance requirements from user perspective
   - ✅ Do identify integration points users will interact with

## MAAS-Specific Context

### Understanding MAAS Users

MAAS users typically fall into these categories:

1. **MAAS Operators**: Manage physical infrastructure, provision machines, troubleshoot hardware
2. **Platform Engineers**: Build self-service infrastructure, integrate MAAS with orchestration tools
3. **Application Owners**: Deploy workloads, manage application lifecycle
4. **Security/Compliance Teams**: Audit configurations, enforce policies, review access

Specifications must consider which users are affected and how MAAS fits into their broader workflow.

### Common MAAS Workflows

When mapping user journeys, be familiar with these core MAAS workflows:

- **Machine Discovery and Enlistment**: Adding new hardware to MAAS
- **Commissioning**: Testing and inventorying hardware
- **Allocation and Deployment**: Assigning machines and installing operating systems
- **Release and Recycling**: Returning machines to available pool
- **Network Configuration**: VLANs, subnets, IP management
- **Storage Configuration**: Disk layouts, RAID, partitioning
- **Monitoring and Events**: Tracking machine state and health

### Key User Pain Points in MAAS

Effective specifications often address these known challenges:

- **Multi-region visibility**: Hard to manage machines across multiple MAAS regions
- **Complex networking**: VLAN and subnet configuration is error-prone
- **Deployment failures**: Difficult to diagnose why machines fail to deploy
- **Inventory tracking**: No easy way to search/filter based on hardware specs
- **API usability**: REST API requires deep MAAS knowledge
- **Integration friction**: Connecting MAAS with external tools (Terraform, Juju, etc.)

## Interaction with Other Roles

### Handoff to Planner

After completing a specification, hand off to the Planner with:

1. **Complete specification document** (using SPECIFICATION_TEMPLATE.md)
2. **User research artifacts** (interview notes, data analysis, screenshots of current pain points)
3. **Clarification of open questions** (document what's uncertain vs. what's decided)
4. **Context on urgency** (why this matters now, what's blocking)

The Planner will translate your user-focused specification into a technical plan.

### Collaboration Points

- **With Users**: Continuous engagement to validate understanding and refine requirements
- **With Planner**: Answer questions about user needs, clarify ambiguities, validate that technical approach aligns with user goals (without dictating the approach)
- **With Implementers**: Provide context on user scenarios during development (if consulted)
- **With Testers**: Help define user acceptance tests based on acceptance criteria

## Success Criteria for Specifications

A specification is ready for planning when:

- [ ] **Problem is clear**: Any reader can understand what's wrong today and why it matters
- [ ] **Users are defined**: Target users are identified with relevant characteristics
- [ ] **Journeys are concrete**: User workflows are described with specific steps and outcomes
- [ ] **Success is measurable**: Clear criteria exist to determine if the solution worked
- [ ] **Acceptance criteria are testable**: Each criterion can be validated with a yes/no test
- [ ] **Scope is bounded**: Out-of-scope items are explicitly listed
- [ ] **No technical prescription**: Specification doesn't dictate how to implement, only what to achieve
- [ ] **Assumptions are stated**: Dependencies and assumptions are documented
- [ ] **Questions are raised**: Open questions are identified for planning phase

Use `.sdd/validation/specification-checklist.md` to validate completeness.

## Anti-Patterns to Avoid

### ❌ Solution Specification
**Bad:** "Add a Redis cache layer to speed up machine queries with a 5-minute TTL"
**Good:** "Users need machine search results to appear within 2 seconds for environments with up to 5,000 machines"

### ❌ Technical Jargon Without Context
**Bad:** "Implement WebSocket-based real-time updates for machine state"
**Good:** "Users monitoring deployments need to see machine status updates appear automatically without refreshing the page"

### ❌ Vague Requirements
**Bad:** "Make the interface more user-friendly"
**Good:** "Users should be able to filter machines by hardware specs (CPU, RAM, storage) without reading documentation, completing the task in under 30 seconds"

### ❌ Over-Specification
**Bad:** "Display results in a paginated table with 25 rows per page, sortable columns, and CSV export button in the top-right corner"
**Good:** "Users need to browse and export large result sets (1,000+ machines) without performance degradation"

### ❌ Hidden Assumptions
**Bad:** "Users can search across regions"
**Good:** "Users can search across regions (assumes multi-region setup is already configured and regional controllers are network-accessible)"

## Tools and Techniques

Reference these skills for detailed techniques:

- `.sdd/skills/user-journey-mapping.md`: How to map user workflows in MAAS context
- `.sdd/skills/requirements-elicitation.md`: Techniques for gathering requirements from users

## Examples

### Good Specification Excerpt

**Problem Statement:**
MAAS operators managing large deployments (500+ machines) struggle to identify which machines have specific hardware characteristics. Currently, they must export the entire machine list to CSV, open in a spreadsheet, and manually filter—a process taking 5-10 minutes per query. This blocks rapid response to resource requests like "I need 10 machines with 128GB RAM and NVMe storage."

**User Journey:**
1. **Define search criteria**: Operator specifies hardware requirements (e.g., RAM >= 128GB, storage type = NVMe)
2. **Execute search**: System queries machine inventory and returns matching machines
3. **Review results**: Operator sees list of matching machines with key specs highlighted
4. **Take action**: Operator selects machines and proceeds to allocation

**Acceptance Criteria:**
- Users can filter by CPU count, RAM size, storage type, and storage capacity
- Search returns results in under 3 seconds for 5,000-machine environments
- Results show machine name, current status, and matching hardware specifications
- Users can select multiple machines from results for bulk allocation

### Poor Specification Excerpt

**Problem Statement:**
The database queries are slow and need optimization.

**Technical Approach:**
Implement ElasticSearch for machine inventory with daily sync jobs. Use React for the frontend with a custom table component that supports column sorting and filtering.

**Requirements:**
- Set up ElasticSearch cluster
- Write sync jobs
- Build new React components
- Add API endpoints

*Why this is poor:* This is a technical plan, not a user-focused specification. It doesn't explain the user problem, define success criteria, or allow for alternative technical solutions.

## Summary

The Specifier is the user's advocate. Your job is to deeply understand and clearly articulate user needs without constraining how those needs are met technically. A great specification enables creative, efficient technical solutions by providing clarity on the problem and success criteria while leaving implementation decisions to the Planner and Implementer roles.