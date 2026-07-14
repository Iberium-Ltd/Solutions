from __future__ import annotations

import json
import traceback
from dataclasses import asdict

import pytest

from ariadne_core.domain.identity_compiler import (
    CandidateEntity,
    EntityType,
    ExtractionLimits,
    RestrictedInputError,
    RestrictedKind,
    Sensitivity,
    SourceSpan,
    TextLimitExceeded,
    UnsafeTextError,
    classify_sensitivity,
    compile_intake_text,
    compile_text,
    deduplicate_candidates,
    detect_restricted_values,
    extract_candidates,
    normalize_candidate_value,
)


def _luhn_value(body: str) -> str:
    for check_digit in "0123456789":
        candidate = f"{body}{check_digit}"
        digits = [int(character) for character in candidate]
        parity = len(digits) % 2
        total = 0
        for index, digit in enumerate(digits):
            if index % 2 == parity:
                digit *= 2
                total += digit - 9 if digit > 9 else digit
            else:
                total += digit
        if total % 10 == 0:
            return candidate
    raise AssertionError("synthetic Luhn construction failed")


def _synthetic_iban() -> str:
    country = "ZZ"
    bban = "SYNTHETIC00001"
    rearranged = f"{bban}{country}00"
    numeric = "".join(
        str(ord(character) - 55) if character.isalpha() else character for character in rearranged
    )
    check_digits = 98 - (int(numeric) % 97)
    return f"{country}{check_digits:02d}{bban}"


def _candidate_map(text: str) -> dict[tuple[EntityType, str], CandidateEntity]:
    return {(item.entity_type, item.canonical_value): item for item in extract_candidates(text)}


def test_restricted_scan_quarantines_supported_classes_without_echoing_values() -> None:
    password = "synthetic-" + "credential"
    one_time_code = "42" + "4200"
    payment_card = _luhn_value("400000000000000")
    bank_account = _synthetic_iban()
    government_id = "SYNTH-" + "DOC-2048"
    auth_secret = "synthetic_" + "token_material"
    auth_link = "https://login.example.invalid/reset?token=" + ("x" * 24)
    key_block = "\n".join(
        (
            "-----" + "BEGIN PRIVATE KEY" + "-----",
            "synthetic-non-key-material",
            "-----" + "END PRIVATE KEY" + "-----",
        )
    )
    text = "\n".join(
        (
            f"password: {password}",
            f"otp: {one_time_code}",
            f"card number: {payment_card}",
            f"IBAN: {bank_account}",
            f"passport number: {government_id}",
            f"access token: {auth_secret}",
            auth_link,
            key_block,
        )
    )

    scan = detect_restricted_values(text)

    assert {descriptor.kind for descriptor in scan.descriptors} == set(RestrictedKind)
    assert [descriptor.ordinal for descriptor in scan.descriptors] == list(
        range(len(scan.descriptors))
    )
    assert len(scan.redacted_text) == len(text)
    serialized_descriptors = json.dumps(
        [asdict(descriptor) for descriptor in scan.descriptors], default=str
    )
    for value in (
        password,
        one_time_code,
        payment_card,
        bank_account,
        government_id,
        auth_secret,
        auth_link,
        key_block,
    ):
        assert value not in scan.redacted_text
        assert value not in serialized_descriptors
        assert value not in repr(scan)


def test_compile_text_redacts_before_extracting_and_keeps_safe_source_spans() -> None:
    secret = "synthetic-" + "credential"
    email = "audit.user@example.invalid"
    text = f"Contact {email}; handle @audit_handle\npassword: {secret}"

    result = compile_text(text)

    assert compile_intake_text is compile_text
    assert len(result.quarantine) == 1
    assert secret not in result.redacted_text
    assert secret not in repr(result)
    values = {(candidate.entity_type, candidate.canonical_value) for candidate in result.candidates}
    assert (EntityType.EMAIL, email) in values
    assert (EntityType.USERNAME, "audit_handle") in values
    for candidate in result.candidates:
        for span in candidate.spans:
            assert result.redacted_text[span.start : span.end].strip()


