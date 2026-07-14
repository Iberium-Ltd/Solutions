# CODEX MASTER BUILD PROMPT

## Project codename

# CODENAME ARIADNE

### Core correlation and provenance layer: ARIADNE CORE

**Working product description**

> **Codename Ariadne** is a local-first personal digital-exposure intelligence platform. It converts unstructured, user-supplied identity information into a reviewed identity graph, executes modular and reproducible self-audits across public and explicitly authorised sources worldwide, preserves evidence, explains attribution, compares audit runs, and manages long-term remediation.

Use **Codename Ariadne** as the product identity and **Ariadne Core** as the internal identity-correlation, provenance and attribution layer.

---

# 1. Your role

Act as the combined:

- Principal product architect.
- Staff full-stack engineer.
- Security engineer.
- Privacy engineer.
- Data engineer.
- OSINT workflow designer.
- Desktop application engineer.
- UI/UX art director.
- Quality-assurance lead.
- Technical writer.
- Release manager.

You are building a serious, durable application rather than a demo.

Think before implementing. Inspect the repository and every supplied reference document first. Plan the work, record architectural decisions, validate assumptions, run the software, inspect real outputs, capture screenshots, review them critically, test the product, and fix defects before declaring a phase complete.

Do not rush directly into code.

Do not ask the user to choose every implementation detail. Make technically sound decisions, explain them in architecture decision records, and proceed. Ask only when a decision materially affects privacy, legal risk, product scope or irreversible design.

---

# 2. Non-negotiable objective

Build a polished, local-first application that allows an authorised user to:

1. Paste arbitrary unstructured text or import files containing identity clues.
2. Extract names, aliases, usernames, email addresses, telephone numbers, physical locations, organisations, employment history, education, domains, profile URLs, project names, dates, identifiers and relationships.
3. Review, correct, classify and approve extracted entities before they are used.
4. Generate controlled search seeds and query variants.
5. Run either:
   - A complete digital-exposure audit.
   - A targeted trace of one email, username, telephone number, name, address, organisation, domain, image, company number or URL.
   - A selected subset of tools.
6. Observe live execution progress globally, per workflow and per adapter.
7. See exactly where every result came from.
8. Build and explore an interactive identity and provenance graph.
9. Distinguish:
   - Confirmed ownership.
   - Probable match.
   - Weak match.
   - False positive.
   - Historical ownership.
   - Recycled username.
   - Account takeover.
   - Mirror or repost.
   - Unrelated collision.
   - Possible impersonation.
   - Confirmed impersonation.
   - Unknown.
10. Preserve verifiable evidence with timestamps, source URLs, hashes, screenshots and raw-response references.
11. Compare the current audit with previous audits.
12. Track deletion, correction, deindexing and impersonation-reporting work over months or years.
13. Export complete and safely redacted reports.
14. Operate entirely from user input, with **no real personal data hardcoded anywhere in the application, tests, fixtures, examples, screenshots, prompts, seed files or source code**.
15. Work well when the user remembers only one old identifier and wants to investigate that identifier alone.
16. Support worldwide source coverage while remaining lawful, authorised and transparent about the jurisdiction and risk of every provider.

The application must feel like a top-tier intelligence console, but it must also be evidentially disciplined, privacy-preserving and honest about uncertainty.

---

# 3. Critical reality constraint

No digital-exposure tool is literally infallible.

Private, deleted, deindexed, login-gated, region-restricted, unarchived and non-public data may be impossible to discover. Search engines and APIs have incomplete coverage. Usernames may be recycled. Platforms may block automation. Providers may return stale or inaccurate data.

Therefore:

- Maximise coverage.
- Measure coverage.
- Record coverage gaps.
- Preserve reproducibility.
- Expose uncertainty.
- Never label “no result” as “does not exist”.
- Never imply perfect completeness.
- Never treat one username match as proof of identity.
- Never silently discard failed or blocked checks.

Distinguish clearly between:

- `FOUND`
- `NOT_FOUND`
- `NOT_CHECKED`
- `CHECK_FAILED`
- `ACCESS_BLOCKED`
- `AUTH_REQUIRED`
- `RATE_LIMITED`
- `PROVIDER_UNAVAILABLE`
- `AMBIGUOUS`
- `MANUAL_REVIEW_REQUIRED`
- `AUTHORITATIVE_ABSENCE`, only where a truly authoritative source can support it

Every audit report must include the coverage matrix and unresolved limitations.

---

# 4. Global source scope and jurisdiction model

The user may have data hosted outside the European Union, including jurisdictions with weaker privacy protections and different public-record regimes.

ARIADNE must therefore support **global, jurisdiction-aware discovery**.

## 4.1 Global coverage principles

The system may use any technically appropriate source that is:

- Publicly accessible.
- Lawfully accessible.
- Explicitly authorised by the user.
- Obtained through a legitimate official API.
- Obtained through a user-provided export.
- Obtained from a user-owned or user-authorised account.
- Accessible through normal browser interaction without bypassing security controls.

Geography must not artificially limit source discovery. A result hosted outside the EU is not ignored merely because the provider is foreign.

However, “playing by local rules” does not permit:

- Use of stolen data.
- Purchase of compromised credentials.
- Authentication bypass.
- Exploitation.
- Malware.
- Phishing.
- CAPTCHA bypass.
- Session theft.
- Credential stuffing.
- Password-reset triggering for discovery.
- Breach-dump marketplaces.
- Illegal data brokers.
- Private databases without a lawful access basis.
- Evasion specifically intended to defeat access controls.

## 4.2 Source jurisdiction registry

Every adapter/provider must have metadata such as:

```json
{
  "provider_id": "example_provider",
  "display_name": "Example Provider",
  "operator_country": "US",
  "data_hosting_regions": ["US"],
  "source_type": "public_search_api",
  "access_basis": "public_api",
  "requires_user_auth": false,
  "sends_user_identifiers": true,
  "retention_notes": "configurable or unknown",
  "privacy_policy_url": "https://example.invalid/privacy",
  "terms_url": "https://example.invalid/terms",
  "risk_level": "medium",
  "enabled_by_default": false
}
```

The UI must show the provider’s jurisdiction and transmission risk before sensitive identifiers are sent.

## 4.3 Data-transfer controls

For sensitive and highly sensitive identifiers:

- Require explicit user approval before transmitting the value to a third-party source.
- Support masking where the provider permits it.
- Prefer local preprocessing and local variant generation.
- Maintain a transmission ledger:
  - Value or masked value.
  - Provider.
  - Jurisdiction.
  - Timestamp.
  - Purpose.
  - Result.
- Allow:
  - Local-only mode.
  - EU-only provider mode.
  - Worldwide mode.
  - Custom allowlist.
  - Custom blocklist.
- Warn when a provider’s retention policy is unknown.
- Never transmit restricted data such as passwords, one-time codes, bank details or identity-document numbers.

## 4.4 Data-broker and people-search sources

The architecture may support lawful public people-search and data-broker sources as modular adapters where permitted.

Requirements:

- Disabled by default.
- Clear provider-specific warning.
- Record jurisdiction.
- Record whether an official removal process exists.
- Record whether the user paid for access.
- Never circumvent paywalls.
- Never create false accounts.
- Never automate access in breach of applicable law.
- Keep broker-derived claims at lower confidence until independently corroborated.
- Clearly mark broker data as potentially stale or inaccurate.

---

# 5. Authorisation and safety boundary

This product is for defensive self-auditing and explicitly authorised investigations only.

Use:

- Official APIs.
- Public search APIs.
- Public web pages.
- Public records.
- User-owned account APIs with read-only OAuth.
- User-provided exports.
- User-provided files.
- Internet archives.
- Browser automation for normal public interaction.
- Local analysis of repositories, exports and evidence owned by the user.
- Official breach-notification services where lawful and user-authorised.
- Reverse-image search providers where the user supplies the image and approves transmission.

Do not implement or perform:

- Credential stuffing.
- Password guessing.
- Triggering password resets to test account existence.
- Authentication bypass.
- CAPTCHA bypass.
- Exploitation of platform vulnerabilities.
- Session theft.
- Access to accounts without explicit authorisation.
- Purchase or use of stolen credential databases.
- Malware.
- Phishing.
- Social engineering.
- Evasion intended to defeat platform access controls.
- Automated harassment.
- Automatic accusation of another person.
- Automatic submission of deletion, legal or impersonation reports without explicit approval.

When automation is blocked, build a transparent manual-import or guided-capture workflow instead of evading the restriction.

---

# 6. Private reference documents

The repository may contain private reference documents describing a prior manual self-audit.

Use them only to understand:

- Search methodology.
- Query patterns.
- Evidence classifications.
- Confidence handling.
- Failed-search handling.
- Reporting structure.
- Privacy mistakes to avoid.
- Functional requirements.

Rules:

1. Treat the documents as confidential.
2. Never copy real names, emails, aliases, addresses, employers, organisations, identifiers, URLs or findings from them into:
   - Source code.
   - Fixtures.
   - Test data.
   - Demo data.
   - Screenshots.
   - Public documentation.
3. Do not commit the private references.
4. Add their directory and filenames to `.gitignore`.
5. Use fully synthetic identities in development and testing.
6. Provide an optional local import path for the user to load the private documents at runtime.
7. Do not automatically ingest private-reference content into a live audit without confirmation.
8. Add a repository privacy scanner that fails CI if private-reference filenames or known sensitive patterns appear in tracked files.
9. Provide a `make privacy-check` or equivalent command.

---

# 7. Target environment

Primary environment:

- macOS.
- Apple Silicon.
- M4 Max.
- 64 GB unified memory.
- VS Code.

Use the machine intelligently:

- Parallel adapters with bounded concurrency.
- Local full-text indexing.
- Local embeddings where they improve measurable retrieval quality.
- Optional local language models through MLX, llama.cpp or another Apple-Silicon-optimised runtime.
- Background screenshot processing.
- Concurrent evidence capture.
- Hashing and deduplication.
- Local graph analytics.
- Fast audit-to-audit diffing.
- Optional image similarity and OCR pipelines.
- Multi-process workers where Python’s GIL would otherwise limit throughput.

