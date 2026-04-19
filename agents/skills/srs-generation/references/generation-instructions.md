# SRS Generation Instructions

Follow these steps to generate the SRS document.

## Step 1: Draft Using `template.md`

Load and follow:
`skills/srs-generation/references/template.md`

Use this annotated template to draft the SRS content.

At this stage:
- use the template's section guidance to decide what each section should contain
- write the document content in full
- keep the draft coherent and structurally complete
- do not output chain-of-thought or hidden reasoning

The draft may still reflect the authoring-oriented structure of `template.md`, but it should
already be a readable SRS draft rather than notes or a planning outline.

## Step 2: Render Final Output Using `template-bare.md`

Load and follow:
`skills/srs-generation/references/template-bare.md`

Use this clean template to render the final SRS output.

At this stage:
- preserve the substantive content from the draft
- align the final document to the clean section skeleton
- remove prompt residue, comments, emoji, instructions, and placeholder guidance
- do not introduce new requirements or unsupported facts

## Step 3: Traceability

If upstream source material exists, preserve traceability where supported by the context. This may
include:
- references
- source-backed rationale
- requirement-to-source mappings
- verification links

Traceability should support understanding and verification, but should not force obsolete document
sections or legacy formatting that the current templates do not require.

## Step 4: Quality Check

Load the quality checklist from:
`skills/srs-generation/references/checklist.md`

Run through every checklist item against the **final rendered SRS**. If any check fails, revise the
draft and/or final rendering before finalizing.

## Step 5: Write Output

1. Sanitize the feature name to create a filename slug
2. Create the `docs/` directory if it doesn't exist
3. Write the final document to `docs/<feature-name>/srs.md`
4. Confirm the file path and provide a concise summary

## Important Guidelines

- Requirements must be unambiguous and testable.
- Use `shall` for mandatory requirements, `should` for recommended ones, and `may` for optional ones.
- Do not invent requirements, interfaces, constraints, or quantitative targets.
- Keep the final document formal and reviewable.
- Separate real requirements from assumptions, background, and appendix material according to the current templates.

## Anti-Shortcut Rules

1. Do not copy source material directly into the final SRS without converting it into formal,
   reviewable requirement language.
2. Do not let authoring hints from `template.md` leak into the final output.
3. Do not preserve comments, emojis, `💬` notes, `➥` instructions, or placeholder guidance in the
   final SRS.
4. Do not treat incomplete notes, unresolved issues, or unsupported assumptions as approved
   requirements.
5. Do not force old-format artifacts such as legacy IEEE 830 chapter families, CRUD matrices, or
   fixed use-case blocks unless the current template pair explicitly requires them.
