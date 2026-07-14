# Codename Ariadne desktop user guide

Use the native macOS app for encrypted, persisted work. The browser at
`http://127.0.0.1:1420` is a synthetic interface preview: it cannot open your
vault and several of its screens are demonstrations.

For the packaged app, double-click **Launch Ariadne.command** at the repository
root. It opens the current local macOS bundle without requiring a Terminal
command.

## First launch

1. Open the native app and select **Create local vault** in the lower-left
   corner. Ariadne creates the encrypted local workspace and opens **Intake**.
2. Add one authorised source. For a harmless trial, paste a fictional record
   such as `Casey Rowan · casey.rowan@example.invalid`, then select **Extract
   locally**. You can instead choose one TXT, Markdown, CSV, JSON, or vCard file
   up to 1 MiB.
3. The first successful intake automatically creates a local review profile.
   Select **Review candidates**, inspect the extracted entities, and record a
   decision for each one.
4. The active profile appears in the upper-right profile switcher. On a later
   launch, unlock the vault and use this switcher to resume an active or draft
   profile.

The **Getting started** screen remains available while the vault is locked.

## Navigation map

| Group | Screen | Practical use |
| --- | --- | --- |
| Overview | Mission Control, New Audit, Operations | Synthetic orientation and workflow demonstrations. Use **Add source** for the live native intake path. |
| Overview | Findings | Review persisted findings, evidence metadata, assessments, and attribution decisions. |
| Explore | Discovery Console | Run approved public web, GitHub-user, or HIBP searches; compose exact multi-engine browser queries; combine identifiers into an inspectable plan; or open a reviewed manual research portal. |
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

### 1. Intake and entity review

Open **Add source** or **New Audit → Continue to intake**. Paste text or select
one supported file, then run local extraction. Ariadne keeps deterministic
extraction even if optional local-model enrichment is unavailable.

On **Entity Review**, select each candidate and confirm, reject, edit, or retain
it according to the available decision controls. Selecting an entity also opens
its **Source origins** panel. Do not treat an extracted candidate as established
identity until you have reviewed its origin and context.

Labelled plain-text rows such as `username,synthetic_alias,current,Primary`
and `name,Synthetic Person,current,Primary` are recognized alongside ordinary
email, URL, domain, and `@handle` patterns. The **Bulk review** panel can apply
one decision, temporal state, search policy, and transmission policy to every
unresolved candidate while preserving each candidate's own sensitivity. Use
individual review for exceptions and uncertain or unrelated identifiers.

### 2. Inspect the Link Map

Open **Link Map** after entity review. Select a node or edge to inspect why it
exists. For a persisted edge, expand **Exact source references** to see its
source, segment, span, support or contradiction disposition, extraction type,
visibility, and confidence. A graph connection is evidence to review, not an
automatic identity conclusion.

### 3. Discover, combine, and capture results

Open **Discovery Console → Public search** and:

1. Choose **Public web search** or **GitHub users**.
2. Enter the exact query that may be sent, for example
   `"Casey Rowan" atlas-lab.example.invalid`.
3. Confirm the authorised self-audit checkbox and run the search.
4. Review the exact URL, title, snippet, provider, and rank of each result.
5. Select **Save finding** only for a useful result.

Saving is atomic: Ariadne retains the reviewed URL reference, a finding, its
neutral assessment, and their links together in the active profile. The raw
search query is not stored. A blocked, empty, partial, or failed provider result
is a coverage state, never proof that something does not exist.

Use **Query composer** to combine an exact phrase, alternatives, `site:`,
excluded sites, `filetype:`, `intitle:`, `inurl:`, excluded terms, date bounds,
and optional provider-specific syntax. The exact generated query stays visible.
After confirming authority, either load it into Ariadne's bounded DuckDuckGo
form or open a user-mediated search in Google, Bing, DuckDuckGo, Brave, Ecosia,
Startpage, or Mojeek. Those links use your default macOS browser; provider
operator support varies, and browser results are not imported or saved
automatically.

