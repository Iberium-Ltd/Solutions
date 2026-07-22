"""Bounded deterministic identity extraction with restricted-value isolation.

The module is deliberately pure: it performs no I/O, persistence, logging, or
network access.  Restricted matches are represented only by type and source
coordinates; their plaintext is never returned in a descriptor or exception.
Quarantine always precedes extraction, and canonical deduplication retains all
distinct source spans so a merged identity never loses its provenance.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import parse_qsl, urlsplit, urlunsplit


class Sensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    SENSITIVE = "SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"
    RESTRICTED = "RESTRICTED"


class EntityType(StrEnum):
    USERNAME = "USERNAME"
    EMAIL = "EMAIL"
    TELEPHONE = "TELEPHONE"
    DOMAIN = "DOMAIN"
    URL = "URL"
    DATE = "DATE"
    IP_ADDRESS = "IP_ADDRESS"
    COORDINATE = "COORDINATE"
    COMPANY_NUMBER = "COMPANY_NUMBER"
    PLATFORM_ID = "PLATFORM_ID"
    POSTAL_CODE = "POSTAL_CODE"
    WALLET_ADDRESS = "WALLET_ADDRESS"


class RestrictedKind(StrEnum):
    PASSWORD = "PASSWORD"
    ONE_TIME_CODE = "ONE_TIME_CODE"
    PAYMENT_CARD = "PAYMENT_CARD"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    GOVERNMENT_IDENTIFIER = "GOVERNMENT_IDENTIFIER"
    PRIVATE_KEY = "PRIVATE_KEY"
    AUTHENTICATION_SECRET = "AUTHENTICATION_SECRET"
    AUTHENTICATION_LINK = "AUTHENTICATION_LINK"


class QuarantineReason(StrEnum):
    RESTRICTED_VALUE = "RESTRICTED_VALUE"


class IdentityCompilerError(ValueError):
    """Base error whose messages never contain source text."""


class TextLimitExceeded(IdentityCompilerError):
    """Raised when bounded processing cannot safely continue."""


class UnsafeTextError(IdentityCompilerError):
    """Raised when text contains controls outside the safe plaintext subset."""


class RestrictedInputError(IdentityCompilerError):
    """Raised when a caller bypasses quarantine and requests direct extraction."""


class CandidateNormalizationError(IdentityCompilerError):
    """Raised when a proposed value is not valid for its declared type."""


_HARD_MAX_TEXT_BYTES = 1_048_576
_HARD_MAX_RESTRICTED_ITEMS = 512
_HARD_MAX_CANDIDATE_OCCURRENCES = 8_192
_HARD_MAX_CANDIDATES = 2_048
_HARD_MAX_VALUE_CHARS = 2_048


@dataclass(frozen=True, slots=True)
class ExtractionLimits:
    max_text_bytes: int = _HARD_MAX_TEXT_BYTES
    max_restricted_items: int = 256
    max_candidate_occurrences: int = 4_096
    max_candidates: int = 1_024
    max_value_chars: int = _HARD_MAX_VALUE_CHARS

    def __post_init__(self) -> None:
        values_and_caps = (
            (self.max_text_bytes, _HARD_MAX_TEXT_BYTES),
            (self.max_restricted_items, _HARD_MAX_RESTRICTED_ITEMS),
            (self.max_candidate_occurrences, _HARD_MAX_CANDIDATE_OCCURRENCES),
            (self.max_candidates, _HARD_MAX_CANDIDATES),
            (self.max_value_chars, _HARD_MAX_VALUE_CHARS),
        )
        if any(value < 1 or value > cap for value, cap in values_and_caps):
            raise ValueError("extraction limits must be positive and within hard bounds")
        if self.max_candidates > self.max_candidate_occurrences:
            raise ValueError("candidate limit cannot exceed occurrence limit")


@dataclass(frozen=True, slots=True, order=True)
class SourceSpan:
    """Half-open Unicode-code-point offsets in the original safe text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("source span must be non-empty and ordered")


@dataclass(frozen=True, slots=True)
class QuarantineDescriptor:
    """Value-free instructions for quarantining one restricted source range."""

    ordinal: int
    kind: RestrictedKind
    span: SourceSpan
    reason: QuarantineReason = QuarantineReason.RESTRICTED_VALUE
    sensitivity: Sensitivity = Sensitivity.RESTRICTED
    masked_preview: str = "[restricted]"


