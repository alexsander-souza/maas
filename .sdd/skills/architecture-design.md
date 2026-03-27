# Architecture Design for MAAS

## Overview

This guide documents established architectural patterns within MAAS and provides guidance on when and how to apply them. These patterns have evolved to address MAAS-specific challenges: managing physical infrastructure, handling asynchronous hardware operations, maintaining regional autonomy, and providing real-time visibility into machine state.

## Purpose

- **Maintain consistency**: Apply proven patterns across the codebase
- **Avoid reinventing**: Leverage existing solutions to common problems
- **Ensure quality**: Use patterns that have been validated in production
- **Accelerate development**: Reduce design time by following established approaches
- **Facilitate maintenance**: Consistent patterns make code easier to understand

## Core MAAS Architectural Principles

### 1. Regional Autonomy

**Principle:** Each MAAS region operates independently and maintains its own state.

**Implications:**
- No central database of machine state across regions
- Regions can function when disconnected from others
- Multi-region features use federated queries, not replication
- Avoid creating dependencies between regions

**Example:**
When designing cross-region search, query each region's API independently rather than replicating data to a central store.

### 2. API-First Development

**Principle:** All functionality must be accessible via REST API before building UI.

**Implications:**
- UI is a client of the API, with no special privileges
- Third-party tools can access same capabilities as web UI
- API design drives feature implementation
- Authentication and authorization enforced at API layer

**Example:**
When adding machine filtering by hardware specs, implement `/api/2.0/machines/?cpu_count_min=32` endpoint first, then build UI component that calls it.

### 3. Idempotent Operations

**Principle:** Operations should be safely retryable without side effects.

**Implications:**
- Machine state transitions handle duplicate requests gracefully
- API endpoints return same result for repeated identical requests
- Background tasks check current state before acting
- Use database constraints to prevent inconsistent state

**Example:**
Allocating an already-allocated machine returns success with current allocation details, not an error.

### 4. Graceful Degradation

**Principle:** Component failures should not cascade; partial functionality is better than total failure.

**Implications:**
- Features degrade gracefully when dependencies unavailable
- Return partial results rather than all-or-nothing
- Show useful error messages, not generic failures
- Continue serving read operations even if writes are impaired

**Example:**
If one rack controller is offline, commissioning still works for machines on other racks.

### 5. Event-Driven Updates

**Principle:** Use asynchronous events for state changes rather than polling.

**Implications:**
- Machine state changes trigger PostgreSQL NOTIFY events
- WebSocket connections receive real-time updates
- Reduce database load from polling
- UI updates immediately when backend state changes

**Example:**
When a machine completes deployment, event is broadcast; all connected clients see status update without refreshing.

## MAAS Architectural Patterns

### Pattern 1: Scatter-Gather (Federated Queries)

**Context:** Need to query data from multiple independent sources (regions, rack controllers, BMCs).

**Problem:** How to aggregate data from distributed sources without central replication.

**Solution:** Query all sources in parallel, collect results, merge and return.

**Structure:**
```
Client Request
    ↓
Coordinator
    ├─→ Source 1 (parallel)
    ├─→ Source 2 (parallel)
    └─→ Source 3 (parallel)
    ↓
Result Merger
    ↓
Response
```

**Implementation:**
- Use Twisted `DeferredList` for parallel async operations
- Set timeouts for each source (fail fast)
- Handle partial failures gracefully
- Merge results in coordinator or client

**MAAS Example:**
Cross-region machine search queries multiple regional APIs simultaneously, merges results with region labels.

**When to Use:**
- Multi-region visibility features
- Aggregating hardware inventory from multiple racks
- Collecting metrics from distributed components

**When NOT to Use:**
- When order of operations matters (use sequential)
- When sources must agree on result (use consensus instead)
- When low latency is critical and sources are slow

**Trade-offs:**
- ✅ Fast: Total time = max(source_times), not sum
- ✅ Resilient: One failure doesn't block all results
- ❌ Complex: Error handling for partial failures
- ❌ Eventual consistency: Results may be slightly out of sync

### Pattern 2: Event-Driven State Updates

**Context:** Multiple clients need real-time visibility into machine/system state changes.

**Problem:** Polling is inefficient and introduces latency; how to push updates to clients.

**Solution:** Use PostgreSQL LISTEN/NOTIFY with WebSocket connections to broadcast state changes.

**Structure:**
```
State Change (DB Transaction)
    ↓
PostgreSQL NOTIFY event
    ↓
Event Handler (Twisted)
    ↓
WebSocket Broadcast
    ↓
Connected Clients (Web UI, CLI)
```

