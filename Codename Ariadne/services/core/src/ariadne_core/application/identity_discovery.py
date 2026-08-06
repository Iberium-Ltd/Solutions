"""Application boundary for persistent people and restart-safe identity audits.

The coordinator separates external execution from durable transitions: the
repository claims work first, the closed broker performs bounded calls outside
database transactions, and each outcome is then committed with its receipt.
Database state remains authoritative across UI navigation, process restarts,
and partial batches.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import RLock
from typing import cast

from sqlalchemy.engine import RowMapping

from ariadne_core.api.identity_discovery_schemas import (
    MAX_AI_CITATIONS,
    MAX_AI_INSIGHTS,
    MAX_AUDITS,
    MAX_LEADS,
    MAX_PROPOSALS,
    MAX_RECEIPTS,
    MAX_RESULTS,
    MAX_SOURCES,
    MAX_TASKS,
    AIAnalysisCitation,
    AIAnalysisInsight,
    AIAnalysisStatus,
    AIInsightKind,
    AuditAIAnalysis,
    AuditControlRequest,
    AuditCreateRequest,
    AuditDetail,
    AuditExecuteRequest,
    AuditMode,
    AuditStage,
    AuditState,
    AuditSummary,
    DiscoveryLead,
    DiscoveryResult,
    FrontierTaskState,
    FrontierTaskSummary,
    FrontierTaskType,
    KnowledgeProposal,
    PersonDetails,
    PersonSource,
    PersonSourceCreateRequest,
    PersonUpdateRequest,
    PersonWorkspace,
    PersonWorkspaceRequest,
    ProposalDecisionRequest,
    SourceType,
    TaskStateCount,
    ToolReceipt,
)
from ariadne_core.application.identity_discovery_tools import (
    InvestigationToolBroker,
    PageHttpTransport,
    ToolExecution,
)
from ariadne_core.application.public_discovery import PublicDiscoveryService
from ariadne_core.application.vault import VaultManager, VaultSubkeyPurpose
from ariadne_core.domain.public_discovery import normalise_public_result_url
from ariadne_core.infrastructure.db.identity_discovery_repository import (
    FrontierTaskRecord,
    IdentityDiscoveryRepository,
)
from ariadne_core.infrastructure.db.repositories import RevisionConflict, SettingsRepository
from ariadne_core.local_ai import (
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIHttpTransport,
    LocalAIWorkspaceTask,
    WorkspaceAnalysisRequest,
)


class IdentityDiscoveryUnavailable(RuntimeError):
    """The vault-backed discovery workspace cannot currently be used."""


class IdentityDiscoveryNotFound(LookupError):
    """The requested person, audit, or proposal does not exist in this scope."""


class IdentityDiscoveryConflict(RuntimeError):
    """The requested mutation conflicts with current durable state."""


class IdentityDiscoveryCoordinator:
    """Coordinate bounded tool calls while the repository owns all durable truth.

    The process-local lock prevents overlapping batches in this sidecar; task
    revisions remain the cross-request correctness boundary. Profile scoping and
    vault availability are rechecked for every operation.
    """

    def __init__(
        self,
        vault: VaultManager,
        *,
        public_discovery: PublicDiscoveryService,
        page_transport: PageHttpTransport | None = None,
        local_ai_transport: LocalAIHttpTransport | None = None,
    ) -> None:
        self._vault = vault
        self._public_discovery = public_discovery
        self._page_transport = page_transport
        self._local_ai_transport = local_ai_transport
        self._execution_lock = RLock()

    def workspace(self, body: PersonWorkspaceRequest) -> PersonWorkspace:
        """Return a bounded projection of one persistent person workspace."""

        try:
            with self._repository() as repository:
                return _workspace(repository.person_workspace(self._vault_id, body.profile_id))
        except LookupError as error:
            raise IdentityDiscoveryNotFound("person workspace is unavailable") from error
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("person workspace failed validation") from error

    def update_person(self, body: PersonUpdateRequest) -> PersonWorkspace:
        """Apply one optimistic person/details update and return the committed view."""

        try:
            with self._repository() as repository:
                repository.update_person(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    expected_profile_revision=body.expected_profile_revision,
                    expected_details_revision=body.expected_details_revision,
                    display_name=body.display_name,
                    purpose=body.purpose,
                    notes=body.notes,
                    tags=body.tags,
                )
                return _workspace(repository.person_workspace(self._vault_id, body.profile_id))
        except LookupError as error:
            raise IdentityDiscoveryNotFound("person workspace is unavailable") from error
        except RevisionConflict as error:
            raise IdentityDiscoveryConflict("person workspace revision is stale") from error
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("person workspace update failed") from error

    def add_source(self, body: PersonSourceCreateRequest) -> PersonWorkspace:
        """Normalize and idempotently retain one explicitly authorized public source."""

        if not body.authorized_self_audit:
            raise IdentityDiscoveryConflict("self-audit authorization is required")
        try:
            url = normalise_public_result_url(body.url)
            with self._repository() as repository:
                repository.add_source(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    source_type=body.source_type.value,
                    url=url,
                    title=body.title,
                    notes=body.notes,
                )
                return _workspace(repository.person_workspace(self._vault_id, body.profile_id))
        except LookupError as error:
            raise IdentityDiscoveryNotFound("person workspace is unavailable") from error
        except (RevisionConflict, RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("person source could not be saved") from error

    def create_audit(self, body: AuditCreateRequest) -> AuditDetail:
        """Snapshot settings and atomically create the run, seed leads, and frontier."""

        if not body.authorized_self_audit:
            raise IdentityDiscoveryConflict("self-audit authorization is required")
        try:
            settings = SettingsRepository(self._vault.engine).get(self._vault_id).values
            use_local_ai = body.use_local_ai and settings.local_ai_enabled
            selected_model = settings.local_ai_selected_model if use_local_ai else None
            with self._repository() as repository:
                seeds = repository.build_seed_tasks(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    provider_ids=body.provider_ids,
                    mode=body.mode.value,
                )
                audit_id = repository.create_audit(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    name=body.name,
                    mode=body.mode.value,
                    provider_ids=body.provider_ids,
                    use_local_ai=use_local_ai,
                    selected_model=selected_model,
                    max_depth=body.max_depth,
                    request_budget=body.request_budget,
                    time_budget_seconds=body.time_budget_seconds,
                    cost_budget_micros=body.cost_budget_micros,
                    seeds=seeds,
                )
                return _audit_detail(
                    body.profile_id,
                    repository.audit_detail(self._vault_id, body.profile_id, audit_id),
                )
        except LookupError as error:
            raise IdentityDiscoveryNotFound("person workspace is unavailable") from error
        except (RevisionConflict, RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("identity audit could not be created") from error

    def audit_detail(self, body: AuditExecuteRequest) -> AuditDetail:
        """Read durable audit state without executing or implicitly resuming work."""

        try:
            with self._repository() as repository:
                return _audit_detail(
                    body.profile_id,
                    repository.audit_detail(self._vault_id, body.profile_id, body.audit_id),
                )
        except LookupError as error:
            raise IdentityDiscoveryNotFound("identity audit is unavailable") from error
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("identity audit failed validation") from error

    def execute_batch(self, body: AuditExecuteRequest) -> AuditDetail:
        """Execute one bounded parallel batch; callers explicitly request each batch.

        Claimed tasks are committed before provider I/O. Every completed attempt
        then records results/proposals, frontier expansion, task state, and a tool
        receipt transactionally before progress is recomputed.
        """

        with self._execution_lock:
            try:
                with self._repository() as repository:
                    tasks = repository.claim_tasks(
                        self._vault_id,
                        body.profile_id,
                        body.audit_id,
                        maximum=body.maximum_tasks,
                    )
                    broker = InvestigationToolBroker(
                        public_discovery=self._public_discovery,
                        page_transport=self._page_transport,
                    )
                    executions = self._execute_tools(broker, tasks)
                    for task, execution in zip(tasks, executions, strict=True):
                        if task.task_type in {
                            "SEARCH_WEB",
                            "SEARCH_USERNAME",
                            "QUERY_GITHUB",
                            "QUERY_REGISTRY",
                            "QUERY_ARCHIVE",
                            "QUERY_CERTIFICATE_TRANSPARENCY",
                        }:
                            repository.record_search_outcome(
                                task,
                                state=execution.state,
                                reason=execution.reason,
                                results=execution.search_results,
                            )
                        else:
                            repository.record_fetch_outcome(
                                task,
                                state=execution.state,
                                reason=execution.reason,
                                page=execution.page,
                            )
                    # The model stage runs on the next empty batch. Returning
                    # the final deterministic checkpoint first keeps Qwen's
                    # cold-start latency out of the search request and lets the
                    # UI show an explicit, recoverable AI-analysis phase.
                    if not tasks:
                        self._run_local_ai_if_ready(repository, body)
                    repository.refresh_audit(self._vault_id, body.profile_id, body.audit_id)
                    return _audit_detail(
                        body.profile_id,
                        repository.audit_detail(self._vault_id, body.profile_id, body.audit_id),
                    )
            except LookupError as error:
                raise IdentityDiscoveryNotFound("identity audit is unavailable") from error
            except RevisionConflict as error:
                raise IdentityDiscoveryConflict("identity audit state changed") from error
            except (RuntimeError, ValueError, TypeError, KeyError) as error:
                raise IdentityDiscoveryConflict("identity audit batch failed") from error

    def control_audit(self, body: AuditControlRequest) -> AuditDetail:
        """Apply an optimistic pause, resume, or cancel transition."""

        try:
            with self._execution_lock, self._repository() as repository:
                repository.control_audit(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    audit_id=body.audit_id,
                    expected_revision=body.expected_revision,
                    action=body.action.value,
                )
                return _audit_detail(
                    body.profile_id,
                    repository.audit_detail(self._vault_id, body.profile_id, body.audit_id),
                )
        except LookupError as error:
            raise IdentityDiscoveryNotFound("identity audit is unavailable") from error
        except RevisionConflict as error:
            raise IdentityDiscoveryConflict("identity audit revision is stale") from error
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("identity audit control failed") from error

    def decide_proposal(self, body: ProposalDecisionRequest) -> AuditDetail:
        """Record human review; only SEARCH_DEEPER schedules additional work."""

        try:
            with self._repository() as repository:
                repository.decide_proposal(
                    vault_id=self._vault_id,
                    profile_id=body.profile_id,
                    audit_id=body.audit_id,
                    proposal_id=body.proposal_id,
                    expected_revision=body.expected_revision,
                    decision=body.decision.value,
                )
                return _audit_detail(
                    body.profile_id,
                    repository.audit_detail(self._vault_id, body.profile_id, body.audit_id),
                )
        except LookupError as error:
            raise IdentityDiscoveryNotFound("identity proposal is unavailable") from error
        except RevisionConflict as error:
            raise IdentityDiscoveryConflict("identity proposal revision is stale") from error
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            raise IdentityDiscoveryConflict("identity proposal decision failed") from error

    @property
    def _vault_id(self) -> str:
        if not self._vault.is_unlocked:
            raise IdentityDiscoveryUnavailable("identity discovery requires an unlocked vault")
        return self._vault.manifest.vault_id

    @contextmanager
    def _repository(self) -> Iterator[IdentityDiscoveryRepository]:
        """Lease the scoped fingerprint subkey only for one repository operation."""

        if not self._vault.is_unlocked:
            raise IdentityDiscoveryUnavailable("identity discovery requires an unlocked vault")
        with self._vault.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as key:
            repository = IdentityDiscoveryRepository(self._vault.engine, fingerprint_key=key)
            try:
                yield repository
            finally:
                repository.close()

    @staticmethod
    def _execute_tools(
        broker: InvestigationToolBroker,
        tasks: tuple[FrontierTaskRecord, ...],
    ) -> tuple[ToolExecution, ...]:
        """Bound parallelism independently from the request's task-count limit."""

        if not tasks:
            return ()
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as executor:
            return tuple(executor.map(broker.execute, tasks))

    def _run_local_ai_if_ready(
        self,
        repository: IdentityDiscoveryRepository,
        body: AuditExecuteRequest,
    ) -> None:
        """Run one selected loopback model after the deterministic frontier is exhausted."""

        projection = repository.prepare_ai_projection(
            self._vault_id, body.profile_id, body.audit_id
        )
        if projection is None:
            return
        citations = cast(tuple[dict[str, str], ...], projection["citations"])
        references = cast(tuple[str, ...], projection["references"])
        selected_model = str(projection["selected_model"])
        if not references:
            repository.record_ai_analysis(
                vault_id=self._vault_id,
                profile_id=body.profile_id,
                audit_id=body.audit_id,
                status="EMPTY",
                result_code="NO_PUBLIC_RESULTS",
                provider=None,
                model_id=None,
                engine_version=None,
                analysis=_fallback_ai_analysis(
                    citations, "No public results were available to analyse."
                ),
            )
            return
        settings = SettingsRepository(self._vault.engine).get(self._vault_id).values
        if not settings.local_ai_enabled or settings.local_ai_selected_model != selected_model:
            repository.record_ai_analysis(
                vault_id=self._vault_id,
                profile_id=body.profile_id,
                audit_id=body.audit_id,
                status="FALLBACK",
                result_code="LOCAL_AI_CONFIGURATION_CHANGED",
                provider=None,
                model_id=None,
                engine_version=None,
                analysis=_fallback_ai_analysis(
                    citations,
                    "The selected local model was unavailable or changed after this audit started.",
                ),
            )
            return
        try:
            result = LocalAIClient(
                LocalAIConfig(
                    enabled=True,
                    provider=settings.local_ai_provider,
                    endpoint=settings.local_ai_endpoint,
                    timeout_seconds=120,
                    max_output_tokens=2_048,
                ),
                transport=self._local_ai_transport,
            ).analyze_workspace(
                WorkspaceAnalysisRequest(
                    task=LocalAIWorkspaceTask.CONNECTIONS,
                    profile_data_json=str(projection["canonical_json"]),
                    allowed_reference_ids=references,
                ),
                model_id=selected_model,
            )
        except (LocalAIError, ValueError) as error:
            code = error.code.value if isinstance(error, LocalAIError) else "INVALID_RESPONSE"
            repository.record_ai_analysis(
                vault_id=self._vault_id,
                profile_id=body.profile_id,
                audit_id=body.audit_id,
                status="FALLBACK",
                result_code=code,
                provider=None,
                model_id=None,
                engine_version=None,
                analysis=_fallback_ai_analysis(
                    citations,
                    "Local model analysis did not complete; deterministic source "
                    "organization remains available.",
                ),
            )
            return
        insights: list[dict[str, object]] = []
        for fact in result.facts:
            insights.append(
                {
                    "kind": "FACT",
                    "statement": fact.statement,
                    "rationale": "Source-grounded model observation; human review required.",
                    "confidence": fact.confidence.value,
                    "evidenceRefs": fact.evidence_refs,
                }
            )
        for connection in result.connections:
            insights.append(
                {
                    "kind": "CONNECTION",
                    "statement": connection.relationship,
                    "rationale": connection.rationale,
                    "confidence": connection.confidence.value,
                    "evidenceRefs": connection.supporting_refs,
                }
            )
            insights.append(
                {
                    "kind": "NEXT_STEP",
                    "statement": connection.verification_suggestion,
                    "rationale": (
                        "The local model proposed this bounded follow-up for a "
                        "source-grounded possible correlation."
                    ),
                    "confidence": None,
                    "evidenceRefs": connection.supporting_refs,
                }
            )
        for step in result.next_steps:
            insights.append(
                {
                    "kind": "NEXT_STEP",
                    "statement": step.suggestion,
                    "rationale": step.rationale,
                    "confidence": None,
                    "evidenceRefs": step.supporting_refs,
                }
            )
        repository.record_ai_analysis(
            vault_id=self._vault_id,
            profile_id=body.profile_id,
            audit_id=body.audit_id,
            status="SUCCEEDED",
            result_code="MODEL_ANALYSIS_SUCCEEDED",
            provider=result.provider.value,
            model_id=result.model_id,
            engine_version=result.engine_version,
            analysis={
                "title": result.title,
                "summary": result.summary,
                "insights": insights[:MAX_AI_INSIGHTS],
                "citations": citations[:MAX_AI_CITATIONS],
                "limitations": result.limitations[:32],
            },
        )