@dataclass(frozen=True, slots=True)
class RestrictedScan:
    descriptors: tuple[QuarantineDescriptor, ...]
    redacted_text: str = field(repr=False)

    @property
    def has_restricted_values(self) -> bool:
        return bool(self.descriptors)


@dataclass(frozen=True, slots=True)
class CandidateEntity:
    entity_type: EntityType
    canonical_value: str = field(repr=False)
    display_mask: str = field(repr=False)
    sensitivity: Sensitivity
    spans: tuple[SourceSpan, ...]
    ordinal: int = 0
    extractor: str = "deterministic-v1"
    confidence_micros: int = 1_000_000

    def __post_init__(self) -> None:
        if not self.canonical_value or len(self.canonical_value) > _HARD_MAX_VALUE_CHARS:
            raise ValueError("candidate canonical value is outside hard bounds")
        if not self.spans:
            raise ValueError("candidate must retain at least one source span")
        if self.ordinal < 0:
            raise ValueError("candidate ordinal must be non-negative")
        if not 0 <= self.confidence_micros <= 1_000_000:
            raise ValueError("candidate confidence must use micro-probability bounds")


@dataclass(frozen=True, slots=True)
class CompilationResult:
    quarantine: tuple[QuarantineDescriptor, ...]
    candidates: tuple[CandidateEntity, ...]
    redacted_text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _RestrictedHit:
    start: int
    end: int
    kind: RestrictedKind


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    entity_type: EntityType
    value: str = field(repr=False)
    span: SourceSpan
    context_before: str = field(default="", repr=False)


_PASSWORD_RE = re.compile(
    r"(?i)\b(?:password|passwd|passphrase|pwd)\b[\"']?\s*(?:is|=|:)\s*"
    r'(?:(?:"(?P<double_quoted_value>(?:\\[^\r\n]|[^"\\\r\n])*)")|'
    r"(?:'(?P<single_quoted_value>(?:\\[^\r\n]|[^'\\\r\n])*)')|"
    r"(?P<bare_value>[^\s\r\n][^\r\n]*))"
)
_OTP_RE = re.compile(
    r"(?i)\b(?:otp|one[- ]time (?:code|password)|verification code|2fa code)\b[\"']?"
    r"\s*(?:is|=|:)?\s*[\"']?(?P<value>\d{4,})\b"
)
_AUTH_SECRET_RE = re.compile(
    r"(?i)\b(?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|"
    r"client[-_ ]?secret|secret[-_ ]?key)\b[\"']?\s*(?:is|=|:)\s*[\"']?"
    r"(?P<value>[^\s\"',;}\]]{8,})"
)
_CARD_CONTEXT_RE = re.compile(
    r"(?i)\b(?:payment )?card(?: number)?\b[\"']?\s*(?:is|=|:)?\s*[\"']?"
    r"(?P<value>(?:\d[ -]?){12,}\d)"
)
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?<!\d[ -])(?:\d[ -]?){12,18}\d(?![ -]?\d)")
_IBAN_RE = re.compile(r"(?i)(?<![A-Z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?! ?[A-Z0-9])")
_BANK_CONTEXT_RE = re.compile(
    r"(?i)\b(?:iban|bank account|routing number)\b[\"']?\s*(?:is|=|:)?\s*[\"']?"
    r"(?P<value>(?:[A-Z0-9]{6,}|\d(?:[ -]?\d){5,}))"
)
_GOVERNMENT_CONTEXT_RE = re.compile(
    r"(?i)\b(?:passport(?: number)?|government id|national id|identity document|"
    r"driver(?:'s)? licen[cs]e)\b[\"']?\s*(?:is|=|:)?\s*[\"']?"
    r"(?P<value>[A-Z0-9][A-Z0-9-]{4,})"
)
_SSN_SHAPE_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PRIVATE_KEY_BEGIN_RE = re.compile(
    r"-----BEGIN (?P<label>(?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY)-----"
)
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "auth",
        "auth_token",
        "code",
        "key",
        "magic",
        "password",
        "reset_token",
        "secret",
        "session",
        "session_id",
        "sid",
        "token",
    }
)
_AUTH_PATH_WORDS = frozenset({"activate", "authentication", "login", "magic", "reset", "verify"})

