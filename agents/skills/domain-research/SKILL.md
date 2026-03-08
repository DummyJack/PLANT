---
name: domain-research
description: Domain research for requirements elicitation using web_search (general research, web scraping) and read_external_file (library/documentation in doc/).
allowed-tools: web_search, read_external_file
---

# Domain Research Skill

Domain research for enriching requirements elicitation with external knowledge. Use **web_search** for general research and web scraping; use **read_external_file** for library and project documentation in the doc/ directory.

## Documentation-First Approach

Before conducting domain research:

1. **read_external_file**: Read reference files under doc/ (regulations, standards, technical docs, library docs).
2. **web_search**: Search the web for industry standards, best practices, regulatory requirements, competitors, and technical documentation.
3. Base all guidance on official documentation and authoritative sources.

## When to Use This Skill

**Keywords:** domain research, industry standards, best practices, competitive analysis, technology research, regulatory requirements

Invoke this skill when:

- Unfamiliar with a domain and need background
- Researching industry standards and best practices
- Investigating regulatory requirements
- Analyzing competitor features
- Exploring technology constraints
- Supplementing stakeholder knowledge

## Available Tools

### General Research — web_search

**Use for:**

- Industry best practices
- Recent developments
- Comparative analysis
- Regulatory overviews

**Tool:** `web_search` (query keywords to get web search results)

```yaml
tool: web_search
example_queries:
  - "e-commerce checkout best practices 2025"
  - "GDPR compliance requirements for SaaS"
  - "authentication patterns for financial applications"
```

### Library Documentation — read_external_file

**Use for:**

- Framework requirements
- API constraints
- Library capabilities
- Technical limitations
- Regulations, standards, and technical docs under project doc/

**Tool:** `read_external_file` (pass path relative to doc/; reads .txt, .md, .json, .pdf, .docx)

```yaml
tool: read_external_file
example:
  - file_path: "regulation.pdf"   # regulation file under doc/
  - file_path: "refs/api-guide.md"
  - file_path: "standards/iso-29148.md"
```

### Web Scraping — web_search

**Use for:**

- Competitor analysis
- Documentation extraction
- Feature comparison
- Market research

**Tool:** `web_search` (search by keywords for summaries and links; equivalent to fetching public web content)

```yaml
tool: web_search
example_queries:
  - "inventory management software features"
  - "competitor product feature comparison"
  - "market requirements for [domain]"
```

## Research Patterns

### Pattern 1: Domain Background

Build foundational domain knowledge:

```yaml
research_pattern: domain_background
steps:
  1. Use web_search for industry overview
  2. Identify key concepts and terminology
  3. Research common requirements in domain
  4. Note regulatory considerations
output: Domain context document
```

### Pattern 2: Best Practices

Research current best practices:

```yaml
research_pattern: best_practices
steps:
  1. Search for "best practices" in domain
  2. Filter for recent (last 2 years)
  3. Identify common patterns
  4. Note recommended approaches
output: Best practices summary
```

### Pattern 3: Competitive Analysis

Research competitor features:

```yaml
research_pattern: competitive_analysis
steps:
  1. Identify key competitors
  2. Use web_search to find competitor feature pages and summaries
  3. Extract capability lists
  4. Compare and contrast
output: Competitive feature matrix
```

### Pattern 4: Regulatory Research

Research compliance requirements:

```yaml
research_pattern: regulatory
steps:
  1. Identify applicable regulations
  2. Research specific requirements
  3. Note mandatory vs recommended
  4. Document compliance criteria
output: Regulatory requirements list
```

### Pattern 5: Technology Constraints

Research technical requirements:

```yaml
research_pattern: technology
steps:
  1. Identify technologies in scope
  2. Use read_external_file for doc/ library and technical docs
  3. Research integration requirements (web_search if needed)
  4. Document technical constraints
output: Technical requirements document
```

## Research Workflow

### Step 1: Define Research Scope

