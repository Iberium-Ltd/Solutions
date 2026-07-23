"""Immutable evidence-original and redacted-derivative contracts."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit

from ariadne_core.domain.public_discovery import normalise_public_result_url

MAX_ARTIFACT_BYTES: Final = 10 * 1_024 * 1_024
MAX_URL_LENGTH: Final = 2_048
MAX_REDIRECTS: Final = 10
MAX_METADATA_ENTRIES: Final = 32
MAX_METADATA_TOTAL_CHARS: Final = 4_096
MAX_ORIGINAL_ARTIFACTS: Final = 1_000
MAX_DERIVATIVE_ARTIFACTS: Final = 2_000
MAX_TIMESTAMP_US: Final = 9_007_199_254_740_991

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MASKED_QUERY_REFERENCE = re.compile(r"^mq_[0-9a-f]{16,64}$")
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,47}$")
_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class EvidenceArtifactKind(StrEnum):
    SCREENSHOT = "SCREENSHOT"
    HTML = "HTML"
    PDF = "PDF"
    RAW_JSON = "RAW_JSON"
    URL_REFERENCE = "URL_REFERENCE"


class EvidenceCaptureMethod(StrEnum):
    BROWSER_CAPTURE = "BROWSER_CAPTURE"
    HTTP_FETCH = "HTTP_FETCH"
    PROVIDER_API = "PROVIDER_API"
    MANUAL_LOCAL_IMPORT = "MANUAL_LOCAL_IMPORT"


def validate_opaque_id(value: str, label: str) -> None:
    """Normalize and reject malformed opaque id before it can reach persistence or an external
    transport.
    """

    if _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def validate_timestamp(value: int, label: str) -> None:
    """Normalize and reject malformed timestamp before it can reach persistence or an external
    transport.
    """

    if type(value) is not int or value < 1 or value > MAX_TIMESTAMP_US:
        raise ValueError(f"{label} is invalid")


def validate_sha256(value: str, label: str) -> None:
    """Normalize and reject malformed sha256 before it can reach persistence or an external
    transport.
    """

    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def validate_safe_url(value: str) -> str:
    """Normalize and reject malformed safe url before it can reach persistence or an external
    transport.
    """

    if not value or len(value) > MAX_URL_LENGTH or any(ord(char) < 33 for char in value):
        raise ValueError("evidence URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("evidence URL is invalid") from error
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("evidence URL scheme or host is unsafe")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("evidence URL credentials are unsafe")
    if parsed.query or parsed.fragment:
        raise ValueError("evidence URL must exclude query and fragment data")
    if port is not None and (port < 1 or port > 65_535):
        raise ValueError("evidence URL port is invalid")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
        (".localhost", ".local", ".internal", ".lan")
    ):
        raise ValueError("evidence URL host is unsafe")
    if hostname.replace(".", "").isdigit() or any(
        label.startswith("0x") for label in hostname.split(".")
    ):
        raise ValueError("evidence URL host encoding is unsafe")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname.encode("idna")
        except UnicodeError as error:
            raise ValueError("evidence URL host is invalid") from error
    else:
        if not address.is_global:
            raise ValueError("evidence URL address is unsafe")
    return value


def validate_safe_url_reference(value: str) -> str:
    """Validate a retained public source URL while preserving its exact query.

    URL references are metadata, not fetch instructions. They may therefore retain
    the provider-returned query string needed to identify an exact source, while
    credentials, fragments, non-public hosts, and non-canonical URL spellings stay
    forbidden.
    """

    if not value or len(value) > MAX_URL_LENGTH:
        raise ValueError("evidence URL reference is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError("evidence URL reference is invalid") from error
    if parsed.fragment:
        raise ValueError("evidence URL reference must exclude fragments")
    if not parsed.query:
        # Preserve the established queryless evidence policy, including reserved
        # synthetic test domains which are never valid public-discovery results.
        return validate_safe_url(value)
    try:
        normalised = normalise_public_result_url(value)
    except ValueError as error:
        raise ValueError("evidence URL reference is unsafe") from error
    if normalised != value:
        raise ValueError("evidence URL reference must be normalized")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceViewport:
    width: int
    height: int
    device_scale_micros: int = 1_000_000

    def __post_init__(self) -> None:
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or self.width < 1
            or self.width > 16_384
            or self.height < 1
            or self.height > 16_384
        ):
            raise ValueError("evidence viewport dimensions are invalid")
        if (
            type(self.device_scale_micros) is not int
            or self.device_scale_micros < 100_000
            or self.device_scale_micros > 8_000_000
        ):
            raise ValueError("evidence viewport scale is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceMetadataEntry:
    key: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if _METADATA_KEY.fullmatch(self.key) is None:
            raise ValueError("evidence metadata key is invalid")
        if not self.value or len(self.value) > 256 or any(ord(char) < 32 for char in self.value):
            raise ValueError("evidence metadata value is invalid")


def _validate_metadata(metadata: tuple[EvidenceMetadataEntry, ...]) -> None:
    if type(metadata) is not tuple or len(metadata) > MAX_METADATA_ENTRIES:
        raise ValueError("evidence metadata is outside the allowed bounds")
    keys = tuple(entry.key for entry in metadata)
    if len(set(keys)) != len(keys):
        raise ValueError("evidence metadata keys must be unique")
    if sum(len(entry.key) + len(entry.value) for entry in metadata) > MAX_METADATA_TOTAL_CHARS:
        raise ValueError("evidence metadata total size is outside the allowed bounds")


@dataclass(frozen=True, slots=True)
class EvidenceArtifactOriginal:
    artifact_id: str
    kind: EvidenceArtifactKind
    content: bytes = field(repr=False)
    content_sha256: str
    captured_at_us: int
    source_url: str | None
    http_status: int | None
    redirect_chain: tuple[str, ...] = field(repr=False)
    masked_query_reference: str | None = field(repr=False)
    provider_id: str
    run_id: str
    finding_id: str | None
    viewport: EvidenceViewport | None
    capture_method: EvidenceCaptureMethod
    metadata: tuple[EvidenceMetadataEntry, ...] = field(repr=False)
    encryption_required: bool = True

    def __post_init__(self) -> None:
        validate_opaque_id(self.artifact_id, "evidence artifact id")
        if not isinstance(self.kind, EvidenceArtifactKind):
            raise TypeError("evidence artifact kind is invalid")
        if type(self.content) is not bytes or len(self.content) > MAX_ARTIFACT_BYTES:
            raise ValueError("evidence artifact bytes are outside the allowed bounds")
        validate_sha256(self.content_sha256, "evidence content hash")
        validate_timestamp(self.captured_at_us, "evidence capture time")
        validate_opaque_id(self.provider_id, "evidence provider id")
        validate_opaque_id(self.run_id, "evidence run id")
        if self.finding_id is not None:
            validate_opaque_id(self.finding_id, "evidence finding id")
        if not isinstance(self.capture_method, EvidenceCaptureMethod):
            raise TypeError("evidence capture method is invalid")
        if self.encryption_required is not True:
            raise ValueError("evidence artifacts require encrypted durable storage")
        if type(self.redirect_chain) is not tuple or len(self.redirect_chain) > MAX_REDIRECTS:
            raise ValueError("evidence redirect chain is outside the allowed bounds")
        if self.masked_query_reference is not None and (
            _MASKED_QUERY_REFERENCE.fullmatch(self.masked_query_reference) is None
        ):
            raise ValueError("masked query reference must be opaque and non-reversible")
        _validate_metadata(self.metadata)

        if self.source_url is not None:
            if self.kind is EvidenceArtifactKind.URL_REFERENCE:
                validate_safe_url_reference(self.source_url)
            else:
                validate_safe_url(self.source_url)
        for redirect in self.redirect_chain:
            validate_safe_url(redirect)
        if self.http_status is not None and (
            type(self.http_status) is not int or self.http_status < 100 or self.http_status > 599
        ):
            raise ValueError("evidence HTTP status is invalid")
        if self.http_status is not None and self.source_url is None:
            raise ValueError("evidence HTTP status requires a source URL")
        if self.redirect_chain and self.source_url is None:
            raise ValueError("evidence redirects require a source URL")
        if self.capture_method is EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT and (
            self.source_url is not None or self.http_status is not None or self.redirect_chain
        ):
            raise ValueError("manual evidence imports cannot claim network capture metadata")
        if self.kind is EvidenceArtifactKind.URL_REFERENCE:
            if self.source_url is None or self.content or self.viewport is not None:
                raise ValueError("URL references require only a safe source URL")
            hash_material = self.source_url.encode("utf-8")
        else:
            if not self.content:
                raise ValueError("evidence artifact content is required")
            hash_material = self.content
        if self.kind is EvidenceArtifactKind.SCREENSHOT and self.viewport is None:
            raise ValueError("screenshot evidence requires a viewport")
        if hashlib.sha256(hash_material).hexdigest() != self.content_sha256:
            raise ValueError("evidence content hash does not match")


@dataclass(frozen=True, slots=True)
class RedactedEvidenceDerivative:
    derivative_id: str
    original_artifact_id: str
    content: bytes = field(repr=False)
    content_sha256: str
    created_at_us: int
    redaction_policy_version: str
    redaction_summary_code: str
    encryption_required: bool = True

    def __post_init__(self) -> None:
        validate_opaque_id(self.derivative_id, "evidence derivative id")
        validate_opaque_id(self.original_artifact_id, "original evidence artifact id")
        if type(self.content) is not bytes or len(self.content) > MAX_ARTIFACT_BYTES:
            raise ValueError("evidence derivative bytes are outside the allowed bounds")
        validate_sha256(self.content_sha256, "evidence derivative hash")
        validate_timestamp(self.created_at_us, "evidence derivative time")
        if _VERSION.fullmatch(self.redaction_policy_version) is None:
            raise ValueError("redaction policy version is invalid")
        if _CODE.fullmatch(self.redaction_summary_code) is None:
            raise ValueError("redaction summary code is invalid")
        if self.encryption_required is not True:
            raise ValueError("evidence derivatives require encrypted durable storage")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("evidence derivative hash does not match")