_EMAIL_RE = re.compile(
    r"(?i)(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"[A-Z](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
)
_HANDLE_RE = re.compile(
    r"(?<![A-Z0-9._%+-])@(?P<value>[A-Z0-9_](?:[A-Z0-9_.-]{0,29}))(?![A-Z0-9_.-])",
    re.IGNORECASE,
)
_DOMAIN_RE = re.compile(
    r"(?i)(?<![A-Z0-9@._-])(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"[A-Z](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?![A-Z0-9._-])"
)
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_IPV6_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?=[0-9A-Fa-f:]{2,45}(?![0-9A-Fa-f:]))"
    r"[0-9A-Fa-f]*:[0-9A-Fa-f:]+"
)
_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_COORDINATE_RE = re.compile(
    r"(?<![\d.])(?P<lat>[+-]?(?:\d{1,2}(?:\.\d{3,})?|90(?:\.0+)?))"
    r"\s*,\s*(?P<lon>[+-]?(?:\d{1,3}(?:\.\d{3,})?|180(?:\.0+)?))(?![\d.])"
)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+|00)?\d[\d ()-]{6,}\d(?!\w)")
_PHONE_CONTEXT_RE = re.compile(
    r"(?i)(?:\bphone\b|\btelephone\b|\bmobile\b|\btel\b)\s*(?:is|=|:)?\s*$"
)
_EVM_WALLET_RE = re.compile(r"(?i)(?<![A-F0-9])0x[A-F0-9]{40}(?![A-F0-9])")
_BECH32_WALLET_RE = re.compile(r"(?i)(?<![A-Z0-9])(?:bc1|tb1)[A-Z0-9]{11,71}(?![A-Z0-9])")
_COMPANY_NUMBER_RE = re.compile(
    r"(?i)\b(?:company|registration) number\b\s*(?:is|=|:)?\s*"
    r"(?P<value>[A-Z0-9][A-Z0-9._/-]{2,})(?![A-Z0-9._/-])"
)
_PLATFORM_ID_RE = re.compile(
    r"(?i)\b(?:platform|account|user|profile|identifier|reference) id\b"
    r"\s*(?:is|=|:)?\s*(?P<value>[A-Z0-9][A-Z0-9._/-]{2,})(?![A-Z0-9._/-])"
)
_POSTAL_CODE_RE = re.compile(
    r"(?i)\b(?:postal|zip) code\b\s*(?:is|=|:)?\s*(?P<value>"
    r"(?:[A-Z]{1,3}\d[A-Z0-9]? ?\d[A-Z]{0,2}|\d{3,10}(?:-\d{2,6})?|"
    r"[A-Z]{1,3}-\d{2,8}))"
)
_DOB_CONTEXT_RE = re.compile(r"(?i)(?:date of birth|\bdob\b|\bborn\b)\s*(?:is|=|:)?\s*$")


def _validate_text(text: str, limits: ExtractionLimits) -> None:
    if len(text) > limits.max_text_bytes:
        raise TextLimitExceeded("text character limit exceeded")
    if len(text.encode("utf-8")) > limits.max_text_bytes:
        raise TextLimitExceeded("text byte limit exceeded")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
        raise UnsafeTextError("text contains a disallowed control character")


def _trim_url_match(text: str, start: int, end: int) -> tuple[str, int]:
    value = text[start:end]
    trimmed = value.rstrip(".,;:!?)]}")
    return trimmed, start + len(trimmed)


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    parity = len(digits) % 2
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _iban_valid(value: str) -> bool:
    compact = "".join(value.split()).upper()
    if not 15 <= len(compact) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", compact):
        return False
    remainder = 0
    for char in compact[4:] + compact[:4]:
        expansion = str(ord(char) - 55) if char.isalpha() else char
        for digit in expansion:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _url_is_authentication_material(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            return True
        query_items = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=64)
        fragment_items = parse_qsl(parsed.fragment, keep_blank_values=True, max_num_fields=64)
    except ValueError:
        return True
    if any(key.casefold() in _SENSITIVE_QUERY_KEYS and bool(item) for key, item in query_items):
        return True
    if any(key.casefold() in _SENSITIVE_QUERY_KEYS and bool(item) for key, item in fragment_items):
        return True
    path_parts = tuple(part for part in parsed.path.casefold().split("/") if part)
    has_auth_word = any(part in _AUTH_PATH_WORDS for part in path_parts)
    has_opaque_path_token = any(
        len(part) >= 16
        and any(char.isdigit() for char in part)
        and any(char.isalpha() for char in part)
        for part in path_parts
    )
    return has_auth_word and has_opaque_path_token