def _workspace(raw: dict[str, object]) -> PersonWorkspace:
    """Validate repository rows into the capped public workspace contract."""

    profile = _row(raw["profile"])
    details_value = raw["details"]
    details = None if details_value is None else _row(details_value)
    counts = _row(raw["counts"])
    source_rows = cast(tuple[RowMapping, ...], raw["sources"])
    audit_rows = cast(tuple[RowMapping, ...], raw["audits"])
    audit_state_counts = cast(dict[str, dict[str, int]], raw["audit_state_counts"])
    return PersonWorkspace(
        person=PersonDetails(
            profile_id=str(profile["id"]),
            display_name=str(profile["display_label"]),
            purpose=str(profile["purpose"]),
            status=str(profile["status"]),
            notes="" if details is None else str(details["notes"]),
            tags=() if details is None else _json_tuple(details["tags_json"]),
            profile_revision=int(profile["revision"]),
            details_revision=0 if details is None else int(details["revision"]),
            identity_count=int(counts["identity_count"]),
            source_count=int(counts["source_count"]),
            audit_count=int(counts["audit_count"]),
            unresolved_proposal_count=int(counts["proposal_count"]),
        ),
        sources=tuple(_source(row) for row in source_rows[:MAX_SOURCES]),
        audits=tuple(
            _audit_summary(row, audit_state_counts.get(str(row["id"]), {}))
            for row in audit_rows[:MAX_AUDITS]
        ),
        has_more_sources=len(source_rows) > MAX_SOURCES,
        has_more_audits=len(audit_rows) > MAX_AUDITS,
    )


