from __future__ import annotations

import json
import os
from hashlib import sha256

import pytest
from pydantic import SecretStr

from ariadne_core.local_ai import (
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpRequest,
    LocalAIHttpResponse,
    LocalAIProvider,
    LocalAIWorkspaceTask,
    OpenAIResponsesClient,
    OpenAIResponsesConfig,
    WorkspaceAnalysisRequest,
)


class RecordingTransport:
    def __init__(self, response: LocalAIHttpResponse) -> None:
        self.response = response
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        return self.response


def _request() -> WorkspaceAnalysisRequest:
    projection = json.dumps(
        {
            "records": [
                {
                    "data": {"outcome": "FOUND", "title": "Synthetic profile result"},
                    "kind": "FINDING",
                    "ref": "finding:11111111-1111-4111-8111-111111111111",
                }
            ],
            "schema": "ariadne.local-ai-workspace-input",
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return WorkspaceAnalysisRequest(
        task=LocalAIWorkspaceTask.SUMMARY,
        question=None,
        profile_data_json=projection,
        allowed_reference_ids=("finding:11111111-1111-4111-8111-111111111111",),
    )


def _output(reference: str) -> dict[str, object]:
    return {
        "title": "Synthetic local summary",
        "summary": "One selected finding is available for review.",
        "sections": [
            {
                "heading": "Findings",
                "items": [
                    {
                        "text": "One deterministic finding record.",
                        "evidence_refs": [reference],
                    }
                ],
            }
        ],
        "facts": [
            {
                "statement": "The selected record has a FOUND outcome.",
                "evidence_refs": [reference],
                "confidence": "HIGH",
            }
        ],
        "connections": [],
        "next_steps": [],
        "unanswered": None,
        "limitations": ["This output requires human review."],
    }


def test_workspace_uses_explicit_ollama_model_and_exact_json_schema() -> None:
    reference = "finding:11111111-1111-4111-8111-111111111111"
    transport = RecordingTransport(
        LocalAIHttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "model": "qwen-local:30b",
                    "message": {"content": json.dumps(_output(reference))},
                }
            ).encode(),
        )
    )

    result = LocalAIClient(
        LocalAIConfig(enabled=True, max_output_tokens=2_048),
        transport=transport,
    ).analyze_workspace(_request(), model_id="qwen-local:30b")

    assert result.model_id == "qwen-local:30b"
    assert result.human_review_required is True
    assert result.sections[0].items[0].evidence_refs == (reference,)
    assert result.facts[0].evidence_refs == (reference,)
    request = transport.requests[0]
    payload = json.loads(request.body or b"")
    assert request.url == "http://127.0.0.1:11434/api/chat"
    assert payload["model"] == "qwen-local:30b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {"num_predict": 2048, "temperature": 0}
    assert payload["format"]["additionalProperties"] is False
    assert "$defs" not in payload["format"]
    assert "$ref" not in json.dumps(payload["format"])
    assert payload["format"]["properties"]["facts"]["items"]["additionalProperties"] is False
    assert "unanswered" in payload["format"]["required"]
    assert "SUMMARY contract" in payload["messages"][1]["content"]
    assert "documentId, textSha256" in payload["messages"][0]["content"]


def test_workspace_discards_uncited_items_but_keeps_exact_reference_validation() -> None:
    reference = "finding:11111111-1111-4111-8111-111111111111"
    output = _output(reference)
    output["sections"] = [
        {
            "heading": "Uncited synthetic section",
            "items": [
                {
                    "text": "This uncited synthetic section item must not surface.",
                    "evidence_refs": [],
                }
            ],
        }
    ]
    output["facts"] = [
        {
            "statement": "This uncited synthetic statement must not surface.",
            "evidence_refs": [],
            "confidence": "LOW",
        }
    ]
    output["connections"] = [
        {
            "from_ref": reference,
            "to_ref": reference,
            "relationship": "UNSUPPORTED_SELF_LINK",
            "supporting_refs": [reference, reference],
            "contradiction_refs": [],
            "confidence": "LOW",
            "rationale": "This unsupported synthetic link must not surface.",
            "verification_suggestion": "Review the source manually.",
        }
    ]
    output["next_steps"] = [
        {
            "priority": 1,
            "suggestion": "This uncited synthetic step must not surface.",
            "rationale": "It has no cited support.",
            "supporting_refs": [],
        }
    ]
    output["unanswered"] = ""
    transport = RecordingTransport(
        LocalAIHttpResponse(
            200,
            json.dumps(
                {"model": "qwen-local:30b", "message": {"content": json.dumps(output)}}
            ).encode(),
        )
    )

    result = LocalAIClient(LocalAIConfig(enabled=True), transport=transport).analyze_workspace(
        _request(), model_id="qwen-local:30b"
    )

    assert result.sections == ()
    assert result.facts == ()
    assert result.connections == ()
    assert result.next_steps == ()
    assert result.unanswered is None
    assert result.limitations[-1] == (
        "Uncited or structurally unsupported model items were discarded."
    )


