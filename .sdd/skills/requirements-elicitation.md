# Requirements Elicitation for MAAS

## Overview

Requirements elicitation is the systematic process of discovering, extracting, and documenting what users need from a system. In the MAAS context, this involves understanding infrastructure management workflows, operational constraints, integration requirements, and user pain points to create specifications that solve real problems.

## Purpose

- **Discover hidden needs**: Uncover requirements users may not explicitly state
- **Validate assumptions**: Test whether what we think users need matches reality
- **Build empathy**: Understand user context, constraints, and pressures
- **Prioritize effectively**: Identify which problems matter most
- **Reduce rework**: Get requirements right before planning and implementation

## MAAS User Landscape

Before eliciting requirements, understand who you're talking to:

### User Categories

1. **MAAS Operators**: Day-to-day machine management, troubleshooting
2. **Platform Engineers**: Building automation, integrating with orchestration
3. **Network Engineers**: Managing MAAS networking, VLAN configuration
4. **Security Teams**: Ensuring compliance, managing access control
5. **Application Owners**: Consuming infrastructure provisioned by MAAS
6. **Executives/Managers**: Concerned with costs, reliability, team efficiency

Each category has different priorities, vocabulary, and pain points.

## Core Elicitation Techniques

### 1. Contextual Inquiry (Observation + Interview)

**When to Use:** Understanding current workflows and identifying pain points

**How It Works:**
- Visit user in their working environment
- Observe them performing actual MAAS tasks
- Ask questions as they work (without interrupting flow)
- Note tools, screens, workarounds, and emotional reactions

**MAAS Application:**
- Shadow operator during machine provisioning
- Watch incident response when deployment fails
- Observe network configuration setup
- See how users interact with MAAS API vs. UI

**Example Questions During Observation:**
- "What are you looking for in this view?"
- "Why did you switch to the terminal?"
- "Is this a typical scenario or an edge case?"
- "What would make this step easier?"

**What to Capture:**
- Actual clicks, commands, and navigation paths
- Time spent on each step
- Context switches (MAAS → terminal → documentation → Slack)
- Workarounds ("I usually just export to CSV because...")
- Moments of confusion or frustration

**Example:**
*Observing operator troubleshooting deployment failure:*
- Clicks on machine → Events tab (15 seconds to load)
- Scrolls through 200+ log entries searching for error
- Copies error message, searches in browser
- Opens 3 documentation tabs, reads for 5 minutes
- Returns to MAAS, retries deployment without changing anything
- **Pain Point Identified:** Error messages don't link to documentation, logs are overwhelming

### 2. Semi-Structured Interviews

**When to Use:** Exploring needs, understanding goals, discovering priorities

**How It Works:**
- Prepare open-ended questions but allow conversation to flow
- Focus on problems, not solutions
- Use "5 Whys" to dig deeper into root causes
- Ask for specific examples, not generalizations

**Interview Structure:**

**Opening (5 min):**
- Establish rapport, explain purpose
- "Tell me about your role with MAAS"
- "What's a typical day like?"

**Current State (15 min):**
- "What are the most frequent tasks you perform in MAAS?"
- "Walk me through [specific workflow]"
- "What takes the most time?"
- "What's most frustrating?"

**Pain Points (15 min):**
- "Tell me about a recent problem you had with MAAS"
- "What workarounds have you developed?"
- "What do you wish MAAS could do that it can't today?"

**Future State (10 min):**
- "If you could change one thing, what would it be?"
- "How would your ideal workflow look?"
- "What would success look like?"

**Closing (5 min):**
- "Is there anything I didn't ask about that I should know?"
- "Who else should I talk to?"

**MAAS-Specific Question Prompts:**

**For Operators:**
- "How do you handle a failed deployment?"
- "What's your process for commissioning new hardware?"
- "How do you track which machines are allocated to which projects?"

**For Platform Engineers:**
- "How does MAAS fit into your infrastructure automation?"
- "What challenges have you faced integrating MAAS with [Terraform/Ansible/Juju]?"
- "What MAAS API limitations have you encountered?"

**For Network Engineers:**
- "Walk me through setting up a new VLAN in MAAS"
- "How do you troubleshoot networking issues?"
- "What's confusing about the MAAS network model?"