def _audit_detail(profile_id: str, raw: dict[str, object]) -> AuditDetail:
    """Validate and cap every growing audit collection at the API boundary."""

    audit = _row(raw["audit"])
    task_rows = cast(tuple[RowMapping, ...], raw["tasks"])
    result_rows = cast(tuple[RowMapping, ...], raw["results"])
    lead_rows = cast(tuple[RowMapping, ...], raw["leads"])
    proposal_rows = cast(tuple[RowMapping, ...], raw["proposals"])
    receipt_rows = cast(tuple[RowMapping, ...], raw["receipts"])
    ai_row_value = raw["ai_analysis"]
    ai_row = None if ai_row_value is None else _row(ai_row_value)
    state_counts = cast(dict[str, int], raw["state_counts"])
    return AuditDetail(
        profile_id=profile_id,
        audit=_audit_summary(audit, state_counts),
        tasks=tuple(_task(row) for row in task_rows[:MAX_TASKS]),
        results=tuple(_result(row) for row in result_rows[:MAX_RESULTS]),
        leads=tuple(_lead(row) for row in lead_rows[:MAX_LEADS]),
        proposals=tuple(_proposal(row) for row in proposal_rows[:MAX_PROPOSALS]),
        receipts=tuple(_receipt(row) for row in receipt_rows[:MAX_RECEIPTS]),
        ai_analysis=None if ai_row is None else _ai_analysis(ai_row),
        has_more_tasks=len(task_rows) > MAX_TASKS,
        has_more_results=len(result_rows) > MAX_RESULTS,
        has_more_leads=len(lead_rows) > MAX_LEADS,
        has_more_proposals=len(proposal_rows) > MAX_PROPOSALS,
        has_more_receipts=len(receipt_rows) > MAX_RECEIPTS,
    )