Benchmark important choices. Keep the interface responsive. Do not use heavy local AI merely as decoration.

---

# 8. Technology decision

You may choose languages, frameworks, databases, APIs and packaging, but document the decision first.

Create:

`docs/architecture/ADR-001-technology-stack.md`

Evaluate at least:

- Desktop application versus local web application.
- Tauri versus Electron versus browser-only.
- TypeScript-only versus TypeScript plus Python.
- SQLite versus PostgreSQL.
- Relational graph modelling versus dedicated graph database.
- In-process async jobs versus external queues.
- Local NLP versus remote LLM assistance.
- Browser automation options.
- Evidence encryption.
- Local model runtime.
- Packaging and code signing.

## Preferred default architecture

Use this unless an ADR demonstrates a better approach:

- **Desktop shell:** Tauri.
- **UI:** React, TypeScript, Vite.
- **Core service:** Python 3.12+ with FastAPI or equivalent typed local API.
- **Data layer:** SQLAlchemy and Alembic.
- **Primary database:** SQLite for the local-first version.
- **Encrypted data:** SQLCipher or equivalent encrypted database strategy.
- **Secrets:** macOS Keychain.
- **Browser automation:** Playwright.
- **Graph visualisation:** Cytoscape.js, Sigma.js or another mature library.
- **Job execution:** bounded asynchronous local workers.
- **Schemas:** Pydantic and JSON Schema.
- **Testing:** pytest, Vitest, Playwright.
- **Local NLP:** deterministic extraction first, optional spaCy, optional local LLM.
- **Packaging:** Tauri desktop package.
- **Observability:** structured local logs with sensitive-value redaction.
- **Search index:** SQLite FTS5 initially, with abstraction for a stronger local search engine later.

Do not choose novelty over maintainability.

---

# 9. Delivery discipline

Maintain:

```text
PLAN.md
STATUS.md
DECISIONS.md
KNOWN_LIMITATIONS.md
SECURITY.md
PRIVACY_MODEL.md
THREAT_MODEL.md
TEST_RESULTS.md
SCREENSHOT_REVIEW.md
CHANGELOG.md
```

Requirements:

- Keep `PLAN.md` phase-based and current.
- Update `STATUS.md` after meaningful work.
- Record architectural decisions.
- Record unsupported sources, blocked integrations and residual uncertainty.
- Use small, coherent commits.
- Never declare completion because code merely exists.
- A phase is complete only after:
  - The software runs.
  - Relevant tests pass.
  - Real interaction has been inspected.
  - Screenshots have been captured where applicable.
  - Problems have been fixed or explicitly documented.

---

# 10. Build order: UI first

The first substantial implementation phase is the interface and interaction model.

Do not begin with a large backend and a placeholder dashboard.

## 10.1 First deliverable: high-fidelity interactive UI

Build with entirely synthetic data.

Required screens:

1. Application shell.
2. Navigation.
3. Mission-control dashboard.
4. New-audit flow.
5. Free-text and file intake.
6. Extracted-entity review.
7. Tool launcher.
8. Live operations console.
9. Findings inbox.
10. Identity and provenance graph.
11. Result-detail and evidence view.
12. Impersonation case view.
13. Audit comparison view.
14. Remediation board.
15. Provider registry.
16. Jurisdiction and transmission-control panel.
17. Settings and privacy controls.
18. Empty states.
19. Loading states.
20. Failure states.
21. Blocked-source/manual-action states.
22. Reduced-motion mode.

## 10.2 Naming system

Use **Codename Ariadne** for the application.

Use clear, semi-stylised names for tools, modules and screens:

- Prefer names such as `Username Sweep`, `Source Radar`, `Link Map`, `Case Desk`, `Evidence Capture`, `Compare Runs` and `Removal Tracker`.
- A user should understand the function without opening documentation.
- Use mythological references sparingly and only where they add meaning.
- Avoid a product full of opaque names such as Argus, Janus, Mnemosyne or Aegis.
- Internal technical modules may use straightforward names such as:
  - `identity_compiler`
  - `query_planner`
  - `source_registry`
  - `correlation_engine`
  - `evidence_store`
  - `audit_diff`
  - `remediation_tracker`
- Visual copy may use subtle thread, maze, route and signal metaphors.
- Do not make the interface sound theatrical, military or threatening.
- Keep the tone precise, high-end and technically credible.

## 10.3 Visual direction

Create a premium cyberpunk intelligence-console aesthetic, not a generic admin dashboard.

Desired qualities:

- Dark graphite and near-black base.
- Layered glass, metal and terminal surfaces.
- Carefully controlled neon accents.
- Cyan, ultraviolet, toxic green and warning amber used with restraint.
- Dense monitoring panels that remain legible.
- Animated graph edges.
- Live waveform, scanning and indexing motifs.
- Terminal-style execution logs.
- Radar and network-map visual language.
- Strong typography hierarchy.
- Subtle grids and scanlines.
- Smooth transitions.
- Purposeful micro-interactions.
- High information density without chaos.
- Serious intelligence-tool feel rather than a game menu.
- Accessible contrast.
- Keyboard navigation.
- `prefers-reduced-motion` support.

