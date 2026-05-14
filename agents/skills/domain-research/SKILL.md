---
name: domain-research
description: Research domain knowledge for requirements engineering. Gathers best practices, regulatory requirements, and competitive insights.
allowed-tools: artifact_query, file_parser, web_search
---

# Domain Research Skill

Research domain knowledge to enrich requirements elicitation.

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| issue | Yes | The issue to research |
| --domain | No | Domain name for organizing output |
| --depth | No | Research depth: `shallow`, `moderate`, `deep` (default: `moderate`) |
| --focus | No | Research focus: `best-practices`, `regulatory`, `competitive`, `technical`, `all` |

## Research Capabilities

### Best Practices Research

- Industry standards
- Common patterns
- Recommended approaches
- Lessons learned

### Regulatory Research

- Compliance requirements
- Legal obligations
- Industry regulations
- Audit requirements

### Competitive Research

- Competitor features
- Market standards
- Differentiation opportunities
- Feature gaps

### Technical Research

- Library capabilities
- Framework requirements
- Integration patterns
- Technology constraints

## Workflow

### Step 1: Parse Research Request

```yaml
research_request:
  issue: "{from argument}"
  domain: "{from --domain}"
  depth: shallow|moderate|deep
  focus: "{from --focus or all}"
```

### Step 2: Load Domain Research Skill

Use this skill to load domain research patterns.

### Step 3: Gather Evidence

Based on focus area:

**Best Practices:**

```yaml
queries:
  - source: external research
    query: "{issue} best practices 2025"
  - source: external research
    query: "{issue} common patterns recommendations"
```

**Regulatory:**

```yaml
queries:
  - source: external research
    query: "{regulation} requirements {industry}"
  - source: official documentation
    action: review regulatory documentation
```

**Competitive:**

```yaml
queries:
  - source: public product information
    action: search competitor features
  - source: external research
    query: "{industry} market leaders features"
```

**Technical:**

```yaml
queries:
  - source: official documentation
    action: review library or framework documentation
  - source: external research
    query: "{technology} integration requirements"
```

### Step 4: Synthesize Findings

Combine research results:

- Extract key findings
- Identify requirements implications
- Note confidence levels
- Flag items needing validation

### Step 5: Save and Report

Save to `.requirements/{domain}/research/`
Display summary of findings.

## Examples

### Best Practices Research

Example output:

```text
Researching: e-commerce checkout optimization
Depth: moderate
Focus: best-practices

Gathering evidence...
  [external research] e-commerce checkout best practices
  [external research] cart abandonment reduction techniques

Key Findings:

1. CHECKOUT FLOW
   - Guest checkout reduces abandonment by 30%
   - Progress indicators increase completion
   - Mobile-first design essential

2. PAYMENT
   - Multiple payment options required
   - Saved payment methods increase conversion
   - Clear security indicators build trust

3. PERFORMANCE
   - Checkout should complete in < 3 steps
   - Page load < 2 seconds critical
   - Real-time validation reduces errors

Derived Requirements (8):
  REQ-RES-001: System shall support guest checkout
  REQ-RES-002: System shall display checkout progress
  REQ-RES-003: System shall support multiple payment methods
  REQ-RES-004: System shall complete checkout in 3 steps or fewer
  ... (4 more)

Confidence: MEDIUM (needs stakeholder validation)

Saved to: .requirements/checkout/research/RES-20251225-170000.yaml
```

### Regulatory Research

Example output:

```text
Researching: PCI-DSS compliance
Depth: deep
Focus: regulatory

Gathering evidence...
  [external research] PCI-DSS requirements payment processing
  [external research] PCI-DSS version-specific changes
  [official documentation] PCI Security Standards Council

Key Findings:

1. DATA PROTECTION (Requirement 3)
   - Never store CVV after authorization
   - Encrypt stored card data (AES-256)
   - Mask PAN when displayed

2. ACCESS CONTROL (Requirement 7-8)
   - Restrict access to need-to-know
   - Unique IDs for each user
   - MFA for administrative access

3. MONITORING (Requirement 10)
   - Log all access to cardholder data
   - Retain logs for 1 year minimum
   - Daily log review required

4. TESTING (Requirement 11)
   - Quarterly vulnerability scans
   - Annual penetration testing
   - Change detection mechanisms

Derived Requirements (15):
  REQ-RES-001: System shall not store CVV/CVC after authorization [MUST]
  REQ-RES-002: System shall encrypt stored card data using AES-256 [MUST]
  REQ-RES-003: System shall mask PAN displaying only last 4 digits [MUST]
  ... (12 more)

Confidence: HIGH (from official documentation)

Saved to: .requirements/payment/research/RES-20251225-171500.yaml
```

