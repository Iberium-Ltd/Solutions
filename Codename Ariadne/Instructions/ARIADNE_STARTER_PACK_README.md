# CODENAME ARIADNE Codex Starter Pack

This archive contains:

1. `CODEX_MASTER_PROMPT_ARIADNE.md`
   - The implementation brief for Codex.
   - Contains no hardcoded personal identity data.
   - Uses synthetic examples only.
   - Defines Codename Ariadne as the product and Ariadne Core as the correlation and provenance layer.

2. `digital_footprint_audit_findings_2026-07-10.md`
   - Private reference findings from the previous self-audit.
   - Contains personal information.
   - Do not commit it to a public repository.

3. `digital_footprint_audit_methodology_2026-07-10.md`
   - Private reference methodology, searches, tools and limitations.
   - Contains personal information.
   - Do not commit it to a public repository.

Recommended setup:

- Create a private local repository.
- Put the two audit reference files under `private_reference/`.
- Add `private_reference/` to `.gitignore`.
- Place the master prompt at the repository root or under `docs/`.
- Open the repository in VS Code.
- Give Codex the master prompt and allow it to inspect the private references locally.
- Require synthetic data for screenshots, tests and fixtures.