def test_labelled_rows_extract_bare_usernames_without_treating_status_as_a_handle() -> None:
    text = (
        "username,synthetic_handle,current,Primary username\n"
        "handle: second.synthetic, historical\n"
        "status,current,metadata only"
    )

    result = compile_text(text)
    usernames = {
        candidate.canonical_value
        for candidate in result.candidates
        if candidate.entity_type is EntityType.USERNAME
    }

    assert usernames == {"synthetic_handle", "second.synthetic"}


def test_json_shaped_restricted_fields_are_quarantined_before_parsing() -> None:
    secret = "synthetic-json-secret"
    result = compile_text(
        '{"password":"' + secret + '","otp":"654321","email":"person@example.invalid"}'
    )

    assert {item.kind for item in result.quarantine} >= {
        RestrictedKind.PASSWORD,
        RestrictedKind.ONE_TIME_CODE,
    }
    assert secret not in result.redacted_text
    assert secret not in repr(result)
    assert any(item.entity_type is EntityType.EMAIL for item in result.candidates)


def test_session_bearing_authentication_links_are_quarantined() -> None:
    session_value = "synthetic-session-material"
    link = f"https://login.example.invalid/account?session={session_value}"

    result = compile_text(link)

    assert any(
        descriptor.kind is RestrictedKind.AUTHENTICATION_LINK for descriptor in result.quarantine
    )
    assert session_value not in result.redacted_text
    assert link not in repr(result)


def test_historical_username_defaults_to_sensitive() -> None:
    result = compile_text("Synthetic Person used the historical handle @old_handle.")
    username = next(item for item in result.candidates if item.entity_type is EntityType.USERNAME)
    assert username.sensitivity is Sensitivity.SENSITIVE
    assert username.display_mask != username.canonical_value


def test_direct_extraction_fails_closed_when_quarantine_was_bypassed() -> None:
    restricted = "synthetic-" + "credential"

    with pytest.raises(RestrictedInputError) as exc_info:
        extract_candidates(f"password: {restricted}")

    assert restricted not in str(exc_info.value)
    assert restricted not in repr(exc_info.value)


def test_long_restricted_tokens_are_fully_redacted_instead_of_partially_matched() -> None:
    restricted = "x" * 4_096
    text = f"password: {restricted}\nEmail: safe@example.invalid"

    scan = detect_restricted_values(text)

    assert len(scan.descriptors) == 1
    assert restricted not in scan.redacted_text
    assert "x" * 32 not in scan.redacted_text
    assert "safe@example.invalid" in scan.redacted_text


@pytest.mark.parametrize(
    "label",
    ("password", "passwd", "passphrase", "pwd"),
)
def test_unquoted_password_phrases_are_redacted_through_end_of_line(label: str) -> None:
    phrase = "alpha bravo charlie"
    text = f"{label}: {phrase}\nEmail: safe@example.invalid"

    scan = detect_restricted_values(text)

    assert len(scan.descriptors) == 1
    assert scan.descriptors[0].kind is RestrictedKind.PASSWORD
    assert phrase not in scan.redacted_text
    assert "bravo charlie" not in scan.redacted_text
    assert "safe@example.invalid" in scan.redacted_text


def test_quoted_password_phrase_redaction_stops_at_the_closing_quote() -> None:
    phrase = "alpha bravo charlie"
    text = '{"password":"' + phrase + '","email":"safe@example.invalid"}'

    scan = detect_restricted_values(text)

    assert len(scan.descriptors) == 1
    assert phrase not in scan.redacted_text
    assert "safe@example.invalid" in scan.redacted_text
    assert json.loads(scan.redacted_text)["email"] == "safe@example.invalid"


def test_escaped_quote_inside_password_is_redacted_without_leaking_a_suffix() -> None:
    phrase = 'alpha"bravo-charlie'
    text = json.dumps({"password": phrase, "email": "safe@example.invalid"})

    scan = detect_restricted_values(text)

    assert len(scan.descriptors) == 1
    assert "bravo-charlie" not in scan.redacted_text
    decoded = json.loads(scan.redacted_text)
    assert decoded["password"].strip() == ""
    assert decoded["email"] == "safe@example.invalid"


def test_overlapping_auth_link_and_password_spans_union_without_suffix_leak() -> None:
    suffix = "trailing-secret"
    text = (
        "password: https://login.example.invalid/reset?token=synthetic-token "
        f"{suffix}\nEmail: safe@example.invalid"
    )

    scan = detect_restricted_values(text)

    assert scan.descriptors
    assert suffix not in scan.redacted_text
    assert "synthetic-token" not in scan.redacted_text
    assert "safe@example.invalid" in scan.redacted_text