**Implementation:**
- Django signals trigger NOTIFY on model save
- Twisted listener subscribes to PostgreSQL notifications
- WebSocket server broadcasts to subscribed clients
- Clients update UI state without page refresh

**MAAS Example:**
Machine status changes (Ready → Allocated → Deploying → Deployed) broadcast to all connected users viewing machine list.

**When to Use:**
- Real-time dashboards and monitoring
- Machine state tracking
- Event logs and audit trails
- Collaborative features (multiple users managing same resources)

**When NOT to Use:**
- Historical data queries (use standard DB queries)
- Infrequent state changes (polling may be simpler)
- When clients are unreliable or frequently disconnected

**Trade-offs:**
- ✅ Real-time: Sub-second latency for updates
- ✅ Efficient: No polling overhead
- ✅ Scalable: Push model reduces database load
- ❌ Complexity: WebSocket connection management
- ❌ State synchronization: Clients must handle reconnection

### Pattern 3: Repository Pattern (Data Access Layer)

**Context:** Need to access database models from multiple parts of application.

**Problem:** Direct Django ORM calls scattered throughout codebase make testing hard and create tight coupling.

**Solution:** Abstract database operations behind repository interfaces.

**Structure:**
```
Service Layer
    ↓
Repository Interface
    ↓
Repository Implementation (Django ORM)
    ↓
Database
```

**Implementation:**
```python
class MachineRepository:
    def get_by_system_id(self, system_id):
        return Machine.objects.get(system_id=system_id)
    
    def find_available(self, filters):
        return Machine.objects.filter(status=NODE_STATUS.READY, **filters)
    
    def allocate(self, machine, user):
        machine.status = NODE_STATUS.ALLOCATED
        machine.owner = user
        machine.save()
```

**MAAS Example:**
`NodeRepository` abstracts machine/device queries, used by API handlers and background tasks.

**When to Use:**
- Complex queries used in multiple places
- When testing requires mocking database
- Separating business logic from data access
- Supporting multiple data sources

**When NOT to Use:**
- Simple CRUD operations in API endpoints
- One-off queries specific to single use case
- When Django ORM is sufficient and team is comfortable with it

**Trade-offs:**
- ✅ Testable: Easy to mock for unit tests
- ✅ Reusable: Common queries in one place
- ✅ Maintainable: Changes to data access centralized
- ❌ Indirection: Extra layer between logic and data
- ❌ Boilerplate: More code to write initially

### Pattern 4: Service Layer (Business Logic)

**Context:** Business logic scattered between views, models, and forms.

**Problem:** Hard to reuse logic, difficult to test, unclear separation of concerns.

**Solution:** Extract business logic into service classes that orchestrate operations.

**Structure:**
```
API Handler / CLI Command
    ↓
Service Layer (business logic)
    ├─→ Repository (data access)
    ├─→ External API (hardware control)
    └─→ Event Publisher (notifications)
```

**Implementation:**
```python
class MachineProvisioningService:
    def __init__(self, machine_repo, power_service, event_service):
        self.machine_repo = machine_repo
        self.power_service = power_service
        self.event_service = event_service
    
    def commission_machine(self, system_id, user):
        # Business logic orchestration
        machine = self.machine_repo.get_by_system_id(system_id)
        
        if machine.status not in ALLOWED_STATUSES:
            raise InvalidStateTransition()
        
        machine.status = NODE_STATUS.COMMISSIONING
        self.machine_repo.save(machine)
        
        self.power_service.power_on(machine)
        self.event_service.publish(MachineCommissioningStarted(machine, user))
        
        return machine
```

**MAAS Example:**
`DeploymentService` orchestrates machine deployment: validates state, applies configuration, initiates deployment, manages power.

**When to Use:**
- Complex workflows involving multiple steps
- Business logic used by both API and CLI
- Operations requiring transaction coordination
- When logic is too complex for Django model methods

**When NOT to Use:**
- Simple CRUD operations
- Presentation logic (belongs in views/serializers)
- When Django model methods are sufficient

**Trade-offs:**
- ✅ Reusable: Logic shared across API, CLI, background jobs
- ✅ Testable: Can test business logic without HTTP layer
- ✅ Clear: Separates concerns (API = interface, Service = logic, Repository = data)
- ❌ More files: Increases codebase size
- ❌ Learning curve: Team must understand layered architecture

### Pattern 5: Adapter Pattern (External System Integration)

