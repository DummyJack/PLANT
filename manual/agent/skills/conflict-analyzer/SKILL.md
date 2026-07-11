---
name: conflict-analyzer
description: Identifies and analyzes conflicts in software requirements including logical contradictions, technical incompatibilities, resource constraints, timeline issues, data conflicts, and stakeholder priority mismatches. Use when reviewing requirement sets, specifications, user stories, or project plans to detect conflicts that could block implementation or cause rework. Provides detailed conflict analysis with resolution strategies.
allowed-tools: artifact_query
---

## Core Capabilities

This skill enables you to:

1. **Detect conflicts** - Identify 8 types of requirement conflicts
2. **Recommend resolutions** - Suggest appropriate resolution strategies
3. **Generate reports** - Create structured conflict analysis reports

## Analysis Workflow

Follow this process when analyzing requirements for conflicts:

### Step 1: Catalog All Requirements

Collect and organize all requirements:
- Extract from documents, user stories, tickets
- Assign unique IDs if not already present
- Group by feature, component, or domain
- Note stakeholder sources

### Step 2: Systematic Conflict Detection

Use `references/conflict_patterns.md` to scan for 8 conflict types:

**1. Logical Conflicts**
- Direct contradictions (A says yes, B says no)
- Mutually exclusive features
- Opposite behaviors
- Example: "Work offline" vs "Require continuous internet"

**2. Technical Conflicts**
- Platform incompatibilities
- Technology stack conflicts
- API/library version mismatches
- Protocol incompatibilities
- Example: "Support IE11" vs "Use ES2022 features"

**3. Resource Conflicts**
- Team capacity limitations
- Budget constraints
- Infrastructure limits
- Bandwidth/performance limits
- Example: "1000 concurrent streams" vs "1 Gbps bandwidth limit"

**4. Temporal Conflicts**
- Dependency deadline mismatches
- Impossible timelines
- Frequency conflicts
- Processing time conflicts
- Example: "Dashboard by March 1" depends on "Auth by March 15"

**5. Data Conflicts**
- Format incompatibilities
- Validation rule conflicts
- Data type mismatches
- Uniqueness conflicts
- Retention policy conflicts
- Example: "Email must be unique" vs "Allow multiple accounts per email"

**6. State Conflicts**
- Invalid state transitions
- State definition overlaps
- Circular state dependencies
- Concurrent state conflicts
- Example: "Processing orders can't be modified" vs "Processing orders can be cancelled"

**7. Priority Conflicts**
- Competing stakeholder priorities
- Performance vs security trade-offs
- UX vs compliance conflicts
- Cost vs reliability tensions
- Example: "Both features critical for v1" but "Only time for one"

**8. Scope Conflicts**
- Feature outside defined scope
- Platform expansion beyond bounds
- Integration beyond standalone scope
- Component boundary violations
- Example: "Web app only" vs "Upload from mobile app"

### Step 3: Recommend Resolution Strategies

Use `references/resolution_strategies.md` to propose solutions:

**Strategy Selection Guide:**

| Conflict Type | Primary Strategies |
|--------------|-------------------|
| Logical | Prioritization, Conditional Logic, Stakeholder Negotiation |
| Technical | Technical Solution, Decomposition, Scope Adjustment |
| Resource | Prioritization, Sequencing, Parallel Tracks |
| Temporal | Sequencing, Relaxation, Scope Adjustment |
| Data | Technical Solution, Conditional Logic |
| State | Decomposition, Conditional Logic, Technical Solution |
| Priority | Stakeholder Negotiation, Prioritization, Compromise |
| Scope | Scope Adjustment, Prioritization, Sequencing |