def _fallback_ai_analysis(
    citations: tuple[dict[str, str], ...], limitation: str
) -> dict[str, object]:
    """Return honest deterministic organization when the selected model cannot run."""

    cited = tuple(item["referenceId"] for item in citations[:8])
    insights: tuple[dict[str, object], ...] = ()
    if cited:
        insights = (
            {
                "kind": "NEXT_STEP",
                "statement": (
                    "Review the highest-ranked exact sources and confirm ownership manually."
                ),
                "rationale": (
                    "Deterministic fallback cannot infer identity ownership or relationships."
                ),
                "confidence": None,
                "evidenceRefs": cited,
            },
        )
    return {
        "title": "Deterministic source review",
        "summary": f"Ariadne retained {len(citations)} exact public result sources for review.",
        "insights": insights,
        "citations": citations[:MAX_AI_CITATIONS],
        "limitations": (limitation,),
    }


def _ai_analysis(row: RowMapping) -> AuditAIAnalysis:
    content = json.loads(str(row["analysis_json"]))
    title = _normalise_ai_text(content.get("title"), 500)
    summary = _normalise_ai_text(content.get("summary"), 4_000)
    limitations = tuple(
        value
        for item in content.get("limitations", ())[:32]
        if (value := _normalise_ai_text(item, 2_000))
    )
    insights: list[AIAnalysisInsight] = []
    for item in content.get("insights", ())[:MAX_AI_INSIGHTS]:
        statement = _normalise_ai_text(item.get("statement"), 2_000)
        if not statement:
            continue
        rationale = _normalise_ai_text(item.get("rationale"), 2_000)
        insights.append(
            AIAnalysisInsight(
                kind=AIInsightKind(str(item["kind"])),
                statement=statement,
                rationale=rationale,
                confidence=None if item.get("confidence") is None else str(item["confidence"]),
                evidence_refs=tuple(str(value) for value in item.get("evidenceRefs", ())),
            )
        )
    return AuditAIAnalysis(
        analysis_id=str(row["id"]),
        status=AIAnalysisStatus(str(row["status"])),
        result_code=str(row["result_code"]),
        provider=_normalise_optional_ai_label(row["provider"], 64),
        model_id=_normalise_optional_ai_label(row["model_id"], 256),
        engine_version=_normalise_optional_ai_label(row["engine_version"], 64),
        title=title or "Local analysis",
        summary=(
            summary
            or "No additional model summary was retained; review the cited source results directly."
        ),
        insights=tuple(insights),
        citations=tuple(
            AIAnalysisCitation(
                reference_id=str(item["referenceId"]),
                result_id=str(item["resultId"]),
                url=str(item["url"]),
                title=str(item["title"]),
            )
            for item in content.get("citations", ())[:MAX_AI_CITATIONS]
        ),
        limitations=limitations,
        created_at_us=int(row["created_at_us"]),
    )


