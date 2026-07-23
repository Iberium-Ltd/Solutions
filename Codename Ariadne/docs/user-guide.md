# Codename Ariadne desktop user guide

Use the native macOS app for encrypted, persisted work. The browser at
`http://127.0.0.1:1420` is a synthetic interface preview: it cannot open your
vault and several of its screens are demonstrations.

For the packaged app, double-click **Launch Ariadne.command** at the repository
root. It opens the current local macOS bundle without requiring a Terminal
command.

## First launch

1. Open the native app and select **Create local vault** in the lower-left
   corner. Ariadne creates the encrypted local workspace and opens the
   profile chooser.
2. Choose **Create a named profile**, enter a local profile label and purpose,
   then select **Create profile and continue**. To resume later, choose
   **Continue an existing profile** instead. Intake cannot silently create a
   generic profile.
3. Add one authorised source. For a harmless trial, paste a fictional record
   such as `Casey Rowan · casey.rowan@example.invalid`, then select **Extract
   locally**. You can instead choose one TXT, Markdown, CSV, JSON, or vCard file
   up to 1 MiB.
4. Select **Review candidates**, inspect the extracted entities, and record a
   decision for each one. Bulk review can apply shared settings to unresolved
   candidates; use individual review for exceptions.
5. The active profile appears in the upper-right profile switcher. On a later
   launch, unlock the vault and use this switcher to resume an active or draft
   profile.

The **Getting started** screen remains available while the vault is locked.

## Navigation map

| Group | Screen | Practical use |
| --- | --- | --- |
| Overview | New Audit | Create or resume a named profile and start the live native intake path. |
| Overview | Mission Control, Operations | Synthetic orientation and workflow demonstrations. |
| Overview | Findings | Review persisted findings, evidence metadata, assessments, and attribution decisions. |
| Explore | People | Review a persistent profile, start or resume a complete audit, inspect run history, and delete the active profile after exact-name confirmation. |
| Explore | Discovery Console | Optional expert tools for one-off public web, GitHub-user, or HIBP searches, multi-engine browser queries, inspectable plans, and manual portals. |
| Explore | AI Workspace | Analyse selected parts of the active encrypted profile with exact citations. |
| Explore | Corpus AI | Analyse several selected local files together without adding them to the profile. |
| Explore | Link Map | Inspect reviewed entities, relationships, confidence, contradictions, and origins. |
| Explore | Geographic Map, Case Desk | Synthetic demonstrations; they do not read the native vault. |
| Track | Compare Runs | Create local checkpoints and compare two persisted snapshots. |
| Track | Removal Tracker | Organise local follow-up cases, drafts, deadlines, evidence links, and status history. |
| Track | Reports | Generate a bounded Markdown or JSON artifact from two checkpoints. |
| Control | Source Radar | Synthetic provider-coverage demonstration. |
| Control | Transmission | Build and inspect a network-free query plan; it does not execute provider searches. |
| Control | Privacy & Settings | Configure the loopback AI runtime and explicit model, font scale, and laptop/standard/ultrawide layout preset. |

## Recommended workflow

### 1. Choose a durable profile

Open **New Audit**, create a named profile or continue an existing one, and
confirm that the displayed profile is the intended destination. A profile is
the long-lived container for identifiers, sources, decisions, audits, results,
proposals, and citations; each full audit is a separate retained run.

### 2. Import once and review

Paste text or select one supported local file and run extraction. On **Entity
Review**, confirm, reject, or edit candidates and inspect source origins when
needed. Labelled rows such as `username,synthetic_alias,current,Primary` and
`name,Synthetic Person,current,Primary` are recognized alongside ordinary
email, URL, domain, and `@handle` patterns.

The **Bulk review** panel applies one decision, temporal state, search policy,
and transmission policy to every unresolved candidate while preserving
entity-specific sensitivity. The reviewed identifiers remain attached to the
profile, so the main workflow does not require retyping them.

### 3. Start the complete audit

After review, continue to **People**. In **Run the complete identity audit**:

1. Name the run.
2. Choose maximum coverage, full rescan, incremental, or retry-blocked mode.
3. Keep the bounded depth and request budget, or adjust them deliberately.
4. Enable the selected local model if it is configured.
5. Enable HIBP only if you accept that its tasks may require a subscription key.
6. Select **Start full audit**.

The durable progress screen advances bounded task batches automatically across
DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate
transparency. It shows actual queued/running/terminal task state, supports
pause/resume/cancel, and survives closing or reopening the view. Blocked,
empty, partial, and failed checks remain coverage states, not claims of absence.

### 4. Review exact results and AI proposals

Use the run's **Results**, **AI analysis**, **Frontier**, and **Review** tabs.
Every retained result includes its exact URL and provider. Local AI output is
review-only and must cite retained result URLs. Confirm a proposal only when its
source supports the relationship; use **Search deeper** or **Unrelated** for
the other cases.

### 5. Finish and download

When discovery is terminal, the **Finish this audit** panel shows any remaining
human reviews. Resolve them, choose Markdown or JSON, and select **Generate and
download**. Ariadne creates an inert local package containing:

- run scope, state, stop reason, task coverage, gaps, and failures;
- exact result URLs and provider attribution;
- recursive leads and review decisions;
- cited AI analysis and limitations; and
- execution receipts, truncation flags, byte count, and SHA-256.

The package is generated from the committed terminal revision and is not stored
inside Ariadne after download.

### Optional advanced tools

The Discovery Console, Query Composer, Transmission screen, individual public
search forms, manual portals, Findings, Link Map, Compare Runs, Removal Tracker,
and legacy Reports are supplementary tools. They are not required to complete
the profile-to-audit-to-package journey.

The Discovery Console can still run explicitly approved one-off DuckDuckGo,
GitHub, or HIBP checks; generate browser handoffs for Google, Bing,
DuckDuckGo, Brave, Ecosia, Startpage, and Mojeek; and open fixed official
portals. It does not automate sign-in, scrape browser results, bypass CAPTCHA,
paywalls, verification, rate limits, or other access controls.

## AI setup

Ariadne does not require a paid or cloud AI service. It supports an explicit
model served on loopback by Ollama or an OpenAI-compatible runtime such as LM
Studio.

1. Start the local runtime and make a model available. For example, Ollama users
   can run `ollama serve` and, once, `ollama pull qwen3:30b`.
2. Open **Privacy & Settings → Connectors and local AI**.
3. Choose **Ollama** (normally `http://127.0.0.1:11434`) or the loopback endpoint
   of the OpenAI-compatible runtime.
4. Select **Discover served models**, choose the exact model, and select **Test
   connection**.
5. Enable **Use local AI assistance** and select **Save local AI**.

The selected model is stored in the encrypted vault. Ariadne never chooses a
different model silently and has no cloud fallback. The result badge states
whether the chosen local model ran or deterministic analysis was used instead.

On this Mac, Ollama's model store is located at
`/Volumes/Predator SSD GM7000/LLMs/Ollama/models`, with
`~/.ollama/models` linked to that directory. **Launch Ariadne.command** exports
the same `OLLAMA_MODELS` path and starts the Ollama application if necessary.
The Ollama application itself remains in `/Applications`; only its large model
data is stored on the SSD. If the SSD is disconnected, Ariadne still opens and
reports local AI as unavailable instead of silently using another model.

Ariadne does not read Ollama model blobs directly. It connects to the loopback
endpoint, discovers the served model IDs, and records the exact selected model
with each AI result. This separation allows the model store to move again
without changing audit data or report provenance.

### Optional OpenAI Responses execution

AI Workspace and Corpus AI also offer **OpenAI Responses** as an explicit
per-request option. Enter the exact API model ID and an OpenAI API key on that
screen. The key is kept only in component/request memory, is never saved to the
vault, and must be entered again for another request. This option sends the
selected bounded projection to OpenAI; the result badge therefore says
**External request used**. `store: false`, strict structured output, response
limits, opaque citation aliases, exact local source remapping, and deterministic
fallback are enforced. The fallback is still labelled as an attempted external
execution so a failed request is not mistaken for local-only operation.

A ChatGPT subscription is not an API credential or API billing plan. Create and
fund an API key separately if you choose this path. You may type any model ID
available to that API project; Ariadne does not silently substitute another
model.

