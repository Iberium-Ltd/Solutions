"""Persistence for people, recursive audit runs, and exact discovery chains.

The repository is the scheduler's source of truth: seed knowledge becomes a
bounded frontier, claimed tasks transition by revision, and each provider
outcome atomically records its results, derived leads/proposals, task status,
and execution receipt. All queries remain vault/profile scoped; keyed HMACs
provide equality and cycle suppression without exposing raw values as indexes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import MetaData, Table, and_, func, insert, or_, select, update
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from ariadne_core.infrastructure.db.repositories import RevisionConflict, now_us

TERMINAL_TASK_STATES = frozenset(
    {
        "SUCCEEDED_EMPTY",
        "SUCCEEDED_RESULTS",
        "BLOCKED",
        "RATE_LIMITED",
        "AUTH_REQUIRED",
        "FAILED_TERMINAL",
        "SKIPPED",
        "CANCELLED",
        "REVIEW_REQUIRED",
        "REVIEWED",
        "SAVED",
    }
)
ACTIVE_AUDIT_STATES = frozenset({"READY", "RUNNING"})


@dataclass(frozen=True, slots=True)
class SeedTask:
    """Pre-persistence work derived from already reviewed person knowledge."""

    task_type: str
    provider_id: str
    payload: str = field(repr=False)
    masked_payload: str
    lead_type: str
    lead_display: str
    lead_value_hmac: str
    source_id: str | None = None
    initial_state: str = "READY"
    priority: int = 70
    information_gain_micros: int = 700_000


@dataclass(frozen=True, slots=True)
class FrontierTaskRecord:
    """One claimed task snapshot; its revision is required to commit the outcome."""

    id: str
    vault_id: str
    profile_id: str
    audit_id: str
    lead_id: str | None
    parent_task_id: str | None
    task_type: str
    provider_id: str
    payload: str = field(repr=False)
    payload_hmac: str
    masked_payload: str
    priority: int
    information_gain_micros: int
    depth: int
    state: str
    attempt_count: int
    retry_limit: int
    revision: int
    started_at_us: int


@dataclass(frozen=True, slots=True)
class SearchResultDraft:
    """Normalized transient provider result accepted by the persistence boundary."""

    provider_id: str
    rank: int
    category: str
    url: str
    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class ExtractedProposalDraft:
    """Source-grounded candidate that must not enter canonical entities implicitly."""

    entity_type: str
    canonical_value: str = field(repr=False)
    display_value: str
    source_url: str
    source_span_start: int | None
    source_span_end: int | None
    confidence_micros: int
    supporting_signals: tuple[str, ...] = ("PUBLIC_SOURCE_EXTRACTION",)
    contradictions: tuple[str, ...] = ()
    model_provider: str | None = None
    model_id: str | None = None


@dataclass(frozen=True, slots=True)
class FetchedPageDraft:
    """Bounded public-page projection; original network bytes are not persisted here."""

    url: str
    title: str
    text_excerpt: str
    content_sha256: str
    http_status: int
    category: str
    links: tuple[str, ...]
    proposals: tuple[ExtractedProposalDraft, ...]


class IdentityDiscoveryRepository:
    """Keep every recursive state transition profile-scoped and transactional.

    A repository instance owns a short-lived fingerprint-key copy. Callers must
    close it after the operation so future equality checks require a fresh vault
    subkey lease.
    """

    def __init__(self, engine: Engine, *, fingerprint_key: bytes | bytearray) -> None:
        self.engine = engine
        self._key = bytes(fingerprint_key)
        metadata = MetaData()
        names = (
            "profiles",
            "settings",
            "entities",
            "identity_people",
            "identity_sources",
            "identity_audit_runs",
            "identity_leads",
            "identity_frontier_tasks",
            "identity_results",
            "identity_proposals",
            "identity_tool_receipts",
            "identity_ai_analyses",
            "identity_entity_origins",
        )
        tables = {name: Table(name, metadata, autoload_with=engine) for name in names}
        self.profiles = tables["profiles"]
        self.settings = tables["settings"]
        self.entities = tables["entities"]
        self.people = tables["identity_people"]
        self.sources = tables["identity_sources"]
        self.audits = tables["identity_audit_runs"]
        self.leads = tables["identity_leads"]
        self.tasks = tables["identity_frontier_tasks"]
        self.results = tables["identity_results"]
        self.proposals = tables["identity_proposals"]
        self.receipts = tables["identity_tool_receipts"]
        self.ai_analyses = tables["identity_ai_analyses"]
        self.entity_origins = tables["identity_entity_origins"]

    def close(self) -> None:
        """Drop the repository's immutable key copy when its scoped lease ends."""

        self._key = bytes(len(self._key))

    def fingerprint(self, value: str) -> str:
        """Create a vault-scoped equality token; never use it as user-facing evidence."""

        return hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def require_profile(self, vault_id: str, profile_id: str) -> RowMapping:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.profiles).where(
                        and_(
                            self.profiles.c.vault_id == vault_id,
                            self.profiles.c.id == profile_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError("person is unavailable")
        return row

    def person_workspace(self, vault_id: str, profile_id: str) -> dict[str, object]:
        """Read bounded collections plus exact totals for one profile projection."""

        profile = self.require_profile(vault_id, profile_id)
        with self.engine.connect() as connection:
            details = (
                connection.execute(
                    select(self.people).where(
                        and_(
                            self.people.c.vault_id == vault_id,
                            self.people.c.profile_id == profile_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            source_rows = tuple(
                connection.execute(
                    select(self.sources)
                    .where(
                        and_(
                            self.sources.c.vault_id == vault_id,
                            self.sources.c.profile_id == profile_id,
                        )
                    )
                    .order_by(self.sources.c.first_seen_at_us.desc())
                    .limit(201)
                ).mappings()
            )
            audit_rows = tuple(
                connection.execute(
                    select(self.audits)
                    .where(
                        and_(
                            self.audits.c.vault_id == vault_id,
                            self.audits.c.profile_id == profile_id,
                        )
                    )
                    .order_by(self.audits.c.created_at_us.desc())
                    .limit(65)
                ).mappings()
            )
            counts = (
                connection.execute(
                    select(
                        select(func.count())
                        .select_from(self.entities)
                        .where(
                            and_(
                                self.entities.c.vault_id == vault_id,
                                self.entities.c.profile_id == profile_id,
                                self.entities.c.deleted_at_us.is_(None),
                            )
                        )
                        .scalar_subquery()
                        .label("identity_count"),
                        select(func.count())
                        .select_from(self.sources)
                        .where(
                            and_(
                                self.sources.c.vault_id == vault_id,
                                self.sources.c.profile_id == profile_id,
                            )
                        )
                        .scalar_subquery()
                        .label("source_count"),
                        select(func.count())
                        .select_from(self.audits)
                        .where(
                            and_(
                                self.audits.c.vault_id == vault_id,
                                self.audits.c.profile_id == profile_id,
                            )
                        )
                        .scalar_subquery()
                        .label("audit_count"),
                        select(func.count())
                        .select_from(self.proposals)
                        .where(
                            and_(
                                self.proposals.c.vault_id == vault_id,
                                self.proposals.c.profile_id == profile_id,
                                self.proposals.c.review_state == "UNREVIEWED",
                            )
                        )
                        .scalar_subquery()
                        .label("proposal_count"),
                    )
                )
                .mappings()
                .one()
            )
            audit_state_counts: dict[str, dict[str, int]] = {}
            for row in connection.execute(
                select(
                    self.tasks.c.audit_id,
                    self.tasks.c.state,
                    func.count().label("count"),
                )
                .where(
                    and_(
                        self.tasks.c.vault_id == vault_id,
                        self.tasks.c.profile_id == profile_id,
                    )
                )
                .group_by(self.tasks.c.audit_id, self.tasks.c.state)
            ).mappings():
                audit_state_counts.setdefault(str(row["audit_id"]), {})[str(row["state"])] = int(
                    row["count"]
                )
        return {
            "profile": profile,
            "details": details,
            "sources": source_rows,
            "audits": audit_rows,
            "counts": counts,
            "audit_state_counts": audit_state_counts,
        }

    def update_person(
        self,
        *,
        vault_id: str,
        profile_id: str,
        expected_profile_revision: int,
        expected_details_revision: int,
        display_name: str,
        purpose: str,
        notes: str,
        tags: tuple[str, ...],
    ) -> None:
        """Update profile and extended details atomically with two revision guards."""

        timestamp = now_us()
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(self.profiles)
                .where(
                    and_(
                        self.profiles.c.vault_id == vault_id,
                        self.profiles.c.id == profile_id,
                        self.profiles.c.revision == expected_profile_revision,
                    )
                )
                .values(
                    display_label=display_name,
                    purpose=purpose,
                    updated_at_us=timestamp,
                    revision=expected_profile_revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("person profile revision conflict")
            if expected_details_revision == 0:
                try:
                    connection.execute(
                        insert(self.people).values(
                            vault_id=vault_id,
                            profile_id=profile_id,
                            notes=notes,
                            tags_json=_json(tags),
                            created_at_us=timestamp,
                            updated_at_us=timestamp,
                            revision=1,
                        )
                    )
                except IntegrityError as error:
                    raise RevisionConflict("person details revision conflict") from error
            else:
                changed = connection.execute(
                    update(self.people)
                    .where(
                        and_(
                            self.people.c.vault_id == vault_id,
                            self.people.c.profile_id == profile_id,
                            self.people.c.revision == expected_details_revision,
                        )
                    )
                    .values(
                        notes=notes,
                        tags_json=_json(tags),
                        updated_at_us=timestamp,
                        revision=expected_details_revision + 1,
                    )
                )
                if changed.rowcount != 1:
                    raise RevisionConflict("person details revision conflict")

    def add_source(
        self,
        *,
        vault_id: str,
        profile_id: str,
        source_type: str,
        url: str,
        title: str | None,
        notes: str,
    ) -> str:
        """Insert one canonical URL idempotently under its keyed fingerprint."""

        self.require_profile(vault_id, profile_id)
        url_hmac = self.fingerprint(url)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(self.sources.c.id).where(
                    and_(
                        self.sources.c.vault_id == vault_id,
                        self.sources.c.profile_id == profile_id,
                        self.sources.c.url_hmac == url_hmac,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            source_id = str(uuid7())
            timestamp = now_us()
            connection.execute(
                insert(self.sources).values(
                    id=source_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    source_type=source_type,
                    canonical_url=url,
                    url_hmac=url_hmac,
                    title=title,
                    notes=notes,
                    relationship_state="UNREVIEWED",
                    parent_source_id=None,
                    first_seen_at_us=timestamp,
                    last_checked_at_us=None,
                    content_sha256=None,
                    http_status=None,
                    revision=1,
                )
            )
            return source_id

    def build_seed_tasks(
        self,
        *,
        vault_id: str,
        profile_id: str,
        provider_ids: tuple[str, ...],
        mode: str,
    ) -> tuple[SeedTask, ...]:
        """Derive eligible, mode-aware work without mutating audit state.

        Only reviewed searchable entities and non-unrelated sources seed normal
        runs. Incremental modes suppress prior successes; retry mode reconstructs
        only failed/blocked work for the selected providers.
        """

        self.require_profile(vault_id, profile_id)
        seeds: list[SeedTask] = []
        with self.engine.connect() as connection:
            if mode == "FAILED_AND_BLOCKED_RETRY":
                previous = tuple(
                    connection.execute(
                        select(self.tasks)
                        .where(
                            and_(
                                self.tasks.c.vault_id == vault_id,
                                self.tasks.c.profile_id == profile_id,
                                self.tasks.c.state.in_(
                                    (
                                        "BLOCKED",
                                        "RATE_LIMITED",
                                        "FAILED_RETRYABLE",
                                        "FAILED_TERMINAL",
                                    )
                                ),
                            )
                        )
                        .order_by(self.tasks.c.updated_at_us.desc())
                        .limit(500)
                    ).mappings()
                )
                return tuple(
                    SeedTask(
                        task_type=str(row["task_type"]),
                        provider_id=str(row["provider_id"]),
                        payload=str(row["payload_text"]),
                        masked_payload=str(row["masked_payload"]),
                        lead_type="RETRY",
                        lead_display=str(row["masked_payload"]),
                        lead_value_hmac=str(row["payload_hmac"]),
                        priority=min(100, int(row["priority"]) + 5),
                        information_gain_micros=int(row["information_gain_micros"]),
                    )
                    for row in previous
                    if str(row["provider_id"]) in provider_ids
                )
            entity_rows = tuple(
                connection.execute(
                    select(self.entities).where(
                        and_(
                            self.entities.c.vault_id == vault_id,
                            self.entities.c.profile_id == profile_id,
                            self.entities.c.deleted_at_us.is_(None),
                            self.entities.c.review_state.in_(("CONFIRMED", "PROBABLE")),
                            self.entities.c.search_policy == "SEARCH_ALLOWED",
                            self.entities.c.transmission_policy == "PROVIDER_ALLOWLIST",
                        )
                    )
                ).mappings()
            )
            source_rows = tuple(
                connection.execute(
                    select(self.sources).where(
                        and_(
                            self.sources.c.vault_id == vault_id,
                            self.sources.c.profile_id == profile_id,
                            self.sources.c.relationship_state != "UNRELATED",
                        )
                    )
                ).mappings()
            )
            completed = (
                set()
                if mode in {"FULL_RESCAN", "MAXIMUM_COVERAGE"}
                else {
                    (
                        str(row["task_type"]),
                        str(row["provider_id"]),
                        str(row["payload_hmac"]),
                    )
                    for row in connection.execute(
                        select(
                            self.tasks.c.task_type,
                            self.tasks.c.provider_id,
                            self.tasks.c.payload_hmac,
                        ).where(
                            and_(
                                self.tasks.c.vault_id == vault_id,
                                self.tasks.c.profile_id == profile_id,
                                self.tasks.c.state.in_(("SUCCEEDED_EMPTY", "SUCCEEDED_RESULTS")),
                            )
                        )
                    ).mappings()
                }
            )
        # Broad contextual attributes are useful only when tied to a person or
        # alias. Searching them alone creates a large unrelated frontier, so
        # direct web seeds are limited to identifiers and names while contextual
        # attributes are emitted as compound queries below.
        web_searchable = {
            "EMAIL",
            "USERNAME",
            "TELEPHONE",
            "PERSON",
            "ALIAS",
            "DOMAIN",
        }
        username_values = {
            str(entity["canonical_value"]).casefold()
            for entity in entity_rows
            if str(entity["entity_type"]) == "USERNAME"
        }
        for entity in entity_rows:
            value = str(entity["canonical_value"])
            masked = str(entity["display_mask"])
            entity_type = str(entity["entity_type"])
            lead_hmac = str(entity["value_hmac"])
            dotted_username_duplicate = (
                entity_type == "DOMAIN" and value.casefold() in username_values
            )
            if (
                "DUCKDUCKGO_HTML" in provider_ids
                and entity_type in web_searchable
                and not dotted_username_duplicate
            ):
                seeds.append(
                    SeedTask(
                        task_type="SEARCH_WEB",
                        provider_id="DUCKDUCKGO_HTML",
                        payload=value,
                        masked_payload=masked,
                        lead_type=entity_type,
                        lead_display=masked,
                        lead_value_hmac=lead_hmac,
                        priority=90 if entity_type in {"EMAIL", "USERNAME"} else 75,
                        information_gain_micros=850_000,
                    )
                )
            if entity_type == "USERNAME" and "GITHUB_USERS" in provider_ids:
                seeds.append(
                    SeedTask(
                        task_type="QUERY_GITHUB",
                        provider_id="GITHUB_USERS",
                        payload=value,
                        masked_payload=masked,
                        lead_type=entity_type,
                        lead_display=masked,
                        lead_value_hmac=lead_hmac,
                        priority=88,
                        information_gain_micros=820_000,
                    )
                )
            if entity_type == "USERNAME" and "GITLAB_USERS" in provider_ids:
                seeds.append(
                    SeedTask(
                        task_type="SEARCH_USERNAME",
                        provider_id="GITLAB_USERS",
                        payload=value,
                        masked_payload=masked,
                        lead_type=entity_type,
                        lead_display=masked,
                        lead_value_hmac=lead_hmac,
                        priority=86,
                        information_gain_micros=800_000,
                    )
                )
            if entity_type == "USERNAME" and "NPM_REGISTRY" in provider_ids:
                seeds.append(
                    SeedTask(
                        task_type="QUERY_REGISTRY",
                        provider_id="NPM_REGISTRY",
                        payload=value,
                        masked_payload=masked,
                        lead_type=entity_type,
                        lead_display=masked,
                        lead_value_hmac=lead_hmac,
                        priority=78,
                        information_gain_micros=720_000,
                    )
                )
            if entity_type == "DOMAIN" and not dotted_username_duplicate:
                if "RDAP_DOMAIN" in provider_ids:
                    seeds.append(
                        SeedTask(
                            task_type="QUERY_REGISTRY",
                            provider_id="RDAP_DOMAIN",
                            payload=value,
                            masked_payload=masked,
                            lead_type=entity_type,
                            lead_display=masked,
                            lead_value_hmac=lead_hmac,
                            priority=84,
                            information_gain_micros=780_000,
                        )
                    )
                if "WAYBACK_CDX" in provider_ids:
                    seeds.append(
                        SeedTask(
                            task_type="QUERY_ARCHIVE",
                            provider_id="WAYBACK_CDX",
                            payload=value,
                            masked_payload=masked,
                            lead_type=entity_type,
                            lead_display=masked,
                            lead_value_hmac=lead_hmac,
                            priority=76,
                            information_gain_micros=700_000,
                        )
                    )
                if "CERTIFICATE_TRANSPARENCY" in provider_ids:
                    seeds.append(
                        SeedTask(
                            task_type="QUERY_CERTIFICATE_TRANSPARENCY",
                            provider_id="CERTIFICATE_TRANSPARENCY",
                            payload=value,
                            masked_payload=masked,
                            lead_type=entity_type,
                            lead_display=masked,
                            lead_value_hmac=lead_hmac,
                            priority=74,
                            information_gain_micros=680_000,
                        )
                    )
            if entity_type == "EMAIL" and "HAVE_I_BEEN_PWNED_V3" in provider_ids:
                seeds.append(
                    SeedTask(
                        task_type="SEARCH_PROVIDER",
                        provider_id="HAVE_I_BEEN_PWNED_V3",
                        payload=value,
                        masked_payload=masked,
                        lead_type=entity_type,
                        lead_display=masked,
                        lead_value_hmac=lead_hmac,
                        initial_state="AUTH_REQUIRED",
                        priority=95,
                        information_gain_micros=900_000,
                    )
                )
        if "DUCKDUCKGO_HTML" in provider_ids:
            people = [
                entity
                for entity in entity_rows
                if str(entity["entity_type"]) in {"PERSON", "ALIAS"}
            ][:4]
            context = [
                entity
                for entity in entity_rows
                if str(entity["entity_type"])
                in {"ORGANISATION", "EMPLOYMENT", "EDUCATION", "LOCATION", "PROJECT"}
            ][:8]
            for person in people:
                for clue in context:
                    person_value = str(person["canonical_value"])
                    clue_value = str(clue["canonical_value"])
                    query = f'"{person_value}" "{clue_value}"'
                    masked_query = f'"{person["display_mask"]}" "{clue["display_mask"]}"'
                    seeds.append(
                        SeedTask(
                            task_type="SEARCH_WEB",
                            provider_id="DUCKDUCKGO_HTML",
                            payload=query,
                            masked_payload=masked_query,
                            lead_type="PERSON",
                            lead_display=masked_query,
                            lead_value_hmac=self.fingerprint(query),
                            priority=82,
                            information_gain_micros=820_000,
                        )
                    )
        for source in source_rows:
            value = str(source["canonical_url"])
            seeds.append(
                SeedTask(
                    task_type="FETCH_URL",
                    provider_id="DIRECT_PUBLIC_WEB",
                    payload=value,
                    masked_payload=value,
                    lead_type="URL",
                    lead_display=value,
                    lead_value_hmac=str(source["url_hmac"]),
                    source_id=str(source["id"]),
                    priority=92,
                    information_gain_micros=900_000,
                )
            )
            if "WAYBACK_CDX" in provider_ids:
                seeds.append(
                    SeedTask(
                        task_type="QUERY_ARCHIVE",
                        provider_id="WAYBACK_CDX",
                        payload=value,
                        masked_payload=value,
                        lead_type="URL",
                        lead_display=value,
                        lead_value_hmac=str(source["url_hmac"]),
                        source_id=str(source["id"]),
                        priority=72,
                        information_gain_micros=650_000,
                    )
                )
        deduplicated: list[SeedTask] = []
        seen: set[tuple[str, str, str]] = set()
        for seed in seeds:
            identity = (seed.task_type, seed.provider_id, self.fingerprint(seed.payload))
            if identity in seen or identity in completed:
                continue
            seen.add(identity)
            deduplicated.append(seed)
        return tuple(deduplicated)

    def create_audit(
        self,
        *,
        vault_id: str,
        profile_id: str,
        name: str,
        mode: str,
        provider_ids: tuple[str, ...],
        use_local_ai: bool,
        selected_model: str | None,
        max_depth: int,
        request_budget: int,
        time_budget_seconds: int,
        cost_budget_micros: int,
        seeds: tuple[SeedTask, ...],
    ) -> str:
        """Atomically persist the run snapshot, seed leads, and deduplicated tasks."""

        audit_id = str(uuid7())
        timestamp = now_us()
        limited = seeds[:request_budget]
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.audits).values(
                    id=audit_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    name=name,
                    mode=mode,
                    state="READY" if limited else "COMPLETED",
                    stage="PLANNING" if limited else "COMPLETE",
                    provider_ids_json=_json(provider_ids),
                    use_local_ai=int(use_local_ai),
                    selected_model=selected_model,
                    max_depth=max_depth,
                    request_budget=request_budget,
                    time_budget_seconds=time_budget_seconds,
                    cost_budget_micros=cost_budget_micros,
                    total_tasks=len(limited),
                    terminal_tasks=sum(
                        seed.initial_state in TERMINAL_TASK_STATES for seed in limited
                    ),
                    result_count=0,
                    lead_count=0,
                    proposal_count=0,
                    progress_micros=1_000_000 if not limited else 0,
                    stop_reason="NO_ELIGIBLE_KNOWLEDGE" if not limited else None,
                    started_at_us=None,
                    finished_at_us=timestamp if not limited else None,
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                )
            )
            lead_by_identity: dict[tuple[str, str], str] = {}
            for seed in limited:
                lead_key = (seed.lead_type, seed.lead_value_hmac)
                lead_id = lead_by_identity.get(lead_key)
                if lead_id is None:
                    lead_id = str(uuid7())
                    lead_by_identity[lead_key] = lead_id
                    connection.execute(
                        insert(self.leads).values(
                            id=lead_id,
                            vault_id=vault_id,
                            profile_id=profile_id,
                            audit_id=audit_id,
                            parent_lead_id=None,
                            source_id=seed.source_id,
                            lead_type=seed.lead_type,
                            display_value=seed.lead_display,
                            value_hmac=seed.lead_value_hmac,
                            source_url=seed.payload if seed.lead_type == "URL" else None,
                            provider_id="PERSON_KNOWLEDGE",
                            depth=0,
                            supporting_signals_json=_json(("CONFIRMED_PERSON_KNOWLEDGE",)),
                            contradictions_json="[]",
                            confidence_micros=1_000_000,
                            ownership_state="CONFIRMED",
                            temporal_state="UNKNOWN",
                            review_state="CONFIRMED",
                            expansion_state="QUEUED",
                            created_at_us=timestamp,
                        )
                    )
                self._insert_task(
                    connection,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    audit_id=audit_id,
                    lead_id=lead_id,
                    parent_task_id=None,
                    task_type=seed.task_type,
                    provider_id=seed.provider_id,
                    payload=seed.payload,
                    masked_payload=seed.masked_payload,
                    priority=seed.priority,
                    information_gain_micros=seed.information_gain_micros,
                    depth=0,
                    state=seed.initial_state,
                )
            connection.execute(
                update(self.audits)
                .where(self.audits.c.id == audit_id)
                .values(lead_count=len(lead_by_identity))
            )
        self.refresh_audit(vault_id, profile_id, audit_id)
        return audit_id

    def claim_tasks(
        self,
        vault_id: str,
        profile_id: str,
        audit_id: str,
        *,
        maximum: int,
    ) -> tuple[FrontierTaskRecord, ...]:
        """Claim the highest-value eligible work with compare-and-swap revisions.

        Time-budget exhaustion is applied before claims. Provider I/O occurs only
        after this transaction closes, so no database lock spans a network call.
        """

        timestamp = now_us()
        with self.engine.begin() as connection:
            audit = self._audit_row(connection, vault_id, profile_id, audit_id)
            if str(audit["state"]) not in ACTIVE_AUDIT_STATES:
                return ()
            # The coordinator serializes batches, so a RUNNING row at the next
            # claim boundary can only be an interrupted attempt. Recover it
            # before selecting work so process loss never strands the frontier.
            interrupted = tuple(
                connection.execute(
                    select(self.tasks).where(
                        and_(
                            self.tasks.c.vault_id == vault_id,
                            self.tasks.c.profile_id == profile_id,
                            self.tasks.c.audit_id == audit_id,
                            self.tasks.c.state == "RUNNING",
                        )
                    )
                ).mappings()
            )
            for row in interrupted:
                retryable = int(row["attempt_count"]) <= int(row["retry_limit"])
                connection.execute(
                    update(self.tasks)
                    .where(
                        and_(
                            self.tasks.c.id == str(row["id"]),
                            self.tasks.c.revision == int(row["revision"]),
                            self.tasks.c.state == "RUNNING",
                        )
                    )
                    .values(
                        state="FAILED_RETRYABLE" if retryable else "FAILED_TERMINAL",
                        stop_reason=(
                            "INTERRUPTED_ATTEMPT" if retryable else "RETRY_LIMIT_EXHAUSTED"
                        ),
                        next_attempt_at_us=timestamp if retryable else None,
                        updated_at_us=timestamp,
                        revision=int(row["revision"]) + 1,
                    )
                )
            started_at_us = audit["started_at_us"]
            if (
                started_at_us is not None
                and timestamp - int(started_at_us) >= int(audit["time_budget_seconds"]) * 1_000_000
            ):
                self._stop_remaining_tasks(
                    connection,
                    audit_id=audit_id,
                    timestamp=timestamp,
                    reason="TIME_BUDGET_EXHAUSTED",
                )
                connection.execute(
                    update(self.audits)
                    .where(self.audits.c.id == audit_id)
                    .values(
                        state="PARTIAL",
                        stage="COMPLETE",
                        stop_reason="TIME_BUDGET_EXHAUSTED",
                        finished_at_us=timestamp,
                        updated_at_us=timestamp,
                        revision=int(audit["revision"]) + 1,
                    )
                )
                return ()
            if audit["started_at_us"] is None:
                connection.execute(
                    update(self.audits)
                    .where(self.audits.c.id == audit_id)
                    .values(
                        state="RUNNING",
                        stage="SEARCHING",
                        started_at_us=timestamp,
                        updated_at_us=timestamp,
                        revision=int(audit["revision"]) + 1,
                    )
                )
            rows = tuple(
                connection.execute(
                    select(self.tasks)
                    .where(
                        and_(
                            self.tasks.c.vault_id == vault_id,
                            self.tasks.c.profile_id == profile_id,
                            self.tasks.c.audit_id == audit_id,
                            or_(
                                self.tasks.c.state == "READY",
                                and_(
                                    self.tasks.c.state == "FAILED_RETRYABLE",
                                    or_(
                                        self.tasks.c.next_attempt_at_us.is_(None),
                                        self.tasks.c.next_attempt_at_us <= timestamp,
                                    ),
                                ),
                            ),
                        )
                    )
                    .order_by(
                        self.tasks.c.priority.desc(),
                        self.tasks.c.information_gain_micros.desc(),
                        self.tasks.c.created_at_us,
                    )
                    .limit(maximum)
                ).mappings()
            )
            claimed: list[FrontierTaskRecord] = []
            for row in rows:
                next_revision = int(row["revision"]) + 1
                changed = connection.execute(
                    update(self.tasks)
                    .where(
                        and_(
                            self.tasks.c.id == str(row["id"]),
                            self.tasks.c.revision == int(row["revision"]),
                            self.tasks.c.state == str(row["state"]),
                        )
                    )
                    .values(
                        state="RUNNING",
                        attempt_count=int(row["attempt_count"]) + 1,
                        last_attempt_at_us=timestamp,
                        updated_at_us=timestamp,
                        revision=next_revision,
                    )
                )
                if changed.rowcount == 1:
                    claimed.append(
                        _task_record(
                            row,
                            state="RUNNING",
                            revision=next_revision,
                            started_at_us=timestamp,
                        )
                    )
            return tuple(claimed)

    def record_search_outcome(
        self,
        task: FrontierTaskRecord,
        *,
        state: str,
        reason: str,
        results: tuple[SearchResultDraft, ...],
    ) -> None:
        """Commit search results, follow-up fetches, task outcome, and receipt together."""

        timestamp = now_us()
        with self.engine.begin() as connection:
            audit = self._audit_row(connection, task.vault_id, task.profile_id, task.audit_id)
            new_tasks = 0
            for result in results:
                url_hmac = self.fingerprint(result.url)
                existing_result = connection.execute(
                    select(self.results.c.id).where(
                        and_(
                            self.results.c.vault_id == task.vault_id,
                            self.results.c.profile_id == task.profile_id,
                            self.results.c.audit_id == task.audit_id,
                            self.results.c.url_hmac == url_hmac,
                        )
                    )
                ).scalar_one_or_none()
                if existing_result is not None:
                    continue
                result_id = str(uuid7())
                connection.execute(
                    insert(self.results).values(
                        id=result_id,
                        vault_id=task.vault_id,
                        profile_id=task.profile_id,
                        audit_id=task.audit_id,
                        task_id=task.id,
                        provider_id=result.provider_id,
                        rank=result.rank,
                        category=result.category,
                        canonical_url=result.url,
                        url_hmac=url_hmac,
                        title=result.title,
                        snippet=result.snippet,
                        content_sha256=None,
                        observed_at_us=timestamp,
                        review_state="UNREVIEWED",
                    )
                )
                lead_id = self._ensure_url_lead(
                    connection,
                    task=task,
                    url=result.url,
                    url_hmac=url_hmac,
                    provider_id=result.provider_id,
                    depth=task.depth + 1,
                    timestamp=timestamp,
                )
                if (
                    task.depth < int(audit["max_depth"])
                    and result.rank <= 3
                    and self._task_count(connection, task.audit_id) < int(audit["request_budget"])
                ):
                    inserted = self._insert_task(
                        connection,
                        vault_id=task.vault_id,
                        profile_id=task.profile_id,
                        audit_id=task.audit_id,
                        lead_id=lead_id,
                        parent_task_id=task.id,
                        task_type="FETCH_URL",
                        provider_id="DIRECT_PUBLIC_WEB",
                        payload=result.url,
                        masked_payload=result.url,
                        priority=max(30, task.priority - result.rank * 5),
                        information_gain_micros=max(
                            200_000, task.information_gain_micros - result.rank * 75_000
                        ),
                        depth=task.depth + 1,
                        state="READY",
                    )
                    new_tasks += int(inserted)
            final_state, final_reason = self._finish_task(
                connection,
                task,
                state=state,
                reason=reason,
                result_count=len(results),
                timestamp=timestamp,
            )
            self._insert_receipt(
                connection,
                task,
                state=final_state,
                reason=final_reason,
                result_count=len(results),
                timestamp=timestamp,
            )
            if new_tasks:
                connection.execute(
                    update(self.audits)
                    .where(self.audits.c.id == task.audit_id)
                    .values(updated_at_us=timestamp)
                )
        self.refresh_audit(task.vault_id, task.profile_id, task.audit_id)

    def record_fetch_outcome(
        self,
        task: FrontierTaskRecord,
        *,
        state: str,
        reason: str,
        page: FetchedPageDraft | None,
    ) -> None:
        """Commit page evidence, proposals, child frontier, outcome, and receipt together."""

        timestamp = now_us()
        result_count = 0
        with self.engine.begin() as connection:
            audit = self._audit_row(connection, task.vault_id, task.profile_id, task.audit_id)
            if page is not None:
                result_count = 1
                source_id = self._upsert_source_from_page(connection, task, page, timestamp)
                self._upsert_page_result(connection, task, page, timestamp)
                lead_id = task.lead_id or self._ensure_url_lead(
                    connection,
                    task=task,
                    url=page.url,
                    url_hmac=self.fingerprint(page.url),
                    provider_id=task.provider_id,
                    depth=task.depth,
                    timestamp=timestamp,
                    source_id=source_id,
                )
                for proposal in page.proposals:
                    self._insert_proposal(connection, task, lead_id, proposal, timestamp)
                available = max(
                    0,
                    int(audit["request_budget"]) - self._task_count(connection, task.audit_id),
                )
                proposal_hmacs = {
                    self.fingerprint(proposal.canonical_value) for proposal in page.proposals
                }
                confirms_known_identifier = False
                if proposal_hmacs:
                    confirms_known_identifier = (
                        connection.execute(
                            select(func.count())
                            .select_from(self.entities)
                            .where(
                                and_(
                                    self.entities.c.vault_id == task.vault_id,
                                    self.entities.c.profile_id == task.profile_id,
                                    self.entities.c.deleted_at_us.is_(None),
                                    self.entities.c.review_state.in_(("CONFIRMED", "PROBABLE")),
                                    self.entities.c.value_hmac.in_(proposal_hmacs),
                                )
                            )
                        ).scalar_one()
                        > 0
                    )
                # One same-site hop from a relevant search result is useful.
                # Deeper recursion needs an exact known identifier on the page;
                # this prevents a high depth setting from becoming a generic
                # crawl while preserving evidence-led expansion.
                may_expand = task.depth <= 1 or confirms_known_identifier
                if task.depth < int(audit["max_depth"]) and may_expand:
                    for index, link in enumerate(page.links[: min(2, available)]):
                        link_hmac = self.fingerprint(link)
                        child_lead_id = self._ensure_url_lead(
                            connection,
                            task=task,
                            url=link,
                            url_hmac=link_hmac,
                            provider_id="DIRECT_PUBLIC_WEB",
                            depth=task.depth + 1,
                            timestamp=timestamp,
                            parent_lead_id=lead_id,
                        )
                        self._insert_task(
                            connection,
                            vault_id=task.vault_id,
                            profile_id=task.profile_id,
                            audit_id=task.audit_id,
                            lead_id=child_lead_id,
                            parent_task_id=task.id,
                            task_type="FETCH_URL",
                            provider_id="DIRECT_PUBLIC_WEB",
                            payload=link,
                            masked_payload=link,
                            priority=max(20, task.priority - index * 4 - 6),
                            information_gain_micros=max(
                                150_000, task.information_gain_micros - index * 60_000 - 80_000
                            ),
                            depth=task.depth + 1,
                            state="READY",
                        )
            final_state, final_reason = self._finish_task(
                connection,
                task,
                state=state,
                reason=reason,
                result_count=result_count,
                timestamp=timestamp,
            )
            self._insert_receipt(
                connection,
                task,
                state=final_state,
                reason=final_reason,
                result_count=result_count,
                timestamp=timestamp,
            )
        self.refresh_audit(task.vault_id, task.profile_id, task.audit_id)

    def control_audit(
        self,
        *,
        vault_id: str,
        profile_id: str,
        audit_id: str,
        expected_revision: int,
        action: str,
    ) -> None:
        """Apply a closed audit transition under the caller's expected revision."""

        timestamp = now_us()
        with self.engine.begin() as connection:
            audit = self._audit_row(connection, vault_id, profile_id, audit_id)
            if int(audit["revision"]) != expected_revision:
                raise RevisionConflict("audit revision conflict")
            current = str(audit["state"])
            if action == "PAUSE" and current in {"READY", "RUNNING"}:
                requested = "PAUSED"
            elif action == "RESUME" and current == "PAUSED":
                requested = "READY"
            elif action == "CANCEL" and current in {"READY", "RUNNING", "PAUSED"}:
                requested = "CANCELLED"
                connection.execute(
                    update(self.tasks)
                    .where(
                        and_(
                            self.tasks.c.audit_id == audit_id,
                            self.tasks.c.state.in_(("PLANNED", "READY", "QUEUED")),
                        )
                    )
                    .values(
                        state="CANCELLED",
                        stop_reason="USER_CANCELLED",
                        updated_at_us=timestamp,
                        revision=self.tasks.c.revision + 1,
                    )
                )
            else:
                raise RevisionConflict("audit control transition conflict")
            connection.execute(
                update(self.audits)
                .where(self.audits.c.id == audit_id)
                .values(
                    state=requested,
                    stop_reason="USER_CANCELLED" if requested == "CANCELLED" else None,
                    finished_at_us=timestamp if requested == "CANCELLED" else None,
                    updated_at_us=timestamp,
                    revision=expected_revision + 1,
                )
            )
        self.refresh_audit(vault_id, profile_id, audit_id)

    def decide_proposal(
        self,
        *,
        vault_id: str,
        profile_id: str,
        audit_id: str,
        proposal_id: str,
        expected_revision: int,
        decision: str,
    ) -> None:
        """Persist review state and promote only explicit positive human decisions."""

        states = {
            "CONFIRM": "CONFIRMED",
            "CONFIRM_HISTORICAL": "CONFIRMED_HISTORICAL",
            "PROBABLE": "PROBABLE",
            "SEARCH_DEEPER": "UNREVIEWED",
            "REJECT": "REJECTED",
            "UNRELATED": "UNRELATED",
            "MERGE": "MERGED",
        }
        timestamp = now_us()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(self.proposals).where(
                        and_(
                            self.proposals.c.vault_id == vault_id,
                            self.proposals.c.profile_id == profile_id,
                            self.proposals.c.audit_id == audit_id,
                            self.proposals.c.id == proposal_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError("proposal is unavailable")
            changed = connection.execute(
                update(self.proposals)
                .where(
                    and_(
                        self.proposals.c.id == proposal_id,
                        self.proposals.c.revision == expected_revision,
                    )
                )
                .values(
                    review_state=states[decision],
                    reviewed_at_us=None if decision == "SEARCH_DEEPER" else timestamp,
                    revision=expected_revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("proposal revision conflict")
            if decision in {"CONFIRM", "CONFIRM_HISTORICAL", "PROBABLE"}:
                self._promote_proposal_entity(
                    connection,
                    row=row,
                    decision=decision,
                    timestamp=timestamp,
                )
            if decision == "SEARCH_DEEPER":
                self._insert_task(
                    connection,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    audit_id=audit_id,
                    lead_id=str(row["lead_id"]),
                    parent_task_id=None,
                    task_type="SEARCH_WEB",
                    provider_id="DUCKDUCKGO_HTML",
                    payload=str(row["canonical_value"]),
                    masked_payload=str(row["display_value"]),
                    priority=95,
                    information_gain_micros=900_000,
                    depth=1,
                    state="READY",
                )
        self.refresh_audit(vault_id, profile_id, audit_id)

    def _promote_proposal_entity(
        self,
        connection: Any,
        *,
        row: RowMapping,
        decision: str,
        timestamp: int,
    ) -> None:
        """Add explicitly accepted knowledge while retaining its exact proposal URL."""

        existing = connection.execute(
            select(self.entities.c.id).where(
                and_(
                    self.entities.c.vault_id == row["vault_id"],
                    self.entities.c.profile_id == row["profile_id"],
                    self.entities.c.entity_type == row["entity_type"],
                    self.entities.c.value_hmac == row["value_hmac"],
                    self.entities.c.deleted_at_us.is_(None),
                )
            )
        ).scalar_one_or_none()
        entity_id = str(existing) if existing is not None else str(uuid7())
        if existing is None:
            sensitive = str(row["entity_type"]) in {"EMAIL", "TELEPHONE", "ADDRESS"}
            connection.execute(
                insert(self.entities).values(
                    id=entity_id,
                    vault_id=row["vault_id"],
                    profile_id=row["profile_id"],
                    entity_type=row["entity_type"],
                    canonical_value=row["canonical_value"],
                    display_mask=row["display_value"],
                    value_hmac=row["value_hmac"],
                    sensitivity="SENSITIVE" if sensitive else "PUBLIC",
                    review_state="PROBABLE" if decision == "PROBABLE" else "CONFIRMED",
                    temporal_state=(
                        "HISTORICAL" if decision == "CONFIRM_HISTORICAL" else "UNKNOWN"
                    ),
                    valid_from_us=None,
                    valid_to_us=None,
                    search_policy="SEARCH_ALLOWED",
                    transmission_policy="PROVIDER_ALLOWLIST",
                    current_decision_id=None,
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                    deleted_at_us=None,
                )
            )
        connection.execute(
            insert(self.entity_origins).values(
                id=str(uuid7()),
                vault_id=row["vault_id"],
                profile_id=row["profile_id"],
                audit_id=row["audit_id"],
                proposal_id=row["id"],
                entity_id=entity_id,
                source_url=row["source_url"],
                created_at_us=timestamp,
            )
        )

    def audit_detail(self, vault_id: str, profile_id: str, audit_id: str) -> dict[str, object]:
        """Return bounded collections with one extra row for truncation detection."""

        with self.engine.connect() as connection:
            audit = self._audit_row(connection, vault_id, profile_id, audit_id)
            tasks = tuple(
                connection.execute(
                    select(self.tasks)
                    .where(self.tasks.c.audit_id == audit_id)
                    .order_by(self.tasks.c.created_at_us)
                    .limit(501)
                ).mappings()
            )
            results = tuple(
                connection.execute(
                    select(self.results)
                    .where(self.results.c.audit_id == audit_id)
                    .order_by(self.results.c.observed_at_us.desc())
                    .limit(501)
                ).mappings()
            )
            leads = tuple(
                connection.execute(
                    select(self.leads)
                    .where(self.leads.c.audit_id == audit_id)
                    .order_by(self.leads.c.created_at_us)
                    .limit(501)
                ).mappings()
            )
            proposals = tuple(
                connection.execute(
                    select(self.proposals)
                    .where(self.proposals.c.audit_id == audit_id)
                    .order_by(self.proposals.c.created_at_us.desc())
                    .limit(251)
                ).mappings()
            )
            receipts = tuple(
                connection.execute(
                    select(self.receipts)
                    .where(self.receipts.c.audit_id == audit_id)
                    .order_by(self.receipts.c.started_at_us.desc())
                    .limit(501)
                ).mappings()
            )
            ai_analysis = (
                connection.execute(
                    select(self.ai_analyses).where(
                        and_(
                            self.ai_analyses.c.vault_id == vault_id,
                            self.ai_analyses.c.profile_id == profile_id,
                            self.ai_analyses.c.audit_id == audit_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            state_counts = self._state_counts(connection, vault_id, profile_id, audit_id)
        return {
            "audit": audit,
            "tasks": tasks,
            "results": results,
            "leads": leads,
            "proposals": proposals,
            "receipts": receipts,
            "ai_analysis": ai_analysis,
            "state_counts": state_counts,
        }

    def prepare_ai_projection(
        self, vault_id: str, profile_id: str, audit_id: str
    ) -> dict[str, object] | None:
        """Claim the one-shot AI stage and build a bounded exact-source projection."""

        with self.engine.begin() as connection:
            audit = self._audit_row(connection, vault_id, profile_id, audit_id)
            if (
                not bool(audit["use_local_ai"])
                or audit["selected_model"] is None
                or str(audit["state"]) in {"PAUSED", "CANCELLED", "FAILED"}
            ):
                return None
            existing = connection.execute(
                select(self.ai_analyses.c.id).where(
                    and_(
                        self.ai_analyses.c.vault_id == vault_id,
                        self.ai_analyses.c.profile_id == profile_id,
                        self.ai_analyses.c.audit_id == audit_id,
                    )
                )
            ).scalar_one_or_none()
            active = int(
                connection.execute(
                    select(func.count())
                    .select_from(self.tasks)
                    .where(
                        and_(
                            self.tasks.c.audit_id == audit_id,
                            self.tasks.c.state.in_(
                                ("PLANNED", "READY", "QUEUED", "RUNNING", "FAILED_RETRYABLE")
                            ),
                        )
                    )
                ).scalar_one()
            )
            if existing is not None or active:
                return None
            result_rows = tuple(
                connection.execute(
                    select(self.results)
                    .where(self.results.c.audit_id == audit_id)
                    # Lower provider ranks carry the strongest query match. Feed
                    # those to the model first so a large recursive run cannot
                    # crowd its best evidence out with late low-value pages.
                    .order_by(
                        self.results.c.rank.asc(),
                        self.results.c.observed_at_us.asc(),
                    )
                    .limit(200)
                ).mappings()
            )
            timestamp = now_us()
            connection.execute(
                update(self.audits)
                .where(self.audits.c.id == audit_id)
                .values(
                    state="RUNNING",
                    stage="AI_ANALYSIS",
                    stop_reason=None,
                    finished_at_us=None,
                    updated_at_us=timestamp,
                    revision=int(audit["revision"]) + 1,
                )
            )

        records: list[dict[str, object]] = []
        citations: list[dict[str, str]] = []
        for row in result_rows:
            reference_id = f"result:{row['id']}"
            record: dict[str, object] = {
                "category": str(row["category"]),
                "provider": str(row["provider_id"]),
                "ref": reference_id,
                "snippet": str(row["snippet"])[:800],
                "title": str(row["title"])[:300],
                "url": str(row["canonical_url"]),
            }
            candidate = _json({"records": (*records, record)})
            if len(candidate.encode("utf-8")) > 56 * 1024:
                break
            records.append(record)
            citations.append(
                {
                    "referenceId": reference_id,
                    "resultId": str(row["id"]),
                    "url": str(row["canonical_url"]),
                    "title": str(row["title"])[:500],
                }
            )
        return {
            "canonical_json": _json({"records": records}),
            "references": tuple(str(item["ref"]) for item in records),
            "citations": tuple(citations),
            "selected_model": str(audit["selected_model"]),
        }

    def record_ai_analysis(
        self,
        *,
        vault_id: str,
        profile_id: str,
        audit_id: str,
        status: str,
        result_code: str,
        provider: str | None,
        model_id: str | None,
        engine_version: str | None,
        analysis: dict[str, object],
    ) -> None:
        """Persist the grounded model result or explicit deterministic fallback once."""

        with self.engine.begin() as connection:
            self._audit_row(connection, vault_id, profile_id, audit_id)
            try:
                connection.execute(
                    insert(self.ai_analyses).values(
                        id=str(uuid7()),
                        vault_id=vault_id,
                        profile_id=profile_id,
                        audit_id=audit_id,
                        status=status,
                        result_code=result_code,
                        provider=provider,
                        model_id=model_id,
                        engine_version=engine_version,
                        analysis_json=_json(analysis),
                        created_at_us=now_us(),
                    )
                )
            except IntegrityError:
                return

    def refresh_audit(self, vault_id: str, profile_id: str, audit_id: str) -> None:
        """Materialize truthful progress and completion from durable frontier counts."""

        timestamp = now_us()
        with self.engine.begin() as connection:
            audit = self._audit_row(connection, vault_id, profile_id, audit_id)
            state_counts = self._state_counts(connection, vault_id, profile_id, audit_id)
            total = sum(state_counts.values())
            terminal = sum(
                count for state, count in state_counts.items() if state in TERMINAL_TASK_STATES
            )
            results = int(
                connection.execute(
                    select(func.count())
                    .select_from(self.results)
                    .where(self.results.c.audit_id == audit_id)
                ).scalar_one()
            )
            leads = int(
                connection.execute(
                    select(func.count())
                    .select_from(self.leads)
                    .where(self.leads.c.audit_id == audit_id)
                ).scalar_one()
            )
            proposals = int(
                connection.execute(
                    select(func.count())
                    .select_from(self.proposals)
                    .where(self.proposals.c.audit_id == audit_id)
                ).scalar_one()
            )
            unresolved_proposals = int(
                connection.execute(
                    select(func.count())
                    .select_from(self.proposals)
                    .where(
                        and_(
                            self.proposals.c.audit_id == audit_id,
                            self.proposals.c.review_state == "UNREVIEWED",
                        )
                    )
                ).scalar_one()
            )
            current_state = str(audit["state"])
            ready_or_active = sum(
                state_counts.get(state, 0)
                for state in ("PLANNED", "READY", "QUEUED", "RUNNING", "FAILED_RETRYABLE")
            )
            stop_reason = audit["stop_reason"]
            stage = str(audit["stage"])
            finished = audit["finished_at_us"]
            if current_state not in {"PAUSED", "CANCELLED", "FAILED"} and ready_or_active == 0:
                review_required = state_counts.get("REVIEW_REQUIRED", 0) + unresolved_proposals
                failures = sum(
                    state_counts.get(state, 0)
                    for state in ("BLOCKED", "RATE_LIMITED", "AUTH_REQUIRED", "FAILED_TERMINAL")
                )
                current_state = "PARTIAL" if failures or review_required else "COMPLETED"
                stage = "REVIEW" if review_required else "COMPLETE"
                stop_reason = (
                    "REVIEW_REQUIRED"
                    if review_required
                    else "COVERAGE_INCOMPLETE"
                    if failures
                    else "FRONTIER_EXHAUSTED"
                )
                finished = timestamp
            elif current_state == "READY" and state_counts.get("RUNNING", 0):
                current_state = "RUNNING"
                stage = "SEARCHING"
            progress = 1_000_000 if total == 0 else min(1_000_000, terminal * 1_000_000 // total)
            connection.execute(
                update(self.audits)
                .where(self.audits.c.id == audit_id)
                .values(
                    state=current_state,
                    stage=stage,
                    total_tasks=total,
                    terminal_tasks=terminal,
                    result_count=results,
                    lead_count=leads,
                    proposal_count=proposals,
                    progress_micros=progress,
                    stop_reason=stop_reason,
                    finished_at_us=finished,
                    updated_at_us=timestamp,
                    revision=int(audit["revision"]) + 1,
                )
            )

    def _audit_row(
        self, connection: Any, vault_id: str, profile_id: str, audit_id: str
    ) -> RowMapping:
        row = (
            connection.execute(
                select(self.audits).where(
                    and_(
                        self.audits.c.vault_id == vault_id,
                        self.audits.c.profile_id == profile_id,
                        self.audits.c.id == audit_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("audit is unavailable")
        return row

    def _state_counts(
        self, connection: Any, vault_id: str, profile_id: str, audit_id: str | None
    ) -> dict[str, int]:
        clauses = [self.tasks.c.vault_id == vault_id, self.tasks.c.profile_id == profile_id]
        if audit_id is not None:
            clauses.append(self.tasks.c.audit_id == audit_id)
        return {
            str(row["state"]): int(row["count"])
            for row in connection.execute(
                select(self.tasks.c.state, func.count().label("count"))
                .where(and_(*clauses))
                .group_by(self.tasks.c.state)
            ).mappings()
        }

    def _task_count(self, connection: Any, audit_id: str) -> int:
        return int(
            connection.execute(
                select(func.count())
                .select_from(self.tasks)
                .where(self.tasks.c.audit_id == audit_id)
            ).scalar_one()
        )

    def _insert_task(
        self,
        connection: Any,
        *,
        vault_id: str,
        profile_id: str,
        audit_id: str,
        lead_id: str | None,
        parent_task_id: str | None,
        task_type: str,
        provider_id: str,
        payload: str,
        masked_payload: str,
        priority: int,
        information_gain_micros: int,
        depth: int,
        state: str,
    ) -> bool:
        """Insert one cycle-resistant task, returning false for an existing fingerprint."""

        payload_hmac = self.fingerprint(payload)
        existing = connection.execute(
            select(self.tasks.c.id).where(
                and_(
                    self.tasks.c.audit_id == audit_id,
                    self.tasks.c.task_type == task_type,
                    self.tasks.c.provider_id == provider_id,
                    self.tasks.c.payload_hmac == payload_hmac,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        timestamp = now_us()
        connection.execute(
            insert(self.tasks).values(
                id=str(uuid7()),
                vault_id=vault_id,
                profile_id=profile_id,
                audit_id=audit_id,
                lead_id=lead_id,
                parent_task_id=parent_task_id,
                task_type=task_type,
                provider_id=provider_id,
                payload_text=payload,
                payload_hmac=payload_hmac,
                masked_payload=masked_payload,
                priority=priority,
                information_gain_micros=information_gain_micros,
                depth=depth,
                state=state,
                attempt_count=0,
                retry_limit=2,
                last_attempt_at_us=None,
                next_attempt_at_us=None,
                result_count=0,
                stop_reason=None,
                receipt_json="{}",
                created_at_us=timestamp,
                updated_at_us=timestamp,
                revision=1,
            )
        )
        return True

    def _ensure_url_lead(
        self,
        connection: Any,
        *,
        task: FrontierTaskRecord,
        url: str,
        url_hmac: str,
        provider_id: str,
        depth: int,
        timestamp: int,
        parent_lead_id: str | None = None,
        source_id: str | None = None,
    ) -> str:
        """Reuse or append a URL lead while preserving its parent discovery edge."""

        existing = connection.execute(
            select(self.leads.c.id).where(
                and_(
                    self.leads.c.audit_id == task.audit_id,
                    self.leads.c.lead_type == "URL",
                    self.leads.c.value_hmac == url_hmac,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return str(existing)
        lead_id = str(uuid7())
        connection.execute(
            insert(self.leads).values(
                id=lead_id,
                vault_id=task.vault_id,
                profile_id=task.profile_id,
                audit_id=task.audit_id,
                parent_lead_id=parent_lead_id if parent_lead_id is not None else task.lead_id,
                source_id=source_id,
                lead_type="URL",
                display_value=url,
                value_hmac=url_hmac,
                source_url=url,
                provider_id=provider_id,
                depth=depth,
                supporting_signals_json=_json(("PUBLIC_RESULT_LINK",)),
                contradictions_json="[]",
                confidence_micros=650_000,
                ownership_state="UNKNOWN",
                temporal_state="UNKNOWN",
                review_state="UNREVIEWED",
                expansion_state="QUEUED",
                created_at_us=timestamp,
            )
        )
        return lead_id

    def _upsert_source_from_page(
        self, connection: Any, task: FrontierTaskRecord, page: FetchedPageDraft, timestamp: int
    ) -> str:
        url_hmac = self.fingerprint(page.url)
        existing = (
            connection.execute(
                select(self.sources).where(
                    and_(
                        self.sources.c.vault_id == task.vault_id,
                        self.sources.c.profile_id == task.profile_id,
                        self.sources.c.url_hmac == url_hmac,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            connection.execute(
                update(self.sources)
                .where(self.sources.c.id == str(existing["id"]))
                .values(
                    title=page.title,
                    last_checked_at_us=timestamp,
                    content_sha256=page.content_sha256,
                    http_status=page.http_status,
                    revision=int(existing["revision"]) + 1,
                )
            )
            return str(existing["id"])
        source_id = str(uuid7())
        connection.execute(
            insert(self.sources).values(
                id=source_id,
                vault_id=task.vault_id,
                profile_id=task.profile_id,
                source_type=_source_type_for_category(page.category),
                canonical_url=page.url,
                url_hmac=url_hmac,
                title=page.title,
                notes="",
                relationship_state="UNREVIEWED",
                parent_source_id=None,
                first_seen_at_us=timestamp,
                last_checked_at_us=timestamp,
                content_sha256=page.content_sha256,
                http_status=page.http_status,
                revision=1,
            )
        )
        return source_id

    def _upsert_page_result(
        self, connection: Any, task: FrontierTaskRecord, page: FetchedPageDraft, timestamp: int
    ) -> None:
        url_hmac = self.fingerprint(page.url)
        existing = connection.execute(
            select(self.results.c.id).where(
                and_(self.results.c.audit_id == task.audit_id, self.results.c.url_hmac == url_hmac)
            )
        ).scalar_one_or_none()
        if existing is not None:
            connection.execute(
                update(self.results)
                .where(self.results.c.id == str(existing))
                .values(content_sha256=page.content_sha256)
            )
            return
        connection.execute(
            insert(self.results).values(
                id=str(uuid7()),
                vault_id=task.vault_id,
                profile_id=task.profile_id,
                audit_id=task.audit_id,
                task_id=task.id,
                provider_id=task.provider_id,
                rank=1,
                category=page.category,
                canonical_url=page.url,
                url_hmac=url_hmac,
                title=page.title,
                snippet=page.text_excerpt,
                content_sha256=page.content_sha256,
                observed_at_us=timestamp,
                review_state="UNREVIEWED",
            )
        )

    def _insert_proposal(
        self,
        connection: Any,
        task: FrontierTaskRecord,
        lead_id: str,
        proposal: ExtractedProposalDraft,
        timestamp: int,
    ) -> None:
        """Skip canonical knowledge and duplicate proposals; otherwise append for review."""

        value_hmac = self.fingerprint(proposal.canonical_value)
        known = connection.execute(
            select(self.entities.c.id).where(
                and_(
                    self.entities.c.vault_id == task.vault_id,
                    self.entities.c.profile_id == task.profile_id,
                    self.entities.c.entity_type == proposal.entity_type,
                    self.entities.c.value_hmac == value_hmac,
                    self.entities.c.deleted_at_us.is_(None),
                )
            )
        ).scalar_one_or_none()
        if known is not None:
            return
        duplicate = connection.execute(
            select(self.proposals.c.id).where(
                and_(
                    self.proposals.c.audit_id == task.audit_id,
                    self.proposals.c.entity_type == proposal.entity_type,
                    self.proposals.c.value_hmac == value_hmac,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return
        connection.execute(
            insert(self.proposals).values(
                id=str(uuid7()),
                vault_id=task.vault_id,
                profile_id=task.profile_id,
                audit_id=task.audit_id,
                lead_id=lead_id,
                entity_type=proposal.entity_type,
                canonical_value=proposal.canonical_value,
                display_value=proposal.display_value,
                value_hmac=value_hmac,
                source_url=proposal.source_url,
                source_span_start=proposal.source_span_start,
                source_span_end=proposal.source_span_end,
                supporting_signals_json=_json(proposal.supporting_signals),
                contradictions_json=_json(proposal.contradictions),
                confidence_micros=proposal.confidence_micros,
                temporal_state="UNKNOWN",
                review_state="UNREVIEWED",
                recommended_actions_json=_json(
                    ("CONFIRM", "CONFIRM_HISTORICAL", "SEARCH_DEEPER", "REJECT")
                ),
                model_provider=proposal.model_provider,
                model_id=proposal.model_id,
                created_at_us=timestamp,
                reviewed_at_us=None,
                revision=1,
            )
        )

    def _finish_task(
        self,
        connection: Any,
        task: FrontierTaskRecord,
        *,
        state: str,
        reason: str,
        result_count: int,
        timestamp: int,
    ) -> tuple[str, str]:
        """Finalize one claimed revision or schedule bounded exponential retry."""

        final_state = state
        next_attempt_at_us = None
        if state == "FAILED_RETRYABLE":
            if task.attempt_count > task.retry_limit:
                final_state = "FAILED_TERMINAL"
                reason = "RETRY_LIMIT_EXHAUSTED"
            else:
                delay_seconds = min(60, 2 ** max(0, task.attempt_count - 1))
                next_attempt_at_us = timestamp + delay_seconds * 1_000_000
        changed = connection.execute(
            update(self.tasks)
            .where(
                and_(
                    self.tasks.c.id == task.id,
                    self.tasks.c.revision == task.revision,
                    self.tasks.c.state == "RUNNING",
                )
            )
            .values(
                state=final_state,
                result_count=result_count,
                stop_reason=reason,
                next_attempt_at_us=next_attempt_at_us,
                receipt_json=_json(
                    {
                        "externalRequest": final_state
                        not in {"BLOCKED", "AUTH_REQUIRED", "REVIEW_REQUIRED"},
                        "reason": reason,
                        "resultCount": result_count,
                    }
                ),
                updated_at_us=timestamp,
                revision=task.revision + 1,
            )
        )
        if changed.rowcount != 1:
            raise RevisionConflict("frontier task completion conflict")
        return final_state, reason

    def _stop_remaining_tasks(
        self,
        connection: Any,
        *,
        audit_id: str,
        timestamp: int,
        reason: str,
    ) -> None:
        """Convert unstarted work to explicit skipped outcomes at a hard stop."""

        connection.execute(
            update(self.tasks)
            .where(
                and_(
                    self.tasks.c.audit_id == audit_id,
                    self.tasks.c.state.in_(("PLANNED", "READY", "QUEUED", "FAILED_RETRYABLE")),
                )
            )
            .values(
                state="SKIPPED",
                stop_reason=reason,
                next_attempt_at_us=None,
                updated_at_us=timestamp,
                revision=self.tasks.c.revision + 1,
            )
        )

    def _insert_receipt(
        self,
        connection: Any,
        task: FrontierTaskRecord,
        *,
        state: str,
        reason: str,
        result_count: int,
        timestamp: int,
    ) -> None:
        """Append an attempt receipt without repeating the raw task argument."""

        execution_state = {
            "SUCCEEDED_RESULTS": "SUCCEEDED",
            "SUCCEEDED_EMPTY": "EMPTY",
            "BLOCKED": "BLOCKED",
            "RATE_LIMITED": "BLOCKED",
            "AUTH_REQUIRED": "BLOCKED",
            "FAILED_RETRYABLE": "FAILED",
            "FAILED_TERMINAL": "FAILED",
            "REVIEW_REQUIRED": "NOT_IMPLEMENTED",
        }.get(state, "FAILED")
        connection.execute(
            insert(self.receipts).values(
                id=str(uuid7()),
                vault_id=task.vault_id,
                profile_id=task.profile_id,
                audit_id=task.audit_id,
                task_id=task.id,
                tool_name=task.task_type,
                arguments_sha256=hashlib.sha256(task.payload.encode("utf-8")).hexdigest(),
                authorization_state="APPROVED",
                execution_state=execution_state,
                result_code=reason,
                result_count=result_count,
                model_provider=None,
                model_id=None,
                started_at_us=task.started_at_us,
                finished_at_us=timestamp,
            )
        )


def _task_record(
    row: RowMapping, *, state: str, revision: int, started_at_us: int
) -> FrontierTaskRecord:
    return FrontierTaskRecord(
        id=str(row["id"]),
        vault_id=str(row["vault_id"]),
        profile_id=str(row["profile_id"]),
        audit_id=str(row["audit_id"]),
        lead_id=None if row["lead_id"] is None else str(row["lead_id"]),
        parent_task_id=None if row["parent_task_id"] is None else str(row["parent_task_id"]),
        task_type=str(row["task_type"]),
        provider_id=str(row["provider_id"]),
        payload=str(row["payload_text"]),
        payload_hmac=str(row["payload_hmac"]),
        masked_payload=str(row["masked_payload"]),
        priority=int(row["priority"]),
        information_gain_micros=int(row["information_gain_micros"]),
        depth=int(row["depth"]),
        state=state,
        attempt_count=int(row["attempt_count"]) + 1,
        retry_limit=int(row["retry_limit"]),
        revision=revision,
        started_at_us=started_at_us,
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _source_type_for_category(category: str) -> str:
    return {
        "SOCIAL": "SOCIAL_PROFILE",
        "FORUM": "FORUM_THREAD",
        "CODE": "GIT_REPOSITORY",
        "DOCUMENT": "DOCUMENT",
        "ARCHIVE": "ARCHIVE",
        "PUBLIC_RECORD": "PUBLIC_RECORD",
        "MEDIA": "MEDIA",
    }.get(category, "WEBSITE")
