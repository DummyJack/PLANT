# SRS Quality Checklist

Use this checklist to validate the final Software Requirements Specification before finalizing.
Every item must pass. If any item fails, revise the draft and/or final rendering, then re-check.

## 1. Template Alignment

- [ ] The final document follows the current `template-bare.md` section structure
- [ ] Major sections are present: `1. Introduction`, `2. Product Overview`, `3. Requirements`, `4. Verification`, and `5. Appendixes`
- [ ] Section numbering and hierarchy are internally consistent
- [ ] No obsolete section families from older SRS formats were introduced unless explicitly required by the current template pair

## 2. Final Output Cleanliness

- [ ] The final SRS does not contain comments, placeholder guidance, authoring instructions, or prompt residue
- [ ] The final SRS does not contain emoji, `💬` hints, `➥` instructions, or template coaching language
- [ ] The final SRS reads like a formal deliverable rather than a drafting artifact
- [ ] Placeholder rows or empty scaffolding are either properly completed or intentionally removed

## 3. Requirement Quality

- [ ] Requirement statements are clear, specific, and unambiguous
- [ ] Requirements use modal verbs intentionally (`shall`, `should`, `may`)
- [ ] Requirements are testable or reviewable through explicit acceptance/verifiability criteria
- [ ] Requirements describe supported system obligations rather than unsupported implementation speculation
- [ ] Terminology is consistent across the document

## 4. Source Discipline

- [ ] Normative requirements are derived from approved, source-backed input
- [ ] Unsupported assumptions are not silently promoted into formal requirements
- [ ] Missing critical detail is handled explicitly rather than fabricated
- [ ] Open questions, unresolved decisions, and process residue are not presented as settled facts

## 5. Structural Coverage

- [ ] The document meaningfully covers product context in Sections 1–2
- [ ] Normative requirements are placed in the appropriate Section 3 subsections
- [ ] Verification content in Section 4 is aligned with the requirements that appear in the document
- [ ] Appendix content, if present, is supplementary rather than normative

## 6. Traceability and Consistency

- [ ] References, glossary entries, and requirement cross-references are internally consistent
- [ ] Requirement identifiers, if used, are unique and used consistently
- [ ] Verification links, rationale, and supporting references do not contradict the requirement statements
- [ ] The final document does not mix incompatible old/new SRS conventions into a half-old, half-new output