def _normalise_ai_text(value: object, maximum: int) -> str:
    """Make stored model prose compatible with the native display contract."""

    text = "" if value is None else str(value)
    text = "".join(
        character
        for character in text
        if character in {"\n", "\t"} or unicodedata.category(character) != "Cc"
    ).strip()
    return text[:maximum].rstrip()


def _normalise_optional_ai_label(value: object, maximum: int) -> str | None:
    """Bound optional provider metadata without inventing a missing label."""

    text = _normalise_ai_text(value, maximum).replace("\n", "").replace("\t", "")
    return text or None


def _source(row: RowMapping) -> PersonSource:
    return PersonSource(
        source_id=str(row["id"]),
        source_type=SourceType(str(row["source_type"])),
        url=str(row["canonical_url"]),
        title=None if row["title"] is None else str(row["title"]),
        notes=str(row["notes"]),
        relationship_state=str(row["relationship_state"]),
        parent_source_id=(
            None if row["parent_source_id"] is None else str(row["parent_source_id"])
        ),
        first_seen_at_us=int(row["first_seen_at_us"]),
        last_checked_at_us=(
            None if row["last_checked_at_us"] is None else int(row["last_checked_at_us"])
        ),
        http_status=None if row["http_status"] is None else int(row["http_status"]),
        revision=int(row["revision"]),
    )


