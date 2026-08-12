# AI Attribution

Arbiter Project ("Arbiter") is developed using a workflow that combines human authorship with AI assistance. This file documents that workflow transparently, names the AI tools involved, and describes how the human-versus-AI contribution boundary is handled.

This file is a disclosure mechanism, not a legal instrument. License terms are in [LICENSE](LICENSE); third-party attribution is in [NOTICE.md](NOTICE.md); name-use policy is in [TRADEMARK.md](TRADEMARK.md); security reporting is in [SECURITY.md](SECURITY.md).

## Tools used

Arbiter's development uses the following AI tools alongside conventional editing, version control, and review:

- **Claude Code** (CLI agent published by Anthropic) — primary AI development assistant. Used for code generation, refactoring, documentation drafting, test scaffolding, and architectural discussion.
- **Anthropic Claude** large language models (currently the Opus family) — the underlying model that powers Claude Code.

The project does not use other code-generation AI tools (e.g., GitHub Copilot, Cursor, etc.) at the time of writing. If that changes, this file will be updated.

AI tools are licensed by the human author at the consumer / individual subscription tier.

## Workflow division

The author treats the following contribution categories as distinct:

- **Human-authored** — design decisions, architectural choices, strategic decomposition, problem framing, decision documents (the internal notes), feedback patterns codified in memory, partner-materials narrative, and review of all generated output. The human author retains direct authorship of these surfaces.
- **AI-assisted** — code and documentation where the human directs the AI tool with concrete instructions, then reviews, modifies, and integrates the output. The substantive selection, arrangement, and editorial control rest with the human; the AI tool generates candidate text/code that the human accepts, rejects, or modifies.
- **AI-generated boilerplate** — purely mechanical scaffolding (e.g., test boilerplate, repetitive type stubs, format conversions) produced by AI on direct request without significant creative selection. This category is minimized in practice; most output is reviewed-and-modified before commit.

Reviewers and downstream users should assume that any source file or documentation in this repository may contain AI-assisted content unless otherwise noted. The human author has reviewed and accepted all committed content.

## Commit-level transparency

Commits that include AI-assisted content carry a `Co-Authored-By:` trailer that names the specific model used — at the time of writing, `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. **The named model changes as the tooling does, and the version in any given commit's trailer is the one that produced it**; this line records the form, not a constant. It previously quoted a superseded model version as though it were the current one, which is the failure mode a disclosure file can least afford. This trailer is a transparency marker — it documents AI involvement in the commit's authorship process. It does not assert that the AI is a legally recognized co-author; under current US copyright doctrine (US Copyright Office guidance, 2023), AI tools are not eligible for copyright authorship.

The presence of the trailer is informational. Its absence on older commits does not imply they were free of AI assistance — the trailer was adopted partway through the project's history and has been applied consistently going forward.

## Legal posture

The legal treatment of AI-assisted and AI-generated content is unsettled in most jurisdictions. The project's working posture is:

- **Copyright (human-contributed portions)**: the human author claims copyright in design choices, selection, arrangement, prompts, review/editorial control, and integration work. These contributions are licensed under the [Apache License 2.0](LICENSE) granted by the human author.
- **Copyright (AI-generated portions)**: under current US Copyright Office guidance, content produced solely by AI without sufficient human authorship may not be eligible for copyright protection. The project does not assert copyright over such portions, nor does it deny that the Apache 2.0 grant applies to them. Downstream users may treat the entire repository as Apache-2.0-licensed for practical purposes; readers concerned about the legal status of specific portions are encouraged to seek their own counsel.
- **Training-data inheritance**: large language models are trained on broad code and documentation corpora, including open-source-licensed material. The project's AI tool vendor (Anthropic) provides assurances regarding output rights; the project relies on those assurances. Downstream legal developments (e.g., pending or future rulings on AI training-data licensing) may affect this posture. The project will update this file if material changes warrant it.

This file is not legal advice. Users with substantive copyright, licensing, or compliance concerns should consult qualified counsel.

## What this means for reusers and contributors

- **Reusers**: treat the repository as Apache-2.0-licensed for practical use, integration, and redistribution per [LICENSE](LICENSE). If you are deploying Arbiter in a context with strict provenance requirements (regulated industries, contractual provenance audits, etc.), incorporate this disclosure into your audit trail.
- **Contributors**: if you submit a pull request, you are representing that any AI-assisted portion of your contribution complies with your AI tool vendor's terms and that you have the right to license your contribution under the project's Apache License 2.0. The project does not require disclosure of AI assistance in contributions, but welcomes it where the contributor wishes to document the workflow.

## Updates

This file is updated when the project's AI-tool usage materially changes — new tools adopted, vendor terms change, legal landscape shifts, or workflow division evolves. Minor model version bumps (e.g., Opus 4.6 → 4.7) do not require an update unless the vendor's terms change.

## License of this file

This AI_ATTRIBUTION file is part of the Arbiter Project documentation and is covered by the project's [Apache License 2.0](LICENSE). See also [TRADEMARK.md](TRADEMARK.md) for Arbiter Project name-use policy.
