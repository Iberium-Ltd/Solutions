from __future__ import annotations

from ariadne_core.application.intake_compiler import (
    prepare_file_intake,
    prepare_pasted_intake,
)


def test_pasted_intake_quarantines_before_extraction_and_keeps_safe_candidates() -> None:
    secret = "synthetic-secret-canary"
    prepared = prepare_pasted_intake(
        (
            "Morgan Vale uses @night_orbit. "
            "Contact: morgan.vale@example.invalid. "
            f"Password: {secret}."
        ),
        display_name="Synthetic pasted source",
    )

    assert prepared.quarantine_count == 1
    assert prepared.candidate_count >= 3
    assert secret not in repr(prepared)
    assert secret not in " ".join(prepared.parsed.text_segments)
    assert all(
        candidate.sensitivity.value != "RESTRICTED"
        for candidate in prepared.deterministic.candidates
    )


def test_selected_json_file_compiles_only_after_redacted_preparse_gate() -> None:
    prepared = prepare_file_intake(
        display_name="synthetic.json",
        declared_media_type="application/json",
        content=(
            b'{"profile":"Morgan Vale","email":"morgan.vale@example.invalid",'
            b'"handle":"@night_orbit"}'
        ),
    )

    assert prepared.source_kind == "FILE"
    assert prepared.detected_media_type == "application/json"
    assert prepared.candidate_count >= 2
    assert prepared.parsed.segments


def test_structured_json_and_csv_secrets_are_redacted_after_decoding() -> None:
    secret = "synthetic-escaped-secret"
    json_prepared = prepare_file_intake(
        display_name="synthetic.json",
        declared_media_type="application/json",
        content=(b'{"pass\\u0077ord":"' + secret.encode() + b'","email":"person@example.invalid"}'),
    )
    csv_prepared = prepare_file_intake(
        display_name="synthetic.csv",
        declared_media_type="text/csv",
        content=("password,email\n" + secret + ",person@example.invalid\n").encode(),
    )

    for prepared in (json_prepared, csv_prepared):
        assert prepared.quarantine_count >= 1
        assert secret not in repr(prepared)
        assert secret not in " ".join(prepared.parsed.text_segments)


def test_semantic_enrichment_can_be_disabled_without_disabling_deterministic_extraction() -> None:
    prepared = prepare_pasted_intake(
        "Morgan Vale uses @night_orbit and person@example.invalid.",
        display_name="Synthetic no-model source",
        semantic_enrichment_enabled=False,
    )

    assert prepared.deterministic.candidates
    assert prepared.semantic.entities == ()
    assert prepared.semantic.relationships == ()
