from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from ariadne_core.api.local_corpus_ai_schemas import (
    LocalCorpusAIExecution,
    LocalCorpusAIRequest,
)
from ariadne_core.application.local_corpus_ai import (
    LocalCorpusAIConflict,
    LocalCorpusAICoordinator,
)
from ariadne_core.application.vault import VaultManager, VaultSubkeyPurpose
from ariadne_core.domain.settings import VaultSettingsPatch
from ariadne_core.infrastructure.db.intake_identity_repository import IntakeIdentityRepository
from ariadne_core.infrastructure.db.repositories import SettingsRepository
from ariadne_core.local_ai import (
    LocalAIHttpRequest,
    LocalAIHttpResponse,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian

PROFILE_ID = "11111111-1111-4111-8111-111111111111"


class ScriptedTransport:
    def __init__(self, responses: list[LocalAIHttpResponse] | None = None) -> None:
        self.responses = responses or []
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected local-model request")
        return self.responses.pop(0)


class ProjectionAwareTransport:
    def __init__(self, *, unsupported_connection: bool = False) -> None:
        self.unsupported_connection = unsupported_connection
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        payload = json.loads(request.body or b"")
        user_content = payload["messages"][1]["content"]
        workspace_json = user_content.split("<ariadne_workspace_request>\n", 1)[1].split(
            "\n</ariadne_workspace_request>", 1
        )[0]
        records = json.loads(workspace_json)["profileData"]["records"]
        document_by_segment = {
            record["ref"]: record["data"]["documentId"]
            for record in records
            if record["kind"] == "DOCUMENT_SEGMENT"
        }
        entity = next(
            record
            for record in records
            if record["kind"] == "ENTITY"
            and len({document_by_segment[reference] for reference in record["data"]["originRefs"]})
            >= 2
        )
        origins = entity["data"]["originRefs"]
        from_ref = origins[0]
        to_ref = next(
            reference
            for reference in origins[1:]
            if document_by_segment[reference] != document_by_segment[from_ref]
        )
        supporting_refs = (
            [from_ref, to_ref] if self.unsupported_connection else [from_ref, to_ref, entity["ref"]]
        )
        output = _model_output(
            segment_ref=from_ref,
            from_ref=from_ref,
            to_ref=to_ref,
            supporting_refs=supporting_refs,
            contradiction_refs=[],
        )
        return LocalAIHttpResponse(
            200,
            json.dumps(
                {"model": payload["model"], "message": {"content": json.dumps(output)}}
            ).encode(),
        )


def _document(name: str, content: bytes) -> dict[str, object]:
    return {
        "displayName": name,
        "declaredMediaType": "application/json",
        "contentBase64": base64.b64encode(content).decode("ascii"),
        "expectedSizeBytes": len(content),
        "expectedSha256": hashlib.sha256(content).hexdigest(),
    }


def _documents() -> tuple[dict[str, object], ...]:
    return (
        _document(
            "synthetic-current.json",
            (
                b'{"email":"shared.person@example.invalid","location":"Sample City",'
                b'"project":"Atlas Signal","note":"Current synthetic profile"}'
            ),
        ),
        _document(
            "synthetic-history.json",
            (
                b'{"email":"shared.person@example.invalid","location":"Other City",'
                b'"project":"Atlas Signal","note":"Historical synthetic profile"}'
            ),
        ),
    )


def _large_documents() -> tuple[dict[str, object], ...]:
    common = {
        "email": "shared.person@example.invalid",
        "project": "Atlas Signal",
    }
    current = {
        **common,
        "location": "Sample City",
        **{
            f"current-field-{index:03d}": (
                f"Synthetic current observation {index:03d} for local reasoning reliability."
            )
            for index in range(80)
        },
    }
    history = {
        **common,
        "location": "Other City",
        **{
            f"history-field-{index:03d}": (
                f"Synthetic historical observation {index:03d} for local reasoning reliability."
            )
            for index in range(80)
        },
    }
    return (
        _document("synthetic-large-current.json", json.dumps(current).encode()),
        _document("synthetic-large-history.json", json.dumps(history).encode()),
    )


def _request(
    *,
    task: str = "SUMMARY",
    question: str | None = None,
    execution: str = "DETERMINISTIC",
    model_id: str | None = None,
    documents: tuple[dict[str, object], ...] | None = None,
    max_segments: int = 200,
) -> LocalCorpusAIRequest:
    return LocalCorpusAIRequest.model_validate(
        {
            "profileId": PROFILE_ID,
            "documents": documents or _documents(),
            "semanticEnrichmentEnabled": False,
            "task": task,
            "question": question,
            "execution": execution,
            "modelId": model_id,
            "maxSegments": max_segments,
        }
    )


def _manager(path: Path) -> VaultManager:
    manager = VaultManager(path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic corpus AI vault")
    with manager.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as key:
        repository = IntakeIdentityRepository(manager.engine, fingerprint_key=key)
        try:
            repository.create_profile(
                vault_id=manifest.vault_id,
                display_label="Synthetic corpus AI profile",
                purpose="Synthetic cited multi-document analysis",
                profile_id=PROFILE_ID,
            )
        finally:
            repository.close()
    return manager


def _resolved_catalog(result: object) -> dict[str, object]:
    return {
        entry.reference_id: entry
        for entry in result.source_catalog  # type: ignore[attr-defined]
    }


def test_request_is_hash_bound_closed_and_task_model_bound() -> None:
    parsed = _request(task="QUESTION", question="Where is Atlas Signal mentioned?")

    assert parsed.execution is LocalCorpusAIExecution.DETERMINISTIC
    assert parsed.documents[0].decoded_content().startswith(b'{"email"')
    assert "shared.person" not in repr(parsed)

    invalid = {
        "profileId": PROFILE_ID,
        "documents": _documents(),
        "semanticEnrichmentEnabled": False,
        "task": "QUESTION",
        "question": None,
        "execution": "LOCAL_MODEL",
        "modelId": None,
    }
    with pytest.raises(ValidationError):
        LocalCorpusAIRequest.model_validate(invalid)
    with pytest.raises(ValidationError):
        LocalCorpusAIRequest.model_validate({**invalid, "unexpected": True})


def test_bounded_projection_fairly_includes_each_document(tmp_path: Path) -> None:
    long_document = _document(
        "synthetic-many-records.json",
        json.dumps({f"field-{index:03d}": f"value-{index:03d}" for index in range(40)}).encode(),
    )
    short_document = _document(
        "synthetic-one-record.json",
        b'{"marker":"second synthetic document"}',
    )

    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(
        _request(documents=(long_document, short_document), max_segments=2)
    )

    assert result.included_counts.documents == 2
    assert result.included_counts.segments == 2
    assert result.projection_truncated is True


def test_connection_projection_reserves_late_cross_document_entity_origins(
    tmp_path: Path,
) -> None:
    current = {
        **{
            f"current-field-{index:03d}": f"Current synthetic filler record {index:03d}"
            for index in range(140)
        },
        "email": "late.shared.person@example.invalid",
    }
    history = {
        **{
            f"history-field-{index:03d}": f"Historical synthetic filler record {index:03d}"
            for index in range(140)
        },
        "email": "late.shared.person@example.invalid",
    }
    documents = (
        _document("synthetic-late-current.json", json.dumps(current).encode()),
        _document("synthetic-late-history.json", json.dumps(history).encode()),
    )

    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(
        _request(task="CONNECTIONS", documents=documents, max_segments=24)
    )

    assert result.available_counts.segments > 200
    assert result.available_counts.shared_entities >= 1
    assert result.included_counts.shared_entities >= 1
    assert result.included_counts.entities >= 1
    assert result.connections
    catalog = _resolved_catalog(result)
    connection = result.connections[0]
    left = catalog[connection.from_ref].sources[0]
    right = catalog[connection.to_ref].sources[0]
    assert left.document_id != right.document_id
    assert connection.shared_entity_refs[0] in catalog
    assert result.projection_truncated is True


def test_deterministic_summary_and_question_have_resolved_segment_provenance(
    tmp_path: Path,
) -> None:
    coordinator = LocalCorpusAICoordinator(_manager(tmp_path))
    summary = coordinator.analyze(_request())
    answer = coordinator.analyze(
        _request(task="QUESTION", question="Which segment mentions Atlas Signal?")
    )

    for result in (summary, answer):
        catalog = _resolved_catalog(result)
        assert result.local_only is True
        assert result.external_network_used is False
        assert result.raw_sources_retained is False
        assert result.persisted is False
        assert result.narrative_label == "DRAFT_SUMMARY_NOT_A_FACT"
        assert result.facts
        for fact in result.facts:
            for reference in fact.evidence_refs:
                entry = catalog[reference]
                assert entry.sources[0].document_name.startswith("synthetic-")
                assert entry.sources[0].segment_id
                assert entry.sources[0].segment_index >= 0
                assert entry.sources[0].locator


def test_organize_groups_each_note_with_an_exact_source_reference(tmp_path: Path) -> None:
    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(_request(task="ORGANIZE"))
    catalog = _resolved_catalog(result)

    assert {section.heading for section in result.sections} == {
        "synthetic-current.json",
        "synthetic-history.json",
    }
    for section in result.sections:
        for item in section.items:
            assert item.label.value == "ORGANIZATION"
            assert item.evidence_refs
            assert all(reference in catalog for reference in item.evidence_refs)


def test_cross_file_connections_require_one_deduplicated_entity_and_flag_uncertainty(
    tmp_path: Path,
) -> None:
    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(_request(task="CONNECTIONS"))

    assert result.available_counts.shared_entities >= 1
    assert result.connections
    connection = next(item for item in result.connections if item.contradiction_refs)
    assert connection.confidence.value == "LOW"
    assert len(connection.shared_entity_refs) == 1
    assert connection.from_ref in connection.supporting_refs
    assert connection.to_ref in connection.supporting_refs
    assert connection.shared_entity_refs[0] in connection.supporting_refs
    assert connection.contradiction_refs

    catalog = _resolved_catalog(result)
    left = catalog[connection.from_ref].sources[0]
    right = catalog[connection.to_ref].sources[0]
    shared = catalog[connection.shared_entity_refs[0]]
    assert left.document_id != right.document_id
    assert {item.document_id for item in shared.sources} == {
        left.document_id,
        right.document_id,
    }
    assert all(catalog[reference].sources for reference in connection.contradiction_refs)
    assert any(item.label.value == "HYPOTHESIS" for item in result.uncertainties)


def test_gap_analysis_suggestions_are_cited_and_never_claim_execution(tmp_path: Path) -> None:
    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(_request(task="GAP_ANALYSIS"))
    catalog = _resolved_catalog(result)

    assert result.next_steps
    assert "no search or change was run" in result.draft_summary.casefold()
    for step in result.next_steps:
        assert step.supporting_refs
        assert all(reference in catalog for reference in step.supporting_refs)
        assert step.origin.value == "DETERMINISTIC"


def test_restricted_values_are_redacted_before_facts_projection_and_result(tmp_path: Path) -> None:
    secret = "synthetic-corpus-ai-secret-canary"
    document = _document(
        "synthetic-restricted.json",
        json.dumps(
            {
                "email": "safe.person@example.invalid",
                "note": "Safe synthetic marker",
                "password": secret,
            },
            separators=(",", ":"),
        ).encode(),
    )

    result = LocalCorpusAICoordinator(_manager(tmp_path)).analyze(_request(documents=(document,)))
    encoded = result.model_dump_json(by_alias=True)

    assert result.restricted_values_redacted >= 1
    assert secret not in encoded
    assert secret not in repr(result)
    assert all(secret not in fact.statement for fact in result.facts)


def _enable_model(manager: VaultManager, model_id: str = "qwen3:30b") -> None:
    SettingsRepository(manager.engine).update(
        manager.manifest.vault_id,
        VaultSettingsPatch(
            local_ai_enabled=True,
            local_ai_provider="OLLAMA",
            local_ai_endpoint="http://127.0.0.1:11434",
            local_ai_selected_model=model_id,
        ),
        expected_revision=1,
    )


@pytest.mark.skipif(
    os.getenv("ARIADNE_RUN_LIVE_LOCAL_AI") != "1",
    reason="set ARIADNE_RUN_LIVE_LOCAL_AI=1 for the opt-in corpus model test",
)
@pytest.mark.parametrize("task", ("SUMMARY", "CONNECTIONS", "GAP_ANALYSIS"))
def test_live_selected_ollama_model_preserves_exact_corpus_sources(
    tmp_path: Path,
    task: str,
) -> None:
    model = os.getenv("ARIADNE_LIVE_LOCAL_AI_MODEL", "qwen3:30b")
    manager = _manager(tmp_path)
    _enable_model(manager, model)

    result = LocalCorpusAICoordinator(manager).analyze(
        _request(
            task=task,
            execution="LOCAL_MODEL",
            model_id=model,
            documents=_large_documents(),
            max_segments=160,
        )
    )

    assert result.execution_mode is LocalCorpusAIExecution.LOCAL_MODEL, result.fallback_reason
    assert result.model_id == model
    catalog = _resolved_catalog(result)
    cited = {reference for fact in result.facts for reference in fact.evidence_refs}
    for connection in result.connections:
        cited.update(connection.supporting_refs)
        cited.update(connection.contradiction_refs)
    for step in result.next_steps:
        cited.update(step.supporting_refs)
    assert cited
    assert cited <= set(catalog)
    assert all(entry.sources for entry in catalog.values())
    assert result.local_only is True
    assert result.external_network_used is False
    assert result.raw_sources_retained is False
    manager.lock()


def _model_output(
    *,
    segment_ref: str,
    from_ref: str,
    to_ref: str,
    supporting_refs: list[str],
    contradiction_refs: list[str],
) -> dict[str, object]:
    return {
        "title": "Synthetic cross-file review",
        "summary": "The supplied synthetic documents contain one cross-file signal.",
        "sections": [
            {
                "heading": "Model review",
                "items": [
                    {
                        "text": "This cited model note remains a review-only summary.",
                        "evidence_refs": [segment_ref],
                    }
                ],
            }
        ],
        "facts": [
            {
                "statement": "The cited segment contains a synthetic profile record.",
                "evidence_refs": [segment_ref],
                "confidence": "HIGH",
            }
        ],
        "connections": [
            {
                "from_ref": from_ref,
                "to_ref": to_ref,
                "relationship": "SHARED_SIGNAL_REQUIRES_REVIEW",
                "supporting_refs": supporting_refs,
                "contradiction_refs": contradiction_refs,
                "confidence": "LOW",
                "rationale": "The cited segments share one extracted entity signal.",
                "verification_suggestion": (
                    "Compare the cited source locators and temporal context manually."
                ),
            }
        ],
        "next_steps": [],
        "unanswered": None,
        "limitations": ["The model output is a review-only draft."],
    }


def test_selected_loopback_model_uses_strict_schema_and_preserves_source_catalog(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _enable_model(manager)
    transport = ProjectionAwareTransport()

    result = LocalCorpusAICoordinator(manager, transport=transport).analyze(
        _request(task="CONNECTIONS", execution="LOCAL_MODEL", model_id="qwen3:30b")
    )

    assert result.execution_mode is LocalCorpusAIExecution.LOCAL_MODEL
    assert result.model_id == "qwen3:30b"
    assert result.facts[0].origin.value == "LOCAL_MODEL"
    assert result.sections[0].items[0].label.value == "CITED_SUMMARY"
    assert result.sections[0].items[0].evidence_refs
    assert result.connections[0].origin.value == "LOCAL_MODEL"
    catalog = _resolved_catalog(result)
    assert all(
        reference in catalog
        for reference in (
            result.connections[0].from_ref,
            result.connections[0].to_ref,
            *result.connections[0].shared_entity_refs,
            *result.connections[0].contradiction_refs,
        )
    )

    wire = transport.requests[0]
    payload = json.loads(wire.body or b"")
    assert wire.url == "http://127.0.0.1:11434/api/chat"
    assert payload["model"] == "qwen3:30b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == "10m"
    assert payload["options"] == {
        "num_ctx": 8192,
        "num_predict": 2048,
        "temperature": 0,
    }
    assert payload["format"]["additionalProperties"] is False
    assert wire.timeout_seconds == 98
    profile_records = json.loads(
        payload["messages"][1]["content"]
        .split("<ariadne_workspace_request>\n", 1)[1]
        .split("\n</ariadne_workspace_request>", 1)[0]
    )["profileData"]["records"]
    assert all(record["ref"].startswith(("segment:s", "entity:e")) for record in profile_records)
    assert "segment:s" not in result.model_dump_json(by_alias=True)
    assert all(entry.reference_id.startswith("corpus-") for entry in result.source_catalog)
    assert all(name.casefold() != "authorization" for name, _value in wire.headers)
    manager.lock()


def test_unsupported_model_connection_is_discarded_without_surfacing_the_claim(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _enable_model(manager)
    transport = ProjectionAwareTransport(unsupported_connection=True)

    result = LocalCorpusAICoordinator(manager, transport=transport).analyze(
        _request(task="CONNECTIONS", execution="LOCAL_MODEL", model_id="qwen3:30b")
    )

    assert result.execution_mode is LocalCorpusAIExecution.LOCAL_MODEL
    assert result.connections
    assert all(connection.origin.value == "DETERMINISTIC" for connection in result.connections)
    assert any("Discarded 1 model-proposed" in note.text for note in result.uncertainties)
    manager.lock()


def test_invalid_model_reference_falls_back_without_losing_cited_connections(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    _enable_model(manager)
    baseline = LocalCorpusAICoordinator(manager).analyze(_request(task="CONNECTIONS"))
    connection = next(item for item in baseline.connections if item.contradiction_refs)
    output = _model_output(
        segment_ref=connection.from_ref,
        from_ref=connection.from_ref,
        to_ref=connection.to_ref,
        supporting_refs=list(connection.supporting_refs),
        contradiction_refs=list(connection.contradiction_refs),
    )
    output["facts"][0]["evidence_refs"] = [f"corpus-entity:{'f' * 64}"]  # type: ignore[index]
    transport = ScriptedTransport(
        [
            LocalAIHttpResponse(
                200,
                json.dumps(
                    {"model": "qwen3:30b", "message": {"content": json.dumps(output)}}
                ).encode(),
            )
        ]
    )

    result = LocalCorpusAICoordinator(manager, transport=transport).analyze(
        _request(task="CONNECTIONS", execution="LOCAL_MODEL", model_id="qwen3:30b")
    )

    assert result.execution_mode is LocalCorpusAIExecution.DETERMINISTIC
    assert result.fallback_reason is not None
    assert result.fallback_reason.value == "INVALID_RESPONSE"
    assert result.provider is None
    assert result.model_id is None
    assert result.connections
    assert all(fact.origin.value == "DETERMINISTIC" for fact in result.facts)
    manager.lock()


def test_model_must_match_persisted_selection_before_transport_is_used(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    _enable_model(manager, "qwen3:30b")
    transport = ScriptedTransport()

    with pytest.raises(LocalCorpusAIConflict, match="persisted selection"):
        LocalCorpusAICoordinator(manager, transport=transport).analyze(
            _request(
                task="SUMMARY",
                execution="LOCAL_MODEL",
                model_id="different-local-model:1b",
            )
        )

    assert transport.requests == []
    manager.lock()