**Context:** Integrating with external systems that have varying APIs or protocols.

**Problem:** Direct integration couples code to specific API versions or implementations.

**Solution:** Create adapter layer that normalizes external API interactions.

**Structure:**
```
MAAS Service
    ↓
Adapter Interface
    ↓
├─ BMC Adapter (IPMI)
├─ BMC Adapter (Redfish)
└─ BMC Adapter (AMT)
    ↓
External System
```

**Implementation:**
```python
class BMCAdapter:
    def power_on(self, credentials):
        raise NotImplementedError
    
    def power_off(self, credentials):
        raise NotImplementedError
    
    def get_power_state(self, credentials):
        raise NotImplementedError

class IPMIAdapter(BMCAdapter):
    def power_on(self, credentials):
        # IPMI-specific implementation
        ipmitool(...)
        return PowerState.ON

class RedfishAdapter(BMCAdapter):
    def power_on(self, credentials):
        # Redfish REST API implementation
        response = requests.post(...)
        return PowerState.ON
```

**MAAS Example:**
Power control adapters for different BMC types (IPMI, Redfish, AMT, Moonshot) all implement common interface.

**When to Use:**
- Multiple implementations of same concept
- External API versions vary across deployments
- Need to switch implementations without changing calling code
- Testing with mock implementations

**When NOT to Use:**
- Single external system with stable API
- When abstraction adds more complexity than value
- Performance-critical code where indirection is costly

**Trade-offs:**
- ✅ Flexible: Easy to add new implementations
- ✅ Testable: Mock adapters for testing
- ✅ Maintainable: Isolate external API changes
- ❌ Abstraction overhead: May oversimplify or complicate
- ❌ Interface evolution: Hard to change interface without updating all adapters

### Pattern 6: Command Pattern (Asynchronous Tasks)

**Context:** Long-running operations that shouldn't block API responses.

**Problem:** Commissioning, deployment, testing take minutes; users shouldn't wait for API response.

**Solution:** Enqueue commands as tasks, return immediately, process asynchronously.

**Structure:**
```
API Request
    ↓
Validate & Enqueue Command
    ↓
Return 202 Accepted
    ↓
Background Worker (Celery/Twisted)
    ↓
Execute Command
    ↓
Update State & Notify
```

**Implementation:**
```python
# API endpoint
def commission_machine(request, system_id):
    machine = get_machine(system_id)
    validate_can_commission(machine)
    
    # Enqueue command
    task_id = commission_task.delay(system_id, request.user.id)
    
    return Response({
        'status': 'accepted',
        'task_id': task_id,
        'machine': machine.system_id
    }, status=202)

# Background task
@celery_app.task
def commission_task(system_id, user_id):
    machine = Machine.objects.get(system_id=system_id)
    machine.status = NODE_STATUS.COMMISSIONING
    machine.save()
    
    # Long-running operation
    power_on(machine)
    wait_for_commissioning_scripts()
    
    machine.status = NODE_STATUS.READY
    machine.save()
```

**MAAS Example:**
Machine commissioning, deployment, hardware testing all use async tasks. API returns immediately; client polls or subscribes to events for completion.

**When to Use:**
- Operations taking >2 seconds
- Hardware interactions (BMC power control)
- External API calls with high latency
- Batch operations on many machines

**When NOT to Use:**
- Fast queries (<100ms)
- Operations requiring immediate feedback
- When task scheduling overhead is significant

**Trade-offs:**
- ✅ Responsive: API returns immediately
- ✅ Scalable: Background workers can be scaled independently
- ✅ Reliable: Tasks can retry on failure
- ❌ Complexity: Asynchronous flow harder to debug
- ❌ State management: Must track task progress
- ❌ Eventual consistency: State changes happen later

### Pattern 7: State Machine (Machine Lifecycle)

**Context:** Machines transition through defined states with rules about valid transitions.

**Problem:** Ad-hoc state changes lead to invalid states and bugs.

**Solution:** Explicit state machine with allowed transitions and guards.

**Structure:**
```
NEW → COMMISSIONING → READY → ALLOCATED → DEPLOYING → DEPLOYED
  ↓         ↓           ↓          ↓           ↓
  └────→ FAILED_COMMISSIONING    FAILED_DEPLOYMENT
```

