---
name: domain-research
description: Research domain knowledge, standards, and regulations for requirements elicitation, then convert findings into actionable constraints and derived requirements.
allowed-tools: web_search, file_parser, artifact_query
---

# Domain Research Skill

Use this skill to enrich requirements with trustworthy external knowledge.

## When to Use

- need domain background for unfamiliar business context
- need standards, compliance, or policy constraints
- need best-practice patterns for implementation decisions
- need evidence-backed risk framing

## Research Workflow

1. Define scope and research questions
2. Collect evidence from reliable sources
3. Extract constraints and implications
4. Convert findings into derived requirements
5. Mark uncertain items as needing validation

## Output Expectations

- keep findings concise and source-traceable
- separate facts, recommendations, and assumptions
- avoid speculative claims without evidence

### Suggested JSON Shape

```json
{
  "findings": ["..."],
  "sources": ["..."],
  "derived_requirements": [
    {"text": "...", "source": "...", "category": "regulatory|best_practice|safety"}
  ],
  "compliance_risks": ["..."]
}
```
