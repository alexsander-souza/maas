# Technology Stack Selection for MAAS

## Overview

Technology stack selection is a critical planning decision that impacts development velocity, operational complexity, team productivity, and long-term maintainability. This guide provides a framework for evaluating and selecting technologies within the MAAS ecosystem.

## Purpose

- **Maintain consistency**: Minimize technology sprawl across MAAS codebase
- **Reduce operational burden**: Fewer technologies = simpler deployment and maintenance
- **Leverage expertise**: Use technologies the team already knows
- **Ensure sustainability**: Choose mature, well-supported technologies
- **Enable contribution**: Lower barrier for community contributions

## Core Principle: Default to MAAS Standard Stack

**The most important rule: When in doubt, use what MAAS already uses.**

Adding new technologies has hidden costs:
- Learning curve for team
- Additional operational monitoring
- More security vulnerabilities to track
- Complex dependency management
- Split team expertise

Only deviate from the standard stack when there's a **compelling, quantified reason** that justifies these costs.

## MAAS Standard Technology Stack

### Backend Stack

| Component | Technology | Version | Notes |
|-----------|-----------|---------|-------|
| **Language** | Python | 3.10+ | Core language, standard library preferred |
| **Web Framework** | Django | 3.2+ | ORM, admin, migrations |
| **Async Framework** | Twisted | 22.10+ | Async I/O, network protocols |
| **API Framework** | Django REST Framework | Custom endpoints | RESTful APIs |
| **Database** | PostgreSQL | 12+ | Primary data store |
| **Message Queue** | RabbitMQ (optional) | 3.8+ | Event distribution (some deployments) |
| **Caching** | Redis | 6.0+ | Session storage, Celery backend |
| **Task Queue** | Celery | 5.x | Background jobs (some deployments) |
| **Testing** | unittest, pytest | Built-in | Unit and integration tests |
| **Linting** | flake8, black | Latest | Code quality |

### Frontend Stack

| Component | Technology | Version | Notes |
|-----------|-----------|---------|-------|
| **Language** | JavaScript/TypeScript | ES6+ | Prefer TypeScript for new code |
| **Framework** | React | 18.x | UI components |
| **State Management** | Redux Toolkit | 1.9+ | Application state |
| **UI Library** | Vanilla Framework | Latest | Canonical design system |
| **Build Tool** | Webpack | 5.x | Module bundling |
| **Testing** | Jest, React Testing Library | Latest | Unit tests |
| **E2E Testing** | Playwright/Selenium | Latest | End-to-end tests |

### Infrastructure Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| **OS** | Ubuntu LTS | 22.04+ preferred |
| **Packaging** | .deb, Snap | Native Ubuntu packaging |
| **Web Server** | Nginx | Reverse proxy, static files |
| **Process Manager** | systemd | Service management |
| **Monitoring** | Prometheus, Grafana | Metrics and visualization |

## Decision Framework

### Step 1: Can the Standard Stack Do This?

**Before considering alternatives, ask:**

1. **Can Python solve this problem?**
   - Python has extensive libraries for most tasks
   - Performance is usually adequate for MAAS use cases
   - Team expertise is in Python

2. **Can Twisted handle this async operation?**
   - Twisted is proven for MAAS's async I/O patterns
   - Mixing async paradigms (Twisted + asyncio) adds complexity

3. **Can PostgreSQL handle this data?**
   - PostgreSQL is feature-rich (JSON, full-text search, time-series)
   - Often no need for additional databases

4. **Can React handle this UI requirement?**
   - React 18 has most modern UI capabilities
   - Vanilla Framework provides Canonical styling

**If yes to any: Use the standard stack.**

### Step 2: Quantify the Problem

If standard stack is insufficient, **quantify the gap**:

- **Performance**: "PostgreSQL query takes 5 seconds; requirement is <500ms"
- **Capability**: "Need to process 10,000 concurrent WebSocket connections; Twisted's limit is ~2,000"
- **Complexity**: "Implementing X in Python would require 2,000 lines vs. 200 in specialized library"

**Vague justifications are insufficient:**
- ❌ "Technology X is more modern"
- ❌ "Technology Y is better for this"
- ❌ "I prefer technology Z"

### Step 3: Evaluate Alternatives

For each alternative, assess:

#### 1. Maturity and Stability

- **Production-ready?** Avoid pre-1.0 releases
- **Active maintenance?** Regular releases, responsive maintainers
- **Community size?** Large community = more resources, better longevity
- **Breaking changes?** Stable API or frequent churn?

**Evaluation:**
- Check GitHub stars, contributors, issue response time
- Review release history and changelogs
- Check for active forks or competing projects

#### 2. Team Expertise

- **Does team know this technology?** If not, what's the learning curve?
- **Is documentation good?** Can new contributors get up to speed?
- **Are there experts available?** Consultants, community support?

**Consideration:**
- 1-2 weeks learning time may be acceptable
- 1-2 months learning curve is a red flag

#### 3. Operational Complexity

