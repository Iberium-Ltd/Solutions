from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast
from urllib.parse import unquote

import pytest
from pydantic import ValidationError

from ariadne_core.api.hibp_schemas import (
    HibpAccountRequest,
    HibpAccountResult,
    HibpDomainRequest,
    HibpDomainResult,
)
from ariadne_core.application.hibp import (
    HibpHttpRequest,
    HibpHttpResponse,
    HibpService,
    HibpTransportError,
    HibpTransportErrorCode,
    UrllibHibpTransport,
)
from ariadne_core.domain.hibp import (
    HIBP_USER_AGENT,
    HibpAccountMode,
    HibpAccountSearchRequest,
    HibpDomainSearchRequest,
    HibpReason,
    HibpState,
)

API_KEY = "a" * 32
EMAIL = "morgan.trace@ariadne-example.invalid"
DOMAIN = "ariadne-example.invalid"
NOW = datetime(2026, 7, 14, 10, 30, tzinfo=UTC)


class RecordingTransport:
    def __init__(self, responses: Iterable[HibpHttpResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[HibpHttpRequest] = []

    def send(self, request: HibpHttpRequest) -> HibpHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected HIBP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _json_response(payload: object, *, status: int = 200, retry_after: int | None = None):
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),)
    if retry_after is not None:
        headers += (("Retry-After", str(retry_after)),)
    return HibpHttpResponse(
        status_code=status,
        headers=headers,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


def _account_request(
    *,
    mode: HibpAccountMode = HibpAccountMode.K_ANONYMITY,
    authorized: bool = True,
    direct_authorized: bool = False,
) -> HibpAccountSearchRequest:
    return HibpAccountSearchRequest(
        email=EMAIL,
        api_key=API_KEY,
        mode=mode,
        authorized_self_audit=authorized,
        authorized_direct_identifier_transmission=direct_authorized,
    )


def _domain_request(*, authorized: bool = True) -> HibpDomainSearchRequest:
    return HibpDomainSearchRequest(
        domain=DOMAIN,
        api_key=API_KEY,
        authorized_self_audit=authorized,
    )


def _headers(request: HibpHttpRequest) -> dict[str, str]:
    return {key.casefold(): value for key, value in request.headers}


def test_account_authorization_and_direct_consent_block_before_dispatch() -> None:
    transport = RecordingTransport([])
    service = HibpService(transport=transport)

    unauthorized = service.search_account(_account_request(authorized=False))
    direct_not_approved = service.search_account(_account_request(mode=HibpAccountMode.DIRECT))

    assert unauthorized.state is HibpState.NOT_CHECKED
    assert unauthorized.reason is HibpReason.SELF_AUDIT_AUTHORIZATION_REQUIRED
    assert direct_not_approved.state is HibpState.NOT_CHECKED
    assert direct_not_approved.reason is HibpReason.DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED
    assert transport.requests == []


def test_k_anonymity_sends_only_six_sha1_characters_and_discards_unmatched_rows() -> None:
    digest = hashlib.sha1(EMAIL.encode(), usedforsecurity=False).hexdigest().upper()
    unrelated_suffix = "0" * 34 if digest[6:] != "0" * 34 else "1" * 34
    payload = [
        {
            "hashSuffix": unrelated_suffix,
            "websites": ["UnrelatedSyntheticBreach"],
        },
        {
            "hashSuffix": digest[6:],
            "websites": ["SyntheticAlpha", "SyntheticBeta"],
        },
        {
            "hashSuffix": "F" * 34,
            "websites": ["NeverProcessedSynthetic"],
        },
    ]
    transport = RecordingTransport([_json_response(payload)])

    result = HibpService(transport=transport, clock=lambda: NOW).search_account(_account_request())

    assert result.state is HibpState.SUCCEEDED
    assert [item.name for item in result.breaches] == ["SyntheticAlpha", "SyntheticBeta"]
    assert "UnrelatedSyntheticBreach" not in repr(result)
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire.url.endswith(f"/breachedaccount/range/{digest[:6]}")
    assert EMAIL not in wire.url
    assert digest[6:] not in wire.url
    assert _headers(wire) == {
        "accept": "application/json",
        "accept-encoding": "identity",
        "user-agent": HIBP_USER_AGENT,
        "hibp-api-key": API_KEY,
    }
    metadata = result.requests[0]
    assert metadata.request_url == wire.url
    assert metadata.http_status == 200
    assert metadata.response_bytes == len(_json_response(payload).body)
    assert metadata.observed_at == NOW
    assert len(metadata.request_sha256) == 64
    assert all(
        item.source_url == f"https://haveibeenpwned.com/api/v3/breach/{item.name}"
        for item in result.breaches
    )


def test_direct_email_requires_both_authorizations_and_uses_truncated_verified_results() -> None:
    transport = RecordingTransport([_json_response([{"Name": "SyntheticVerifiedBreach"}])])

    result = HibpService(transport=transport, clock=lambda: NOW).search_account(
        _account_request(
            mode=HibpAccountMode.DIRECT,
            direct_authorized=True,
        )
    )

    assert result.state is HibpState.SUCCEEDED
    assert result.direct_transmission_authorized is True
    wire = transport.requests[0]
    assert unquote(wire.url).startswith(
        "https://haveibeenpwned.com/api/v3/breachedAccount/" + EMAIL
    )
    assert wire.url.endswith("?truncateResponse=true&IncludeUnverified=false")
    assert result.requests[0].request_url == wire.url
    assert API_KEY not in result.requests[0].request_url


def test_account_404_is_truthful_empty_success() -> None:
    result = HibpService(
        transport=RecordingTransport([_json_response({}, status=404)])
    ).search_account(_account_request(mode=HibpAccountMode.DIRECT, direct_authorized=True))

    assert result.state is HibpState.SUCCEEDED
    assert result.reason is HibpReason.NO_RESULTS
    assert result.breaches == ()


def test_k_anonymity_404_is_rejected_because_range_must_return_200() -> None:
    result = HibpService(
        transport=RecordingTransport([_json_response({}, status=404)])
    ).search_account(_account_request())

    assert result.state is HibpState.FAILED
    assert result.reason is HibpReason.UPSTREAM_REJECTED


def test_rate_limit_surfaces_retry_after_without_retrying_or_bypassing() -> None:
    transport = RecordingTransport([_json_response({}, status=429, retry_after=7)])

    result = HibpService(transport=transport).search_account(_account_request())

    assert result.state is HibpState.RATE_LIMITED
    assert result.reason is HibpReason.UPSTREAM_RATE_LIMITED
    assert result.retry_after_seconds == 7
    assert result.requests[0].retry_after_seconds == 7
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("response", "state", "reason"),
    [
        (_json_response({}, status=302), HibpState.ACCESS_BLOCKED, HibpReason.REDIRECT_REFUSED),
        (_json_response({}, status=401), HibpState.ACCESS_BLOCKED, HibpReason.INVALID_API_KEY),
        (
            _json_response({}, status=403),
            HibpState.ACCESS_BLOCKED,
            HibpReason.UPSTREAM_ACCESS_BLOCKED,
        ),
        (
            _json_response({}, status=503),
            HibpState.FAILED,
            HibpReason.UPSTREAM_UNAVAILABLE,
        ),
    ],
)
def test_account_statuses_are_reported_honestly(
    response: HibpHttpResponse,
    state: HibpState,
    reason: HibpReason,
) -> None:
    result = HibpService(transport=RecordingTransport([response])).search_account(
        _account_request()
    )

    assert result.state is state
    assert result.reason is reason