@pytest.mark.parametrize("value", ("x", "xy"))
def test_explicit_short_password_values_are_not_exempt_from_redaction(value: str) -> None:
    scan = detect_restricted_values(f"password: {value}\nSafe marker")

    assert len(scan.descriptors) == 1
    assert scan.descriptors[0].kind is RestrictedKind.PASSWORD
    assert value not in scan.redacted_text.splitlines()[0]
    assert "Safe marker" in scan.redacted_text


def test_deterministic_extractors_emit_typed_normalized_candidates() -> None:
    wallet = "0x" + ("ab" * 20)
    text = "\n".join(
        (
            "Email: audit.user@EXAMPLE.INVALID",
            "Phone: +999 (555) 010-204",
            "Profile: https://Portal.Example.Invalid:443/profile?id=42",
            "Handle: @synthetic_handle",
            "IPv4: 192.0.2.44",
            "IPv6: 2001:db8::7",
            "DOB: 2000-02-29",
            "Coordinates: 48.1230, 11.4560",
            "Domain: Signals.Example.Invalid",
            "company number: ARI-2048",
            "platform id: synthetic.account-7",
            "postal code: ZZ-0000",
            f"wallet: {wallet}",
        )
    )

    candidates = _candidate_map(text)

    expected = {
        (EntityType.EMAIL, "audit.user@example.invalid"),
        (EntityType.TELEPHONE, "+999555010204"),
        (EntityType.URL, "https://portal.example.invalid/profile?id=42"),
        (EntityType.USERNAME, "synthetic_handle"),
        (EntityType.IP_ADDRESS, "192.0.2.44"),
        (EntityType.IP_ADDRESS, "2001:db8::7"),
        (EntityType.DATE, "2000-02-29"),
        (EntityType.COORDINATE, "48.123,11.456"),
        (EntityType.DOMAIN, "signals.example.invalid"),
        (EntityType.COMPANY_NUMBER, "ARI-2048"),
        (EntityType.PLATFORM_ID, "synthetic.account-7"),
        (EntityType.POSTAL_CODE, "ZZ-0000"),
        (EntityType.WALLET_ADDRESS, wallet),
    }
    assert expected <= set(candidates)
    assert [candidate.ordinal for candidate in extract_candidates(text)] == list(
        range(len(candidates))
    )
    assert (
        candidates[(EntityType.TELEPHONE, "+999555010204")].sensitivity
        is Sensitivity.HIGHLY_SENSITIVE
    )
    assert candidates[(EntityType.DATE, "2000-02-29")].sensitivity is Sensitivity.HIGHLY_SENSITIVE
    assert candidates[(EntityType.COMPANY_NUMBER, "ARI-2048")].sensitivity is Sensitivity.PUBLIC
    assert candidates[(EntityType.EMAIL, "audit.user@example.invalid")].display_mask == (
        "a•••@example.invalid"
    )


def test_normalization_deduplicates_exact_semantics_and_retains_all_spans() -> None:
    text = " ".join(
        (
            "repeat@Example.Invalid",
            "repeat@example.invalid",
            "https://portal.example.invalid:443/path",
            "https://portal.example.invalid/path",
            "+999 555 010 204",
            "+999-555-010-204",
        )
    )

    candidates = _candidate_map(text)

    assert len(candidates[(EntityType.EMAIL, "repeat@example.invalid")].spans) == 2
    assert len(candidates[(EntityType.URL, "https://portal.example.invalid/path")].spans) == 2
    assert len(candidates[(EntityType.TELEPHONE, "+999555010204")].spans) == 2


def test_email_local_part_case_is_not_unsafely_merged() -> None:
    candidates = extract_candidates("Case@example.invalid case@example.invalid")
    emails = {
        candidate.canonical_value
        for candidate in candidates
        if candidate.entity_type is EntityType.EMAIL
    }
    assert emails == {"Case@example.invalid", "case@example.invalid"}


