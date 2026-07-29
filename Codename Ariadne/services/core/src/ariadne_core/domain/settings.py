"""Closed, secret-free settings contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ariadne_core.local_ai import (
    LocalAIError,
    LocalAIProvider,
    validate_loopback_endpoint,
    validate_model_id,
)


class TransmissionMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    EU_ONLY = "EU_ONLY"
    WORLDWIDE = "WORLDWIDE"
    CUSTOM = "CUSTOM"


class SettingKey(StrEnum):
    # Retained for encrypted-vault schema compatibility. Foreground sessions
    # now lock only on an explicit user action or application shutdown.
    AUTO_LOCK_SECONDS = "auto_lock_seconds"
    HIGHLY_SENSITIVE_FTS = "highly_sensitive_fts"
    LOCK_ON_SLEEP = "lock_on_sleep"
    LOCAL_AI_ENABLED = "local_ai_enabled"
    LOCAL_AI_ENDPOINT = "local_ai_endpoint"
    LOCAL_AI_PROVIDER = "local_ai_provider"
    LOCAL_AI_SELECTED_MODEL = "local_ai_selected_model"
    REMOTE_AI_ENABLED = "remote_ai_enabled"
    REVEAL_TTL_SECONDS = "reveal_ttl_seconds"
    TELEMETRY_ENABLED = "telemetry_enabled"
    TRANSMISSION_MODE = "transmission_mode"


class VaultSettings(BaseModel):
    """The complete allowlisted vault settings view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Legacy persisted fields remain parseable so existing vaults upgrade
    # without rewriting history; no runtime observer consumes either value.
    auto_lock_seconds: int = Field(default=300, ge=30, le=86_400)
    highly_sensitive_fts: bool = False
    lock_on_sleep: bool = True
    local_ai_enabled: bool = False
    local_ai_endpoint: str = "http://127.0.0.1:11434"
    local_ai_provider: LocalAIProvider = LocalAIProvider.OLLAMA
    local_ai_selected_model: str | None = None
    remote_ai_enabled: bool = False
    reveal_ttl_seconds: int = Field(default=30, ge=5, le=300)
    telemetry_enabled: bool = False
    transmission_mode: TransmissionMode = TransmissionMode.LOCAL_ONLY

    @field_validator("local_ai_provider")
    @classmethod
    def validate_local_ai_provider(cls, value: LocalAIProvider) -> LocalAIProvider:
        if value is LocalAIProvider.OPENAI_RESPONSES:
            raise ValueError("external AI credentials and providers are request-ephemeral")
        return value

    @field_validator("local_ai_endpoint")
    @classmethod
    def validate_local_ai_endpoint(cls, value: str) -> str:
        try:
            return validate_loopback_endpoint(value)
        except LocalAIError:
            raise ValueError("local AI endpoint is invalid") from None

    @field_validator("local_ai_selected_model")
    @classmethod
    def validate_local_ai_selected_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_model_id(value)
        except LocalAIError:
            raise ValueError("local AI model is invalid") from None

    @model_validator(mode="after")
    def enforce_privacy_invariants(self) -> VaultSettings:
        if self.telemetry_enabled:
            raise ValueError("telemetry is unavailable in the local foundation")
        if self.remote_ai_enabled:
            raise ValueError("remote AI is unavailable in the local foundation")
        if self.local_ai_enabled and self.local_ai_selected_model is None:
            raise ValueError("enabled local AI requires an explicit model")
        return self


class VaultSettingsPatch(BaseModel):
    """A partial settings mutation; unknown and secret-like keys are impossible."""

    model_config = ConfigDict(extra="forbid")

    auto_lock_seconds: int | None = Field(default=None, ge=30, le=86_400)
    highly_sensitive_fts: bool | None = None
    lock_on_sleep: bool | None = None
    local_ai_enabled: bool | None = None
    local_ai_endpoint: str | None = None
    local_ai_provider: LocalAIProvider | None = None
    local_ai_selected_model: str | None = None
    remote_ai_enabled: bool | None = None
    reveal_ttl_seconds: int | None = Field(default=None, ge=5, le=300)
    telemetry_enabled: bool | None = None
    transmission_mode: TransmissionMode | None = None

    @field_validator("local_ai_provider")
    @classmethod
    def validate_local_ai_provider(cls, value: LocalAIProvider | None) -> LocalAIProvider | None:
        if value is LocalAIProvider.OPENAI_RESPONSES:
            raise ValueError("external AI credentials and providers are request-ephemeral")
        return value

    def apply(self, current: VaultSettings) -> VaultSettings:
        changes = self.model_dump(exclude_none=True)
        if "local_ai_selected_model" in self.model_fields_set:
            changes["local_ai_selected_model"] = self.local_ai_selected_model
        return VaultSettings.model_validate({**current.model_dump(), **changes})