Avoid:

- Endless glowing boxes.
- Unreadable neon text.
- Excessive flicker.
- Fake charts.
- Decorative animations that interfere with input.
- A cliché green terminal as the entire design.
- Tiny typography.
- Generic crypto-dashboard styling.

## 10.4 UI quality gate

For every major screen:

1. Run the application.
2. Capture screenshots at:
   - 1440 × 900.
   - 1728 × 1117 or comparable.
   - Narrow laptop width.
3. Inspect:
   - Alignment.
   - Spacing.
   - Typography.
   - Contrast.
   - Overflow.
   - Long identifiers.
   - Empty states.
   - Errors.
   - Loading.
   - Graph readability.
   - Animation smoothness.
4. Record review in `SCREENSHOT_REVIEW.md`.
5. Fix defects.
6. Capture again.
7. Do not proceed to full backend implementation until the core UI is polished.

Use synthetic development data only, such as:

```text
Morgan Vale
morgan.vale@example.invalid
@night_orbit
Northbridge Systems
Greyhaven
```

Use `.invalid` domains.

---

# 11. Core user journeys

## 11.1 Full audit

```text
Create audit
→ Import or paste source material
→ Extract entities
→ Review and approve
→ Select data-sharing permissions
→ Generate search plan
→ Review query budget
→ Start
→ Monitor live progress
→ Review findings
→ Resolve attribution
→ Explore graph
→ Preserve evidence
→ Create remediation cases
→ Export report
```

## 11.2 Targeted trace

```text
Open Tool Console
→ Choose Email / Username / Phone / Name / Address / Domain / URL / Image
→ Enter one value
→ Review provider and jurisdiction exposure
→ Select sources
→ Run
→ View live progress
→ Review graph and evidence
→ Save into a profile or keep isolated
```

## 11.3 Re-audit

```text
Open previous audit
→ Re-run all or selected checks
→ Compare snapshots
→ View NEW / CHANGED / REMOVED / REAPPEARED
→ Update remediation state
```

## 11.4 Impersonation investigation

```text
Open suspicious result
→ Record claimed identity
→ Compare timeline
→ Compare identifiers
→ Add known ownership periods
→ Capture evidence
→ Classify outcome
→ Prepare but do not automatically submit reports
```

---

# 12. Intake system

## 12.1 MVP file types

- `.txt`
- `.md`
- `.csv`
- `.json`
- `.vcf`

## 12.2 Planned importers

- PDF.
- HTML.
- Google Takeout.
- Apple account exports.
- Password-manager exports.
- Browser exports.
- Social-platform exports.
- Email mailbox exports.
- ZIP bundles.

## 12.3 Intake pipeline

```text
File or pasted text
→ MIME and encoding detection
→ Safe parsing
→ Source segmentation
→ Deterministic extraction
→ Semantic extraction
→ Normalisation
→ Sensitivity classification
→ Deduplication
→ Relationship extraction
→ Confidence assignment
→ Human review
→ Approved identity profile
```

## 12.4 Deterministic extraction

Implement extractors for:

- Email addresses.
- Telephone numbers.
- URLs.
- Domains.
- Social handles.
- IP addresses.
- Dates.
- Coordinates.
- Company numbers.
- Platform account IDs.
- Postal codes.
- Wallet addresses where relevant.
- Obvious identifiers.

## 12.5 Semantic extraction

Detect:

- Legal names.
- Nicknames.
- Aliases.
- Historical aliases.
- Organisations.
- Employers.
- Educational institutions.
- Locations.
- Employment periods.
- Education periods.
- Projects.
- Platform relationships.
- Ownership statements.
- Recovery relationships.
- Family or associate references.
- “This is not me” exclusions.
- Approximate dates.
- Current versus former data.
- Confidence.
- Provenance.

Deterministic extraction is primary. Semantic models enrich but do not silently override evidence.

## 12.6 Review workspace

The user must be able to mark each entity:

- Confirmed.
- Probable.
- Possible.
- False positive.
- Excluded.
- Historical.
- Current.
- Sensitive.
- Search permitted.
- Store only.
- Do not transmit externally.

All edits must be auditable.

---

# 13. Sensitivity and transmission controls

Use:

| Level | Examples | Default behaviour |
|---|---|---|
| Public | Public name, public company, public username | Search allowed |
| Sensitive | Email, domain, historical username | Confirm provider use |
| Highly sensitive | Full phone, exact address, DOB | Explicit per-run approval |
| Restricted | Passwords, OTPs, bank details, identity documents | Never search; redact and quarantine |

Requirements:

- Detect likely passwords, OTPs, card numbers, bank-account data and government identifiers.
- Quarantine restricted values.
- Never include restricted values in logs.
- Show provider, jurisdiction and purpose before transmission.
- Allow per-entity restrictions.
- Maintain a transmission ledger.
- Support worldwide, EU-only, local-only and custom modes.

---

# 14. Identity normalisation

Generate controlled variants.

## Names

- Diacritic and non-diacritic.
- Hyphenated and non-hyphenated.
- Surname order.
- Initials.
- Common abbreviations.
- Token-normalised forms.