def test_public_normalization_and_sensitivity_helpers_are_conservative() -> None:
    assert normalize_candidate_value(EntityType.DOMAIN, "EXAMPLE.INVALID.") == "example.invalid"
    assert normalize_candidate_value(EntityType.TELEPHONE, "00999 555 010 204") == ("+999555010204")
    assert classify_sensitivity(EntityType.USERNAME) is Sensitivity.PUBLIC
    assert classify_sensitivity(EntityType.EMAIL) is Sensitivity.SENSITIVE
    assert classify_sensitivity(EntityType.TELEPHONE) is Sensitivity.HIGHLY_SENSITIVE
    assert (
        classify_sensitivity(EntityType.DATE, context_before="date of birth: ")
        is Sensitivity.HIGHLY_SENSITIVE
    )
    assert (
        classify_sensitivity(EntityType.DATE, context_before="observed: ") is Sensitivity.SENSITIVE
    )


def test_explicit_deduplication_uses_conservative_sensitivity_and_provenance() -> None:
    first = CandidateEntity(
        entity_type=EntityType.DATE,
        canonical_value="2000-02-29",
        display_mask="2000-••-••",
        sensitivity=Sensitivity.SENSITIVE,
        spans=(SourceSpan(0, 10),),
    )
    second = CandidateEntity(
        entity_type=EntityType.DATE,
        canonical_value="2000-02-29",
        display_mask="2000-••-••",
        sensitivity=Sensitivity.HIGHLY_SENSITIVE,
        spans=(SourceSpan(20, 30),),
    )

    result = deduplicate_candidates((first, second))

    assert len(result) == 1
    assert result[0].sensitivity is Sensitivity.HIGHLY_SENSITIVE
    assert result[0].spans == (SourceSpan(0, 10), SourceSpan(20, 30))


def test_strict_text_and_card_validation_avoid_silent_truncation() -> None:
    with pytest.raises(TextLimitExceeded, match="byte limit"):
        detect_restricted_values("é" * 6, limits=ExtractionLimits(max_text_bytes=8))
    with pytest.raises(UnsafeTextError, match="control"):
        detect_restricted_values("safe\x00text")
    invalid_luhn = "4" + ("0" * 14) + "1"
    assert not detect_restricted_values(f"unlabelled {invalid_luhn}").descriptors
    assert not extract_candidates("date 2026-02-30 and IP 999.999.999.999")


def test_configured_item_and_candidate_bounds_fail_closed() -> None:
    otp_one = "11" + "2233"
    otp_two = "44" + "5566"
    with pytest.raises(TextLimitExceeded, match="restricted item"):
        detect_restricted_values(
            f"otp: {otp_one}\notp: {otp_two}",
            limits=ExtractionLimits(max_restricted_items=1),
        )
    with pytest.raises(TextLimitExceeded, match="occurrence"):
        extract_candidates(
            "one@example.invalid two@example.invalid",
            limits=ExtractionLimits(max_candidate_occurrences=1, max_candidates=1),
        )
    with pytest.raises(TextLimitExceeded, match="unique candidate"):
        extract_candidates(
            "one@example.invalid two@example.invalid",
            limits=ExtractionLimits(max_candidate_occurrences=2, max_candidates=1),
        )
    with pytest.raises(TextLimitExceeded, match="candidate value"):
        extract_candidates(
            "long-local@example.invalid",
            limits=ExtractionLimits(max_value_chars=8),
        )


def test_compilation_is_repeatable_and_candidate_repr_masks_exact_values() -> None:
    text = "audit.user@example.invalid @synthetic_handle 192.0.2.44"

    first = compile_text(text)
    second = compile_text(text)

    assert first == second
    for candidate in first.candidates:
        assert candidate.canonical_value not in repr(candidate)


@pytest.mark.parametrize(
    ("entity_type", "rejected"),
    (
        (EntityType.IP_ADDRESS, "999.999.999.999"),
        (EntityType.DATE, "2026-02-30"),
        (EntityType.URL, "https://example.invalid:not-a-port/"),
        (EntityType.DOMAIN, "not_a_domain.invalid"),
    ),
)
def test_normalization_tracebacks_never_echo_rejected_values(
    entity_type: EntityType, rejected: str
) -> None:
    try:
        normalize_candidate_value(entity_type, rejected)
    except ValueError as error:
        rendered = "".join(traceback.format_exception(error))
    else:
        raise AssertionError("invalid synthetic value was accepted")

    assert rejected not in rendered