- **What does deployment look like?** Additional services, configuration?
- **How is it monitored?** Metrics, logs, debugging tools?
- **What's the failure mode?** Graceful degradation or catastrophic?
- **Resource requirements?** Memory, CPU, storage overhead?

**Example:**
Adding Elasticsearch: +1 JVM service, +2GB RAM, +monitoring, +backup strategy

#### 4. Integration Fit

- **How does it integrate with MAAS?** Clean interfaces or tight coupling?
- **Ubuntu packaging available?** .deb, Snap, or manual installation?
- **License compatible?** AGPL for MAAS; check dependency licenses
- **Python bindings available?** If it's not Python-native

#### 5. Long-Term Sustainability

- **What if we need to remove it?** Can we migrate off easily?
- **What's the upgrade path?** Major version upgrades smooth or painful?
- **Vendor lock-in risk?** Open-source or proprietary?

### Step 4: Make a Decision

Use this scoring matrix:

| Criterion | Weight | Score (1-5) | Weighted Score |
|-----------|--------|-------------|----------------|
| Solves problem | 3x | | |
| Maturity/stability | 2x | | |
| Team expertise | 2x | | |
| Operational simplicity | 2x | | |
| Integration fit | 1x | | |
| Long-term sustainability | 1x | | |

**Scoring:**
- 5 = Excellent fit
- 4 = Good fit
- 3 = Acceptable
- 2 = Concerning
- 1 = Poor fit

**Decision Threshold:**
- **Weighted score ≥ 35**: Consider adopting
- **Weighted score 25-34**: Proceed with caution, have mitigation plan
- **Weighted score < 25**: Do not adopt; find alternative

### Step 5: Justify and Document

**Document the decision:**
1. **Problem statement**: What gap exists in standard stack?
2. **Quantified need**: Specific metrics or capabilities required
3. **Alternatives evaluated**: At least 2-3 options considered
4. **Scoring**: Use the matrix above
5. **Trade-offs**: What are we accepting with this choice?
6. **Migration plan**: How to remove this if it doesn't work out?

## Technology Categories and Guidance

### Databases

**Standard: PostgreSQL**

**Consider alternatives when:**
- ✅ Need specialized query capabilities (graph, vector similarity, geospatial beyond PostGIS)
- ✅ Scale beyond single PostgreSQL instance and sharding isn't viable
- ✅ Specific data model fits better (document store, time-series)

**Alternatives:**
- **Redis**: Caching, session storage, pub/sub (already in stack for Celery)
- **Elasticsearch**: Full-text search with complex queries (heavy operational cost)
- **InfluxDB**: High-volume time-series metrics (if Prometheus insufficient)

**Usually NOT justified:**
- ❌ MongoDB, CouchDB: PostgreSQL JSON support is typically sufficient
- ❌ Neo4j: MAAS doesn't have complex graph query needs
- ❌ Cassandra: MAAS scale doesn't require distributed databases

### Async/Concurrency Frameworks

**Standard: Twisted**

**Consider alternatives when:**
- ✅ New isolated service (not integrated with MAAS core)
- ✅ Twisted lacks required protocol support
- ✅ Team expertise strongly in different framework

**Alternatives:**
- **asyncio**: If building new service separate from Twisted codebase
- **Gevent**: Simpler than Twisted for some use cases, but adds another paradigm

**Usually NOT justified:**
- ❌ Mixing Twisted and asyncio in same service (complexity nightmare)
- ❌ Threading for I/O-bound work (async is better fit)

### Background Task Processing

**Standard: Celery (optional) or Twisted deferreds**

**Consider alternatives when:**
- ✅ Celery operational overhead not justified for use case
- ✅ Need different scheduling semantics

**Alternatives:**
- **RQ**: Simpler than Celery, Redis-based
- **Twisted `deferToThread`**: For occasional background work

**Usually NOT justified:**
- ❌ Airflow, Prefect: Overkill for MAAS task patterns
- ❌ Custom task queue: Complex to build correctly

### Frontend Frameworks

**Standard: React**

**Consider alternatives when:**
- ✅ Building completely separate UI (not integrated with MAAS web UI)
- ✅ React fundamentally cannot handle requirement

**Alternatives:**
- **Vue, Angular**: If building isolated admin tool or plugin
- **Vanilla JS**: For simple, non-reactive widgets

**Usually NOT justified:**
- ❌ Rewriting existing React UI in different framework (massive cost)
- ❌ "Framework X is better" without quantified benefit

### HTTP Clients

**Standard: treq (Twisted), requests (sync), axios (frontend)**

**Consider alternatives when:**
- ✅ Need HTTP/2, HTTP/3 specific features
- ✅ Standard clients lack specific capability

**Alternatives:**
- **httpx**: Modern, async-capable alternative to requests
- **aiohttp**: If using asyncio

**Usually NOT justified:**
- ❌ Adding new HTTP client just for minor convenience features

### Data Serialization

**Standard: JSON (API), Pickle (internal), Protocol Buffers (curtin)**