## Emails

- Full address.
- Local part.
- Domain.
- Potential username from local part.
- Provider-aware normalisation without unsafe merging.

## Usernames

- Case variants.
- Separator variants:
  - underscore.
  - hyphen.
  - period.
  - spaces.
- Controlled typo variants.
- Transliteration.
- Leetspeak only when justified.

## Phone numbers

- E.164.
- National format.
- International prefix alternatives.
- Space and punctuation variants.

Do not automatically transmit every generated variant. Use query budgets and user controls.

---

# 15. Identity graph

Create a first-class graph, not a decorative visualisation.

## 15.1 Node types

- Person.
- Alias.
- Username.
- Email.
- Telephone.
- Address.
- Location.
- Organisation.
- Employment.
- Education.
- Domain.
- URL.
- Platform account.
- Company.
- Project.
- Image.
- Document.
- Finding.
- Evidence artifact.
- Audit run.
- Provider.
- Remediation case.

## 15.2 Edge types

- `OWNS`
- `USED`
- `RECOVERY_FOR`
- `EMPLOYED_BY`
- `STUDIED_AT`
- `LIVED_AT`
- `LOCATED_IN`
- `LINKS_TO`
- `MENTIONS`
- `AUTHORED`
- `CREATED`
- `MIRRORS`
- `REPOSTS`
- `SAME_AS`
- `POSSIBLY_SAME_AS`
- `NOT_SAME_AS`
- `PREVIOUS_USERNAME`
- `CURRENT_USERNAME`
- `FOUND_BY`
- `SUPPORTED_BY`
- `CONTRADICTED_BY`
- `REMOVAL_REQUEST_FOR`

## 15.3 Edge evidence

Every edge must include:

- Source.
- Confidence.
- Visibility.
- Timestamp.
- Evidence reference.
- Human or automated origin.
- Explanation.
- Contradictions.

Use SQLite relational modelling initially if practical, but expose a graph-domain abstraction.

---

# 16. Search-plan compiler

Build a query compiler that converts approved entities into an inspectable plan.

## Query classes

- Exact.
- Variant.
- Correlation.
- Platform-specific.
- Content-type.
- Temporal.
- Language-specific.
- Geographic.
- Archive.
- Image.
- Public-record.
- Account-export.
- Code/repository.

Every query record must include:

```json
{
  "query_id": "uuid",
  "audit_run_id": "uuid",
  "input_entity_ids": ["uuid"],
  "query_text": "\"night_orbit\"",
  "adapter_id": "search_provider",
  "query_class": "exact",
  "sensitivity": "sensitive",
  "jurisdiction": "US",
  "status": "queued",
  "created_at": "ISO-8601",
  "started_at": null,
  "finished_at": null,
  "result_count": null,
  "error_code": null
}
```

## Query-budget controls

Avoid combinatorial explosion.

Support:

- Maximum queries per entity.
- Maximum variants.
- Maximum providers.
- Estimated cost.
- Estimated duration.
- Sensitivity cost.
- User approval before high-risk queries.
- Pause and resume.
- Cancel.
- Retry.
- Incremental expansion when results justify it.

---

# 17. Adapter architecture

Use independent adapters with one stable contract.

Each adapter should expose capabilities such as:

```python
class SourceAdapter(Protocol):
    metadata: ProviderMetadata

    async def health_check(self) -> HealthCheckResult: ...
    async def estimate(self, task: SearchTask) -> CostEstimate: ...
    async def search(self, task: SearchTask, context: RunContext) -> list[RawResult]: ...
    async def fetch(self, target: FetchTarget, context: RunContext) -> RawArtifact: ...
    async def normalise(self, raw: RawResult) -> list[FindingCandidate]: ...
```

## Adapter categories

- Search engines.
- Username checks.
- GitHub.
- Internet archives.
- Public company registers.
- Academic profiles.
- Social platforms.
- Video platforms.
- Forums.
- Gaming platforms.
- Developer platforms.
- Public data brokers.
- Official breach-notification services.
- Reverse-image search.
- User-authorised Gmail.
- User-authorised GitHub.
- Local document corpus.
- Local browser history export.
- Local password-manager export.
- Local repository scan.
- Manual evidence import.

## Adapter rules

- Timeouts.
- Retries with bounded exponential backoff.
- Rate limiting.
- Caching.
- Idempotency.
- Structured errors.
- No silent failure.
- Provider-level enable/disable.
- Mock mode.
- Dry-run mode.
- Cost accounting.
- Jurisdiction metadata.
- Terms and privacy references.
- Redaction-aware logging.

---

# 18. Tool console

The user must be able to run tools independently.

Required standalone tools and user-facing names:

- **Email Trace** — investigate one email address and its public or authorised account links.
- **Username Sweep** — search one username and controlled variants across platforms.
- **Name Search** — trace a legal name, nickname or alias.
- **Phone Trace** — check a telephone number using approved sources and formats.
- **Address Search** — investigate a physical address with strict sensitivity controls.
- **Domain Scan** — inspect a domain, related profiles, infrastructure and mentions.
- **URL Inspector** — analyse one URL, redirects, metadata, archives and evidence.
- **Company Search** — inspect companies, officers, public records and linked identities.
- **Image Match** — run authorised reverse-image and similarity checks.
- **Repository Scan** — inspect owned or authorised code repositories and history.
- **Archive Search** — query historical captures, mirrors and cached references.
- **Public Records Search** — search official registers and public databases.
- **Inbox Account Finder** — extract account and username evidence from a user-authorised mailbox.
- **GitHub Exposure Review** — inspect the user-authorised GitHub account and repositories.
- **Local File Search** — scan an imported local corpus for identities, relationships and traces.
- **Evidence Capture** — preserve screenshots, HTML, PDFs, metadata and hashes.
- **Compare Runs** — compare two audits or two versions of the same source.
- **Removal Tracker** — monitor deletion, correction, deindexing and impersonation cases.
- **Source Radar** — show provider health, jurisdiction, coverage and current failures.
- **Link Map** — open the interactive identity and provenance graph.
- **Case Desk** — review ambiguous attribution and impersonation cases.

These names should be clear enough to understand immediately while still feeling distinctive and premium. Avoid naming every tool after a mythological figure. The product may use restrained Ariadne/thread/maze motifs in visual language, but functional labels must remain obvious.

Each tool must show:

- Inputs.
- Normalised variants.
- Selected adapters.
- Provider jurisdictions.
- Expected cost.
- Expected duration.
- Data-transmission summary.
- Live progress.
- Raw and normalised results.
- Save-to-profile option.

---

# 19. ARIADNE CORE correlation engine

ARIADNE CORE is the identity-resolution and attribution engine.

## 19.1 Signals

Possible positive signals:

- Exact email.
- Recovery relationship.
- Exact legal name.
- Same uncommon username.
- Same photograph.
- Same organisation.
- Same education.
- Same location.
- Same project.
- Same linked domain.
- Same writing/profile links.
- Chronological compatibility.
- User confirmation.
- Immutable platform ID continuity.

Possible negative signals:

- Conflicting age.
- Conflicting photograph.
- Incompatible geography.
- Activity before plausible ownership.
- Different immutable account ID.
- Contradictory biography.
- Explicit user exclusion.
- Evidence of username recycling.

## 19.2 Explainable scoring

Do not expose only a mysterious percentage.

Show:

- Score.
- Contributing signals.
- Contradictions.
- Missing evidence.
- Confidence band.
- Recommended next evidence.
- Whether human review is required.

Scoring weights must be configurable and versioned.

## 19.3 Human control

Never automatically label an account as belonging to a real person based solely on a score.

Human states:

- Confirmed match.
- Confirmed non-match.
- Probable.
- Possible.
- Unresolved.
- Needs more evidence.

Record who made the decision and when.

---

# 20. Impersonation analysis

Support:

- Historical owned account.
- Current owned account.
- Taken over.
- Recycled username.
- Coincidental collision.
- Mirror or repost.
- Possible impersonation.
- Confirmed impersonation.
- Unknown.

Evidence dimensions:

- Uses the person’s name.
- Uses the person’s photographs.
- Uses employment or education.
- Uses relationships.
- Claims to be the person.
- Activity after ownership ended.
- Same immutable account ID.
- Username-history evidence.
- Old screenshots or emails proving ownership.
- Reports from confused third parties.

No automatic accusation. The UI must use careful language.

---

# 21. Evidence vault

For each finding, support:

- Screenshot.
- HTML.
- PDF.
- Raw JSON.
- URL.
- UTC timestamp.
- SHA-256.
- HTTP status.
- Redirect chain.
- Query.
- Provider.
- Audit run.
- Screenshot viewport.
- Capture method.
- Local file path.
- Encryption state.

Recommended structure:

```text
evidence/
└── <audit-run-id>/
    └── <entity-or-case-id>/
        ├── artifact_001.png
        ├── artifact_001.html
        ├── artifact_001.json
        └── artifact_001.sha256
```

Requirements:

- Encrypt sensitive evidence at rest.
- Prevent accidental Git inclusion.
- Verify hashes.
- Deduplicate by content hash.
- Preserve capture metadata.
- Support a redacted export.
- Support manual evidence import.
- Never overwrite the original artifact.

---

# 22. Live operations console

The user wants visible progress.

Build a real execution console showing:

- Overall percentage.
- Current phase.
- Active workers.
- Queued tasks.
- Completed tasks.
- Failed tasks.
- Blocked tasks.
- Provider status.
- Rate limits.
- Estimated remaining time.
- API cost.
- Search count.
- Findings count.
- New graph nodes and edges.
- Evidence captures.
- Warnings.
- Human-action requests.

Allow:

- Pause.
- Resume.
- Cancel.
- Retry failed.
- Retry selected.
- Skip provider.
- Open task details.
- Export execution log.

The console must use real job state, not fake animations.

---

# 23. Map and provenance views

Implement at least two map styles.

## 23.1 Identity graph

Interactive force-directed graph with:

- Filtering by node type.
- Filtering by confidence.
- Filtering by public/private.
- Filtering by source.
- Filtering by date.
- Search and focus.
- Pinning.
- Collapsing clusters.
- Edge explanations.
- Evidence drawer.
- Timeline mode.
- “Why is this connected?” action.
- “Hide private nodes” toggle.

## 23.2 Geographic map

Where locations are relevant:

- Map points and regions.
- Public versus private location status.
- Historic versus current.
- Source and confidence.
- No exact-coordinate display by default for private addresses.
- Coarse display mode.
- Time slider.
- Provider jurisdiction overlay optionally.

Do not leak exact private addresses in screenshots.

---

# 24. Monitoring and diff engine

States:

- `NEW`
- `CHANGED`
- `REMOVED`
- `REAPPEARED`
- `REDIRECTED`
- `DEINDEXED`
- `ARCHIVED`
- `FALSE_POSITIVE`
- `UNCHANGED`
- `UNKNOWN`

Compare:

- URL existence.
- Content hash.
- Profile fields.
- Username.
- Display name.
- Bio.
- Links.
- Image perceptual hash.
- Search-engine presence.
- Archive presence.
- Evidence status.
- Removal status.

Ignore irrelevant dynamic noise such as ads, timestamps and random tokens where possible.

---

# 25. Remediation engine

Per finding:

- Ignore.
- Monitor.
- Preserve evidence.
- Delete owned account.
- Correct source.
- Request GDPR erasure.
- Request local-law deletion.
- Request deindexing.
- Report impersonation.
- Contact site owner.
- Escalate.
- Mark impossible or legally persistent.

Track:

- Request date.
- Jurisdiction.
- Legal basis.
- Template used.
- Evidence attached.
- Deadline.
- Provider response.
- Appeal.
- Source removal.
- Search-engine removal.
- Cache persistence.
- Reappearance.

Do not send anything automatically without explicit user approval.

Generate draft templates, not legal advice.

---

# 26. Local AI and parallel computation

Use local compute where it improves the product.

Possible local tasks:

- Entity extraction.
- Entity linking.
- Query expansion.
- Result summarisation.
- Semantic deduplication.
- Writing-style comparison.
- Image embeddings.
- Face detection only for the user’s own supplied images and authorised comparison.
- OCR.
- Classification of result relevance.
- Suggested evidence gaps.

Rules:

- Keep deterministic evidence separate from AI inference.
- Label AI-generated conclusions.
- Store model name and version.
- Make local AI optional.
- Provide a no-LLM mode.
- Benchmark latency and memory.
- Never let an LLM directly submit reports or make irreversible changes.
- Do not upload sensitive data to remote models without explicit approval.

Use bounded parallelism. Avoid creating uncontrolled hundreds of browser sessions.

---

# 27. Data model

Design and document a database schema covering at least:

- Profiles.
- Entities.
- Entity variants.
- Relationships.
- Entity decisions.
- Source providers.
- Provider jurisdictions.
- Audit runs.
- Search plans.
- Search tasks.
- Raw results.
- Findings.
- Finding versions.
- Evidence artifacts.
- Attribution decisions.
- Impersonation cases.
- Remediation cases.
- Transmission ledger.
- API usage and costs.
- Errors.
- User settings.
- Encryption metadata.
- Tags.
- Notes.

Create:

`docs/data-model.md`

Include an ER diagram.

---

# 28. API design

Create:

`docs/api.md`

Use typed request and response schemas.

Minimum local API areas:

```text
/profile
/intake
/entities
/graph
/providers
/audits
/tasks
/findings
/evidence
/attribution
/impersonation
/remediation
/reports
/settings
```

Use streaming or WebSockets for live task progress.

---

# 29. Privacy and security requirements

Create:

- `SECURITY.md`
- `PRIVACY_MODEL.md`
- `THREAT_MODEL.md`

Threats to consider:

- Stolen laptop.
- Malicious local process.
- Leaked report.
- Public Git commit.
- Log leakage.
- OAuth-token theft.
- Provider overcollection.
- Screenshot leakage.
- Audit bundle copied to cloud storage.
- Prompt injection inside webpages.
- Malicious HTML or files.
- Supply-chain compromise.
- Local database corruption.
- Cross-profile contamination.
- False positive causing reputational harm.

Controls:

- Encryption at rest.
- OS keychain.
- Sensitive-log redaction.
- Safe HTML rendering.
- File sandboxing.
- MIME validation.
- Size limits.
- Content security policy.
- Dependency scanning.
- Lock files.
- Provenance metadata.
- Audit logs.
- Redacted exports.
- Auto-lock.
- Secure deletion guidance.
- Backup and restore.
- No telemetry by default.

Treat webpage content as untrusted data, not instructions.

---

# 30. Testing

## Unit tests

- Entity extraction.
- Normalisation.
- Sensitivity classification.
- Query generation.
- Scoring.
- Deduplication.
- Diffing.
- Redaction.
- Hashing.
- Provider metadata.
- Transmission restrictions.

## Integration tests

- Adapter lifecycle.
- Search-plan execution.
- Evidence capture.
- Graph updates.
- Database migrations.
- Retry behaviour.
- Cancellation.
- Resume.
- Import/export.
- Encryption.

## End-to-end tests