**Techniques for Deeper Insight:**

**The 5 Whys:**
```
User: "Deployment is slow"
Why? "It takes too long to find available machines"
Why? "I can't filter by hardware specs"
Why? "The UI doesn't have those filters"
Why? "I have to check each machine manually"
Why? "Because I need specific GPU models and that's not searchable"
→ Root need: Hardware-based search, specifically GPU model filtering
```

**Silence:**
After user answers, pause 3-5 seconds. Often they'll add crucial details:
"Actually, the bigger issue is..." (reveals hidden pain point)

**Concreteness:**
- Don't accept: "Search is bad"
- Ask: "Show me the last time search didn't work for you. What were you looking for?"

### 3. Task Analysis

**When to Use:** Understanding specific workflows in detail

**How It Works:**
- Ask user to demonstrate a complete task
- Document every step, decision, and artifact
- Identify inputs, outputs, dependencies

**MAAS Example: "Provision 10 Machines for New Cluster"**

**Task Decomposition:**
```
1. Receive requirement (input: CPU/RAM/storage specs, network requirements)
2. Search for available machines
   - Decision: Check web UI or use CLI?
   - Pain Point: No hardware filter in UI
3. Identify candidates (output: list of 15 possible machines)
4. Verify network connectivity for each
   - Artifact: Spreadsheet tracking machine IPs and VLAN assignments
5. Allocate machines
   - Decision: Allocate all at once or one-by-one?
6. Apply tags for project identification
7. Configure custom storage layout (if needed)
8. Deploy OS
9. Verify deployment success
10. Hand off IPs to requestor
```

**Questions to Ask:**
- "What information do you need before starting?"
- "How do you decide between option A and B?"
- "What can go wrong at this step?"
- "How do you verify this worked?"
- "What happens if this fails?"

### 4. Problem/Goal-Oriented Questions

**When to Use:** Ensuring focus on real needs, not assumed solutions

**The Key Principle:** Ask about problems and goals, not solutions

**Anti-Pattern:**
"Would you like a dashboard widget showing machine health?"
*(This assumes the solution)*

**Better Approach:**
"How do you currently monitor machine health?"
"What triggers you to check on machines?"
"What would you do if you noticed a problem?"

**MAAS Examples:**

**Bad (Solution-Focused):**
- "Should we add a GraphQL API?"
- "Do you want Kubernetes integration?"

**Good (Problem-Focused):**
- "What's difficult about the current REST API?"
- "Tell me about deploying MAAS-provisioned machines into Kubernetes"
- "What are you trying to accomplish when you use [feature]?"

### 5. Personas and Scenario Development

**When to Use:** Generalizing from individual users to user categories

**How It Works:**
- Synthesize interview data into representative user types
- Create scenarios showing how personas use MAAS
- Validate scenarios with real users

**Example MAAS Persona:**

**Name:** Sarah, Senior Platform Engineer
**Environment:** 5-region MAAS deployment, 2000+ machines
**Goals:** 
- Maintain 99.9% provisioning success rate
- Enable developer self-service via Terraform
- Minimize manual intervention

**Pain Points:**
- Multi-region visibility gap
- Terraform provider has authentication quirks
- No way to set provisioning quotas per team

**Typical Scenario:**
Dev team requests 20 machines for staging environment. Sarah needs to verify capacity exists across regions, allocate machines with appropriate network access, and provide Terraform module for team to deploy.

**Usage in Elicitation:**
Present persona to other users: "Does this sound like your situation?"

### 6. Data-Driven Discovery

**When to Use:** Finding patterns in actual system usage

**MAAS Data Sources:**

**Event Logs:**
- Which machine states appear most in logs?
- What errors occur most frequently?
- What's the time distribution of deployments (identifying slow cases)?

**API Usage Patterns:**
- Which endpoints are called most?
- What call sequences reveal integration patterns?
- Where do API errors spike?

**Web UI Analytics:**
- Which pages get most traffic?
- Where do users spend the most time?
- What navigation paths are most common?

**Support Tickets:**
- Categorize by theme (networking, deployment, hardware, etc.)
- Identify recurring questions
- Note workarounds users have discovered