**Implementation:**
```python
MACHINE_TRANSITIONS = {
    NODE_STATUS.NEW: [NODE_STATUS.COMMISSIONING, NODE_STATUS.READY],
    NODE_STATUS.COMMISSIONING: [NODE_STATUS.READY, NODE_STATUS.FAILED_COMMISSIONING],
    NODE_STATUS.READY: [NODE_STATUS.ALLOCATED, NODE_STATUS.COMMISSIONING],
    NODE_STATUS.ALLOCATED: [NODE_STATUS.DEPLOYING, NODE_STATUS.READY],
    # ...
}

def transition_to(machine, new_status, user):
    if new_status not in MACHINE_TRANSITIONS.get(machine.status, []):
        raise InvalidStateTransition(
            f"Cannot transition from {machine.status} to {new_status}"
        )
    
    machine.status = new_status
    machine.save()
    
    emit_event(MachineStatusChanged(machine, user))
```

**MAAS Example:**
Machine status lifecycle strictly enforced. Can't deploy a machine that's not allocated; can't release a machine that's not deployed.

**When to Use:**
- Complex lifecycle with many states
- State transitions have business rules
- Need to prevent invalid states
- Audit trail of state changes important

**When NOT to Use:**
- Simple on/off states
- States are independent (not a sequence)
- Transitions are always valid (no guards needed)

**Trade-offs:**
- ✅ Correctness: Prevents invalid states
- ✅ Clarity: State diagram documents behavior
- ✅ Maintainable: Rules in one place
- ❌ Rigidity: Can be hard to handle edge cases
- ❌ Complexity: More code than simple state field

### Pattern 8: Optimistic Locking (Concurrent Updates)

**Context:** Multiple processes or users may update same machine simultaneously.

**Problem:** Last write wins can lose updates or create inconsistent state.

**Solution:** Use version field to detect concurrent modifications.

**Implementation:**
```python
class Machine(Model):
    system_id = CharField(primary_key=True)
    status = IntegerField()
    version = IntegerField(default=0)  # Optimistic lock
    
    def save(self, *args, **kwargs):
        if self.pk:
            # Update only if version matches
            updated = Machine.objects.filter(
                system_id=self.system_id,
                version=self.version
            ).update(
                status=self.status,
                version=F('version') + 1,
                **kwargs
            )
            
            if updated == 0:
                raise ConcurrentModificationError(
                    "Machine was modified by another process"
                )
            
            self.version += 1
        else:
            super().save(*args, **kwargs)
```

**MAAS Example:**
Machine allocation checks that machine is still in expected state before transitioning. If another user allocated it first, operation fails gracefully.

**When to Use:**
- Resources that can be modified concurrently
- Critical state transitions (allocation, deployment)
- When detecting conflicts is better than silently overwriting

**When NOT to Use:**
- Single-writer scenarios
- Append-only data (logs, events)
- When last-write-wins is acceptable

**Trade-offs:**
- ✅ Safe: Detects concurrent modifications
- ✅ No locks: No performance impact of pessimistic locking
- ❌ Retry logic: Client must handle failures and retry
- ❌ Not for high-contention: Many retries if resource highly contested

## Integration Patterns

### Pattern 9: Webhook Pattern (External Notifications)

**Context:** External systems need to be notified of MAAS events.

**Problem:** External systems can't subscribe to PostgreSQL NOTIFY; polling is inefficient.

**Solution:** Provide webhook registration and delivery mechanism.

**Structure:**
```
MAAS Event
    ↓
Webhook Manager
    ↓
HTTP POST to registered URLs
    ↓
External System (Slack, PagerDuty, Custom)
```

**Implementation:**
- Users register webhook URLs via API
- Event handler triggers webhook delivery
- Retry failed deliveries with exponential backoff
- Log webhook calls for audit/debugging

**MAAS Example:**
Notify Slack when machine deployment fails; trigger PagerDuty when hardware fault detected.

**When to Use:**
- Integrating with external monitoring/alerting
- Custom workflows triggered by MAAS events
- Audit logging to external systems

### Pattern 10: API Gateway Pattern (Multi-Region Access)

**Context:** Users need unified access to multiple MAAS regions.

**Problem:** Each region has separate API; users must authenticate to each.

**Solution:** Gateway service that routes requests to appropriate region.

**Structure:**
```
Client
    ↓
API Gateway (single endpoint)
    ↓
├─→ Region 1 API
├─→ Region 2 API
└─→ Region 3 API
```

**Implementation:**
- Gateway maintains region registry
- Routes requests based on machine system_id or explicit region parameter
- Handles authentication to regional controllers
- Aggregates responses for cross-region queries