**Consider alternatives when:**
- ✅ Performance critical serialization of large datasets
- ✅ Cross-language communication requires specific format

**Alternatives:**
- **MessagePack**: Faster, more compact than JSON
- **YAML**: Configuration files (already used)
- **TOML**: Configuration files

**Usually NOT justified:**
- ❌ Replacing JSON API with binary format (breaks compatibility)

### Monitoring and Observability

**Standard: Prometheus (metrics), Syslog (logs)**

**Consider alternatives when:**
- ✅ Need distributed tracing
- ✅ Log aggregation at scale

**Alternatives:**
- **Jaeger, Zipkin**: Distributed tracing
- **ELK Stack, Grafana Loki**: Log aggregation
- **OpenTelemetry**: Unified observability

**Usually NOT justified:**
- ❌ Proprietary monitoring (vendor lock-in)

## Common Scenarios

### Scenario 1: "We need better performance"

**Wrong approach:**
"Let's rewrite this in Go/Rust/C++ because it's faster"

**Right approach:**
1. **Profile first**: Where is the bottleneck? (CPU, I/O, database)
2. **Optimize Python**: Algorithmic improvements, caching, better data structures
3. **Database optimization**: Indexes, query optimization, connection pooling
4. **Consider Cython**: Speed up Python bottlenecks without leaving Python
5. **Only then**: Consider language switch for critical path

**Example:**
Machine query slow → Profile → Database N+1 queries → Add `select_related()` → Problem solved (no new technology needed)

### Scenario 2: "We need real-time updates"

**Wrong approach:**
"Let's add Socket.io or Firebase"

**Right approach:**
MAAS already has WebSocket support and PostgreSQL NOTIFY pattern. Extend existing infrastructure.

### Scenario 3: "We need full-text search"

**Wrong approach:**
"Let's add Elasticsearch"

**Right approach:**
1. **Try PostgreSQL full-text search first**: Often sufficient for MAAS use cases
2. **Quantify insufficiency**: Query time, relevance scoring, language support
3. **If truly insufficient**: Then evaluate Elasticsearch with operational cost in mind

### Scenario 4: "I want to try technology X"

**Wrong approach:**
"Let's use this in production to learn it"

**Right approach:**
1. **Personal project**: Experiment on your own time
2. **Internal tool**: Try in low-risk internal tooling
3. **Prototype**: Build proof-of-concept outside main codebase
4. **Present findings**: Show quantified benefits vs. costs
5. **Team decision**: If compelling, propose for production

## Red Flags

Watch out for these warning signs:

### 🚩 "It's the new hotness"

Bleeding-edge technology is exciting but risky. Wait for 1.0+ and production adoption.

### 🚩 "Everyone else is using it"

What works for Google/Facebook may not fit MAAS scale or needs.

### 🚩 "It's better/modern/cleaner"

Subjective opinions aren't enough. Quantify the benefit.

### 🚩 "Just for this one small thing"

Small additions have long-term costs. Today's "small thing" becomes tomorrow's maintenance burden.

### 🚩 "We'll migrate later"

Tech debt accumulates. If you wouldn't commit to maintaining it for 5 years, don't add it.

## Approval Process

### Low-Risk Additions (Python libraries)

**Criteria:**
- Pure Python, no system dependencies
- Well-maintained (recent releases, active maintainers)
- Compatible license
- < 10 transitive dependencies

**Process:**
- Document in technical plan
- Code review approval sufficient

### Medium-Risk Additions (Services, frameworks)

**Criteria:**
- New service or framework
- Operational complexity (monitoring, deployment)
- Team needs to learn it

**Process:**
- Full technology evaluation (use decision framework)
- Technical plan with detailed justification
- Architect review and approval
- Proof-of-concept in staging

### High-Risk Additions (Core infrastructure changes)

**Criteria:**
- Changes to core MAAS architecture
- Replaces existing technology
- Affects all deployments
- Significant operational impact

**Process:**
- ADR (Architecture Decision Record)
- Technology evaluation with scoring matrix
- Multiple stakeholder reviews (engineering, operations, product)
- Extended testing period
- Migration plan for existing deployments

## Deprecation and Removal

When removing technologies:

1. **Document reasons**: Why is this being removed?
2. **Migration plan**: How do existing users upgrade?
3. **Timeline**: Give sufficient notice (one major release minimum)
4. **Fallback**: Provide alternative solution
5. **Support**: Help users migrate

## Summary

**Key Principles:**

1. **Default to standard stack**: MAAS has a proven, stable technology foundation
2. **Quantify the need**: "Better" isn't enough; show concrete benefits
3. **Evaluate rigorously**: Use the decision framework, score alternatives
4. **Consider operational cost**: Deployment, monitoring, maintenance burden
5. **Think long-term**: Can we maintain this for 5+ years?
6. **Document decisions**: Future maintainers will thank you
7. **Be conservative**: Boring technology is often the best technology

The best technology choice is usually the one that's already in the stack. Only deviate when the benefits clearly outweigh the costs, and when those benefits are quantified and documented.