def test_workspace_rejects_unknown_citations_and_open_output() -> None:
    output = _output("finding:22222222-2222-4222-8222-222222222222")
    output["action"] = "send"
    transport = RecordingTransport(
        LocalAIHttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "model": "qwen-local:30b",
                    "message": {"content": json.dumps(output)},
                }
            ).encode(),
        )
    )

    with pytest.raises(LocalAIError) as raised:
        LocalAIClient(
            LocalAIConfig(enabled=True),
            transport=transport,
        ).analyze_workspace(_request(), model_id="qwen-local:30b")

    assert raised.value.code is LocalAIErrorCode.INVALID_RESPONSE


def test_workspace_validates_structured_connection_support_and_verification() -> None:
    left = "finding:11111111-1111-4111-8111-111111111111"
    right = "finding:22222222-2222-4222-8222-222222222222"
    projection = json.dumps(
        {
            "records": [
                {"data": {"title": "Synthetic A"}, "kind": "FINDING", "ref": left},
                {"data": {"title": "Synthetic B"}, "kind": "FINDING", "ref": right},
            ],
            "schema": "ariadne.local-ai-workspace-input",
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    model_output = _output(left)
    model_output["connections"] = [
        {
            "from_ref": left,
            "to_ref": right,
            "relationship": "POSSIBLY_RELATED",
            "supporting_refs": [left],
            "contradiction_refs": [],
            "confidence": "LOW",
            "rationale": "The selected records share one bounded synthetic signal.",
            "verification_suggestion": "Compare independent provenance before confirmation.",
        }
    ]
    transport = RecordingTransport(
        LocalAIHttpResponse(
            200,
            json.dumps(
                {
                    "model": "qwen-local:30b",
                    "message": {"content": json.dumps(model_output)},
                }
            ).encode(),
        )
    )

    result = LocalAIClient(LocalAIConfig(enabled=True), transport=transport).analyze_workspace(
        WorkspaceAnalysisRequest(
            task=LocalAIWorkspaceTask.CONNECTIONS,
            question=None,
            profile_data_json=projection,
            allowed_reference_ids=(left, right),
        ),
        model_id="qwen-local:30b",
    )

    assert result.connections[0].supporting_refs == (left,)
    assert result.connections[0].contradiction_refs == ()
    assert result.connections[0].verification_suggestion.startswith("Compare")


def test_openai_responses_uses_ephemeral_key_strict_schema_and_exact_aliases() -> None:
    reference = "finding:11111111-1111-4111-8111-111111111111"
    alias = f"source_alias:{sha256(reference.encode()).hexdigest()[:32]}"
    key = "synthetic_ephemeral_openai_key"
    transport = RecordingTransport(
        LocalAIHttpResponse(
            200,
            json.dumps(
                {
                    "model": "synthetic-openai-model-2026-07-14",
                    "output": [
                        {
                            "id": "reasoning-synthetic",
                            "summary": [{"text": "must not surface", "type": "summary_text"}],
                            "type": "reasoning",
                        },
                        {
                            "content": [
                                {
                                    "annotations": [],
                                    "text": json.dumps(_output(alias)),
                                    "type": "output_text",
                                }
                            ],
                            "id": "message-synthetic",
                            "role": "assistant",
                            "status": "completed",
                            "type": "message",
                        },
                    ],
                    "status": "completed",
                }
            ).encode(),
        )
    )

    config = OpenAIResponsesConfig(
        api_key=SecretStr(key),
        max_output_tokens=768,
    )
    result = OpenAIResponsesClient(config, transport=transport).analyze_workspace(
        _request(),
        model_id="synthetic-openai-model",
    )

    assert result.provider is LocalAIProvider.OPENAI_RESPONSES
    assert result.facts[0].evidence_refs == (reference,)
    assert result.sections[0].items[0].evidence_refs == (reference,)
    assert "must not surface" not in repr(result)
    wire_request = transport.requests[0]
    wire_payload = json.loads(wire_request.body or b"")
    assert wire_request.url == "https://api.openai.com/v1/responses"
    assert dict(wire_request.headers)["Authorization"] == f"Bearer {key}"
    assert key not in repr(config)
    assert key not in repr(wire_request)
    assert key not in (wire_request.body or b"").decode()
    assert wire_payload["store"] is False
    assert wire_payload["stream"] is False
    assert wire_payload["max_output_tokens"] == 768
    assert wire_payload["text"]["format"]["type"] == "json_schema"
    assert wire_payload["text"]["format"]["strict"] is True
    assert "unanswered" in wire_payload["text"]["format"]["schema"]["required"]
    assert "$defs" not in wire_payload["text"]["format"]["schema"]
    prompt = json.dumps(wire_payload["input"])
    assert alias in prompt
    assert reference not in prompt


def test_openai_responses_rejects_unknown_alias_and_incomplete_output() -> None:
    unknown_alias = "source_alias:00000000000000000000000000000000"
    invalid_citation = RecordingTransport(
        LocalAIHttpResponse(
            200,
            json.dumps(
                {
                    "model": "synthetic-openai-model",
                    "output": [
                        {
                            "content": [
                                {
                                    "text": json.dumps(_output(unknown_alias)),
                                    "type": "output_text",
                                }
                            ],
                            "role": "assistant",
                            "status": "completed",
                            "type": "message",
                        }
                    ],
                    "status": "completed",
                }
            ).encode(),
        )
    )
    client = OpenAIResponsesClient(
        OpenAIResponsesConfig(api_key=SecretStr("synthetic_ephemeral_openai_key")),
        transport=invalid_citation,
    )

    with pytest.raises(LocalAIError) as invalid:
        client.analyze_workspace(_request(), model_id="synthetic-openai-model")

    assert invalid.value.code is LocalAIErrorCode.INVALID_RESPONSE

    incomplete = RecordingTransport(
        LocalAIHttpResponse(
            200,
            json.dumps(
                {
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "model": "synthetic-openai-model",
                    "output": [{"type": "reasoning"}],
                    "status": "incomplete",
                }
            ).encode(),
        )
    )
    limited = OpenAIResponsesClient(
        OpenAIResponsesConfig(api_key=SecretStr("synthetic_ephemeral_openai_key")),
        transport=incomplete,
    )

    with pytest.raises(LocalAIError) as truncated:
        limited.analyze_workspace(_request(), model_id="synthetic-openai-model")

    assert truncated.value.code is LocalAIErrorCode.RESPONSE_LIMIT


@pytest.mark.skipif(
    os.getenv("ARIADNE_RUN_LIVE_LOCAL_AI") != "1",
    reason="set ARIADNE_RUN_LIVE_LOCAL_AI=1 for the opt-in loopback model test",
)
def test_live_ollama_workspace_schema() -> None:
    model = os.getenv("ARIADNE_LIVE_LOCAL_AI_MODEL", "qwen3:30b")
    client = LocalAIClient(
        LocalAIConfig(
            enabled=True,
            endpoint="http://127.0.0.1:11434",
            timeout_seconds=60,
            max_output_tokens=1_024,
        )
    )

    try:
        result = client.analyze_workspace(_request(), model_id=model)
    except LocalAIError as error:
        # An undersized model may violate the accepted schema or invent a ref; that is a safe,
        # post-validation failure rather than an Ollama grammar/request failure.
        assert error.code is LocalAIErrorCode.INVALID_RESPONSE
        return

    assert result.model_id == model
    assert result.human_review_required is True
    assert all(
        reference in _request().allowed_reference_ids
        for fact in result.facts
        for reference in fact.evidence_refs
    )
