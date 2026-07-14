from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ariadne_core.api.intake_schemas import (
    EntityDecisionRequest,
    EntityOriginPageRequest,
    EntityOriginPageResult,
    EntitySummary,
    GraphNode,
    PasteIntakeRequest,
    ProfileCreateRequest,
)


def test_paste_intake_is_strict_bounded_and_requires_consent() -> None:
    profile_id = str(uuid4())
    accepted = PasteIntakeRequest.model_validate(
        {
            "idempotencyKey": "synthetic-paste-0001",
            "profileId": profile_id,
            "displayName": "Synthetic pasted source",
            "content": "Invented local-only profile text.",
            "consentConfirmed": True,
            "retainRawSource": False,
        }
    )
    assert accepted.profile_id == profile_id
    assert "Invented local-only" not in repr(accepted)

    for mutation in (
        {"consentConfirmed": False},
        {"content": ""},
        {"unexpected": True},
    ):
        candidate = accepted.model_dump(by_alias=True)
        candidate.update(mutation)
        with pytest.raises(ValidationError):
            PasteIntakeRequest.model_validate(candidate)


def test_labels_reject_whitespace_and_control_characters() -> None:
    for value in (" leading", "trailing ", "line\nbreak"):
        with pytest.raises(ValidationError):
            ProfileCreateRequest.model_validate(
                {
                    "idempotencyKey": "synthetic-profile-0001",
                    "displayLabel": value,
                    "purpose": "Synthetic defensive audit",
                }
            )

    accepted = ProfileCreateRequest.model_validate(
        {
            "idempotencyKey": "synthetic-profile-0002",
            "displayLabel": "Synthetic private label",
            "purpose": "Synthetic private purpose",
        }
    )
    assert "Synthetic private label" not in repr(accepted)
    assert "Synthetic private purpose" not in repr(accepted)


def test_entity_decision_policy_cannot_weaken_sensitive_or_excluded_state() -> None:
    base = {
        "idempotencyKey": "synthetic-decision-0001",
        "profileId": str(uuid4()),
        "entityId": str(uuid4()),
        "expectedRevision": 1,
        "decisionType": "POLICY_CHANGE",
        "reviewState": "CONFIRMED",
        "sensitivity": "HIGHLY_SENSITIVE",
        "temporalState": "CURRENT",
        "searchPolicy": "ALLOW",
        "transmissionPolicy": "POLICY_CONTROLLED",
        "reason": "Synthetic review",
    }
    with pytest.raises(ValidationError, match="highly sensitive"):
        EntityDecisionRequest.model_validate(base)

    excluded = {
        **base,
        "decisionType": "EXCLUDE",
        "reviewState": "EXCLUDED",
        "sensitivity": "SENSITIVE",
        "searchPolicy": "STORE_ONLY",
        "transmissionPolicy": "NEVER",
    }
    with pytest.raises(ValidationError, match="excluded entities"):
        EntityDecisionRequest.model_validate(excluded)

    contradictory = {
        **base,
        "decisionType": "CONFIRM",
        "reviewState": "FALSE_POSITIVE",
        "sensitivity": "SENSITIVE",
        "searchPolicy": "DENY",
        "transmissionPolicy": "NEVER",
    }
    with pytest.raises(ValidationError, match="inconsistent"):
        EntityDecisionRequest.model_validate(contradictory)

    accepted = EntityDecisionRequest.model_validate(
        {
            **contradictory,
            "reviewState": "CONFIRMED",
            "searchPolicy": "REQUIRE_APPROVAL",
            "transmissionPolicy": "REQUIRE_EACH_APPROVAL",
        }
    )
    assert accepted.review_state.value == "CONFIRMED"
    assert "Synthetic review" not in repr(accepted)