def _add_restricted_hit(
    hits: list[_RestrictedHit],
    *,
    start: int,
    end: int,
    kind: RestrictedKind,
    limits: ExtractionLimits,
) -> None:
    if end <= start:
        return
    overlapping = [hit for hit in hits if start < hit.end and end > hit.start]
    if overlapping:
        merged_start = min(start, *(hit.start for hit in overlapping))
        merged_end = max(end, *(hit.end for hit in overlapping))
        retained_kind = overlapping[0].kind
        hits[:] = [hit for hit in hits if hit not in overlapping]
        hits.append(
            _RestrictedHit(
                start=merged_start,
                end=merged_end,
                kind=retained_kind,
            )
        )
        return
    if len(hits) >= limits.max_restricted_items:
        raise TextLimitExceeded("restricted item limit exceeded")
    hits.append(_RestrictedHit(start=start, end=end, kind=kind))


def _context_hits(
    text: str,
    pattern: re.Pattern[str],
    kind: RestrictedKind,
) -> Iterator[tuple[int, int, RestrictedKind]]:
    for match in pattern.finditer(text):
        group_name = next(
            (
                name
                for name in (
                    "value",
                    "double_quoted_value",
                    "single_quoted_value",
                    "bare_value",
                )
                if name in match.groupdict() and match.group(name) is not None
            ),
            None,
        )
        if group_name is not None:
            yield match.start(group_name), match.end(group_name), kind


def _find_restricted_hits(text: str, limits: ExtractionLimits) -> list[_RestrictedHit]:
    hits: list[_RestrictedHit] = []

    for match in _PRIVATE_KEY_BEGIN_RE.finditer(text):
        label = match.group("label")
        footer = f"-----END {label}-----"
        footer_start = text.find(footer, match.end())
        end = len(text) if footer_start < 0 else footer_start + len(footer)
        _add_restricted_hit(
            hits,
            start=match.start(),
            end=end,
            kind=RestrictedKind.PRIVATE_KEY,
            limits=limits,
        )

    for match in _URL_RE.finditer(text):
        value, end = _trim_url_match(text, match.start(), match.end())
        if _url_is_authentication_material(value):
            _add_restricted_hit(
                hits,
                start=match.start(),
                end=end,
                kind=RestrictedKind.AUTHENTICATION_LINK,
                limits=limits,
            )

    contextual_patterns = (
        (_PASSWORD_RE, RestrictedKind.PASSWORD),
        (_OTP_RE, RestrictedKind.ONE_TIME_CODE),
        (_AUTH_SECRET_RE, RestrictedKind.AUTHENTICATION_SECRET),
        (_CARD_CONTEXT_RE, RestrictedKind.PAYMENT_CARD),
        (_BANK_CONTEXT_RE, RestrictedKind.BANK_ACCOUNT),
        (_GOVERNMENT_CONTEXT_RE, RestrictedKind.GOVERNMENT_IDENTIFIER),
    )
    for pattern, kind in contextual_patterns:
        for start, end, found_kind in _context_hits(text, pattern, kind):
            _add_restricted_hit(hits, start=start, end=end, kind=found_kind, limits=limits)

    for match in _CARD_CANDIDATE_RE.finditer(text):
        if _luhn_valid(match.group()):
            _add_restricted_hit(
                hits,
                start=match.start(),
                end=match.end(),
                kind=RestrictedKind.PAYMENT_CARD,
                limits=limits,
            )

    for match in _IBAN_RE.finditer(text):
        if _iban_valid(match.group()):
            _add_restricted_hit(
                hits,
                start=match.start(),
                end=match.end(),
                kind=RestrictedKind.BANK_ACCOUNT,
                limits=limits,
            )

    for match in _SSN_SHAPE_RE.finditer(text):
        _add_restricted_hit(
            hits,
            start=match.start(),
            end=match.end(),
            kind=RestrictedKind.GOVERNMENT_IDENTIFIER,
            limits=limits,
        )

    hits.sort(key=lambda hit: (hit.start, hit.end, hit.kind.value))
    return hits