### AI Workspace or Corpus AI?

- Use **AI Workspace** for the active profile. Select only the needed scopes:
  entities, graph, findings, remediation, audit coverage, or an optional local
  document.
- Use **Corpus AI** to compare several selected files without importing or
  persisting them. The result and its source catalog are ephemeral.

Both screens can run deterministic analysis. Select **Local model** when you
want the configured loopback model to synthesize the bounded projection, or
**OpenAI Responses** only when you intentionally want the selected projection
to leave the Mac.

| Task | Use it for |
| --- | --- |
| SUMMARY | A short cited overview of the selected evidence. |
| ORGANIZE | Grouping records or file notes without changing the underlying data. |
| QUESTION | One grounded question; phrase it narrowly and check every cited answer. |
| CONNECTIONS | Possible cross-record or cross-file links. These are labelled hypotheses and include supporting, contradicting, and verification references. |
| GAP_ANALYSIS | Cited suggestions for the next checks. Suggestions are not executed automatically. |

Model output is review-only and can be incomplete or wrong. Unknown citations,
uncited factual items, and structurally unsupported links are rejected or
discarded; a deterministic fallback may appear when model output is invalid.

## Inspect exact sources

- **Entity Review:** select an entity, then use **Inspect all stored origins**
  and **Load next exact origins**. Each origin shows source ID and SHA-256,
  segment ID/index/locator/span, extractor and run identity, timestamp, and
  confidence.
- **Link Map:** select an edge and expand **Exact source references**.
- **Finding detail:** inspect the exact source URL, URL/content hashes, provider,
  capture run, artifact ID, HTTP status, and redirect count when available.
- **Discovery Console:** public results show exact result URLs and provider
  identifiers; the query composer shows the exact generated query and browser
  handoff URL; HIBP results show exact API endpoints, request hashes, response
  metadata, and breach-record URLs.
- **AI Workspace:** every organized note, factual statement, connection, and
  suggested check exposes its cited source cards inline.
- **Corpus AI:** inspect citations beside each item and the **Exact source
  catalog** at the bottom, including file name, document/segment identity,
  index, and locator.

Exact provenance tells you where a statement came from. It does not prove the
source statement is true or that two similar records belong to the same person.

## Display size and monitor presets

Open **Privacy & Settings → Display** to choose 90%, 100%, 110%, 125%, or 140%
font scaling. Choose **Auto**, **Laptop**, **Standard**, or **Ultrawide** for the
content width, gutters, sidebar, and grid behavior. Preferences are local to the
app and apply immediately across every screen; selecting a different preset
does not resize the macOS window itself.

## Locked-vault behavior

Locking replaces vault-backed screens with the protected-workspace view, removes
sensitive content from the rendered page, revokes in-memory workflow selection,
and prevents native operations. No background audit starts while locked. Unlock
from the lower-left vault card, then reselect the profile in the upper-right
switcher if needed. If the local service is unavailable, restart the native app;
the browser preview is not a substitute for vault access.

## Current non-features

- No background scheduler or guarantee to “find everything.” Full audits run
  while the native application is open and retain committed progress between
  sessions.
- No authenticated Gmail, GitHub, or other account connectors.
- Automated full-audit discovery is limited to the seven credential-free
  surfaces listed above, plus optional authorised HIBP tasks. Multi-engine query
  links and other listed services are user-mediated browser handoffs or manual
  portals, with no result scraping, login, CAPTCHA, paywall, rate-limit, or
  access-control bypass.
- No automatic provider contact, takedown submission, message sending, or form
  dispatch.
- No active evidence-content viewer, malware scanner, OCR, PDF/Office/archive
  intake, bulk intake, or files larger than the documented bounds.
- Final audit packages and legacy reports are Markdown or JSON only and are not
  retained by Ariadne after local save.
- Mission Control, Operations, Geographic Map, Case Desk, and Source Radar
  remain synthetic demonstrations in the current native build.
- Local-model answers remain fallible and do not establish ownership,
  attribution, legal status, or exhaustive coverage.

For implementation constraints, see [Known Limitations](../KNOWN_LIMITATIONS.md).
