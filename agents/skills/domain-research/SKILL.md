---
name: domain-research
description: Research external domain knowledge to support requirements review without directly creating formal requirements. Gathers best practices, regulatory requirements, and competitive insights.
allowed-tools: artifact_query, read_file, web_search
---

# Domain Research Skill

Research external domain knowledge to support requirements review without directly creating formal requirements.

## Priority Rules

- If the caller provides an output schema, follow the caller schema exactly.
- Do not create formal requirements unless the caller explicitly asks for requirements.
- Treat research findings as evidence, constraints, risks, recommendations, or open questions that need stakeholder or analyst validation.
- Do not write files unless the caller explicitly asks you to save artifacts.

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

### Step 5: Return Findings

Return structured findings to the caller using the caller's requested format.
If no format is provided, summarize findings, constraints, risks, recommendations, sources, confidence, and validation gaps.

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

Requirement Implications (not formal requirements):
  - Guest checkout may be a candidate requirement.
  - Checkout progress display may be a candidate requirement.
  - Multiple payment options may be a candidate requirement.
  - Short checkout flow may be a candidate usability constraint.
  ... (4 more)

Confidence: MEDIUM (needs stakeholder validation)
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

Requirement Implications (not formal requirements):
  - Not storing CVV/CVC after authorization may be a mandatory constraint.
  - Encrypting stored card data may be a mandatory constraint.
  - Masking displayed PAN may be a mandatory constraint.
  ... (12 more)

Confidence: HIGH (from official documentation)
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

Requirement Implications (not formal requirements):
  - Real-time inventory visibility may be table stakes.
  - Multiple warehouse support may be a candidate requirement.
  - Barcode scanner integration may be a candidate integration need.
  ... (7 more)

Confidence: LOW (based on public information)

No files are written unless requested by the caller.
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

Requirement Implications (not formal requirements):
  - React 18+ may be a technical constraint.
  - Server/client state separation may be a design recommendation.
  - Bundle size impact may need validation as a quality constraint.
  ... (2 more)

Confidence: MEDIUM (verify with team)

Saved to: .requirements/frontend/research/RES-20251225-174500.yaml
```

## Fallback Output Format

Use this only when the caller does not provide a schema.

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

  requirement_implications:
    - text: "{candidate implication, not a formal requirement}"
      source_detail: "{specific source}"
      confidence: high|medium|low
      needs_validation: true
      implication_type: constraint|risk|recommendation|candidate_requirement|open_question

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