def detect_restricted_values(
    text: str, *, limits: ExtractionLimits | None = None
) -> RestrictedScan:
    """Return value-free quarantine descriptors and same-length redacted text."""

    active_limits = limits or ExtractionLimits()
    _validate_text(text, active_limits)
    hits = _find_restricted_hits(text, active_limits)
    redacted = list(text)
    for hit in hits:
        for index in range(hit.start, hit.end):
            if redacted[index] not in "\r\n":
                redacted[index] = " "
    descriptors = tuple(
        QuarantineDescriptor(
            ordinal=index,
            kind=hit.kind,
            span=SourceSpan(start=hit.start, end=hit.end),
        )
        for index, hit in enumerate(hits)
    )
    return RestrictedScan(descriptors=descriptors, redacted_text="".join(redacted))


def _normalise_domain(value: str) -> str:
    candidate = unicodedata.normalize("NFC", value.strip().rstrip(".")).casefold()
    if not candidate or len(candidate) > 253:
        raise CandidateNormalizationError("domain is outside canonical bounds")
    try:
        labels = candidate.split(".")
        if len(labels) < 2 or any(not label for label in labels):
            raise UnicodeError
        canonical = ".".join(label.encode("idna").decode("ascii") for label in labels)
    except UnicodeError:
        raise CandidateNormalizationError("domain is not canonicalisable") from None
    if any(len(label) > 63 for label in canonical.split(".")):
        raise CandidateNormalizationError("domain label is outside canonical bounds")
    if any(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
        for label in canonical.split(".")
    ):
        raise CandidateNormalizationError("domain label is invalid")
    return canonical


def _normalise_decimal(value: str, *, minimum: Decimal, maximum: Decimal) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise CandidateNormalizationError("coordinate component is invalid") from None
    if not number.is_finite() or not minimum <= number <= maximum:
        raise CandidateNormalizationError("coordinate component is outside bounds")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def normalize_candidate_value(entity_type: EntityType, value: str) -> str:
    """Canonicalise a non-restricted deterministic candidate without unsafe merging."""

    candidate = unicodedata.normalize("NFC", value.strip())
    if not candidate or len(candidate) > _HARD_MAX_VALUE_CHARS:
        raise CandidateNormalizationError("candidate value is outside canonical bounds")

    if entity_type is EntityType.EMAIL:
        if candidate.count("@") != 1:
            raise CandidateNormalizationError("email structure is invalid")
        local, domain = candidate.rsplit("@", 1)
        if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
            raise CandidateNormalizationError("email local part is invalid")
        if ".." in local:
            raise CandidateNormalizationError("email local part is invalid")
        return f"{local}@{_normalise_domain(domain)}"
    if entity_type is EntityType.DOMAIN:
        return _normalise_domain(candidate)
    if entity_type is EntityType.URL:
        try:
            parsed = urlsplit(candidate)
            if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
                raise CandidateNormalizationError("URL scheme or host is invalid")
            if parsed.username is not None or parsed.password is not None:
                raise CandidateNormalizationError("URL user information is prohibited")
            host = _normalise_domain(parsed.hostname) if "." in parsed.hostname else parsed.hostname
            try:
                host = ipaddress.ip_address(host).compressed
            except ValueError:
                host = _normalise_domain(host)
            port = parsed.port
        except ValueError:
            raise CandidateNormalizationError("URL is invalid") from None
        scheme = parsed.scheme.casefold()
        host_display = f"[{host}]" if ":" in host else host
        netloc = host_display
        if port is not None and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            netloc = f"{host_display}:{port}"
        return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))
    if entity_type is EntityType.TELEPHONE:
        compact = re.sub(r"[ ()-]", "", candidate)
        if compact.startswith("00"):
            compact = f"+{compact[2:]}"
        prefix = "+" if compact.startswith("+") else ""
        digits = compact.removeprefix("+")
        if not digits.isdigit() or not 8 <= len(digits) <= 15:
            raise CandidateNormalizationError("telephone is outside canonical bounds")
        return f"{prefix}{digits}"
    if entity_type is EntityType.IP_ADDRESS:
        try:
            return ipaddress.ip_address(candidate).compressed
        except ValueError:
            raise CandidateNormalizationError("IP address is invalid") from None
    if entity_type is EntityType.DATE:
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            raise CandidateNormalizationError("date is invalid") from None
    if entity_type is EntityType.COORDINATE:
        parts = candidate.split(",")
        if len(parts) != 2:
            raise CandidateNormalizationError("coordinate is invalid")
        latitude = _normalise_decimal(
            parts[0].strip(), minimum=Decimal("-90"), maximum=Decimal("90")
        )
        longitude = _normalise_decimal(
            parts[1].strip(), minimum=Decimal("-180"), maximum=Decimal("180")
        )
        return f"{latitude},{longitude}"
    if entity_type is EntityType.USERNAME:
        username = candidate.removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,29}", username):
            raise CandidateNormalizationError("username is invalid")
        return username
    if entity_type is EntityType.WALLET_ADDRESS:
        if re.fullmatch(r"(?i)0x[A-F0-9]{40}", candidate):
            return candidate.casefold()
        if re.fullmatch(r"(?i)(?:bc1|tb1)[A-Z0-9]{11,71}", candidate):
            return candidate.casefold()
        raise CandidateNormalizationError("wallet address is invalid")
    if entity_type is EntityType.POSTAL_CODE:
        canonical = " ".join(candidate.upper().split())
        if not 3 <= len(canonical) <= 16:
            raise CandidateNormalizationError("postal code is outside canonical bounds")
        return canonical
    if entity_type in {EntityType.COMPANY_NUMBER, EntityType.PLATFORM_ID}:
        canonical = " ".join(candidate.split())
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ /-]{2,63}", canonical):
            raise CandidateNormalizationError("identifier is invalid")
        return canonical.upper() if entity_type is EntityType.COMPANY_NUMBER else canonical
    raise CandidateNormalizationError("entity type is not supported by deterministic normalisation")