```yaml
research_scope:
  domain: "{domain name}"
  topic: "{specific focus area}"
  depth: shallow|moderate|deep
  sources: [web_search, read_external_file]
```

### Step 2: Execute Research Queries

For each research need:

1. Select appropriate tool: **web_search** (general research, competitors, regulations) or **read_external_file** (doc/ regulations, standards, technical docs)
2. Formulate effective query or file path
3. Process results
4. Extract requirements

### Step 3: Synthesize Findings

Combine research into actionable requirements:

- Identify common patterns
- Note conflicts or options
- Highlight mandatory items
- Suggest priorities

### Step 4: Document Results

Save research findings and derived requirements.

## Output Format

### Research Results

```yaml
research_session:
  id: "RES-{timestamp}"
  domain: "{domain}"
  topic: "{research topic}"
  timestamp: "{ISO-8601}"

  queries_executed:
    - tool: web_search
      query: "{query text}"
      results_count: {number}

    - tool: read_external_file
      file_path: "{path under doc/}"
      content_type: documentation|regulation|standard

  findings:
    domain_context:
      - "{key finding 1}"
      - "{key finding 2}"

    best_practices:
      - "{recommended practice 1}"
      - "{recommended practice 2}"

    regulatory:
      - regulation: "GDPR"
        requirements:
          - "{requirement 1}"
          - "{requirement 2}"

    competitive:
      - competitor: "{name}"
        features:
          - "{feature 1}"
          - "{feature 2}"

  derived_requirements:
    - id: REQ-RES-001
      text: "{requirement statement}"
      source: research
      source_detail: "{where this came from}"
      confidence: low  # Research-derived = low confidence
      needs_validation: true
      category: "{category}"

  recommendations:
    - topic: "{topic}"
      finding: "{what research showed}"
      implication: "{what this means for requirements}"

  gaps_in_research:
    - "{area where more research needed}"
```

## Query Optimization

### Effective web_search Queries (General Research)

```yaml
tool: web_search
query_patterns:
  best_practices:
    template: "{domain} {topic} best practices {year}"
    example: "e-commerce checkout best practices 2025"

  requirements:
    template: "{domain} {topic} requirements specifications"
    example: "healthcare application HIPAA requirements"

  comparison:
    template: "{topic A} vs {topic B} for {use case}"
    example: "OAuth 2.0 vs SAML for enterprise SSO"

  regulatory:
    template: "{regulation} requirements for {industry}"
    example: "PCI-DSS requirements for payment processing"
```

### Effective read_external_file Usage (Library / Documentation)

```yaml
tool: read_external_file
usage:
  library_features:
    file_path: "doc/{library or API guide}.md"
    purpose: Read technical docs and API guides under doc/

  regulation_standards:
    file_path: "doc/regulation.pdf"  # or doc/standards/*.md
    purpose: Regulations and standards documents
```

### Effective web_search Queries (Web / Competitor Research)

```yaml
tool: web_search
query_patterns:
  competitor_features:
    query: "{competitor} features {product type}"
    purpose: Competitor features and market info

  documentation:
    query: "{technology} documentation requirements"
    purpose: Technical docs and requirements summaries
```

## Confidence Levels

Research-derived requirements have inherent confidence limits:

```yaml
confidence_levels:
  high:
    sources: [official documentation, regulatory text]
    note: "Verified from authoritative source"

  medium:
    sources: [industry articles, best practice guides]
    note: "Generally accepted but verify with stakeholders"

  low:
    sources: [competitor analysis, general web]
    note: "Use as starting point, requires validation"
```

## Delegation

For follow-up actions:

- **interview-conducting**: Validate research with stakeholders
- **gap-analysis**: Check research fills identified gaps
- **elicitation-methodology**: Return for technique selection

## Output Location

Save research results to:

```text
.requirements/{domain}/research/RES-{timestamp}.yaml
```

## Related

- `elicitation-methodology` - Parent hub skill
- `gap-analysis` - Research to fill gaps
- `interview-conducting` - Validate research findings

---

**Last Updated:** 2025-12-29
