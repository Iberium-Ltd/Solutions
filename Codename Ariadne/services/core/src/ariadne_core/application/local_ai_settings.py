"""Encrypted settings and explicit user-gesture boundary for optional local AI.

Connection testing and model discovery are separate explicit actions; settings
alone never cause a model request or transmit workspace content.
"""

from __future__ import annotations

from ariadne_core.api.schemas import (
    LocalAIConnectionResult,
    LocalAIConnectionStatus,
    LocalAIEndpointRequest,
    LocalAIModelDiscoveryResult,
    LocalAIModelSummary,
    LocalAISettings,
    LocalAISettingsUpdateRequest,
    LocalAIUnloadResult,
    LocalAIUnloadStatus,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.settings import VaultSettingsPatch
from ariadne_core.infrastructure.db.repositories import (
    RevisionConflict,
    SettingsRepository,
    SettingsSnapshot,
)
from ariadne_core.local_ai import (
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpTransport,
)


class LocalAISettingsUnavailable(RuntimeError):
    """The encrypted settings store is not currently available."""


class LocalAISettingsConflict(RuntimeError):
    """The caller attempted to replace a newer settings revision."""


class LocalAISettingsService:
    """Keep provider configuration local and model execution opt-in."""

    def __init__(
        self,
        vault: VaultManager,
        *,
        transport: LocalAIHttpTransport | None = None,
    ) -> None:
        self._vault = vault
        self._transport = transport

    def get(self) -> LocalAISettings:
        return _settings_response(self._repository().get(self._vault.manifest.vault_id))

    def update(self, request: LocalAISettingsUpdateRequest) -> LocalAISettings:
        try:
            snapshot = self._repository().update(
                self._vault.manifest.vault_id,
                VaultSettingsPatch(
                    local_ai_enabled=request.enabled,
                    local_ai_provider=request.provider,
                    local_ai_endpoint=request.endpoint,
                    local_ai_selected_model=request.selected_model,
                ),
                expected_revision=request.expected_revision,
            )
        except RevisionConflict:
            raise LocalAISettingsConflict("local AI settings revision is stale") from None
        return _settings_response(snapshot)

    def discover(self, request: LocalAIEndpointRequest) -> LocalAIModelDiscoveryResult:
        models = self._client(request).list_models()
        return LocalAIModelDiscoveryResult(
            models=tuple(
                LocalAIModelSummary(provider=model.provider, model_id=model.model_id)
                for model in models
            )
        )

    def test_connection(self, request: LocalAIEndpointRequest) -> LocalAIConnectionResult:
        try:
            client = self._client(request)
            models = client.list_models()
            selected_available = (
                None
                if request.selected_model is None
                else any(model.model_id == request.selected_model for model in models)
            )
            if request.selected_model is not None and selected_available:
                # A connection test with a selected model is also an explicit,
                # content-free preload. UI can therefore report "ready" only
                # after the inference server has actually loaded that model.
                client.preload(model_id=request.selected_model)
        except LocalAIError as error:
            status = {
                LocalAIErrorCode.TIMEOUT: LocalAIConnectionStatus.TIMEOUT,
                LocalAIErrorCode.INVALID_RESPONSE: LocalAIConnectionStatus.INVALID_RESPONSE,
            }.get(error.code, LocalAIConnectionStatus.UNAVAILABLE)
            return LocalAIConnectionResult(
                status=status,
                reachable=False,
                model_count=0,
                selected_model_available=None,
            )
        return LocalAIConnectionResult(
            status=(
                LocalAIConnectionStatus.MODEL_UNAVAILABLE
                if selected_available is False
                else LocalAIConnectionStatus.AVAILABLE
            ),
            reachable=True,
            model_count=len(models),
            selected_model_available=selected_available,
        )

    def unload(self, request: LocalAIEndpointRequest) -> LocalAIUnloadResult:
        """Release one explicitly selected model without changing saved configuration."""

        if request.selected_model is None:
            raise LocalAISettingsConflict("a selected local model is required")
        unloaded = self._client(request).unload(model_id=request.selected_model)
        return LocalAIUnloadResult(
            provider=request.provider,
            model_id=request.selected_model,
            status=(LocalAIUnloadStatus.UNLOADED if unloaded else LocalAIUnloadStatus.UNSUPPORTED),
        )

    def _client(self, request: LocalAIEndpointRequest) -> LocalAIClient:
        return LocalAIClient(
            LocalAIConfig(
                enabled=True,
                provider=request.provider,
                endpoint=request.endpoint,
                # A cold 30B-class model on an external SSD can legitimately
                # need longer than a connectivity probe. The native boundary
                # applies a matching hard deadline and the provider remains
                # restricted to loopback.
                timeout_seconds=120,
            ),
            transport=self._transport,
        )

    def _repository(self) -> SettingsRepository:
        if not self._vault.is_unlocked:
            raise LocalAISettingsUnavailable("local AI settings require an unlocked vault")
        return SettingsRepository(self._vault.engine)


def _settings_response(snapshot: SettingsSnapshot) -> LocalAISettings:
    return LocalAISettings(
        enabled=snapshot.values.local_ai_enabled,
        provider=snapshot.values.local_ai_provider,
        endpoint=snapshot.values.local_ai_endpoint,
        selected_model=snapshot.values.local_ai_selected_model,
        revision=snapshot.revision,
    )