def classify_sensitivity(entity_type: EntityType, *, context_before: str = "") -> Sensitivity:
    """Apply the conservative default handling class independently of visibility."""

    if entity_type is EntityType.USERNAME and re.search(
        r"(?i)\b(?:historical|former|previous|old)\b", context_before[-64:]
    ):
        return Sensitivity.SENSITIVE
    if entity_type in {EntityType.USERNAME, EntityType.COMPANY_NUMBER}:
        return Sensitivity.PUBLIC
    if entity_type in {EntityType.TELEPHONE, EntityType.COORDINATE}:
        return Sensitivity.HIGHLY_SENSITIVE
    if entity_type is EntityType.DATE and _DOB_CONTEXT_RE.search(context_before[-64:]):
        return Sensitivity.HIGHLY_SENSITIVE
    return Sensitivity.SENSITIVE


def _mask_domain(value: str) -> str:
    labels = value.split(".")
    suffix = ".".join(labels[-2:]) if len(labels) > 2 else labels[-1]
    return f"•••.{suffix}"


def _display_mask(entity_type: EntityType, value: str, sensitivity: Sensitivity) -> str:
    if sensitivity is Sensitivity.PUBLIC:
        return value
    if entity_type is EntityType.EMAIL:
        local, domain = value.rsplit("@", 1)
        return f"{local[:1]}•••@{domain}"
    if entity_type is EntityType.DOMAIN:
        return _mask_domain(value)
    if entity_type is EntityType.URL:
        hostname = urlsplit(value).hostname or "hidden"
        return f"{urlsplit(value).scheme}://{_mask_domain(hostname)}/…"
    if entity_type is EntityType.TELEPHONE:
        return f"••••••{value[-2:]}"
    if entity_type is EntityType.DATE:
        return f"{value[:4]}-••-••"
    if entity_type is EntityType.IP_ADDRESS:
        return f"{value.split('.', 1)[0]}.•••" if "." in value else f"{value.split(':', 1)[0]}:•••"
    if entity_type is EntityType.COORDINATE:
        return "[exact location hidden]"
    if entity_type is EntityType.POSTAL_CODE:
        return "[postal code hidden]"
    if entity_type is EntityType.WALLET_ADDRESS:
        return f"{value[:4]}…{value[-4:]}"
    if len(value) <= 4:
        return "••••"
    return f"{value[:2]}…{value[-2:]}"


def _pattern_candidates(
    text: str,
    pattern: re.Pattern[str],
    entity_type: EntityType,
    *,
    group: str | int = 0,
) -> Iterator[_RawCandidate]:
    for match in pattern.finditer(text):
        start, end = match.span(group)
        yield _RawCandidate(
            entity_type=entity_type,
            value=match.group(group),
            span=SourceSpan(start=start, end=end),
            context_before=text[max(0, start - 64) : start],
        )


