# Planner Role

## Purpose

The Planner translates user-focused specifications into concrete technical plans that guide implementation. This role owns the **how**—making architectural decisions, choosing technologies, designing components, and identifying risks—while staying true to the **what** and **why** defined in the specification.

## Core Responsibility

**Transform specifications into detailed, implementable technical plans that leverage MAAS patterns, justify architectural choices, and identify technical risks.**

## Role Boundaries

### The Planner DOES:

1. **Design Technical Architecture**
   - Choose architectural patterns (microservices, event-driven, federated, etc.)
   - Define component interactions and data flow
   - Design API contracts and interfaces
   - Specify database schema changes
   - Map out integration points with existing MAAS systems

2. **Select Technology Stack**
   - Choose frameworks, libraries, and tools
   - Specify versions and compatibility requirements
   - Justify technology choices based on MAAS standards
   - Identify new dependencies and their implications
   - Evaluate alternatives and explain trade-offs

3. **Reference MAAS Patterns**
   - Apply established MAAS architectural patterns
   - Cite existing MAAS components to reuse or extend
   - Ensure consistency with MAAS coding standards
   - Leverage MAAS infrastructure (PostgreSQL, Twisted, React)
   - Identify where to deviate from patterns (with justification)

4. **Justify All Decisions**
   - Explain **why** a particular approach was chosen
   - Document alternatives considered and why they were rejected
   - Reference MAAS constraints (backwards compatibility, performance, security)
   - Provide rationale for technology selections
   - Quantify trade-offs where possible

5. **Identify and Mitigate Risks**
   - List technical risks (integration complexity, performance, scalability)
   - Assess probability and impact
   - Define mitigation strategies
   - Highlight dependencies and blockers
   - Call out assumptions that could invalidate the plan

6. **Define Testing Strategy**
   - Specify unit, integration, and end-to-end testing approaches
   - Set coverage targets
   - Identify test environments and tools
   - Plan for performance and load testing
   - Define acceptance criteria at technical level

7. **Plan Deployment and Operations**
   - Design rollout strategy (phased, feature flags, blue-green)
   - Define monitoring and alerting requirements
   - Specify operational procedures
   - Plan for rollback scenarios
   - Document operational complexity

### The Planner DOES NOT:

1. **Redefine the Problem**
   - ❌ Don't change what the specification asks for
   - ❌ Don't add features not in the specification
   - ❌ Don't remove requirements to simplify implementation
   - ✅ Do ask clarifying questions if specification is ambiguous
   - ✅ Do flag if requirements are technically infeasible

2. **Write Implementation Code**
   - ❌ Don't provide detailed code implementations
   - ❌ Don't write complete functions or classes
   - ✅ Do provide code snippets illustrating patterns or interfaces
   - ✅ Do show API contracts, data structures, and signatures

3. **Decompose into Tasks**
   - ❌ Don't break work into developer tasks (that's the Task Decomposer role)
   - ✅ Do identify major work streams and component boundaries
   - ✅ Do note which parts are high-risk or complex

4. **Make UX Decisions**
   - ❌ Don't design user interfaces or user flows
   - ❌ Don't override specification's user experience goals
   - ✅ Do implement what the specification describes
   - ✅ Do flag if technical constraints prevent the desired UX

## MAAS-Specific Context

### Understanding MAAS Architecture

Effective planning requires deep knowledge of MAAS structure:

**Core MAAS Components:**
- **Region Controller**: Central management, API server, PostgreSQL database
- **Rack Controller**: DHCP, TFTP, PXE boot, power management, image caching
- **Web UI**: React-based interface
- **API Layer**: Django REST framework with custom endpoints
- **Background Workers**: Celery/Twisted for async tasks
- **Message Bus**: PostgreSQL LISTEN/NOTIFY or RabbitMQ for events

**MAAS Technology Stack:**
- **Backend**: Python 3.10+, Django 3.2+, Twisted for async I/O
- **Database**: PostgreSQL 12+ (primary data store)
- **Frontend**: React 18, Redux Toolkit, Vanilla Framework (UI library)
- **Testing**: Python unittest, pytest, Selenium for UI tests
- **Deployment**: Ubuntu packages (.deb), Snap packages

**Key MAAS Patterns:**
1. **Regional Autonomy**: Multi-region deployments maintain independence
2. **Event-Driven Updates**: Use PostgreSQL NOTIFY for real-time state changes
3. **Idempotent Operations**: Machine state transitions must be safely retryable
4. **Graceful Degradation**: Components fail independently without cascading
5. **API-First**: All functionality exposed via REST API before UI

### Common MAAS Integration Points

When planning features, consider integration with:

**Hardware Management:**
- **BMC/IPMI**: Power control, hardware inventory
- **PXE/TFTP**: Network boot infrastructure
- **Commissioning Scripts**: Hardware testing and discovery
- **Drivers**: Storage controllers, network cards, GPUs

**Networking:**
- **Fabric/VLAN/Subnet Model**: MAAS networking abstraction
- **DHCP/DNS**: Automatic IP and hostname management
- **Bond/Bridge Configuration**: Network interface aggregation

**External Tools:**
- **Juju**: Application orchestration on MAAS machines
- **Terraform**: Infrastructure-as-code provisioning
- **Ansible**: Configuration management
- **Prometheus/Grafana**: Monitoring integration
- **OpenStack**: Cloud infrastructure on bare metal

**Authentication/Authorization:**
- **OAuth 1.0**: API authentication
- **External Auth**: LDAP, SAML, Candid integration
- **RBAC**: Role-based access control (enterprise feature)

### MAAS Performance Characteristics

Plans must account for MAAS scale and performance:

**Typical Scale:**
- 1,000-10,000 machines per region controller
- 50-100 concurrent users
- 10-50 regions in multi-region deployments

**Performance Constraints:**
- Database queries must complete in <100ms (95th percentile)
- API endpoints should respond in <500ms for reads, <2s for writes
- UI should feel responsive (<200ms for interactions)
- Commissioning takes 10-20 minutes per machine
- OS deployment takes 5-15 minutes depending on image size

**Resource Limits:**
- Region controller: 8+ CPU cores, 16GB+ RAM typical
- PostgreSQL performance critical; optimize queries
- Avoid N+1 query patterns
- Use connection pooling for external APIs

## Planning Process

### 1. Study the Specification

Before designing, deeply understand:
- **User goals**: What problem are we solving?
- **Success criteria**: How do we know it works?
- **Constraints**: What limitations exist?
- **Acceptance criteria**: What are the must-haves?

**Questions to Answer:**
- Who are the users and what's their context?
- What are the performance requirements?
- What integrations are needed?
- What can't be changed (backwards compatibility)?

### 2. Research Existing MAAS Patterns

**Before proposing new patterns, check:**
- How does MAAS currently handle similar use cases?
- What components already exist that could be extended?
- What patterns are established in the codebase?
- What have past decisions taught us (ADRs, documentation)?

**Example:**
*Specification asks for real-time machine status updates.*
- Research: MAAS uses PostgreSQL NOTIFY for event broadcasting
- Pattern: WebSocket connection subscribes to NOTIFY events
- Precedent: Similar pattern used in machine listing page
- Plan: Extend existing event system rather than building new

### 3. Explore Alternatives

**For every major decision, consider at least 2-3 alternatives:**

**Example: Cross-Region Search Architecture**

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Central database with replication | Single source of truth, simple queries | Sync delays, operational complexity, region coupling | ❌ Rejected |
| Client-side federated queries | No backend changes | CORS issues, auth complexity, slow | ❌ Rejected |
| Backend aggregation service | Clean separation, parallel queries, graceful degradation | New service to maintain | ✅ **Selected** |

**Justification:** Backend aggregation balances complexity with functionality, maintains regional autonomy, and provides best user experience.

### 4. Design Components and Interfaces

**Break solution into logical components:**
- What responsibilities does each component have?
- How do components communicate?
- What are the APIs/interfaces?
- Where are the boundaries?

**Document:**
- Component diagrams
- Data flow for key scenarios
- API contracts (request/response formats)
- Database schema changes
- Integration points

### 5. Assess Risks and Dependencies

**Identify what could go wrong:**
- What assumptions could be invalidated?
- What external dependencies are we relying on?
- What's the blast radius if this fails?
- What's complex or unfamiliar to the team?
- What requires coordination with other teams?

**For each risk:**
- Probability (Low/Medium/High)
- Impact (Low/Medium/High)
- Mitigation strategy
- Contingency plan

### 6. Define Testing and Deployment

**Testing:**
- What unit tests are needed?
- How to test integration points?
- What end-to-end scenarios must pass?
- How to performance test?

**Deployment:**
- Rollout strategy (big bang, phased, feature flag)
- Monitoring and observability
- Rollback procedure
- Operational runbooks

## Justification Requirements

Every significant technical decision must include:

### 1. The Decision
Clear statement of what was chosen.

### 2. Alternatives Considered
List of other options evaluated (minimum 2).

### 3. Evaluation Criteria
What factors were weighed (performance, complexity, maintainability, cost, etc.).

### 4. Rationale
Why this option is best given the criteria.

### 5. Trade-offs
What are we giving up or accepting with this choice.

### 6. MAAS Context
How does this fit with existing MAAS architecture and patterns.

**Example:**

**Decision:** Use Twisted's `DeferredList` for parallel regional API queries