Use **Plan & combine** when you have several email, username, domain, name, or
URL ideas. Add the identifiers, select the available providers, and compile the
plan. Compilation is deterministic and makes no network request. Every step
shows the identifier hash, destination route, transmission mode, and
prerequisites. Select **Load** to move one step into the relevant search form;
you still approve and run it separately.

Use **Breach exposure** for Have I Been Pwned v3. Enter your subscription key,
which is held only for that request and then cleared. Email checks default to
the six-character SHA-1 k-anonymity range API; direct email mode requires a
second approval. Domain enumeration first confirms that HIBP lists the domain
as verified for the supplied subscription. Results show the exact request URL,
HTTP status, observation time, request hash, breach-record URLs, attribution,
and retry guidance.

**Manual portals** opens fixed official entry points for services such as
DeHashed, Spokeo, Intelius, the Wayback Machine, ICANN Lookup, Companies House,
GitHub Search, and Google's Results about you. These are user-mediated links,
not automated integrations: subscriptions and provider terms still apply, and
Ariadne does not automate sign-in or access challenges. Bring back only a
reviewed source URL or local export through the normal finding/evidence flow;
never import exposed passwords or secrets.

### 4. Review findings and evidence

Open **Findings**, filter the queue, and open a finding. The detail screen shows
the outcome separately from visibility, confidence, and human attribution.
Review the exact source URL and capture metadata when present, attach or import
an allowed evidence artifact if needed, and record the human decision.

Original evidence content remains sealed; the current UI exposes integrity and
provenance metadata rather than actively rendering untrusted content.

### 5. Compare checkpoints

Open **Compare Runs** and create a local checkpoint. Enter one or more opaque
provider IDs, such as `provider.synthetic.local`, and describe the coverage and
run state honestly. This snapshots finding fingerprints and coverage without
contacting a provider or copying evidence bytes.

Create another checkpoint after the profile changes. With two checkpoints,
choose the baseline and current run to review new, changed, unchanged, or absent
finding fingerprints and coverage differences. Absence in one snapshot does
not by itself prove removal.

### 6. Organise remediation

Create a case from a reviewed finding, then use **Removal Tracker** to maintain
its local draft, deadline, evidence links, approval state, status, and append-only
history. Ariadne prepares and tracks work locally; it does not send a request,
contact a provider, submit a form, or provide legal advice.

### 7. Generate a report

**Reports** requires two checkpoints. Choose baseline and current runs, then:

- use **Redacted** for the default artifact, which preserves opaque source
  mappings and hashes while omitting revealing values and exact URLs; or
- use **Full · explicit approval** only when you intend to include the available
  finding, remediation, and exact-source details.

Choose Markdown or canonical JSON, generate the report, review its preview and
SHA-256, then explicitly save it. Generated reports are held in memory until you
save them; Ariadne does not manage the saved file afterward.

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

- No background scheduler, broad crawler, or guarantee to “find everything.”
- No authenticated Gmail, GitHub, or other account connectors.
- Automated discovery is limited to DuckDuckGo HTML, unauthenticated GitHub-user
  search, and authorised HIBP v3 account/domain checks. Multi-engine query links
  and other listed services are user-mediated browser handoffs or manual
  portals, with no result scraping, login, CAPTCHA, paywall, rate-limit, or
  access-control bypass.
- No automatic provider contact, takedown submission, message sending, or form
  dispatch.
- No active evidence-content viewer, malware scanner, OCR, PDF/Office/archive
  intake, bulk intake, or files larger than the documented bounds.
- Reports are Markdown or JSON only and are not retained by Ariadne after local
  save.
- Mission Control, New Audit planning, Operations, Geographic Map, Case Desk,
  and Source Radar remain synthetic demonstrations.
- Local-model answers remain fallible and do not establish ownership,
  attribution, legal status, or exhaustive coverage.

For implementation constraints, see [Known Limitations](../KNOWN_LIMITATIONS.md).
