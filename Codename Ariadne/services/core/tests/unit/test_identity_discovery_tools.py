from __future__ import annotations

import json
from collections.abc import Iterable
from typing import cast
from uuid import uuid4

from ariadne_core.application.identity_discovery_tools import (
    InvestigationToolBroker,
    PageHttpResponse,
)
from ariadne_core.application.public_discovery import PublicDiscoveryService
from ariadne_core.infrastructure.db.identity_discovery_repository import FrontierTaskRecord


class JsonTransport:
    def __init__(self, payloads: Iterable[object]) -> None:
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> PageHttpResponse:
        assert timeout_seconds == 12.0
        assert max_bytes == 1_048_576
        self.urls.append(url)
        return PageHttpResponse(200, "application/json", json.dumps(self.payloads.pop(0)).encode())


def _task(task_type: str, provider_id: str, payload: str) -> FrontierTaskRecord:
    identifier = str(uuid4())
    return FrontierTaskRecord(
        id=identifier,
        vault_id=str(uuid4()),
        profile_id=str(uuid4()),
        audit_id=str(uuid4()),
        lead_id=None,
        parent_task_id=None,
        task_type=task_type,
        provider_id=provider_id,
        payload=payload,
        payload_hmac="0" * 64,
        masked_payload="synthetic",
        priority=70,
        information_gain_micros=700_000,
        depth=0,
        state="RUNNING",
        attempt_count=1,
        retry_limit=2,
        revision=2,
        started_at_us=1,
    )


def test_credential_free_provider_adapters_return_exact_public_sources() -> None:
    transport = JsonTransport(
        [
            [
                {
                    "username": "synthetic-orbit",
                    "name": "Synthetic Orbit",
                    "web_url": "https://gitlab.com/synthetic-orbit",
                }
            ],
            {
                "objects": [
                    {
                        "package": {
                            "name": "synthetic-package",
                            "description": "Synthetic package.",
                            "links": {"npm": "https://www.npmjs.com/package/synthetic-package"},
                        }
                    }
                ]
            },
            {"ldhName": "example.test", "handle": "SYNTHETIC-1"},
            [
                ["timestamp", "original", "statuscode", "digest"],
                ["20250102030405", "https://example.test/profile", "200", "ABC"],
            ],
            [
                {
                    "id": 742,
                    "common_name": "example.test",
                    "name_value": "example.test\nwww.example.test",
                }
            ],
        ]
    )
    broker = InvestigationToolBroker(
        public_discovery=cast(PublicDiscoveryService, object()),
        page_transport=transport,
    )
    tasks = (
        _task("SEARCH_USERNAME", "GITLAB_USERS", "synthetic-orbit"),
        _task("QUERY_REGISTRY", "NPM_REGISTRY", "synthetic-orbit"),
        _task("QUERY_REGISTRY", "RDAP_DOMAIN", "example.test"),
        _task("QUERY_ARCHIVE", "WAYBACK_CDX", "example.test"),
        _task("QUERY_CERTIFICATE_TRANSPARENCY", "CERTIFICATE_TRANSPARENCY", "example.test"),
    )

    executions = tuple(broker.execute(task) for task in tasks)

    assert all(item.state == "SUCCEEDED_RESULTS" for item in executions)
    urls = tuple(item.search_results[0].url for item in executions)
    assert urls == (
        "https://gitlab.com/synthetic-orbit",
        "https://www.npmjs.com/package/synthetic-package",
        transport.urls[2],
        "https://web.archive.org/web/20250102030405/https://example.test/profile",
        "https://crt.sh/?id=742",
    )
    assert len(set(urls)) == 5
