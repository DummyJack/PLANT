# SRS Generation Instructions

以下強制規則**依序優先遵守**，再進行後續步驟：

1. **禁止硬掰** — 只轉寫「需求草稿（draft_markdown）」與 Context（含 feedback）中已有的需求、範圍、約束與決策。不得憑空新增需求、資料模型、ER 圖、介面規格、技術選型（如 API、資料庫、通訊協定）或範本佔位（如 [Name]、YYYY-MM-DD、[Describe...]、[PRD document name and link]）。若某章節在來源中無對應資料，該節直接標註「**待補**」或「本文件無相關資料」，勿填寫猜測或範例。
2. **缺料就標待補** — References、Open Questions、Change Request Log 等表單若無實際來源或專案紀錄，應標「**待補**」或省略該表，勿保留未替換的佔位符。資料模型、外部介面等若草稿未提及，該章節標「待補」或「待討論後補入」。
3. **章節編號從 1 開始** — 產出之 SRS 章節編號依序為：**1.** Introduction、**2.** Overall Description、**3.** …，直至附錄。勿從 3 開始編號。

---

Follow these steps exactly to generate the SRS document.

## Step 1: Generate Document

Load and follow the SRS template from the skill reference file at:
`skills/srs-generation/references/template.md`

Generate the complete SRS following the template structure. Key requirements:
- **Section numbering starts at 1**: Use "## 1. Introduction", "## 2. Overall Description", "## 3. …" (do not start at 3).
- Only include content that exists in the draft or context; for any section without source material, write "待補" or "本文件無相關資料" — do not invent requirements, data models, interfaces, or placeholder text.
- Functional requirement IDs: FR-<MODULE>-<NNN> (e.g., FR-AUTH-001)
- Non-functional requirement IDs: NFR-<CATEGORY>-<NNN> (e.g., NFR-PERF-001)
- Each functional requirement must include: description, input/output, acceptance criteria, priority (only for content present in the draft)
- Each non-functional requirement must include: description, metric, target value, measurement method (only for content present in the draft)
- Include CRUD matrix / data model / external interfaces **only if** the draft or context provides corresponding information; otherwise mark that section "待補".
- Include use case descriptions (actors, preconditions, main flow, alternate flows, postconditions) to the extent the draft specifies; do not invent flows not implied by the draft.

## Step 2: Traceability Matrix

**Chain mode** (PRD found):
- Create a requirements traceability matrix mapping PRD items → SRS requirements
- Every PRD feature should map to at least one SRS functional requirement
- Flag any PRD items that are not covered by the SRS

**Standalone mode** (no PRD):
- Skip the PRD traceability matrix
- Instead, include a "Requirements Source" section noting that requirements were derived from user clarification (not an upstream PRD)
- Add a note: *"To establish full traceability, consider running `/spec-forge:prd` first, then re-running `/spec-forge:srs`."*

## Step 3: Quality Check

Load the quality checklist from:
`skills/srs-generation/references/checklist.md`

Run through every item in the checklist. For any failed check, revise the document before finalizing.

## Step 4: Write Output

1. Sanitize the feature name to create a filename slug (lowercase, hyphens, no special chars)
2. Create the `docs/` directory if it doesn't exist
3. Write the final document to `docs/<feature-name>/srs.md`
4. Confirm the file path and provide a brief summary

## Important Guidelines

- Requirements must be unambiguous — each requirement should have exactly one interpretation
- Requirements must be testable — each must have clear acceptance criteria
- Requirements must be traceable — link back to PRD items where applicable
- Use "shall" for mandatory requirements, "should" for recommended, "may" for optional
- Avoid implementation details — describe WHAT, not HOW
- Include boundary conditions and error scenarios for each requirement

## Anti-Shortcut Rules

The following shortcuts are **strictly prohibited** — they are common AI failure modes that produce low-quality SRS documents:

1. **Do NOT copy-paste PRD content as requirements.** The PRD describes *what the product should be*; the SRS must specify *what the system shall do* in precise, testable terms. Simply rephrasing PRD bullets is not requirements engineering.
2. **Do NOT skip alternative flows and exception scenarios.** Every use case has error paths, edge cases, and recovery scenarios. Writing only the happy path is incomplete. Each functional requirement must include alternative and exception flows.
3. **Do NOT use vague verbs.** Words like "handle", "manage", "process", or "support" are ambiguous. Replace with specific behaviors: "validate", "reject with error code 422", "persist to the `orders` table", "return within 200ms".
4. **Do NOT omit boundary conditions.** Every input field, parameter, and data entity has limits. If you don't specify min/max lengths, allowed characters, and range constraints, engineers will guess differently.
5. **Do NOT write untestable requirements.** If a requirement cannot be verified by a concrete test case, it is not a valid requirement. Every requirement must have measurable acceptance criteria (Given/When/Then or explicit conditions).