**Example Analysis:**
```
Support ticket analysis (last 90 days):
- 45% networking configuration issues
- 30% deployment failures (unclear root cause)
- 15% API authentication problems
- 10% hardware compatibility

→ Prioritize: Better networking UX, deployment diagnostics
```

### 7. Comparative Analysis

**When to Use:** Understanding user expectations based on other tools

**Questions:**
- "What other infrastructure tools do you use?"
- "How does [competitor] handle this?"
- "What do you like about [other tool]?"
- "If you could bring one feature from [tool X] to MAAS, what would it be?"

**Example:**
"We use Foreman for some legacy infrastructure. Their template system makes OS customization really easy. In MAAS, cloud-init is more powerful but harder to get started with. Could we have simple templates for common cases?"

→ Reveals need for simplified cloud-init presets

### 8. Negative Brainstorming

**When to Use:** Breaking through "I don't know what I need" situations

**How It Works:**
Ask users what they DON'T want or what would make things WORSE

**Questions:**
- "What would make MAAS completely unusable for you?"
- "What's the worst deployment experience you can imagine?"
- "If we made one change that would frustrate you the most, what would it be?"

**Example:**
"The worst thing would be if MAAS started requiring manual approval for every deployment. We do hundreds per day—that would kill our automation."

→ Reveals priority: automation and non-blocking workflows are critical

## Stakeholder-Specific Strategies

### Operators (Hands-On Users)

**Best Techniques:**
- Contextual inquiry (shadow their work)
- Task analysis
- Show-me-how sessions

**Focus Areas:**
- Day-to-day workflow efficiency
- Error handling and troubleshooting
- Repetitive tasks that could be automated

**Communication Style:**
- Concrete, practical examples
- "Show me" rather than "tell me"
- Focus on time savings

### Platform Engineers (Integration-Focused)

**Best Techniques:**
- Semi-structured interviews
- API usage analysis
- Integration scenario mapping

**Focus Areas:**
- API capabilities and limitations
- Integration points with other tools
- Automation and programmatic access
- Reliability and predictability

**Communication Style:**
- Technical depth is welcome
- Discuss patterns and architectures
- Code examples resonate

### Executives/Managers

**Best Techniques:**
- Structured interviews (respect time constraints)
- Metrics and data review
- Business impact analysis

**Focus Areas:**
- Team productivity
- Cost efficiency
- Risk and compliance
- Strategic goals

**Communication Style:**
- Business outcomes, not technical features
- ROI and metrics
- Brief and focused

## Common Pitfalls and How to Avoid Them

### ❌ Pitfall 1: Accepting Solutions as Requirements

**Example:**
User: "We need a Redis cache for machine queries"

**Why It's a Pitfall:**
This is a solution, not a requirement. The real requirement might be "fast queries" which could have multiple solutions.

**How to Redirect:**
"What problem are you trying to solve with caching?"
"Tell me about the query performance you're experiencing"
"What would acceptable performance look like?"

### ❌ Pitfall 2: Leading Questions

**Bad:**
"Wouldn't it be great if MAAS had real-time updates?"

**Why It's a Pitfall:**
Biases user toward agreeing with your assumption

**Better:**
"How do you currently know when a machine's status changes?"
"Do you need to see changes immediately, or is periodic refresh acceptable?"

### ❌ Pitfall 3: Ignoring Edge Cases

**Example:**
User: "Well, 99% of the time we just use the default..."

**Why It's a Pitfall:**
The 1% case might be critical (security, compliance, major incidents)

**How to Dig:**
"Tell me about that 1% situation"
"When was the last time you hit an edge case?"
"What happens when the default doesn't work?"

### ❌ Pitfall 4: Only Talking to Power Users

**Why It's a Pitfall:**
Power users have workarounds; they don't represent typical user struggles

**How to Balance:**
- Interview users with varying experience levels
- Find users who stopped using a feature (why?)
- Talk to new team members (fresh perspective)

### ❌ Pitfall 5: Confusing "Loud" with "Important"

**Why It's a Pitfall:**
The user who emails most isn't necessarily representative

**How to Validate:**
- Triangulate: multiple sources confirm need
- Check data: how many users are affected?
- Measure impact: time lost, errors caused, revenue affected

## Documentation During Elicitation

### In-Session Notes