def _url_candidates(text: str) -> Iterator[_RawCandidate]:
    for match in _URL_RE.finditer(text):
        value, end = _trim_url_match(text, match.start(), match.end())
        yield _RawCandidate(
            entity_type=EntityType.URL,
            value=value,
            span=SourceSpan(start=match.start(), end=end),
            context_before=text[max(0, match.start() - 64) : match.start()],
        )


def _ip_candidates(text: str) -> Iterator[_RawCandidate]:
    yield from _pattern_candidates(text, _IPV4_RE, EntityType.IP_ADDRESS)
    yield from _pattern_candidates(text, _IPV6_RE, EntityType.IP_ADDRESS)


def _coordinate_candidates(text: str) -> Iterator[_RawCandidate]:
    for match in _COORDINATE_RE.finditer(text):
        yield _RawCandidate(
            entity_type=EntityType.COORDINATE,
            value=f"{match.group('lat')},{match.group('lon')}",
            span=SourceSpan(start=match.start(), end=match.end()),
            context_before=text[max(0, match.start() - 64) : match.start()],
        )


def _phone_candidates(text: str) -> Iterator[_RawCandidate]:
    for match in _PHONE_RE.finditer(text):
        value = match.group()
        starts_international = value.startswith(("+", "00"))
        context_before = text[max(0, match.start() - 32) : match.start()]
        if starts_international or _PHONE_CONTEXT_RE.search(context_before):
            yield _RawCandidate(
                entity_type=EntityType.TELEPHONE,
                value=value,
                span=SourceSpan(start=match.start(), end=match.end()),
                context_before=context_before,
            )


def _raw_candidates(text: str) -> Iterator[_RawCandidate]:
    yield from _pattern_candidates(text, _EMAIL_RE, EntityType.EMAIL)
    yield from _url_candidates(text)
    yield from _pattern_candidates(text, _HANDLE_RE, EntityType.USERNAME, group="value")
    yield from _pattern_candidates(
        text,
        re.compile(
            r"(?im)^\s*(?:username|user|handle)\s*[,;:\t]\s*"
            r"(?P<value>[A-Za-z0-9_][A-Za-z0-9_.-]{0,29})"
            r"(?=\s*(?:[,;\t]|$))"
        ),
        EntityType.USERNAME,
        group="value",
    )
    yield from _ip_candidates(text)
    yield from _coordinate_candidates(text)
    yield from _pattern_candidates(text, _ISO_DATE_RE, EntityType.DATE)
    yield from _phone_candidates(text)
    yield from _pattern_candidates(text, _DOMAIN_RE, EntityType.DOMAIN)
    yield from _pattern_candidates(text, _EVM_WALLET_RE, EntityType.WALLET_ADDRESS)
    yield from _pattern_candidates(text, _BECH32_WALLET_RE, EntityType.WALLET_ADDRESS)
    yield from _pattern_candidates(
        text, _COMPANY_NUMBER_RE, EntityType.COMPANY_NUMBER, group="value"
    )
    yield from _pattern_candidates(text, _PLATFORM_ID_RE, EntityType.PLATFORM_ID, group="value")
    yield from _pattern_candidates(text, _POSTAL_CODE_RE, EntityType.POSTAL_CODE, group="value")


def _extract_safe_text(text: str, limits: ExtractionLimits) -> tuple[CandidateEntity, ...]:
    """Extract canonical candidates while preserving every exact occurrence span."""

    grouped: dict[tuple[EntityType, str], tuple[Sensitivity, list[SourceSpan]]] = {}
    occurrences = 0
    sensitivity_rank = {
        Sensitivity.PUBLIC: 0,
        Sensitivity.SENSITIVE: 1,
        Sensitivity.HIGHLY_SENSITIVE: 2,
        Sensitivity.RESTRICTED: 3,
    }
    for raw in _raw_candidates(text):
        if len(raw.value) > limits.max_value_chars:
            raise TextLimitExceeded("candidate value limit exceeded")
        try:
            canonical = normalize_candidate_value(raw.entity_type, raw.value)
        except CandidateNormalizationError:
            continue
        if len(canonical) > limits.max_value_chars:
            raise TextLimitExceeded("candidate value limit exceeded")
        occurrences += 1
        if occurrences > limits.max_candidate_occurrences:
            raise TextLimitExceeded("candidate occurrence limit exceeded")
        key = (raw.entity_type, canonical)
        sensitivity = classify_sensitivity(raw.entity_type, context_before=raw.context_before)
        current = grouped.get(key)
        if current is None:
            if len(grouped) >= limits.max_candidates:
                raise TextLimitExceeded("unique candidate limit exceeded")
            grouped[key] = (sensitivity, [raw.span])
            continue
        current_sensitivity, spans = current
        if raw.span not in spans:
            spans.append(raw.span)
        if sensitivity_rank[sensitivity] > sensitivity_rank[current_sensitivity]:
            grouped[key] = (sensitivity, spans)

    entities = [
        CandidateEntity(
            entity_type=entity_type,
            canonical_value=canonical,
            display_mask=_display_mask(entity_type, canonical, sensitivity),
            sensitivity=sensitivity,
            spans=tuple(sorted(spans)),
        )
        for (entity_type, canonical), (sensitivity, spans) in grouped.items()
    ]
    entities.sort(
        key=lambda entity: (entity.spans[0].start, entity.entity_type.value, entity.canonical_value)
    )
    return tuple(replace(entity, ordinal=ordinal) for ordinal, entity in enumerate(entities))


