---
name: srs-generation
description: >
  Generates professional Software Requirements Specification (SRS) documents using the current
  two-stage template flow. This skill activates when the user needs a requirements document,
  requirements specification, SRS, functional requirements, non-functional requirements, software
  requirements, or requirements engineering output. It transforms approved, source-backed
  requirements into a formal, reviewable specification.
instructions: >
  Generate a complete Software Requirements Specification using the annotated drafting template at
  references/template.md, then render the final clean output using
  references/template-bare.md. Validate the final result against references/checklist.md before
  finalizing.
---

# SRS Generation Skill

## Purpose

This skill generates a formal Software Requirements Specification (SRS) from approved, source-backed
requirements. It is intended for specification writing, not exploratory analysis or requirement
discovery.

The current SRS generation contract is **two-stage**:

1. `references/template.md`
   - annotated drafting template
   - used to expand content, structure sections, and guide writing
2. `references/template-bare.md`
   - clean final template
   - used to render the final publishable output without prompt residue

## Inputs

This skill works best when provided:
- approved or baselined requirements
- supported context such as assumptions, dependencies, glossary terms, decisions, and revisions
- source-backed rationale where available

If upstream source material such as a PRD exists, it may be used for traceability context, but it
does not authorize inventing new requirements.

## Responsibilities

This skill is responsible for:
- producing an SRS that follows the current template pair
- translating approved requirements into formal specification content
- keeping the document clear, verifiable, and suitable for review or baseline
- removing instructional residue from the final deliverable
- preserving traceability where the context supports it

This skill is not responsible for:
- discovering new requirements
- resolving open questions
- deciding scope or priority without support
- inventing unsupported interfaces, thresholds, obligations, or actors
- promoting draft or unresolved content into formal requirements

## Two-Stage Workflow

### Stage 1: Draft With `template.md`

Use `references/template.md` as the annotated drafting template.

At this stage:
- follow the section structure and guidance embedded in the template
- expand the actual SRS content using the provided context
- keep the draft readable and structurally complete
- do not include chain-of-thought or internal reasoning

### Stage 2: Render With `template-bare.md`

Use `references/template-bare.md` to produce the final SRS.

At this stage:
- preserve the substance of the draft
- remove guidance text, emoji, comments, placeholder instructions, and prompt residue
- align the final output to the clean document skeleton
- do not add facts or requirements that are not supported by the draft/context

## Working Principles

- Use only information supported by the provided context.
- Prefer explicit gaps over fabricated certainty.
- Keep normative content in the final document, and remove authoring hints from the final output.
- Treat `template.md` as authoring guidance and `template-bare.md` as the final layout contract.
- Follow the checklist against the **final rendered output**, not just the draft.

## Requirement Writing Expectations

- Requirements should be clear, specific, and testable.
- Use precise modal verbs such as `shall`, `should`, and `may` intentionally.
- Keep statements focused on what the system must do.
- Avoid unsupported implementation detail unless it is a true constraint.
- Keep terminology consistent across the entire document.

## Output Convention

The final SRS document is written to `docs/<feature-name>/srs.md` in the project root, where
`<feature-name>` is a sanitized, lowercase, hyphen-separated slug derived from the user's input.
The `docs/<feature-name>/` directory is created if it does not already exist. If a file with the
same name already exists, confirm with the user before overwriting.
