# Conflict Report (Markdown Output)

Produce a **Requirement Conflict Analysis Report** in Markdown. Use the provided **Context** as the sole source of data (conflicts, requirements, stakeholders, scope, rough_idea, open_questions, decisions, system_models). Apply conflict-analyzer concepts (severity, type, impact, resolution strategies) when filling each section.

## Output: Markdown Only

- Output **only** Markdown. Do not wrap in code fences or add JSON.
- Structure must follow the sections below.

## Report Structure

1. **Title**  
   `# Requirement Conflict Analysis Report`

2. **Executive Summary**  
   - Project (from scope or rough_idea)  
   - Analysis Date  
   - Requirements Analyzed  
   - Conflicts Found  
   - Analyzer (e.g. Plant Analyst)

3. **Per conflict** (for each item in Context.conflicts)  
   - Heading: `### {id} [SEVERITY] (type)`  
   - Involved requirements (id + text from Context.requirements)  
   - Conflict description  
   - Impact: technical, business, timeline  
   - Resolution Options (option, strategy, description, RECOMMENDED if applicable)  
   - Recommended Resolution  
   - Stakeholders to involve  
   - Dependencies (from Context.system_models if relevant)

4. **Conflict Matrix**  
   Table: | Req 1 | Req 2 | Conflict ID |

5. **Recommendations**  
   - Immediate Action  
   - High Priority  
   - Preventive Measures (optional)

6. **Footer**  
   Unresolved / Resolved counts (use Context.decisions to infer resolved where appropriate).

## Context Fields

| Field | Use |
|-------|-----|
| conflicts | Only use items with label=Conflict; each has id, description, requirement_ids, conflict_type, etc. |
| requirements | Resolve requirement_ids to id + text; source_stakeholders for "Stakeholders to involve" |
| stakeholders | Names/roles for report metadata and per-conflict stakeholders |
| scope | Project name (description), in_scope, out_of_scope for context |
| rough_idea | Fallback project summary if scope.description empty |
| open_questions | Can inform "impact if unanswered" in Recommendations |
| decisions | Recent decisions; help distinguish resolved vs unresolved |
| system_models | Dependency between components → Dependency Graph / Dependent Requirements Blocked |
| round_num | Optional; can note "Round N" in metadata |

## Quality

- Every constraint/impact/recommendation must be grounded in Context; do not invent data.
- If Context.conflicts is empty, output a minimal report with Executive Summary and zero conflicts.
