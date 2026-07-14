"""Deterministic, non-executing plans for composing authorised provider checks."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from ariadne_core.domain.hibp import normalise_hibp_domain, normalise_hibp_email
from ariadne_core.domain.public_discovery import (
    normalise_discovery_query,
    normalise_public_result_url,
)

HARD_MAX_INVESTIGATION_IDENTIFIERS = 32
HARD_MAX_INVESTIGATION_STEPS = 128
MAX_INVESTIGATION_IDENTIFIER_VALUE_BYTES = 1_024

_IDENTIFIER_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)

InvestigationExecutionRoute = Literal[
    "/v1/discovery/public/search",
    "/v1/discovery/hibp/account",
    "/v1/discovery/hibp/domain",
]


class InvestigationIdentifierKind(StrEnum):
    EMAIL = "EMAIL"
    USERNAME = "USERNAME"
    DOMAIN = "DOMAIN"
    NAME = "NAME"
    URL = "URL"


class InvestigationProvider(StrEnum):
    DUCKDUCKGO_HTML = "DUCKDUCKGO_HTML"
    GITHUB_USERS = "GITHUB_USERS"
    HAVE_I_BEEN_PWNED_V3 = "HAVE_I_BEEN_PWNED_V3"


class InvestigationOperation(StrEnum):
    PUBLIC_WEB_SEARCH = "PUBLIC_WEB_SEARCH"
    GITHUB_USER_SEARCH = "GITHUB_USER_SEARCH"
    HIBP_EMAIL_K_ANONYMITY = "HIBP_EMAIL_K_ANONYMITY"
    HIBP_EMAIL_DIRECT = "HIBP_EMAIL_DIRECT"
    HIBP_VERIFIED_DOMAIN_ENUMERATION = "HIBP_VERIFIED_DOMAIN_ENUMERATION"


class InvestigationTransmission(StrEnum):
    DIRECT_PUBLIC_QUERY = "DIRECT_PUBLIC_QUERY"
    PARTIAL_SHA1_PREFIX = "PARTIAL_SHA1_PREFIX"
    DIRECT_EMAIL = "DIRECT_EMAIL"
    PROVIDER_VERIFIED_DOMAIN = "PROVIDER_VERIFIED_DOMAIN"


class InvestigationPrerequisite(StrEnum):
    EXPLICIT_SELF_AUDIT_AUTHORIZATION = "EXPLICIT_SELF_AUDIT_AUTHORIZATION"
    HIBP_API_KEY = "HIBP_API_KEY"
    HIBP_K_ANONYMITY_SUBSCRIPTION = "HIBP_K_ANONYMITY_SUBSCRIPTION"
    DIRECT_IDENTIFIER_TRANSMISSION_AUTHORIZATION = "DIRECT_IDENTIFIER_TRANSMISSION_AUTHORIZATION"
    PROVIDER_VERIFIED_DOMAIN = "PROVIDER_VERIFIED_DOMAIN"


class InvestigationNotice(StrEnum):
    SELF_AUDIT_AUTHORIZATION_REQUIRED = "SELF_AUDIT_AUTHORIZATION_REQUIRED"
    HIBP_API_KEY_REQUIRED = "HIBP_API_KEY_REQUIRED"
    HIBP_EMAIL_MODE_NOT_AUTHORIZED = "HIBP_EMAIL_MODE_NOT_AUTHORIZED"


@dataclass(frozen=True, slots=True)
class InvestigationIdentifier:
    identifier_ref: str
    kind: InvestigationIdentifierKind
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identifier_ref, str)
            or _IDENTIFIER_REF.fullmatch(self.identifier_ref) is None
        ):
            raise ValueError("investigation identifier reference is invalid")
        if not isinstance(self.kind, InvestigationIdentifierKind):
            raise ValueError("investigation identifier kind is invalid")
        object.__setattr__(self, "value", normalise_investigation_identifier(self.kind, self.value))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class InvestigationPlanRequest:
    identifiers: tuple[InvestigationIdentifier, ...]
    enabled_providers: tuple[InvestigationProvider, ...]
    authorized_self_audit: bool
    hibp_api_key_available: bool = False
    hibp_k_anonymity_available: bool = False
    authorized_direct_email_transmission: bool = False

    def __post_init__(self) -> None:
        if not 1 <= len(self.identifiers) <= HARD_MAX_INVESTIGATION_IDENTIFIERS:
            raise ValueError("investigation identifier count is invalid")
        references = [item.identifier_ref for item in self.identifiers]
        if len(references) != len(set(references)):
            raise ValueError("investigation identifier references must be unique")
        identities = [(item.kind, item.value) for item in self.identifiers]
        if len(identities) != len(set(identities)):
            raise ValueError("investigation identifiers must be unique")
        if not self.enabled_providers or len(self.enabled_providers) > len(InvestigationProvider):
            raise ValueError("investigation provider selection is invalid")
        if any(not isinstance(item, InvestigationProvider) for item in self.enabled_providers):
            raise ValueError("investigation provider selection is invalid")
        if len(self.enabled_providers) != len(set(self.enabled_providers)):
            raise ValueError("investigation provider selection must be unique")
        if any(
            type(value) is not bool
            for value in (
                self.authorized_self_audit,
                self.hibp_api_key_available,
                self.hibp_k_anonymity_available,
                self.authorized_direct_email_transmission,
            )
        ):
            raise ValueError("investigation plan authorization is invalid")


@dataclass(frozen=True, slots=True)
class InvestigationPlanStep:
    step_id: str
    identifier_ref: str
    identifier_kind: InvestigationIdentifierKind
    identifier_sha256: str
    provider: InvestigationProvider
    operation: InvestigationOperation
    execution_route: InvestigationExecutionRoute
    transmission: InvestigationTransmission
    prerequisites: tuple[InvestigationPrerequisite, ...]
    sequence: int
    executes_during_compilation: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        if not re.fullmatch(r"step-[0-9]{3}", self.step_id, re.ASCII):
            raise ValueError("investigation step id is invalid")
        if _IDENTIFIER_REF.fullmatch(self.identifier_ref) is None:
            raise ValueError("investigation step identifier reference is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", self.identifier_sha256, re.ASCII):
            raise ValueError("investigation step identifier digest is invalid")
        if (
            not isinstance(self.identifier_kind, InvestigationIdentifierKind)
            or not isinstance(self.provider, InvestigationProvider)
            or not isinstance(self.operation, InvestigationOperation)
            or not isinstance(self.transmission, InvestigationTransmission)
        ):
            raise ValueError("investigation step classification is invalid")
        if self.execution_route not in {
            "/v1/discovery/public/search",
            "/v1/discovery/hibp/account",
            "/v1/discovery/hibp/domain",
        }:
            raise ValueError("investigation step route is invalid")
        if not self.prerequisites or any(
            not isinstance(item, InvestigationPrerequisite) for item in self.prerequisites
        ):
            raise ValueError("investigation step prerequisites are invalid")
        if type(self.sequence) is not int or not 1 <= self.sequence <= HARD_MAX_INVESTIGATION_STEPS:
            raise ValueError("investigation step sequence is invalid")
        if self.executes_during_compilation or not self.human_review_required:
            raise ValueError("investigation plan compiler cannot execute provider steps")


@dataclass(frozen=True, slots=True)
class InvestigationPlan:
    plan_id: str
    steps: tuple[InvestigationPlanStep, ...]
    notices: tuple[InvestigationNotice, ...]
    authorization_confirmed: bool
    deterministic: bool = True
    executed: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"plan-[0-9a-f]{24}", self.plan_id, re.ASCII):
            raise ValueError("investigation plan id is invalid")
        if len(self.steps) > HARD_MAX_INVESTIGATION_STEPS:
            raise ValueError("investigation step count is invalid")
        if tuple(item.sequence for item in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("investigation step order is invalid")
        if any(not isinstance(item, InvestigationNotice) for item in self.notices):
            raise ValueError("investigation plan notice is invalid")
        if len(self.notices) != len(set(self.notices)):
            raise ValueError("investigation plan notices must be unique")
        if not self.authorization_confirmed and self.steps:
            raise ValueError("unauthorized investigation plan cannot contain steps")
        if not self.deterministic or self.executed:
            raise ValueError("investigation plan compiler state is invalid")


def normalise_investigation_identifier(
    kind: InvestigationIdentifierKind,
    value: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError("investigation identifier is invalid")
    if kind is InvestigationIdentifierKind.EMAIL:
        result = normalise_hibp_email(value)
    elif kind is InvestigationIdentifierKind.DOMAIN:
        result = normalise_hibp_domain(value)
    elif kind is InvestigationIdentifierKind.URL:
        result = normalise_public_result_url(value)
    else:
        result = normalise_discovery_query(value)
        maximum = 128 if kind is InvestigationIdentifierKind.USERNAME else 256
        if len(result) > maximum:
            raise ValueError("investigation identifier is invalid")
        if kind is InvestigationIdentifierKind.USERNAME and any(
            character.isspace() for character in result
        ):
            raise ValueError("investigation username is invalid")
    if len(result.encode("utf-8")) > MAX_INVESTIGATION_IDENTIFIER_VALUE_BYTES or any(
        unicodedata.category(character) in {"Cc", "Cs"} for character in result
    ):
        raise ValueError("investigation identifier is invalid")
    return result


def deterministic_plan_id(request: InvestigationPlanRequest) -> str:
    payload = {
        "identifiers": [
            {
                "ref": item.identifier_ref,
                "kind": item.kind.value,
                "sha256": item.sha256,
            }
            for item in request.identifiers
        ],
        "providers": sorted(item.value for item in request.enabled_providers),
        "authorized": request.authorized_self_audit,
        "hibpKey": request.hibp_api_key_available,
        "hibpKAnon": request.hibp_k_anonymity_available,
        "directEmail": request.authorized_direct_email_transmission,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"plan-{hashlib.sha256(canonical).hexdigest()[:24]}"
