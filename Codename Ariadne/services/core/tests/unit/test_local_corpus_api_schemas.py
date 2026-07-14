from __future__ import annotations

import base64
import hashlib

import pytest
from pydantic import ValidationError

from ariadne_core.api.local_corpus_schemas import (
    LocalCorpusDocumentsRequest,
    LocalCorpusProjectionRequest,
    LocalCorpusSearchHitResult,
    LocalCorpusSearchRequest,
    LocalCorpusSearchResult,
)


def _document(
    *,
    name: str = "synthetic.txt",
    media_type: str = "text/plain",
    content: bytes = b"Synthetic corpus marker.",
) -> dict[str, object]:
    return {
        "displayName": name,
        "declaredMediaType": media_type,
        "contentBase64": base64.b64encode(content).decode("ascii"),
        "expectedSizeBytes": len(content),
        "expectedSha256": hashlib.sha256(content).hexdigest(),
    }


def test_document_batch_contract_is_exact_hash_bound_and_repr_safe() -> None:
    body = {
        "documents": (
            _document(),
            _document(
                name="synthetic.json",
                media_type="application/json",
                content=b'{"note":"Synthetic JSON marker"}',
            ),
        ),
        "semanticEnrichmentEnabled": True,
    }
    parsed = LocalCorpusDocumentsRequest.model_validate(body)

    assert parsed.model_dump(mode="json", by_alias=True) == {
        **body,
        "documents": list(body["documents"]),
    }
    assert parsed.documents[0].decoded_content() == b"Synthetic corpus marker."
    assert len(parsed.input_manifest_sha256) == 64
    assert "Synthetic corpus marker" not in repr(parsed)
    assert "content_base64" not in repr(parsed.documents[0])


@pytest.mark.parametrize(
    "mutation",
    (
        {"expectedSizeBytes": 1},
        {"expectedSha256": "0" * 64},
        {"contentBase64": "YWJ="},
    ),
)
def test_document_rejects_size_hash_and_noncanonical_base64_mismatches(
    mutation: dict[str, object],
) -> None:
    body = _document(content=b"abc")
    body.update(mutation)

    with pytest.raises(ValidationError, match=r"binding|encoding"):
        LocalCorpusDocumentsRequest.model_validate({"documents": (body,)})


@pytest.mark.parametrize(
    ("name", "media_type"),
    (
        ("../synthetic.txt", "text/plain"),
        ("synthetic.exe", "text/plain"),
        ("synthetic.txt", "application/json"),
        ("synthetic.json", "text/plain"),
        ("synthetic\n.json", "application/json"),
    ),
)
def test_document_rejects_paths_unsupported_suffixes_and_media_mismatches(
    name: str,
    media_type: str,
) -> None:
    with pytest.raises(ValidationError):
        LocalCorpusDocumentsRequest.model_validate(
            {"documents": (_document(name=name, media_type=media_type),)}
        )


def test_batch_enforces_aggregate_decoded_byte_limit() -> None:
    chunk = b"x" * 900_000
    documents = tuple(_document(name=f"synthetic-{index}.txt", content=chunk) for index in range(5))

    with pytest.raises(ValidationError, match="aggregate byte limit"):
        LocalCorpusDocumentsRequest.model_validate({"documents": documents})


def test_search_and_projection_queries_are_closed_and_bounded() -> None:
    base = {"documents": (_document(),)}
    search = LocalCorpusSearchRequest.model_validate(
        {**base, "query": "Synthetic marker", "limit": 20}
    )
    projection = LocalCorpusProjectionRequest.model_validate(
        {**base, "query": "Synthetic marker", "maxSegments": 100}
    )

    assert search.query == projection.query
    for mutation in (
        {"query": " leading"},
        {"query": "line\nbreak"},
        {"query": "x" * 513},
        {"query": "valid", "limit": 101},
        {"query": "valid", "unexpected": True},
    ):
        with pytest.raises(ValidationError):
            LocalCorpusSearchRequest.model_validate({**base, **mutation})


def test_search_result_contract_hides_excerpts_and_binds_provenance() -> None:
    source_hash = "1" * 64
    document_id = f"corpus-document:0001:{source_hash}"
    hit = {
        "segmentId": f"{document_id}:segment:0",
        "documentId": document_id,
        "documentName": "synthetic.txt",
        "segmentIndex": 0,
        "locator": "line:1",
        "score": 1_010_001,
        "matchedTerms": ("synthetic",),
        "excerpt": "Synthetic result excerpt.",
    }
    result = LocalCorpusSearchResult.model_validate(
        {
            "corpusId": f"corpus:{'2' * 64}",
            "inputManifestSha256": "3" * 64,
            "documentCount": 1,
            "segmentCount": 1,
            "entityCount": 0,
            "restrictedValuesRedacted": 0,
            "localOnly": True,
            "rawSourcesRetained": False,
            "query": "synthetic",
            "hits": (hit,),
        }
    )

    assert isinstance(result.hits[0], LocalCorpusSearchHitResult)
    assert result.hits[0].segment_id.startswith(document_id)
    assert "Synthetic result excerpt" not in repr(result)
    with pytest.raises(ValidationError):
        LocalCorpusSearchResult.model_validate(
            {**result.model_dump(by_alias=True), "rawSourcesRetained": True}
        )