def test_masked_identity_provenance_and_graph_labels_are_hidden_from_repr() -> None:
    source_label = "Synthetic local source label"
    segment_locator = '{"locator":"line:4"}'
    origin_explanation = "Synthetic deterministic extraction"
    entity = EntitySummary.model_validate(
        {
            "entityId": str(uuid4()),
            "entityType": "USERNAME",
            "displayValue": "synthetic-masked-value",
            "sensitivity": "SENSITIVE",
            "reviewState": "UNREVIEWED",
            "temporalState": "UNKNOWN",
            "searchPolicy": "STORE_ONLY",
            "transmissionPolicy": "LOCAL_ONLY",
            "confidenceMicros": 750_000,
            "provenanceLabel": "synthetic-private-provenance",
            "origins": (
                {
                    "sourceId": str(uuid4()),
                    "sourceDisplayName": source_label,
                    "sourceSha256": "a" * 64,
                    "segmentId": str(uuid4()),
                    "segmentIndex": 3,
                    "segmentLocator": segment_locator,
                    "sourceSpanStart": 12,
                    "sourceSpanEnd": 24,
                    "extractionRunId": str(uuid4()),
                    "extractorKind": "DETERMINISTIC",
                    "extractorName": "synthetic-compiler",
                    "extractorVersion": "1",
                    "originKind": "DETERMINISTIC",
                    "observedAtUs": 1_000,
                    "confidenceMicros": 750_000,
                    "explanation": origin_explanation,
                },
            ),
            "originsTruncated": False,
            "revision": 1,
        }
    )
    node = GraphNode.model_validate(
        {
            "nodeId": str(uuid4()),
            "nodeType": "USERNAME",
            "displayLabel": "synthetic-private-node-label",
            "sensitivity": "SENSITIVE",
            "entityId": entity.entity_id,
        }
    )

    assert entity.display_value not in repr(entity)
    assert entity.provenance_label not in repr(entity)
    assert source_label not in repr(entity)
    assert segment_locator not in repr(entity)
    assert origin_explanation not in repr(entity)
    assert node.display_label not in repr(node)

    truncated = entity.model_dump(mode="python", by_alias=True)
    truncated["originsTruncated"] = True
    with pytest.raises(ValidationError, match="fill the response bound"):
        EntitySummary.model_validate(truncated)

    incomplete_extractor = entity.model_dump(mode="python", by_alias=True)
    incomplete_extractor["origins"][0]["extractorVersion"] = None
    with pytest.raises(ValidationError, match="extractor metadata is incomplete"):
        EntitySummary.model_validate(incomplete_extractor)


def test_entity_origin_page_is_bounded_exact_and_consistent() -> None:
    profile_id = str(uuid4())
    entity_id = str(uuid4())
    origin = {
        "sourceId": str(uuid4()),
        "sourceDisplayName": "Synthetic paginated source",
        "sourceSha256": "b" * 64,
        "segmentId": str(uuid4()),
        "segmentIndex": 7,
        "segmentLocator": '{"kind":"paragraph","index":7}',
        "sourceSpanStart": 2,
        "sourceSpanEnd": 18,
        "extractionRunId": None,
        "extractorKind": None,
        "extractorName": None,
        "extractorVersion": None,
        "originKind": "USER_INPUT",
        "observedAtUs": 1_750_000_000_123_456,
        "confidenceMicros": 1_000_000,
        "explanation": "Synthetic metadata-only exact origin.",
    }
    request = EntityOriginPageRequest.model_validate(
        {"profileId": profile_id, "entityId": entity_id, "offset": 32, "limit": 12}
    )
    result = EntityOriginPageResult.model_validate(
        {
            **request.model_dump(by_alias=True),
            "origins": (origin,),
            "total": 33,
            "hasMore": False,
        }
    )
    assert result.total == 33
    assert "Synthetic paginated source" not in repr(result)
    assert "Synthetic metadata-only exact origin" not in repr(result)

    for mutation in (
        {"limit": 13},
        {"origins": (), "hasMore": True},
        {"hasMore": True},
        {"origins": ({**origin, "sourceContent": "must not cross"},)},
    ):
        candidate = result.model_dump(by_alias=True)
        candidate.update(mutation)
        with pytest.raises(ValidationError):
            EntityOriginPageResult.model_validate(candidate)

    past_end = EntityOriginPageResult.model_validate(
        {
            "profileId": profile_id,
            "entityId": entity_id,
            "offset": 100,
            "limit": 12,
            "origins": (),
            "total": 33,
            "hasMore": False,
        }
    )
    assert past_end.origins == ()

    maximum_origin = {
        **origin,
        "sourceDisplayName": "🧭" * 255,
        "segmentLocator": "🧭" * 16_384,
        "explanation": "🧭" * 2_048,
    }
    maximum_page = EntityOriginPageResult.model_validate(
        {
            "profileId": profile_id,
            "entityId": entity_id,
            "offset": 0,
            "limit": 12,
            "origins": tuple(maximum_origin for _ in range(12)),
            "total": 12,
            "hasMore": False,
        }
    )
    assert len(maximum_page.model_dump_json(by_alias=True).encode("utf-8")) <= 1_048_576