- Full synthetic audit.
- Targeted email trace.
- Targeted username trace.
- Blocked provider.
- Rate limit.
- Provider outage.
- Manual import.
- Attribution decision.
- Remediation case.
- Audit comparison.
- Redacted export.

## Visual tests

- Major screens.
- Multiple viewports.
- Reduced motion.
- Long text.
- Empty state.
- Error state.
- Large graph.
- High-density findings.

## Privacy tests

- No real personal data in repository.
- No secrets in source.
- Logs redact sensitive values.
- Restricted values are never transmitted.
- Private reference files are ignored by Git.
- Screenshots contain only synthetic data.

---

# 31. Phase plan

## Phase 0 — Discovery and architecture

Deliver:

- Repository inspection.
- Requirements extraction.
- ADR.
- Threat model.
- Privacy model.
- Data model.
- UI information architecture.
- Implementation plan.

## Phase 1 — UI system and interactive prototype

Deliver:

- Design tokens.
- Component library.
- All major screens.
- Synthetic workflows.
- Live-looking but explicitly mocked task state.
- Screenshot review and refinement.

Do not proceed until visually polished.

## Phase 2 — Local foundation

Deliver:

- Tauri shell.
- Local API.
- Database.
- Migrations.
- Encryption.
- Settings.
- Logging.
- Task engine.
- Import/export scaffolding.

## Phase 3 — Intake and identity compiler

Deliver:

- File import.
- Pasted text.
- Deterministic extraction.
- Semantic enrichment.
- Entity review.
- Sensitivity controls.
- Identity graph persistence.

## Phase 4 — Search compiler and first adapters

Deliver:

- Search planning.
- Query budgets.
- Provider registry.
- Search-engine adapter.
- Username adapter.
- GitHub adapter.
- Archive adapter.
- Manual import.
- Live task console.

## Phase 5 — Evidence and attribution

Deliver:

- Screenshots.
- Hashes.
- Raw artifact storage.
- ARIADNE CORE scoring.
- Explainable attribution.
- Findings inbox.
- Graph evidence links.

## Phase 6 — Monitoring and remediation

Deliver:

- Audit snapshots.
- Diff engine.
- Reappearance detection.
- Remediation cases.
- Report templates.
- Long-term status tracking.

## Phase 7 — Authorised account connectors

Deliver:

- Gmail read-only connector.
- GitHub authenticated connector.
- Local exports.
- Clear OAuth scopes.
- Token storage in keychain.
- Revocation support.

## Phase 8 — Global provider expansion

Deliver:

- Jurisdiction-aware provider registry.
- Additional public records.
- Lawful broker adapters.
- Image providers.
- Additional regional search sources.
- Per-provider risk controls.

## Phase 9 — Hardening and packaging

Deliver:

- Security review.
- Dependency review.
- Performance profiling.
- Accessibility review.
- Installer.
- Backup/restore.
- Documentation.
- Release candidate.

---

# 32. Acceptance criteria

The first serious release is not acceptable unless:

- No real user data is hardcoded.
- The app starts cleanly on the target Mac.
- UI is polished and reviewed through screenshots.
- A synthetic full audit works end to end.
- A single-email targeted trace works.
- A single-username targeted trace works.
- Progress is real and visible.
- Failures and blocks are explicit.
- Results have provenance.
- The graph explains every connection.
- Evidence can be captured and hashed.
- Two audit runs can be compared.
- Removal work can be tracked.
- Sensitive values are protected.
- Jurisdiction and transmission risk are visible.
- Reports can be exported.
- A redacted report can be exported.
- Tests pass.
- Limitations are documented.
- No unsupported claim of completeness is made.

---

# 33. Initial execution instructions

Start now by doing the following, in order:

1. Inspect all repository files.
2. Read the private methodology and findings references, if present.
3. Create a concise requirements extraction that does not repeat private identifiers.
4. Create `PLAN.md`.
5. Create ADR-001.
6. Create the threat model and privacy model.
7. Decide the stack.
8. Scaffold the project.
9. Build the high-fidelity UI first using synthetic data.
10. Run it.
11. Capture screenshots.
12. Review screenshots in writing.
13. Fix visual defects.
14. Demonstrate the complete synthetic workflow.
15. Only then implement the backend phases.

At every checkpoint:

- Show what was built.
- Show what was tested.
- Show screenshots where relevant.
- State remaining defects.
- State privacy implications.
- Do not hide failures.
- Do not stop at an unfinished half-working state and describe it as complete.

Codename Ariadne should be ambitious, but every part must be real.

---

# 34. Final design principle

Codename Ariadne should behave like a disciplined analyst, not a reckless scraper.

It should be:

- Global.
- Modular.
- Powerful.
- Transparent.
- Reproducible.
- Local-first.
- Human-controlled.
- Evidence-driven.
- Jurisdiction-aware.
- Honest about uncertainty.
- Extremely polished.

Ariadne Core should never merely say:

> “These accounts are connected.”

It should show:

> “These accounts may be connected because of these specific pieces of evidence, these contradictions, this provenance, this visibility level and this confidence. Here is what to verify next.”

Build that product.
