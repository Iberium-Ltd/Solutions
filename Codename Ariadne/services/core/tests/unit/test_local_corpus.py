from __future__ import annotations

import hashlib
import json

import pytest

from ariadne_core.application.local_corpus import (
    LocalCorpusBuildError,
    LocalCorpusDocumentInput,
    LocalCorpusLimits,
    build_local_corpus,
)
from ariadne_core.domain.local_corpus import (
    CorpusQueryError,
    build_corpus_analysis_projection,
)


def _synthetic_documents() -> tuple[LocalCorpusDocumentInput, ...]:
    return (
        LocalCorpusDocumentInput(
            display_name="synthetic-notes.txt",
            declared_media_type="text/plain",
            content=(
                b"Morgan Vale uses @night_orbit and synthetic.person@example.invalid.\n"
                b"Morgan Vale worked at Example Observatory."
            ),
        ),
        LocalCorpusDocumentInput(
            display_name="synthetic-history.md",
            declared_media_type="text/markdown",
            content=(
                b"# Synthetic history\n"
                b"The historical contact was synthetic.person@example.invalid.\n"
                b"Morgan Vale lived in Sample City."
            ),
        ),
        LocalCorpusDocumentInput(
            display_name="synthetic-accounts.csv",
            declared_media_type="text/csv",
            content=(b"email,profile id\nsynthetic.person@example.invalid,synthetic-profile-42\n"),
        ),
        LocalCorpusDocumentInput(
            display_name="synthetic-profile.json",
            declared_media_type="application/json",
            content=(
                b'{"name":"Morgan Vale","email":"synthetic.person@example.invalid",'
                b'"location":"Sample City"}'
            ),
        ),
        LocalCorpusDocumentInput(
            display_name="synthetic-contact.vcf",
            declared_media_type="text/vcard",
            content=(
                b"BEGIN:VCARD\nVERSION:4.0\nFN:Morgan Vale\n"
                b"EMAIL:synthetic.person@example.invalid\nEND:VCARD\n"
            ),
        ),
    )


def test_builds_all_supported_formats_with_provenance_and_deduplication() -> None:
    corpus = build_local_corpus(_synthetic_documents())

    assert [document.source_format for document in corpus.documents] == [
        "TEXT",
        "MARKDOWN",
        "CSV",
        "JSON",
        "VCARD",
    ]
    assert corpus.raw_sources_retained is False
    assert len(corpus.segments) >= 10
    segment_ids = {segment.segment_id for segment in corpus.segments}
    email_entities = [entity for entity in corpus.entities if entity.entity_type == "EMAIL"]
    assert len(email_entities) == 1
    assert {occurrence.document_id for occurrence in email_entities[0].occurrences} == {
        document.document_id for document in corpus.documents
    }
    assert all(occurrence.segment_id in segment_ids for occurrence in email_entities[0].occurrences)
    assert any(entity.entity_type == "PERSON" for entity in corpus.entities)


def test_restricted_values_never_reach_segments_search_projection_or_repr() -> None:
    secret = "synthetic-corpus-secret-canary"
    corpus = build_local_corpus(
        (
            LocalCorpusDocumentInput(
                display_name="synthetic-secret.json",
                declared_media_type="application/json",
                content=(
                    '{"password":"'
                    + secret
                    + '","email":"safe@example.invalid","note":"safe marker"}'
                ).encode(),
            ),
        )
    )
    projection = build_corpus_analysis_projection(corpus)

    assert corpus.restricted_value_count >= 1
    assert secret not in repr(corpus)
    assert secret not in " ".join(segment.text for segment in corpus.segments)
    assert secret not in projection.canonical_json
    assert corpus.search(secret) == ()
    assert corpus.search("safe marker")


def test_search_is_case_insensitive_stable_and_uses_all_terms() -> None:
    corpus = build_local_corpus(_synthetic_documents())

    first = corpus.search("MORGAN observatory")
    second = corpus.search("MORGAN observatory")

    assert first == second
    assert len(first) == 1
    assert "Example Observatory" in first[0].excerpt
    assert first[0].matched_terms == ("morgan", "observatory")
    assert corpus.search("Morgan nonexistent") == ()
    with pytest.raises(CorpusQueryError, match="must not be empty"):
        corpus.search("  ")


def test_projection_is_canonical_citation_ready_and_bounded() -> None:
    corpus = build_local_corpus(_synthetic_documents())
    first = build_corpus_analysis_projection(
        corpus,
        query="observatory",
        max_bytes=8_192,
        max_segments=10,
    )
    second = build_corpus_analysis_projection(
        corpus,
        query="observatory",
        max_bytes=8_192,
        max_segments=10,
    )
    payload = json.loads(first.canonical_json)

    assert first == second
    assert first.input_sha256 == hashlib.sha256(first.canonical_json.encode()).hexdigest()
    assert len(first.canonical_json.encode()) <= 8_192
    assert first.local_only is True
    assert first.raw_sources_included is False
    assert first.included_segments == 1
    assert first.references
    assert {record["ref"] for record in payload["records"]} == set(first.references)
    assert any(record["kind"] == "DOCUMENT_SEGMENT" for record in payload["records"])
    assert "Example Observatory" in first.canonical_json


def test_batch_limits_fail_before_unbounded_processing() -> None:
    document = LocalCorpusDocumentInput(
        display_name="synthetic.txt",
        declared_media_type="text/plain",
        content=b"synthetic marker",
    )
    with pytest.raises(LocalCorpusBuildError, match="document limit"):
        build_local_corpus((document, document), limits=LocalCorpusLimits(max_documents=1))
    with pytest.raises(LocalCorpusBuildError, match="byte limit"):
        build_local_corpus(
            (document,),
            limits=LocalCorpusLimits(max_total_bytes=4),
        )
    with pytest.raises(LocalCorpusBuildError, match="at least one"):
        build_local_corpus(())
    with pytest.raises(LocalCorpusBuildError, match="occurrence limit"):
        build_local_corpus(
            (
                LocalCorpusDocumentInput(
                    display_name="synthetic-occurrences.txt",
                    declared_media_type="text/plain",
                    content=b"first@example.invalid second@example.invalid",
                ),
            ),
            limits=LocalCorpusLimits(max_entity_occurrences=1),
        )