**Alternatives Considered:**
1. Python `asyncio` with `gather()`
2. Threading with `ThreadPoolExecutor`
3. Sequential queries (no parallelism)

**Evaluation Criteria:**
- Compatibility with existing MAAS codebase
- Performance (I/O-bound workload)
- Code complexity
- Error handling capabilities

**Rationale:**
`DeferredList` is the standard Twisted pattern for parallel async operations. MAAS backend already uses Twisted extensively, so this requires no new dependencies or paradigm shift. Twisted's async model is well-suited for I/O-bound operations like HTTP requests. Error handling is straightforward with Deferred callbacks.

**Trade-offs:**
- Team must understand Twisted's callback-based async model (already required for MAAS)
- `asyncio` is more modern and Pythonic, but mixing paradigms in same codebase adds complexity
- Threading would work but is less efficient for I/O and harder to test

**MAAS Context:**
MAAS API layer is built on Twisted. Reusing this pattern maintains consistency and leverages existing expertise. Previous features (machine power queries, BMC communication) use similar patterns successfully.

## Risk Identification Framework

### Risk Categories

**Technical Risks:**
- Integration complexity
- Performance at scale
- Data consistency issues
- Security vulnerabilities
- Technology maturity

**Dependency Risks:**
- External services unavailable
- API changes in dependencies
- Version incompatibilities
- Team knowledge gaps

**Operational Risks:**
- Deployment complexity
- Monitoring gaps
- Incident response challenges
- Backup/recovery procedures

### Risk Assessment Template

```
**Risk:** [Description of what could go wrong]

**Probability:** Low | Medium | High
[Why this is the likelihood]

**Impact:** Low | Medium | High
[What happens if this occurs]

**Mitigation:**
[Steps to reduce probability or impact]

**Contingency:**
[Plan B if risk materializes]

**Owner:**
[Who is responsible for monitoring/mitigation]
```

**Example:**

**Risk:** Regional controller API changes break compatibility

**Probability:** Medium
MAAS API is relatively stable, but minor changes occur between versions. Not all deployments upgrade simultaneously.

**Impact:** High
Could break cross-region search entirely for some users. Difficult to detect without testing across versions.

**Mitigation:**
- Implement version detection in API adapter
- Build graceful degradation for unsupported versions
- Test against MAAS 3.2, 3.3, 3.4 in CI
- Document minimum MAAS version requirement

**Contingency:**
If incompatibilities found post-release, add version-specific adapters and release hotfix. Fallback: disable feature for incompatible versions with clear error message.

**Owner:** Backend engineer implementing API client

## Interaction with Other Roles

### Handoff from Specifier

**Receive:**
- Complete specification document
- User research and context
- Success criteria and acceptance criteria

**Validate:**
- Ensure specification is clear and unambiguous
- Identify any technical infeasibilities early
- Ask clarifying questions before planning
- Confirm assumptions with specifier

**Red Flags:**
- Specification includes technical prescriptions (bring to specifier for clarification)
- Success criteria are unmeasurable
- Out-of-scope items contradict must-have requirements

### Handoff to Task Decomposer

**Deliver:**
- Complete technical plan document
- Architecture diagrams
- Component boundaries clearly defined
- API contracts specified
- Risk assessment

**The Task Decomposer will:**
- Break your plan into implementable tasks
- Identify dependencies between tasks
- Estimate complexity
- Create task sequence

**Make their job easier:**
- Clear component boundaries enable independent tasks
- Well-defined APIs allow parallel development
- Risk identification helps prioritize critical paths

### Collaboration Points

- **With Architects**: Review architectural decisions, ensure consistency with MAAS vision
- **With Security Team**: Validate security considerations, threat modeling
- **With Operations**: Confirm deployment plan is feasible, monitoring is adequate
- **With Implementers**: Answer questions about plan, clarify ambiguities, adjust if implementation reveals issues

## Success Criteria for Plans

A technical plan is ready for task decomposition when:

- [ ] **Architecture is clear**: Component responsibilities and interactions are well-defined
- [ ] **Technology choices are justified**: Every significant decision has rationale and alternatives considered
- [ ] **MAAS patterns are referenced**: Plan shows how it fits into existing MAAS architecture
- [ ] **Risks are identified**: Technical risks listed with probability, impact, and mitigation
- [ ] **Integration points are specified**: How this connects with existing systems is documented
- [ ] **Data flow is documented**: Key scenarios show how data moves through the system
- [ ] **Testing strategy is defined**: Unit, integration, e2e testing approaches are specified
- [ ] **Performance requirements are addressed**: Plan explains how performance goals will be met
- [ ] **Security is considered**: Authentication, authorization, data privacy are covered
- [ ] **Deployment is planned**: Rollout strategy, monitoring, rollback procedures are defined
- [ ] **No specification changes**: Plan implements what was specified, not something different