def _audit_summary(row: RowMapping, counts: Mapping[str, int]) -> AuditSummary:
    return AuditSummary(
        audit_id=str(row["id"]),
        name=str(row["name"]),
        mode=AuditMode(str(row["mode"])),
        state=AuditState(str(row["state"])),
        stage=AuditStage(str(row["stage"])),
        provider_ids=_json_tuple(row["provider_ids_json"]),
        use_local_ai=bool(row["use_local_ai"]),
        selected_model=None if row["selected_model"] is None else str(row["selected_model"]),
        max_depth=int(row["max_depth"]),
        request_budget=int(row["request_budget"]),
        total_tasks=int(row["total_tasks"]),
        terminal_tasks=int(row["terminal_tasks"]),
        result_count=int(row["result_count"]),
        lead_count=int(row["lead_count"]),
        proposal_count=int(row["proposal_count"]),
        progress_micros=int(row["progress_micros"]),
        stop_reason=None if row["stop_reason"] is None else str(row["stop_reason"]),
        task_states=tuple(
            TaskStateCount(state=FrontierTaskState(state), count=count)
            for state, count in sorted(counts.items())
        ),
        started_at_us=None if row["started_at_us"] is None else int(row["started_at_us"]),
        finished_at_us=(None if row["finished_at_us"] is None else int(row["finished_at_us"])),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
        revision=int(row["revision"]),
    )