def test_transport_failures_are_redacted_and_typed() -> None:
    timeout = HibpService(
        transport=RecordingTransport([HibpTransportError(HibpTransportErrorCode.TIMEOUT)])
    ).search_account(_account_request())
    secret = "synthetic-transport-secret"
    generic = HibpService(transport=RecordingTransport([RuntimeError(secret)])).search_account(
        _account_request()
    )

    assert timeout.reason is HibpReason.TIMEOUT
    assert timeout.requests[0].http_status is None
    assert generic.reason is HibpReason.NETWORK_UNAVAILABLE
    assert secret not in repr(generic)


def test_domain_must_appear_in_provider_subscriptions_before_enumeration() -> None:
    transport = RecordingTransport(
        [_json_response([{"DomainName": "different-synthetic.invalid"}])]
    )

    result = HibpService(transport=transport).search_domain(_domain_request())

    assert result.state is HibpState.ACCESS_BLOCKED
    assert result.reason is HibpReason.DOMAIN_NOT_PROVIDER_VERIFIED
    assert result.provider_verified_domain is False
    assert len(result.requests) == 1
    assert result.requests[0].operation.value == "VERIFY_SUBSCRIBED_DOMAIN"
    assert transport.requests[0].url.endswith("/subscribedDomains")


def test_verified_domain_is_enumerated_second_with_exact_sources() -> None:
    transport = RecordingTransport(
        [
            _json_response(
                [
                    {
                        "DomainName": DOMAIN.upper(),
                        "PwnCount": 2,
                        "NextSubscriptionRenewal": "2027-01-01T00:00:00Z",
                    }
                ]
            ),
            _json_response(
                {
                    "synthetic.alias": ["SyntheticBeta", "SyntheticAlpha"],
                    "other-synthetic": ["SyntheticAlpha"],
                }
            ),
        ]
    )

    result = HibpService(transport=transport, clock=lambda: NOW).search_domain(_domain_request())

    assert result.state is HibpState.SUCCEEDED
    assert result.provider_verified_domain is True
    assert [item.alias for item in result.accounts] == [
        "other-synthetic",
        "synthetic.alias",
    ]
    assert [item.name for item in result.accounts[1].breaches] == [
        "SyntheticAlpha",
        "SyntheticBeta",
    ]
    assert [item.operation.value for item in result.requests] == [
        "VERIFY_SUBSCRIBED_DOMAIN",
        "DOMAIN_ENUMERATION",
    ]
    assert transport.requests[0].url.endswith("/subscribedDomains")
    assert transport.requests[1].url.endswith(f"/breachedDomain/{DOMAIN}")
    assert all(_headers(item)["hibp-api-key"] == API_KEY for item in transport.requests)