**Capture:**
- Direct quotes (in quotes)
- Observed actions [in brackets]
- Your interpretations (in parentheses)
- Pain points **in bold**
- Workarounds *in italics*

**Example:**
```
"I can never find the machines I need" - spends 5 minutes clicking through machine list
[Opens Excel spreadsheet with machine inventory - clearly a workaround]
**Pain point: No hardware-based filtering**
(Seems frustrated, sighs repeatedly)
*Maintains separate spreadsheet because MAAS search is insufficient*
```

### Post-Session Synthesis

**Within 24 hours:**
- Review notes
- Identify themes
- List direct requirements
- Flag questions for follow-up
- Note contradictions between users

**Template:**
```
## Interview: [Name, Role, Date]

### Key Problems Identified:
1. Can't filter machines by GPU model (mentioned 3x, high frustration)
2. Deployment errors are cryptic
3. No way to track cost per project

### User Workflows:
- [Summarize main workflows observed]

### Quotes:
- "If I could search by hardware, it would save me 30 minutes every single day"

### Follow-up Questions:
- How many GPU models are in their environment?
- What error messages are most confusing?
```

## Validation and Prioritization

### Validating Requirements

**Techniques:**
1. **Show-back:** Present synthesized requirements to users for confirmation
2. **Prototype testing:** Mockup a solution, gather feedback
3. **Triangulation:** Does this match what others said?
4. **Data validation:** Do metrics support this claim?

**Example:**
User says: "Everyone struggles with networking setup"
Validation: Check support tickets (40% are networking), interview 5 other operators (4 confirm)
→ Validated

### Prioritization Framework

**Rank by:**
1. **Frequency:** How often does this problem occur?
2. **Impact:** How much time/money/frustration does it cause?
3. **User Count:** How many users are affected?
4. **Strategic Alignment:** Does this fit business goals?

**MAAS Example:**
```
Requirement: Hardware-based machine search
- Frequency: Daily for 80% of operators
- Impact: Saves 30 min/day (high)
- User Count: ~200 active operators
- Strategic: Enables enterprise adoption (high)
→ Priority: HIGH

Requirement: Dark mode for web UI
- Frequency: Constant (always visible)
- Impact: Aesthetic preference (low)
- User Count: Some users prefer it
- Strategic: Not aligned with goals
→ Priority: LOW
```

## From Elicitation to Specification

### Translating Insights

**Elicitation Output → Specification Section**

- **User pain points** → Problem Statement
- **Observed workflows** → User Journeys (current state)
- **Desired outcomes** → User Journeys (future state)
- **Performance complaints** → Success Criteria (quantified)
- **Must-have capabilities** → Acceptance Criteria
- **Workarounds** → Evidence of problems to solve
- **Cross-tool integration** → Dependencies and assumptions

### Example Translation

**From Interview:**
"I maintain a spreadsheet of machines because I can't search MAAS by CPU or RAM. Every time someone asks for machines with 64GB+ RAM, I filter my spreadsheet, then manually look up each machine in MAAS to check if it's available. This wastes 30 minutes per request, and I get 2-3 requests per day."

**Specification Section (Problem Statement):**
MAAS operators managing large deployments cannot efficiently locate machines matching specific hardware requirements. Without hardware-based search capabilities, operators resort to maintaining external spreadsheets and performing manual, per-machine verification in the MAAS UI. This adds 30+ minutes to each provisioning request (2-3 daily), resulting in ~15 hours of wasted effort per week per operator.

**Specification Section (Acceptance Criteria):**
- [ ] Users can filter machines by minimum CPU count
- [ ] Users can filter machines by minimum RAM size
- [ ] Search results display in under 3 seconds for 5,000-machine environments
- [ ] Filters can be combined (AND logic)

## Summary

Effective requirements elicitation for MAAS requires:

1. **Talk to diverse users** (operators, engineers, managers)
2. **Observe real work** (not just interviews)
3. **Focus on problems** (not solutions)
4. **Dig deep with Why** (get to root causes)
5. **Validate with data** (logs, metrics, multiple sources)
6. **Capture concrete examples** (not generalizations)
7. **Translate to specifications** (problem-focused, testable)

The goal is to understand what users truly need so specifications enable effective solutions without prescribing how those solutions are built.