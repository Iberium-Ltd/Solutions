from __future__ import annotations

from ariadne_core.domain.identity_compiler import compile_text
from ariadne_core.domain.semantic_enrichment import (
    RelationshipType,
    SemanticEntityType,
    enrich_semantics,
)


def test_semantic_rules_preserve_explainable_people_relationships_and_history() -> None:
    text = (
        "Morgan Vale uses the historical handle @night_orbit.\n"
        "Morgan Vale worked at Northbridge Systems.\n"
        "Morgan Vale lived in Greyhaven."
    )
    deterministic = compile_text(text)
    result = enrich_semantics(deterministic.redacted_text, deterministic.candidates)

    assert {(item.entity_type, item.canonical_value) for item in result.entities} >= {
        (SemanticEntityType.PERSON, "Morgan Vale"),
        (SemanticEntityType.ORGANISATION, "Northbridge Systems"),
        (SemanticEntityType.LOCATION, "Greyhaven"),
    }
    assert {item.relationship_type for item in result.relationships} >= {
        RelationshipType.PREVIOUS_USERNAME,
        RelationshipType.EMPLOYED_BY,
        RelationshipType.LIVED_AT,
    }
    assert all(item.explanation_code for item in result.relationships)


def test_semantic_rules_never_reintroduce_quarantined_text_or_silent_model_claims() -> None:
    secret = "synthetic-secret-marker"
    compiled = compile_text(f"Morgan Vale uses @night_orbit. Password: {secret}.\nThis is not me.")
    result = enrich_semantics(compiled.redacted_text, compiled.candidates)

    assert secret not in repr(compiled)
    assert secret not in repr(result)
    assert result.engine_name == "bounded-semantic-rules"
    assert result.exclusion_spans
    assert all(item.confidence_micros < 1_000_000 for item in result.entities)


def test_relationships_use_person_mentions_in_the_same_sentence() -> None:
    text = (
        "Alice Smith worked at Alpha Corp. "
        "Bob Jones worked at Beta Corp. "
        "Alice Smith worked at Gamma Corp. "
        "Unrelated note uses @detached_handle."
    )
    compiled = compile_text(text)
    result = enrich_semantics(compiled.redacted_text, compiled.candidates)
    edges = {
        (
            relationship.source.canonical_value,
            relationship.target.canonical_value,
            relationship.relationship_type,
        )
        for relationship in result.relationships
    }

    assert ("Alice Smith", "Gamma Corp", RelationshipType.EMPLOYED_BY) in edges
    assert ("Bob Jones", "Gamma Corp", RelationshipType.EMPLOYED_BY) not in edges
    assert all(target != "detached_handle" for _source, target, _kind in edges)


def test_negation_never_becomes_a_positive_relationship_and_sensitive_repr_is_masked() -> None:
    alias = "Synthetic Secret Alias"
    text = (
        f"My name is Morgan Vale. Known as {alias}. "
        "Morgan Vale never worked at Acme Labs. "
        "Morgan Vale does not live in Greyhaven."
    )
    compiled = compile_text(text)
    result = enrich_semantics(compiled.redacted_text, compiled.candidates)

    assert result.exclusion_spans
    assert all(
        relationship.target.canonical_value not in {"Acme Labs", "Greyhaven"}
        for relationship in result.relationships
    )
    assert alias not in repr(result)
    assert all(entity.sensitivity.value == "SENSITIVE" for entity in result.entities)


def test_labelled_rows_extract_people_without_absorbing_trailing_columns() -> None:
    text = "name,Synthetic Person,current,Primary name\nperson;Second Example;historical;Prior name"
    compiled = compile_text(text)

    result = enrich_semantics(compiled.redacted_text, compiled.candidates)

    people = {
        entity.canonical_value
        for entity in result.entities
        if entity.entity_type is SemanticEntityType.PERSON
    }
    assert people == {"Synthetic Person", "Second Example"}
