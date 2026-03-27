# User Journey Mapping for MAAS

## Overview

User journey mapping is the process of documenting the sequence of steps a user takes to accomplish a goal, including their actions, the system's responses, decision points, pain points, and emotional states. In the MAAS context, this helps identify where improvements are needed and ensures specifications address real workflow challenges.

## Purpose

- **Understand current workflows** (as-is journeys) to identify pain points
- **Design future workflows** (to-be journeys) that the specification should enable
- **Validate assumptions** about how users interact with MAAS
- **Communicate user needs** to technical teams without prescribing solutions
- **Identify integration points** with other tools and systems

## Journey Mapping Framework

### Basic Journey Structure

Every user journey should include:

1. **Actor**: Who is performing this journey (specific user role)
2. **Trigger**: What initiates the journey (event, need, or request)
3. **Goal**: What the user is trying to accomplish
4. **Steps**: Sequence of actions and system responses
5. **Outcome**: End state when the journey completes
6. **Context**: Environment, tools, constraints

### Step Detail Template

For each step in the journey:

```
[Step Number]. [Action Name]: [What the user does]
   - System Response: [What the system does in reaction]
   - User Sees: [What feedback/information the user receives]
   - Decision Point: [If applicable, what choices the user must make]
   - Pain Point: [If applicable, what frustrates or blocks the user]
```

## MAAS-Specific Journey Types

### 1. Machine Lifecycle Journeys

Track how users move machines through MAAS states:

**Example: Provisioning New Hardware**

- **Trigger**: New servers arrive in datacenter
- **Actor**: MAAS Operator
- **Steps**: Enlist → Commission → Tag → Allocate → Deploy → Verify
- **Pain Points**: Manual MAC address entry, commissioning failures without clear diagnostics

**Example: Recycling Deployed Machines**

- **Trigger**: Application decommissioned, machines need to return to pool
- **Actor**: Platform Engineer
- **Steps**: Identify machines → Release → Verify data wiped → Return to ready state
- **Pain Points**: Uncertainty about data sanitization, can't bulk-release by application tag

### 2. Network Configuration Journeys

Focus on VLAN, subnet, and IP management workflows:

**Example: Setting Up Multi-VLAN Environment**

- **Actor**: Network-aware MAAS Operator
- **Steps**: Define VLANs → Create subnets → Assign IP ranges → Configure fabric → Test connectivity
- **Pain Points**: Complex relationship between fabrics/VLANs/subnets, easy to misconfigure

### 3. Troubleshooting Journeys

Document diagnostic and problem-resolution workflows:

**Example: Diagnosing Deployment Failure**

- **Trigger**: Machine stuck in "Deploying" state for 30+ minutes
- **Actor**: MAAS Operator (on-call, time pressure)
- **Steps**: Notice alert → Check machine status → Review event log → Identify error → Search documentation → Attempt resolution → Retry deployment
- **Pain Points**: Event logs are verbose and hard to parse, root cause not obvious, documentation search is slow

### 4. Integration Journeys

Map how users connect MAAS with external tools:

**Example: Terraform-Driven Provisioning**

- **Actor**: Platform Engineer
- **Steps**: Define infrastructure as code → Run terraform plan → Allocate machines via MAAS API → Configure networking → Deploy → Output machine IPs to Terraform state
- **Pain Points**: API authentication setup is complex, machine allocation timing is unpredictable

### 5. Monitoring and Operations Journeys

Track ongoing operational workflows:

**Example: Daily Health Check**

- **Actor**: MAAS Operator (routine task)
- **Steps**: Login → Review dashboard → Check failed machines → Investigate anomalies → Clear alerts → Document issues
- **Pain Points**: No single "health score," must check multiple views, no trend analysis

## Techniques for Gathering Journey Data

### 1. User Shadowing

Observe users performing actual MAAS tasks:

- **When**: Best for understanding current (as-is) workflows
- **How**: Sit with operator during real work, take notes without interrupting
- **Focus**: Note exact clicks, commands, wait times, context switches, frustration moments
- **MAAS Context**: Shadow during commissioning, deployment, or incident response

**Example Questions:**
- "What are you checking for in the event log?"
- "Why did you switch to the CLI instead of using the web UI?"
- "How do you know when commissioning is complete?"

### 2. Task Walkthroughs

Ask users to demonstrate specific workflows:

- **When**: When you need to understand a particular scenario
- **How**: Ask user to perform a task while narrating their thought process
- **Focus**: Decision points, workarounds, tools used outside MAAS
- **MAAS Context**: "Show me how you provision a machine for a specific workload"

**Example Tasks:**
- "Allocate 5 machines with specific hardware requirements"
- "Set up networking for a new subnet"
- "Find all machines deployed in the last 24 hours"

### 3. Interview-Based Journey Elicitation

Discuss workflows conversationally:

- **When**: Early discovery or when shadowing isn't feasible
- **How**: Ask users to describe a recent task step-by-step
- **Focus**: Trigger, frequency, time taken, pain points
- **MAAS Context**: Focus on critical or frequent workflows

**Example Questions:**
- "Walk me through the last time you had to troubleshoot a failed deployment"
- "What's your process when someone requests 10 new machines?"
- "How do you handle machine failures during off-hours?"

### 4. Journey Reconstruction from Data

Analyze MAAS logs and metrics to understand actual usage:

- **When**: To validate self-reported workflows or find hidden patterns
- **How**: Examine audit logs, event logs, API access patterns
- **Focus**: Frequency of actions, time between steps, error rates
- **MAAS Context**: Machine state transitions, API endpoint usage, web UI navigation

**Data Points:**
- Machine state change timestamps (time from allocation to deployment)
- Event log patterns (common errors, most-viewed events)
- API usage (which endpoints are called together, in what sequence)

### 5. Pain Point Mapping

Focus specifically on identifying where workflows break down:

- **When**: When improving existing features
- **How**: Ask users "What's the most frustrating part of [task]?"
- **Focus**: Wait times, errors, manual workarounds, context switches
- **MAAS Context**: Common complaints: slow queries, unclear error messages, repetitive manual steps

**Pain Point Categories:**
- **Time sinks**: "This takes 20 minutes when it should take 2"
- **Error-prone**: "I always forget to do X and have to start over"
- **Opacity**: "I can't tell why this failed"
- **Workarounds**: "I export to CSV because the UI can't filter properly"

## MAAS User Archetypes

Tailor journey mapping to these common MAAS user profiles:

### The Operator (Day-to-Day Manager)

- **Focus**: Routine provisioning, troubleshooting, monitoring
- **Journey Characteristics**: Repetitive tasks, time-sensitive, prefers UI for visibility
- **Pain Points**: Lack of automation, poor search/filter, unclear errors

### The Platform Engineer (Automation Builder)

- **Focus**: Integration with orchestration tools, API usage, self-service infrastructure
- **Journey Characteristics**: Scripting-heavy, needs reliability and predictability
- **Pain Points**: API complexity, authentication, inconsistent behavior

### The Incident Responder (On-Call)

- **Focus**: Fast diagnosis and resolution, often under pressure
- **Journey Characteristics**: Short, urgent, need clear signals
- **Pain Points**: Verbose logs, slow queries, hard-to-find documentation

### The Architect (Strategic Planner)

- **Focus**: Multi-region setup, capacity planning, integration strategy
- **Journey Characteristics**: Infrequent but high-impact, needs global visibility
- **Pain Points**: No cross-region view, no capacity forecasting, hard to model complex networking

## Journey Documentation Best Practices

### 1. Use Concrete Examples

**Bad (too abstract):**
"User searches for machines and filters results"

**Good (concrete):**
"Operator searches for 'gpu' tag, applies filter 'status=ready', sees 12 matching machines, sorts by RAM descending, selects top 3 machines"

### 2. Include Timing

Add time estimates to identify bottlenecks:

```
1. Search for machines (5 seconds)
2. Review results and identify candidates (2 minutes)
3. Manually check each machine's network config (5 minutes)  ← Pain point
4. Allocate machines (10 seconds)
```

### 3. Show System State Changes

Make it clear how MAAS state evolves:

```
1. User clicks "Allocate"
   - System: Machine state changes New → Allocated
   - System: Machine is locked to user
   - User sees: Status badge turns blue, "Allocated to: jdoe"
```

### 4. Highlight Cross-Tool Workflows

MAAS is rarely used in isolation:

```
1. User defines infrastructure in Terraform
2. Terraform calls MAAS API to allocate machines
3. User SSHs to machines to verify connectivity  ← Context switch
4. User updates Juju model with machine IPs  ← Another tool
5. Juju deploys applications to machines
```

### 5. Note Workarounds and Hacks

These reveal where MAAS falls short:

```
Pain Point: Can't filter by hardware specs in UI
Workaround: User exports all machines to CSV, opens in Excel, filters there, 
then manually looks up machines by name in MAAS UI (adds 10 minutes)
```

## Example: Complete Journey Map

**Journey: Emergency Hardware Replacement**

**Actor:** MAAS Operator (on-call)  
**Trigger:** 2 AM alert - physical server failure, workload needs migration  
**Goal:** Replace failed machine with spare and redeploy workload  
**Context:** On-call, limited VPN access, urgency to restore service  

**Steps:**

1. **Receive alert**: Monitoring system reports machine "node-345" failed
   - User Sees: Alert on phone, machine name and failure type
   - Decision: Access MAAS via mobile or laptop?
   - Pain Point: Mobile UI is not optimized, must use laptop

2. **Login to MAAS**: Navigate to MAAS web UI via VPN
   - System Response: Authentication successful
   - User Sees: Dashboard
   - Duration: 30 seconds (including VPN connect)

3. **Locate failed machine**: Search for "node-345"
   - System Response: Shows machine in "Failed testing" state
   - User Sees: Machine details, last event log entries
   - Pain Point: Event log is cryptic, doesn't clearly state hardware failure type
   - Duration: 20 seconds

4. **Identify workload**: Check tags to see what was deployed
   - User Sees: Tags indicate "database-cluster", "production"
   - Decision: Critical workload, need immediate replacement
   - Pain Point: No easy way to see what applications are running on machine
   - Duration: 30 seconds

5. **Find replacement machine**: Search for ready machines with similar specs
   - System Response: Shows list of ready machines
   - User Sees: Machine names, but must click each to see full specs
   - Pain Point: Can't filter by "CPU >= 32" or "RAM >= 256GB"
   - Workaround: Manually check 8 machines one by one
   - Duration: 5 minutes

6. **Allocate replacement**: Allocate "node-389" with correct tags
   - System Response: Machine allocated successfully
   - User Sees: Status changes to "Allocated to: on-call-operator"
   - Duration: 10 seconds

7. **Deploy OS**: Deploy Ubuntu 22.04 LTS
   - System Response: Deployment starts, machine reboots
   - User Sees: Status "Deploying", progress indicator
   - Duration: Wait 8 minutes for deployment
   - Pain Point: No way to expedite deployment for urgent situations

8. **Verify deployment**: Check machine is "Deployed" and reachable
   - System Response: Machine shows "Deployed"
   - User Sees: IP address assigned
   - Pain Point: Must SSH manually to verify, no built-in connectivity test
   - Duration: 1 minute

9. **Hand off to application team**: Notify team machine is ready
   - Action: Send Slack message with machine IP and details
   - Pain Point: Manual notification, no integration with incident management
   - Duration: 1 minute

**Total Time:** ~16 minutes  
**Major Pain Points:**  
- Finding replacement with right specs (5 min)
- Waiting for deployment (8 min)
- Manual verification steps (2 min)

**Outcome:** Workload team can proceed with application redeployment, but 16-minute delay contributes to SLA miss

**To-Be Vision:** With hardware-based search and deployment profiles, could reduce to ~9 minutes (8 min deployment is unavoidable)

## Integration with Specification

Once journeys are mapped, translate them into specification sections:

- **Journeys → User Journeys section**: Document to-be journeys showing improved workflow
- **Pain Points → Problem Statement**: Articulate what's broken today
- **Workarounds → Success Criteria**: Define how feature eliminates workarounds
- **Time sinks → Performance requirements**: "Search must return in <3 seconds"
- **Manual steps → Acceptance Criteria**: "User can filter by hardware specs without exporting to CSV"

## Validation Checklist

Before using a journey in a specification, verify:

- [ ] Journey is based on real user observation or interview (not assumed)
- [ ] Specific user role is identified
- [ ] Trigger and goal are clear
- [ ] Steps are concrete and actionable (not vague)
- [ ] System responses are documented
- [ ] Pain points are explicitly called out
- [ ] Timing is included (where relevant)
- [ ] Journey represents a complete task (has clear outcome)
- [ ] Cross-tool interactions are noted
- [ ] Journey is representative (not an edge case, unless that's the focus)

## Summary

Effective user journey mapping in MAAS requires understanding both the tool (machine lifecycle, networking model, API patterns) and the users (operators, engineers, incident responders). Focus on concrete, observable workflows, document pain points explicitly, and use journeys to drive problem-focused specifications that enable better solutions.