**MAAS Example:**
Cross-region search service acts as gateway, querying multiple regions and merging results.

**When to Use:**
- Multi-region deployments
- Unified authentication across regions
- Cross-region queries and operations

**When NOT to Use:**
- Single-region deployments
- When region-specific operations are rare
- Adds complexity without benefit

## Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Central State Database for Regions

**Problem:** Creating central database that replicates all regional machine data.

**Why it's bad:**
- Breaks regional autonomy
- Synchronization delays and consistency issues
- Single point of failure
- Operational complexity (managing replication)
- Regions become dependent on central system

**What to do instead:**
Use federated queries (scatter-gather pattern) to query regions on-demand.

### ❌ Anti-Pattern 2: Synchronous External API Calls in Request Path

**Problem:** API endpoint makes synchronous call to BMC/external service and waits.

**Why it's bad:**
- Blocks worker thread
- Slow external service causes timeouts
- Doesn't scale under load
- Poor user experience (waiting for response)

**What to do instead:**
Use command pattern with async tasks. Return 202 Accepted immediately, process in background.

### ❌ Anti-Pattern 3: Polling for State Changes

**Problem:** Client repeatedly queries API to check if machine status changed.

**Why it's bad:**
- Inefficient (most polls return no change)
- Increases database and API load
- Introduces latency (poll interval)
- Doesn't scale with many clients

**What to do instead:**
Use event-driven updates with WebSocket or webhook notifications.

### ❌ Anti-Pattern 4: God Objects

**Problem:** Single class or module does too many things (e.g., `MachineManager` handles allocation, deployment, networking, storage, power).

**Why it's bad:**
- Hard to understand and test
- Changes have wide blast radius
- Tight coupling between unrelated concerns
- Multiple developers conflict when editing

**What to do instead:**
Separate concerns into focused services (`AllocationService`, `DeploymentService`, `PowerService`).

### ❌ Anti-Pattern 5: Leaky Abstractions

**Problem:** Adapter pattern that exposes underlying implementation details (e.g., IPMI-specific fields in generic BMC interface).

**Why it's bad:**
- Defeats purpose of abstraction
- Makes it hard to add new implementations
- Calling code becomes dependent on specific adapters

**What to do instead:**
Design adapter interface based on common capabilities, not specific implementations. Use adapter-specific extensions only when necessary.

### ❌ Anti-Pattern 6: Ignoring Idempotency

**Problem:** Operations fail or have side effects when retried (e.g., allocating machine twice creates two allocation records).

**Why it's bad:**
- Network failures and retries are inevitable
- Can't safely retry failed operations
- Creates inconsistent state
- Users fear retrying, leading to stuck workflows

**What to do instead:**
Design operations to be idempotent. Check current state before acting. Use database constraints to prevent duplicates.

## Decision Framework

### Choosing the Right Pattern

Ask these questions:

1. **Is this a common MAAS problem?**
   - Yes → Check if existing pattern applies
   - No → Consider if pattern makes sense for MAAS

2. **Does this maintain MAAS principles?**
   - Regional autonomy preserved?
   - API-first approach?
   - Graceful degradation?
   - Idempotent operations?

3. **What's the complexity trade-off?**
   - Does pattern solve a real problem?
   - Is added complexity justified?
   - Will team understand and maintain it?

4. **How does it fit existing codebase?**
   - Consistent with current architecture?
   - Reuses existing components?
   - Follows MAAS conventions?

5. **What are the operational implications?**
   - Monitoring and debugging?
   - Performance characteristics?
   - Failure modes?

### Pattern Combination

Patterns often work together:

**Example: Machine Deployment**
- **State Machine**: Enforce valid status transitions
- **Command Pattern**: Run deployment asynchronously
- **Event-Driven Updates**: Broadcast status changes to UI
- **Adapter Pattern**: Abstract OS image deployment mechanisms
- **Service Layer**: Orchestrate deployment workflow

## Summary

Effective MAAS architecture design requires:

1. **Understand MAAS principles**: Regional autonomy, API-first, idempotency, graceful degradation
2. **Apply proven patterns**: Use established solutions to common problems
3. **Justify decisions**: Explain why a pattern fits the problem
4. **Maintain consistency**: Follow existing codebase conventions
5. **Consider trade-offs**: Every pattern has costs and benefits
6. **Avoid anti-patterns**: Learn from past mistakes
7. **Think operationally**: Consider monitoring, debugging, and failure modes

A well-architected MAAS feature leverages existing patterns, maintains system principles, and balances complexity with functionality.