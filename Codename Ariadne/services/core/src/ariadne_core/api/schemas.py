"""Pydantic-authoritative schemas for the bounded Phase 2.1 API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import RFC_4122, UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ariadne_core.local_ai import (
    LocalAIError,
    LocalAIProvider,
    validate_loopback_endpoint,
    validate_model_id,
)


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        hide_input_in_errors=True,
        populate_by_name=True,
        strict=True,
    )


class RuntimeTransport(StrEnum):
    DEV_LOOPBACK = "DEV_LOOPBACK"
    UNIX_SOCKET = "UNIX_SOCKET"


class FeatureStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNAVAILABLE = "UNAVAILABLE"


class FeatureKey(StrEnum):
    AUTHENTICATED_LOCAL_API = "authenticated_local_api"
    DATABASE = "database"
    MIGRATIONS = "migrations"
    ENCRYPTION = "encryption"
    SETTINGS = "settings"
    TASK_ENGINE = "task_engine"
    EVENTS = "events"
    IMPORT_EXPORT = "import_export"
    KEY_LEASE = "key_lease"
    VAULT_LIFECYCLE = "vault_lifecycle"
    INTAKE = "intake"
    IDENTITY_COMPILER = "identity_compiler"
    ENTITY_REVIEW = "entity_review"
    IDENTITY_GRAPH = "identity_graph"
    LOCAL_AI = "local_ai"
    QUERY_POLICY = "query_policy"
    EVIDENCE = "evidence"
    ATTRIBUTION = "attribution"
    AUDIT_COMPARISON = "audit_comparison"
    REMEDIATION = "remediation"
    PUBLIC_DISCOVERY = "public_discovery"


class CapabilityVersions(ApiModel):
    contract: Literal[1]
    schema_: Literal["ariadne-v1"] = Field(alias="schema")
    events: Literal[1]
    core: Literal["0.1.0"]


class CipherCapability(ApiModel):
    required: Literal["SQLCIPHER"]
    available: bool
    sqlite_version: str | None
    cipher_version: str | None


class FeatureCapability(ApiModel):
    key: FeatureKey
    status: FeatureStatus


class SystemCapabilities(ApiModel):
    versions: CapabilityVersions
    transport: RuntimeTransport
    cipher: CipherCapability
    features: tuple[FeatureCapability, ...]


class LockState(StrEnum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    LOCKING = "LOCKING"


class VaultState(StrEnum):
    NO_VAULT = "NO_VAULT"
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class CompatibilityState(StrEnum):
    COMPATIBLE = "COMPATIBLE"


class SessionState(ApiModel):
    lock_state: LockState
    vault_state: VaultState
    compatibility: CompatibilityState
    authenticated_transport: Literal[True]
    session_expires_at: datetime | None
    active_reveal_capabilities: int = Field(ge=0)


class LocalAISettings(ApiModel):
    enabled: bool
    provider: LocalAIProvider
    endpoint: str
    selected_model: str | None
    revision: int = Field(ge=1)


class LocalAISettingsUpdateRequest(ApiModel):
    enabled: bool
    provider: LocalAIProvider = Field(strict=False)
    endpoint: str = Field(min_length=1, max_length=256)
    selected_model: str | None = Field(default=None, max_length=256)
    expected_revision: int = Field(ge=1)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: LocalAIProvider) -> LocalAIProvider:
        if value is LocalAIProvider.OPENAI_RESPONSES:
            raise ValueError("external AI cannot be persisted as a local provider")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        try:
            return validate_loopback_endpoint(value)
        except LocalAIError:
            raise ValueError("local AI endpoint is invalid") from None

    @field_validator("selected_model")
    @classmethod
    def validate_selected_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_model_id(value)
        except LocalAIError:
            raise ValueError("local AI model is invalid") from None

    @model_validator(mode="after")
    def require_selected_model_when_enabled(self) -> LocalAISettingsUpdateRequest:
        if self.enabled and self.selected_model is None:
            raise ValueError("enabled local AI requires a selected model")
        return self


class LocalAIEndpointRequest(ApiModel):
    provider: LocalAIProvider = Field(strict=False)
    endpoint: str = Field(min_length=1, max_length=256)
    selected_model: str | None = Field(default=None, max_length=256)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: LocalAIProvider) -> LocalAIProvider:
        if value is LocalAIProvider.OPENAI_RESPONSES:
            raise ValueError("external AI cannot use the local endpoint boundary")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        try:
            return validate_loopback_endpoint(value)
        except LocalAIError:
            raise ValueError("local AI endpoint is invalid") from None

    @field_validator("selected_model")
    @classmethod
    def validate_selected_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_model_id(value)
        except LocalAIError:
            raise ValueError("local AI model is invalid") from None


class LocalAIModelSummary(ApiModel):
    provider: LocalAIProvider
    model_id: str = Field(min_length=1, max_length=256)


class LocalAIModelDiscoveryResult(ApiModel):
    models: tuple[LocalAIModelSummary, ...] = Field(max_length=512)


class LocalAIConnectionStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class LocalAIConnectionResult(ApiModel):
    status: LocalAIConnectionStatus
    reachable: bool
    model_count: int = Field(ge=0, le=512)
    selected_model_available: bool | None


class LocalAIUnloadStatus(StrEnum):
    UNLOADED = "UNLOADED"
    UNSUPPORTED = "UNSUPPORTED"


class LocalAIUnloadResult(ApiModel):
    provider: LocalAIProvider
    model_id: str = Field(min_length=1, max_length=256)
    status: LocalAIUnloadStatus


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise ValueError(f"{label} is invalid")
    return value


def _canonical_uuid_v4(value: str, *, label: str) -> str:
    _canonical_uuid(value, label=label)
    if UUID(value).version != 4:
        raise ValueError(f"{label} is invalid")
    return value


def _canonical_key_reference(value: str) -> str:
    prefix = "kc:v1:"
    if not value.startswith(prefix):
        raise ValueError("key reference is invalid")
    _canonical_uuid_v4(value.removeprefix(prefix), label="key reference")
    return value


class VaultCreateRequest(ApiModel):
    display_name: str = Field(min_length=1, max_length=80)
    transaction_id: str
    vault_id: str
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_key_ref: str = Field(max_length=64)
    backup_key_ref: str = Field(max_length=64)
    format_version: Literal[1]
    database_key_version: Literal[1]

    @field_validator("format_version", "database_key_version", mode="before")
    @classmethod
    def validate_version_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("version is invalid")
        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("display name is invalid")
        return value

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, value: str) -> str:
        return _canonical_uuid_v4(value, label="transaction id")

    @field_validator("vault_id")
    @classmethod
    def validate_vault_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="vault id")

    @field_validator("database_key_ref", "backup_key_ref")
    @classmethod
    def validate_key_reference(cls, value: str) -> str:
        return _canonical_key_reference(value)

    @model_validator(mode="after")
    def validate_distinct_references(self) -> VaultCreateRequest:
        if self.database_key_ref == self.backup_key_ref:
            raise ValueError("key references must be distinct")
        return self


class VaultUnlockRequest(ApiModel):
    transaction_id: str
    vault_id: str
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_key_ref: str = Field(max_length=64)
    database_key_version: Literal[1]

    @field_validator("database_key_version", mode="before")
    @classmethod
    def validate_version_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("version is invalid")
        return value

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, value: str) -> str:
        return _canonical_uuid_v4(value, label="transaction id")

    @field_validator("vault_id")
    @classmethod
    def validate_vault_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="vault id")

    @field_validator("database_key_ref")
    @classmethod
    def validate_key_reference(cls, value: str) -> str:
        return _canonical_key_reference(value)


class VaultDescriptor(ApiModel):
    vault_id: str
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_key_ref: str
    backup_key_ref: str
    format_version: Literal[1]
    database_key_version: Literal[1]
    vault_state: VaultState


class VaultLifecycleResult(ApiModel):
    vault_id: str
    lock_state: LockState
    vault_state: VaultState

    @field_validator("vault_id")
    @classmethod
    def validate_vault_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="vault id")

    @model_validator(mode="after")
    def validate_consistent_state(self) -> VaultLifecycleResult:
        valid = (self.lock_state is LockState.LOCKED and self.vault_state is VaultState.LOCKED) or (
            self.lock_state is LockState.UNLOCKED and self.vault_state is VaultState.UNLOCKED
        )
        if not valid:
            raise ValueError("vault lifecycle state is inconsistent")
        return self


class EventReplayDisposition(StrEnum):
    OK = "OK"
    GAP = "GAP"
    CURSOR_EXPIRED = "CURSOR_EXPIRED"


class EventReplayRequest(ApiModel):
    cursor: str | None = Field(default=None, max_length=36)
    max_events: int = Field(default=32, ge=1, le=64)

    @field_validator("cursor")
    @classmethod
    def validate_cursor(cls, value: str | None) -> str | None:
        if value is not None:
            _canonical_uuid(value, label="event cursor")
        return value


class SafeCoreEvent(ApiModel):
    event_id: str
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=96, pattern=r"^[A-Z][A-Z0-9_]*$")
    resource_type: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    resource_id: str | None = None
    resource_revision: int | None = Field(default=None, ge=1)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="event id")

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, value: str | None) -> str | None:
        if value is not None:
            _canonical_uuid(value, label="resource id")
        return value


class EventReplayResult(ApiModel):
    disposition: EventReplayDisposition
    events: tuple[SafeCoreEvent, ...] = Field(max_length=64)
    next_cursor: str | None
    has_more: bool

    @field_validator("next_cursor")
    @classmethod
    def validate_next_cursor(cls, value: str | None) -> str | None:
        if value is not None:
            _canonical_uuid(value, label="event cursor")
        return value


class SafeDisplayArg(ApiModel):
    key: Literal["count", "durationMs", "catalogCode"]
    integer_value: int | None = None
    catalog_code: str | None = None


class SafeMessage(ApiModel):
    message_code: str
    args: tuple[SafeDisplayArg, ...]


class FieldError(ApiModel):
    path: str
    code: str
    message: SafeMessage


class ApiErrorBody(ApiModel):
    code: str
    message: SafeMessage
    request_id: str
    retryable: bool
    field_errors: tuple[FieldError, ...] | None = None


class ApiError(ApiModel):
    error: ApiErrorBody
