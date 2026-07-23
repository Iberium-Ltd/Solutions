from __future__ import annotations

import json
from collections.abc import Iterable

import pytest

from ariadne_core.domain.semantic_enrichment import RelationshipType, SemanticEntityType
from ariadne_core.local_ai import (
    EnrichmentRequest,
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpRequest,
    LocalAIHttpResponse,
    LocalAIProvider,
)


class RecordingTransport:
    def __init__(self, responses: Iterable[LocalAIHttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected local AI request")
        return self.responses.pop(0)


class FailingTransport:
    def __init__(self, message: str) -> None:
        self.message = message

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        del request
        raise RuntimeError(self.message)


def _json_response(payload: object, *, status: int = 200) -> LocalAIHttpResponse:
    return LocalAIHttpResponse(
        status_code=status,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


def _model_output(*, surface: str = "Northbridge Systems", start: int = 22) -> dict[str, object]:
    return {
        "entities": [
            {
                "entity_type": "PERSON",
                "surface": "Morgan Vale",
                "start": 0,
                "end": 11,
                "confidence_micros": 800_000,
                "explanation_code": "model.person.explicit",
            },
            {
                "entity_type": "ORGANISATION",
                "surface": surface,
                "start": start,
                "end": start + len(surface),
                "confidence_micros": 750_000,
                "explanation_code": "model.organisation.explicit",
            },
        ],
        "relationships": [
            {
                "source_index": 0,
                "target_index": 1,
                "relationship_type": "EMPLOYED_BY",
                "start": 0,
                "end": start + len(surface),
                "confidence_micros": 700_000,
                "explanation_code": "model.employment.explicit",
            }
        ],
    }


def test_client_is_disabled_by_default_without_touching_transport() -> None:
    transport = RecordingTransport([])
    client = LocalAIClient(transport=transport)

    assert client.enabled is False
    with pytest.raises(LocalAIError) as raised:
        client.list_models()

    assert raised.value.code is LocalAIErrorCode.DISABLED
    assert transport.requests == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:11434",
        "http://192.0.2.10:11434",
        "http://example.invalid:11434",
        "http://127.0.0.1:11434/api",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434?next=http://192.0.2.1",
        "http://0.0.0.0:11434",
    ],
)
def test_configuration_rejects_every_non_loopback_or_ambiguous_endpoint(endpoint: str) -> None:
    with pytest.raises(LocalAIError) as raised:
        LocalAIConfig(enabled=True, endpoint=endpoint)

    assert raised.value.code is LocalAIErrorCode.INVALID_CONFIGURATION
    assert endpoint not in str(raised.value)


def test_configuration_accepts_only_explicit_loopback_forms() -> None:
    assert LocalAIConfig(endpoint="http://127.1.2.3:11434/").endpoint == ("http://127.1.2.3:11434")
    assert LocalAIConfig(endpoint="http://[::1]:1234").endpoint == "http://[::1]:1234"
    assert LocalAIConfig(endpoint="http://localhost:1234").endpoint == ("http://localhost:1234")


def test_ollama_lists_installed_models_with_no_credentials() -> None:
    transport = RecordingTransport(
        [
            _json_response(
                {
                    "models": [
                        {"name": "qwen-local:7b", "model": "qwen-local:7b"},
                        {"name": "qwen-local:7b"},
                        {"model": "granite-local:8b"},
                    ]
                }
            )
        ]
    )
    client = LocalAIClient(LocalAIConfig(enabled=True), transport=transport)

    models = client.list_models()

    assert [(model.provider, model.model_id) for model in models] == [
        (LocalAIProvider.OLLAMA, "qwen-local:7b"),
        (LocalAIProvider.OLLAMA, "granite-local:8b"),
    ]
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url == "http://127.0.0.1:11434/api/tags"
    assert request.body is None
    assert all(name.casefold() != "authorization" for name, _value in request.headers)


def test_openai_compatible_lists_lm_studio_served_models() -> None:
    transport = RecordingTransport(
        [_json_response({"object": "list", "data": [{"id": "lmstudio-community/model-gguf"}]})]
    )
    config = LocalAIConfig(
        enabled=True,
        provider=LocalAIProvider.OPENAI_COMPATIBLE,
        endpoint="http://127.0.0.1:1234",
    )

    models = LocalAIClient(config, transport=transport).list_models()

    assert models[0].provider is LocalAIProvider.OPENAI_COMPATIBLE
    assert models[0].model_id == "lmstudio-community/model-gguf"
    assert transport.requests[0].url == "http://127.0.0.1:1234/v1/models"


def test_ollama_executes_bounded_grounded_structured_enrichment() -> None:
    text = "Morgan Vale worked at Northbridge Systems."
    transport = RecordingTransport(
        [
            _json_response(
                {"model": "qwen-local:7b", "message": {"content": json.dumps(_model_output())}}
            )
        ]
    )
    client = LocalAIClient(LocalAIConfig(enabled=True), transport=transport)

    result = client.enrich(EnrichmentRequest(redacted_text=text), model_id="qwen-local:7b")

    assert result.provider is LocalAIProvider.OLLAMA
    assert result.model_id == "qwen-local:7b"
    assert result.human_review_required is True
    assert result.entities[1].entity_type is SemanticEntityType.ORGANISATION
    assert result.relationships[0].relationship_type is RelationshipType.EMPLOYED_BY
    wire_request = transport.requests[0]
    payload = json.loads(wire_request.body or b"")
    assert payload["model"] == "qwen-local:7b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["format"]["additionalProperties"] is False
    assert payload["keep_alive"] == "10m"
    assert payload["options"] == {
        "num_ctx": 8192,
        "num_predict": 1024,
        "temperature": 0,
    }
    assert all(name.casefold() != "authorization" for name, _value in wire_request.headers)
    assert text not in repr(wire_request)
    assert "Northbridge Systems" not in repr(result)


def test_openai_compatible_uses_strict_json_schema_and_explicit_model() -> None:
    text = "Morgan Vale worked at Northbridge Systems."
    transport = RecordingTransport(
        [
            _json_response(
                {
                    "model": "lmstudio-community/model-gguf",
                    "choices": [
                        {"message": {"role": "assistant", "content": json.dumps(_model_output())}}
                    ],
                }
            )
        ]
    )
    config = LocalAIConfig(
        enabled=True,
        provider=LocalAIProvider.OPENAI_COMPATIBLE,
        endpoint="http://127.0.0.1:1234",
        max_output_tokens=512,
    )

    LocalAIClient(config, transport=transport).enrich(
        EnrichmentRequest(redacted_text=text),
        model_id="lmstudio-community/model-gguf",
    )

    request = transport.requests[0]
    payload = json.loads(request.body or b"")
    assert request.url == "http://127.0.0.1:1234/v1/chat/completions"
    assert payload["model"] == "lmstudio-community/model-gguf"
    assert payload["max_tokens"] == 512
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_enrichment_never_chooses_a_model_implicitly() -> None:
    client = LocalAIClient(LocalAIConfig(enabled=True), transport=RecordingTransport([]))

    with pytest.raises(LocalAIError) as raised:
        client.enrich(EnrichmentRequest(redacted_text="Synthetic text"), model_id="")

    assert raised.value.code is LocalAIErrorCode.MODEL_REQUIRED


def test_model_output_must_be_exactly_grounded_in_redacted_input() -> None:
    text = "Morgan Vale worked at Northbridge Systems."
    ungrounded = _model_output(surface="Imagined Company", start=22)
    transport = RecordingTransport(
        [_json_response({"model": "qwen-local:7b", "message": {"content": json.dumps(ungrounded)}})]
    )
    client = LocalAIClient(LocalAIConfig(enabled=True), transport=transport)

    result = client.enrich(
        EnrichmentRequest(redacted_text=text),
        model_id="qwen-local:7b",
    )
    assert all(entity.surface != "Imagined Company" for entity in result.entities)


def test_unique_exact_surface_repairs_model_character_arithmetic() -> None:
    text = "Morgan Vale worked at Northbridge Systems."
    wrong_offsets = _model_output(start=5)
    transport = RecordingTransport(
        [
            _json_response(
                {
                    "model": "qwen-local:7b",
                    "message": {"content": json.dumps(wrong_offsets)},
                }
            )
        ]
    )

    result = LocalAIClient(
        LocalAIConfig(enabled=True),
        transport=transport,
    ).enrich(
        EnrichmentRequest(redacted_text=text),
        model_id="qwen-local:7b",
    )

    organisation = next(
        entity
        for entity in result.entities
        if entity.entity_type is SemanticEntityType.ORGANISATION
    )
    assert (organisation.start, organisation.end) == (22, 41)
    assert text[organisation.start : organisation.end] == organisation.surface
    assert result.relationships == ()


def test_request_response_and_service_failures_are_bounded_and_redacted() -> None:
    request_limited = LocalAIClient(
        LocalAIConfig(enabled=True, max_input_bytes=10),
        transport=RecordingTransport([]),
    )
    with pytest.raises(LocalAIError) as input_error:
        request_limited.enrich(
            EnrichmentRequest(redacted_text="Synthetic text"),
            model_id="local-model",
        )
    assert input_error.value.code is LocalAIErrorCode.REQUEST_LIMIT

    response_limited = LocalAIClient(
        LocalAIConfig(enabled=True, max_response_bytes=16),
        transport=RecordingTransport([LocalAIHttpResponse(200, b"x" * 17)]),
    )
    with pytest.raises(LocalAIError) as response_error:
        response_limited.list_models()
    assert response_error.value.code is LocalAIErrorCode.RESPONSE_LIMIT

    sensitive_marker = "synthetic-prompt-marker"
    unavailable = LocalAIClient(
        LocalAIConfig(enabled=True),
        transport=FailingTransport(sensitive_marker),
    )
    with pytest.raises(LocalAIError) as service_error:
        unavailable.list_models()
    assert service_error.value.code is LocalAIErrorCode.UNAVAILABLE
    assert sensitive_marker not in str(service_error.value)
    assert sensitive_marker not in repr(service_error.value)


def test_non_success_and_malformed_json_never_surface_upstream_bodies() -> None:
    sensitive_marker = "synthetic-upstream-private-marker"
    rejected = LocalAIClient(
        LocalAIConfig(enabled=True),
        transport=RecordingTransport([LocalAIHttpResponse(500, sensitive_marker.encode())]),
    )
    with pytest.raises(LocalAIError) as status_error:
        rejected.list_models()
    assert status_error.value.code is LocalAIErrorCode.UPSTREAM_REJECTED
    assert sensitive_marker not in str(status_error.value)

    malformed = LocalAIClient(
        LocalAIConfig(enabled=True),
        transport=RecordingTransport([LocalAIHttpResponse(200, sensitive_marker.encode())]),
    )
    with pytest.raises(LocalAIError) as json_error:
        malformed.list_models()
    assert json_error.value.code is LocalAIErrorCode.INVALID_RESPONSE
    assert sensitive_marker not in str(json_error.value)