def test_domain_authorization_blocks_even_provider_verification() -> None:
    transport = RecordingTransport([])

    result = HibpService(transport=transport).search_domain(_domain_request(authorized=False))

    assert result.state is HibpState.NOT_CHECKED
    assert transport.requests == []


def test_unexpected_credential_fields_are_never_returned() -> None:
    credential = "synthetic-password-material"
    response = _json_response([{"Name": "SyntheticBreach", "Password": credential}])

    result = HibpService(transport=RecordingTransport([response])).search_account(
        _account_request(mode=HibpAccountMode.DIRECT, direct_authorized=True)
    )

    assert result.state is HibpState.FAILED
    assert result.reason is HibpReason.INVALID_RESPONSE
    assert credential not in repr(result)


def test_secret_values_are_hidden_from_schema_and_transport_representations() -> None:
    body = HibpAccountRequest.model_validate(
        {
            "email": EMAIL,
            "apiKey": API_KEY,
            "mode": "K_ANONYMITY",
            "authorizedSelfAudit": True,
        }
    )
    transport = RecordingTransport([_json_response([])])
    result = HibpService(transport=transport).search_account(body.to_domain())
    wire = HibpAccountResult.from_domain(result)

    assert API_KEY not in repr(body)
    assert EMAIL not in repr(body)
    assert API_KEY not in repr(body.to_domain())
    assert EMAIL not in repr(body.to_domain())
    assert API_KEY not in repr(transport.requests[0])
    assert EMAIL not in repr(transport.requests[0])
    assert API_KEY not in wire.model_dump_json(by_alias=True)


def test_strict_schemas_reject_invalid_keys_and_unknown_fields_without_echo() -> None:
    invalid_key = "not-a-valid-synthetic-api-key"
    with pytest.raises(ValidationError) as captured:
        HibpDomainRequest.model_validate(
            {
                "domain": DOMAIN,
                "apiKey": invalid_key,
                "authorizedSelfAudit": True,
                "password": "synthetic-password-material",
            }
        )

    assert invalid_key not in str(captured.value)


def test_wire_results_include_required_attribution_and_no_credentials() -> None:
    domain = HibpService(
        transport=RecordingTransport(
            [
                _json_response([{"DomainName": DOMAIN}]),
                _json_response({"synthetic": ["SyntheticBreach"]}),
            ]
        )
    ).search_domain(_domain_request())
    wire = HibpDomainResult.from_domain(domain).model_dump(by_alias=True, mode="json")

    assert wire["provider"] == "HAVE_I_BEEN_PWNED_V3"
    assert wire["attribution"] == "Have I Been Pwned"
    assert wire["providerHomeUrl"] == "https://haveibeenpwned.com/"
    assert wire["apiDocumentationUrl"] == "https://haveibeenpwned.com/API/v3"
    assert wire["license"] == "CC BY 4.0"
    assert API_KEY not in json.dumps(wire)


def test_large_domain_projection_is_bounded_and_truthfully_partial() -> None:
    accounts = {f"synthetic-{index:04d}": ["SyntheticBoundedBreach"] for index in range(2_001)}
    domain = HibpService(
        transport=RecordingTransport(
            [
                _json_response([{"DomainName": DOMAIN}]),
                _json_response(accounts),
            ]
        )
    ).search_domain(_domain_request())
    wire = HibpDomainResult.from_domain(domain).model_dump_json(by_alias=True)

    assert domain.state is HibpState.SUCCEEDED
    assert domain.reason is HibpReason.PARTIAL_RESULTS
    assert domain.truncated is True
    assert len(domain.accounts) <= 2_000
    assert len(wire.encode()) <= 1_048_576


def test_production_transport_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: tuple[object, ...] = ()

    class SyntheticOpener:
        pass

    def capture(*items: object) -> SyntheticOpener:
        nonlocal handlers
        handlers = items
        return SyntheticOpener()

    monkeypatch.setattr(urllib.request, "build_opener", capture)

    assert UrllibHibpTransport() is not None
    proxy = next(item for item in handlers if isinstance(item, urllib.request.ProxyHandler))
    redirect = next(
        item for item in handlers if isinstance(item, urllib.request.HTTPRedirectHandler)
    )
    assert cast(urllib.request.ProxyHandler, proxy).proxies == {}
    assert type(redirect) is not urllib.request.HTTPRedirectHandler