### Competitive Research

Example output:

```text
Researching: inventory management software competitors
Depth: moderate
Focus: competitive

Gathering evidence...
  [public product information] inventory management software features
  [external research] inventory management market leaders

Competitors Analyzed:

1. CompetitorA
   - Real-time inventory tracking
   - Multi-warehouse support
   - Barcode scanning
   - Automated reorder points

2. CompetitorB
   - AI demand forecasting
   - Supplier management
   - Integration marketplace
   - Mobile app

3. CompetitorC
   - Simple interface
   - Low-cost option
   - Basic reporting
   - Limited integrations

Feature Matrix:
  Feature               | A | B | C | Our Need?
  Real-time tracking    | ✓ | ✓ | ✓ | Table stakes
  Multi-warehouse       | ✓ | ✓ | - | Should have
  AI forecasting        | - | ✓ | - | Differentiator?
  Supplier management   | ✓ | ✓ | - | Should have
  Mobile app            | ✓ | ✓ | - | Should have

Derived Requirements (10):
  REQ-RES-001: System shall provide real-time inventory visibility [MUST]
  REQ-RES-002: System shall support multiple warehouse locations [SHOULD]
  REQ-RES-003: System shall integrate with barcode scanners [SHOULD]
  ... (7 more)

Confidence: LOW (based on public information)

Saved to: .requirements/inventory/research/RES-20251225-173000.yaml
```

### Technical Research

Example output:

```text
Researching: React state management
Depth: moderate
Focus: technical

Gathering evidence...
  [official documentation] React library documentation
  [official documentation] state management documentation
  [external research] React state management patterns

Key Findings:

1. BUILT-IN OPTIONS
   - useState for local state
   - useReducer for complex state
   - Context API for global state (with caveats)

2. EXTERNAL LIBRARIES
   - Redux Toolkit (complex apps)
   - Zustand (simple, performant)
   - Jotai (atomic state)
   - React Query (server state)

3. RECOMMENDATIONS
   - Start simple (useState, Context)
   - Add complexity only when needed
   - Separate server state from client state

Technical Constraints:
  - React 18+ required for new patterns
  - SSR considerations for Next.js
  - Bundle size implications

Derived Requirements (5):
  REQ-RES-001: System shall use React 18 or later [CONSTRAINT]
  REQ-RES-002: System shall separate server state from client state [SHOULD]
  REQ-RES-003: System shall minimize bundle size impact of state library [SHOULD]
  ... (2 more)

Confidence: MEDIUM (verify with team)

Saved to: .requirements/frontend/research/RES-20251225-174500.yaml
```

## Output Format

### Saved YAML Structure

```yaml
research_session:
  id: "RES-{timestamp}"
  issue: "{issue}"
  domain: "{domain}"
  depth: shallow|moderate|deep
  focus: "{focus area}"
  timestamp: "{ISO-8601}"

  queries:
    - source: external research
      query: "{query text}"
      success: true

    - source: official documentation
      issue: "{issue}"
      success: true

  findings:
    category_1:
      - "{finding 1}"
      - "{finding 2}"

    category_2:
      - "{finding 3}"

  derived_requirements:
    - id: REQ-RES-001
      text: "{requirement}"
      source: research
      source_detail: "{specific source}"
      confidence: high|medium|low
      needs_validation: true
      priority: must|should|could

  recommendations:
    - "{recommendation 1}"
    - "{recommendation 2}"

  gaps_for_further_research:
    - "{issue needing more research}"
```

## Integration

### Follow-Up Work

- Validate research with stakeholders.
- Check whether research fills known gaps.
- Run deeper research on specific uncertain issues.
- Consolidate all source findings into requirements, constraints, risks, or open questions.