def extract_candidates(
    safe_text: str, *, limits: ExtractionLimits | None = None
) -> tuple[CandidateEntity, ...]:
    """Extract from safe text, refusing inputs that still contain restricted values."""

    active_limits = limits or ExtractionLimits()
    scan = detect_restricted_values(safe_text, limits=active_limits)
    if scan.has_restricted_values:
        raise RestrictedInputError("restricted input must be quarantined before extraction")
    return _extract_safe_text(safe_text, active_limits)


def deduplicate_candidates(
    candidates: Iterable[CandidateEntity], *, limits: ExtractionLimits | None = None
) -> tuple[CandidateEntity, ...]:
    """Merge exact canonical candidates while retaining every distinct origin span."""

    active_limits = limits or ExtractionLimits()
    grouped: dict[tuple[EntityType, str], CandidateEntity] = {}
    occurrences = 0
    sensitivity_rank = {
        Sensitivity.PUBLIC: 0,
        Sensitivity.SENSITIVE: 1,
        Sensitivity.HIGHLY_SENSITIVE: 2,
        Sensitivity.RESTRICTED: 3,
    }
    for candidate in candidates:
        if candidate.sensitivity is Sensitivity.RESTRICTED:
            raise RestrictedInputError("restricted candidates cannot enter deduplication")
        occurrences += len(candidate.spans)
        if occurrences > active_limits.max_candidate_occurrences:
            raise TextLimitExceeded("candidate occurrence limit exceeded")
        key = (candidate.entity_type, candidate.canonical_value)
        existing = grouped.get(key)
        if existing is None:
            if len(grouped) >= active_limits.max_candidates:
                raise TextLimitExceeded("unique candidate limit exceeded")
            grouped[key] = candidate
            continue
        sensitivity = (
            candidate.sensitivity
            if sensitivity_rank[candidate.sensitivity] > sensitivity_rank[existing.sensitivity]
            else existing.sensitivity
        )
        spans = tuple(sorted(set(existing.spans).union(candidate.spans)))
        grouped[key] = CandidateEntity(
            entity_type=candidate.entity_type,
            canonical_value=candidate.canonical_value,
            display_mask=_display_mask(
                candidate.entity_type, candidate.canonical_value, sensitivity
            ),
            sensitivity=sensitivity,
            spans=spans,
            ordinal=min(existing.ordinal, candidate.ordinal),
            extractor=existing.extractor,
            confidence_micros=min(existing.confidence_micros, candidate.confidence_micros),
        )
    ordered = sorted(
        grouped.values(),
        key=lambda entity: (
            entity.spans[0].start,
            entity.entity_type.value,
            entity.canonical_value,
        ),
    )
    return tuple(replace(entity, ordinal=ordinal) for ordinal, entity in enumerate(ordered))


def compile_text(text: str, *, limits: ExtractionLimits | None = None) -> CompilationResult:
    """Quarantine first, then extract only from same-length redacted text.

    Equal-length redaction keeps offsets stable across quarantine descriptors,
    candidates, later human review, and evidence receipts.
    """

    active_limits = limits or ExtractionLimits()
    scan = detect_restricted_values(text, limits=active_limits)
    candidates = _extract_safe_text(scan.redacted_text, active_limits)
    return CompilationResult(
        quarantine=scan.descriptors,
        candidates=candidates,
        redacted_text=scan.redacted_text,
    )


compile_intake_text = compile_text