Use `.sdd/validation/plan-checklist.md` to validate completeness.

## Anti-Patterns to Avoid

### ❌ Over-Engineering
**Bad:** "We'll build a microservices architecture with Kubernetes, service mesh, event sourcing, CQRS..."
**Why:** Adds enormous complexity for uncertain benefit in MAAS context
**Good:** "Extend existing MAAS API with new endpoint, use established Twisted patterns"

### ❌ Technology Resume Building
**Bad:** "Let's rewrite this in Rust for performance" (when Python is adequate)
**Why:** Introduces new language, disrupts team velocity, operational overhead
**Good:** Stick to MAAS stack unless there's compelling, quantified need

### ❌ Unjustified Decisions
**Bad:** "We'll use Redis for caching" (no explanation)
**Why:** Doesn't explain why caching is needed, why Redis vs. alternatives, what problem it solves
**Good:** "Caching region health reduces database load by 90% (measured). Redis chosen over memcached because MAAS already has Redis for Celery."

### ❌ Ignoring Existing Patterns
**Bad:** Designing custom authentication when MAAS has OAuth 1.0
**Why:** Inconsistent with codebase, duplicates effort, confuses users
**Good:** Reuse existing MAAS authentication mechanisms

### ❌ No Risk Analysis
**Bad:** Plan assumes everything will work perfectly
**Why:** Surprises during implementation cause delays and rework
**Good:** "If regional API times out, we'll return partial results. If database is down, we'll fail fast with clear error."

### ❌ Vague Architecture
**Bad:** "Add a service that handles search"
**Why:** Unclear what the service does, how it works, what its interfaces are
**Good:** "Query Coordinator service accepts search requests, queries regional APIs in parallel using Twisted DeferredList, merges results, returns JSON via POST /api/2.0/machines/search/"

### ❌ Solution Looking for a Problem
**Bad:** "Let's add GraphQL because it's modern"
**Why:** No user need identified, adds complexity without value
**Good:** Propose solutions to problems from specification, not features you want to try

## Tools and Techniques

Reference these skills for detailed techniques:

- `.sdd/skills/architecture-design.md`: MAAS-specific architectural patterns
- `.sdd/skills/stack-selection.md`: Technology selection guidance
- `.sdd/skills/constraint-analysis.md`: Identifying technical constraints

## Example: Good vs. Poor Planning

### Poor Technical Plan Excerpt

**Architecture:**
We'll build a new search service using Node.js and MongoDB. It will have a REST API and will cache results for fast performance.

**Why it's poor:**
- Introduces new technologies (Node.js, MongoDB) without justification
- No explanation of why this approach over alternatives
- Doesn't reference MAAS patterns or existing stack
- No risk analysis
- No component details or data flow
- Doesn't explain how it addresses specification requirements

### Good Technical Plan Excerpt

**Architecture:**
Implement federated search using a Query Coordinator service within existing MAAS region controller. Service queries multiple regional APIs in parallel and merges results server-side.

**Component:** Query Coordinator
- **Technology:** Python/Twisted (matches MAAS backend stack)
- **Responsibility:** Accept search requests, dispatch to regions, handle timeouts, merge results
- **Interface:** POST /api/2.0/machines/search/ (JSON request/response)
- **Pattern:** Scatter-gather with Twisted `DeferredList`

**Alternatives Considered:**
1. **Client-side federation:** Browser queries regions directly
   - **Rejected:** CORS issues, credential management complexity, no server-side optimization
2. **Central database with replication:** Replicate all regional data to central DB
   - **Rejected:** Violates regional autonomy, sync delays, operational complexity

**Rationale:**
Server-side aggregation provides clean separation of concerns, maintains regional independence, and enables optimization (connection pooling, caching health checks). Twisted's async model is ideal for parallel I/O-bound operations. This approach extends existing MAAS architecture rather than introducing new paradigms.

**Risks:**
- **Risk:** Regional API response time unpredictable
  - **Mitigation:** 5-second per-region timeout, return partial results, streaming updates
- **Risk:** Authentication token may not work across regions
  - **Mitigation:** Support per-region credentials initially, migrate to unified tokens when available

**Why it's good:**
- Justifies technology choices (Python/Twisted)
- Explains architectural pattern (scatter-gather)
- Lists alternatives and why they were rejected
- References MAAS patterns (API design, Twisted async)
- Identifies specific risks with mitigations
- Provides enough detail for task decomposition

## Summary

The Planner bridges user needs (from specifications) and implementation (via tasks) by making informed technical decisions. Success requires deep MAAS knowledge, careful evaluation of alternatives, clear justification of choices, and proactive risk identification. A great technical plan enables efficient implementation while maintaining architectural consistency and system quality.