def _task(row: RowMapping) -> FrontierTaskSummary:
    return FrontierTaskSummary(
        task_id=str(row["id"]),
        lead_id=None if row["lead_id"] is None else str(row["lead_id"]),
        parent_task_id=None if row["parent_task_id"] is None else str(row["parent_task_id"]),
        task_type=FrontierTaskType(str(row["task_type"])),
        provider_id=str(row["provider_id"]),
        masked_payload=str(row["masked_payload"]),
        priority=int(row["priority"]),
        information_gain_micros=int(row["information_gain_micros"]),
        depth=int(row["depth"]),
        state=FrontierTaskState(str(row["state"])),
        attempt_count=int(row["attempt_count"]),
        retry_limit=int(row["retry_limit"]),
        result_count=int(row["result_count"]),
        stop_reason=None if row["stop_reason"] is None else str(row["stop_reason"]),
        revision=int(row["revision"]),
    )


def _result(row: RowMapping) -> DiscoveryResult:
    return DiscoveryResult(
        result_id=str(row["id"]),
        task_id=str(row["task_id"]),
        provider_id=str(row["provider_id"]),
        rank=int(row["rank"]),
        category=str(row["category"]),
        url=str(row["canonical_url"]),
        title=str(row["title"]),
        snippet=str(row["snippet"]),
        observed_at_us=int(row["observed_at_us"]),
        review_state=str(row["review_state"]),
    )


def _lead(row: RowMapping) -> DiscoveryLead:
    return DiscoveryLead(
        lead_id=str(row["id"]),
        parent_lead_id=(None if row["parent_lead_id"] is None else str(row["parent_lead_id"])),
        source_id=None if row["source_id"] is None else str(row["source_id"]),
        lead_type=str(row["lead_type"]),
        display_value=str(row["display_value"]),
        source_url=None if row["source_url"] is None else str(row["source_url"]),
        provider_id=str(row["provider_id"]),
        depth=int(row["depth"]),
        supporting_signals=_json_tuple(row["supporting_signals_json"]),
        contradictions=_json_tuple(row["contradictions_json"]),
        confidence_micros=int(row["confidence_micros"]),
        ownership_state=str(row["ownership_state"]),
        temporal_state=str(row["temporal_state"]),
        review_state=str(row["review_state"]),
        expansion_state=str(row["expansion_state"]),
    )


def _proposal(row: RowMapping) -> KnowledgeProposal:
    return KnowledgeProposal(
        proposal_id=str(row["id"]),
        lead_id=str(row["lead_id"]),
        entity_type=str(row["entity_type"]),
        display_value=str(row["display_value"]),
        source_url=str(row["source_url"]),
        source_span_start=(
            None if row["source_span_start"] is None else int(row["source_span_start"])
        ),
        source_span_end=None if row["source_span_end"] is None else int(row["source_span_end"]),
        supporting_signals=_json_tuple(row["supporting_signals_json"]),
        contradictions=_json_tuple(row["contradictions_json"]),
        confidence_micros=int(row["confidence_micros"]),
        temporal_state=str(row["temporal_state"]),
        review_state=str(row["review_state"]),
        recommended_actions=_json_tuple(row["recommended_actions_json"]),
        model_provider=None if row["model_provider"] is None else str(row["model_provider"]),
        model_id=None if row["model_id"] is None else str(row["model_id"]),
        revision=int(row["revision"]),
    )


def _receipt(row: RowMapping) -> ToolReceipt:
    return ToolReceipt(
        receipt_id=str(row["id"]),
        task_id=None if row["task_id"] is None else str(row["task_id"]),
        tool_name=FrontierTaskType(str(row["tool_name"])),
        authorization_state=str(row["authorization_state"]),
        execution_state=str(row["execution_state"]),
        result_code=str(row["result_code"]),
        result_count=int(row["result_count"]),
        model_provider=None if row["model_provider"] is None else str(row["model_provider"]),
        model_id=None if row["model_id"] is None else str(row["model_id"]),
        started_at_us=int(row["started_at_us"]),
        finished_at_us=int(row["finished_at_us"]),
    )


def _row(value: object) -> RowMapping:
    if not isinstance(value, Mapping):
        raise TypeError("repository row is invalid")
    return cast(RowMapping, value)


def _json_tuple(value: object) -> tuple[str, ...]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("persisted JSON list is invalid")
    return tuple(decoded)