**For each conflict, provide:**
1. **Multiple options** (2-3 resolution approaches)
2. **Pros and cons** of each option
3. **Implementation effort** (time, cost, complexity)
4. **Trade-offs** (what's gained/lost)
5. **Recommended approach** with rationale

**Example:**

```
Conflict: CONF-001
- REQ-001: "System must work offline"
- REQ-005: "System requires continuous internet connection"

Resolution Options:

Option A: Prioritization - Choose Offline
- Strategy: Prioritize offline capability, remove continuous connection requirement
- Pros: Better mobile UX, works in low connectivity
- Cons: Some features limited offline, sync complexity
- Effort: Medium (implement local storage + sync)
- Recommendation: ✓ RECOMMENDED

Option B: Conditional Logic - Support Both Modes
- Strategy: Online mode (full features) + Offline mode (core features)
- Pros: Maximum flexibility, supports all users
- Cons: High complexity, essentially building two systems
- Effort: High (dual implementation + mode switching)
- Recommendation: Not recommended unless both modes essential

Option C: Compromise - Offline-First with Sync
- Strategy: Core features work offline, sync when connected
- Pros: Best of both worlds, graceful degradation
- Cons: Conflict resolution needed, moderate complexity
- Effort: Medium-High (offline core + background sync)
- Recommendation: Consider if offline critical but connectivity available most of time
```

### Step 4: Create Conflict Report

Structure findings for stakeholders:

```markdown
# {Scenario}

## Conflicts

### CONF-001: Connectivity Model
**Requirements:**
- REQ-001: "System must work offline"
- REQ-005: "System requires continuous internet connection"

**Conflict:** Mutually exclusive connectivity requirements
**Type:** Logical Conflict

**Resolution Options:**
[As shown in Step 4 above]

**Recommended Resolution:**
Schedule stakeholder meeting within 3 days to decide on connectivity model.
Recommended: Offline-first with sync when connected.

**Stakeholders to Involve:**
- Product Manager (business requirements)
- Engineering Lead (technical feasibility)
- UX Designer (user experience)
- Key customers (use cases)

---

### CONF-002: Resource Allocation
**Requirements:**
- REQ-020: "Deliver mobile app by March 1" (needs 3 devs, 8 weeks)
- REQ-025: "Complete API redesign by March 1" (needs 3 devs, 8 weeks)

**Conflict:** Same resource, same timeline
**Type:** Resource Conflict

**Resolution Options:**
[Similar format]

**Recommended Resolution:**
Prioritize mobile app (customer-facing, competitive pressure).
Reschedule API redesign to May 1 (internal, less urgent).

---

```

## Output Formats

**Markdown Report** (default) - Comprehensive analysis for stakeholders

When format not specified, provide Markdown report.

## Best Practices

1. **Scan systematically** - Check all requirement pairs, not just obvious ones
2. **Check related requirements** - If another requirement changes the conflict interpretation, explain that relation in the conflict reason
3. **Involve stakeholders early** - Don't resolve alone, collaborate
4. **Document rationale** - Record why conflicts exist and why resolutions chosen
5. **Track rationale** - Understand why each conflict exists and what decision it needs
6. **Be specific** - Vague conflict descriptions don't help resolution
7. **Propose solutions** - Don't just identify problems, suggest fixes
8. **Follow up** - Verify resolutions actually work

## Common Pitfalls to Avoid

**Don't flag as conflicts when:**
- Requirements are complementary, not contradictory
- One requirement is subset of another (specialization)
- Apparent conflict is due to unclear wording (ambiguity issue)
- Requirements apply to different contexts or users
- Timeline allows sequential implementation

**Do flag as conflicts when:**
- Literally impossible to satisfy both
- Would require mutually exclusive technology choices
- Same resource needed for multiple things simultaneously
- Dependencies create impossible sequences
- Stakeholders have incompatible expectations

## Example Analysis

**Input Requirements:**

```
REQ-001: Support 10,000 concurrent users
REQ-002: Page load time under 1 second
REQ-003: Display 500 products with high-res images per page
REQ-004: Use free hosting tier (1 CPU, 512MB RAM)
REQ-005: Launch in 2 weeks
```

**Conflicts Detected:**

**CONF-001:** Resource vs Performance
- REQ-001 (10k users) + REQ-002 (<1s load) + REQ-004 (free tier)
- Conflict: Free tier cannot handle 10k concurrent users with 1s response
- Resolution: Upgrade hosting (paid tier) OR reduce user count OR relax timing

**CONF-002:** Performance vs Features
- REQ-002 (<1s load) + REQ-003 (500 items with images)
- Conflict: Loading 500 hi-res images cannot complete in 1 second
- Resolution: Reduce items per page OR lazy load OR relax timing

**CONF-003:** Timeline vs Scope
- REQ-005 (2 weeks) vs complexity of all features
- Conflict: Full implementation needs 6-8 weeks minimum
- Resolution: MVP with core features in 2 weeks OR extend timeline

**Recommended Resolutions:**
1. Upgrade hosting to support user load (CONF-001)
2. Reduce to 50 items per page with lazy loading (CONF-002)
3. Launch MVP in 2 weeks, full features in 6 weeks (CONF-003)

## Resources

- `references/conflict_patterns.md` - Comprehensive catalog of 8 conflict types with detection patterns
- `references/resolution_strategies.md` - Detailed resolution strategies by conflict type
