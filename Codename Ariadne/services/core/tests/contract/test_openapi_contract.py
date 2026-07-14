from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ariadne_core.api.app import create_contract_app
from ariadne_core.api.middleware import ROUTE_POLICIES

ROOT = Path(__file__).resolve().parents[4]


def test_openapi_is_offline_only_and_has_exact_route_capabilities() -> None:
    document = create_contract_app().openapi()

    assert document["openapi"].startswith("3.1.")
    expected = {
        ("get", "/v1/session"): (
            "session.read",
            0,
            65536,
            "ANY",
            "NONE",
            "LAUNCH_SESSION",
        ),
        ("get", "/v1/system/capabilities"): (
            "system.capabilities.read",
            0,
            65536,
            "ANY",
            "NONE",
            "LAUNCH_SESSION",
        ),
        ("post", "/v1/events/replay"): (
            "events.replay",
            128,
            65536,
            "UNLOCKED",
            "VAULT",
            "SHELL_INTERNAL",
        ),
        ("post", "/v1/vaults"): (
            "vault.create",
            1024,
            65536,
            "NO_VAULT",
            "VAULT",
            "USER_GESTURE_KEYCHAIN",
        ),
        ("post", "/v1/vaults/current/unlock"): (
            "vault.current.unlock",
            1024,
            65536,
            "LOCKED",
            "VAULT",
            "USER_GESTURE_KEYCHAIN",
        ),
        ("post", "/v1/vaults/current/lock"): (
            "vault.current.lock",
            0,
            65536,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("get", "/v1/profiles"): (
            "profiles.list",
            0,
            262144,
            "UNLOCKED",
            "VAULT",
            "SHELL_INTERNAL",
        ),
        ("post", "/v1/profiles"): (
            "profile.create",
            1024,
            65536,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("post", "/v1/intake/paste"): (
            "intake.paste",
            1_052_672,
            65536,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/intake/file"): (
            "intake.file",
            1_402_880,
            65536,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE_FILE_PICKER",
        ),
        ("post", "/v1/intake/review"): (
            "entities.review",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/entities/origins"): (
            "entity.origins",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/entities/decision"): (
            "entity.decision",
            2048,
            65536,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/graph/snapshot"): (
            "graph.snapshot",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("get", "/v1/local-ai/settings"): (
            "local_ai.settings.read",
            0,
            2048,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("post", "/v1/local-ai/settings"): (
            "local_ai.settings.update",
            1024,
            2048,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("post", "/v1/local-ai/models"): (
            "local_ai.models.discover",
            1024,
            262_144,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("post", "/v1/local-ai/test"): (
            "local_ai.connection.test",
            1024,
            2048,
            "UNLOCKED",
            "VAULT",
            "USER_GESTURE",
        ),
        ("post", "/v1/local-ai/workspace/analyze"): (
            "local_ai.workspace.analyze",
            100_000,
            131_072,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/local-ai/corpus/analyze"): (
            "local_ai.corpus.analyze",
            5_750_000,
            256_000,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/query/providers"): (
            "query.providers.read",
            512,
            16384,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/query/plans"): (
            "query.plans.create",
            2048,
            262_144,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/query/dry-run"): (
            "query.dry_run.execute",
            1024,
            4096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/discovery/public/search"): (
            "discovery.public.search",
            8_192,
            262_144,
            "ANY",
            "NONE",
            "USER_GESTURE",
        ),
        ("post", "/v1/discovery/public/capture"): (
            "discovery.public.capture",
            8_192,
            4_096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/discovery/hibp/account"): (
            "discovery.hibp.account",
            4_096,
            1_048_576,
            "ANY",
            "NONE",
            "USER_GESTURE",
        ),
        ("post", "/v1/discovery/hibp/domain"): (
            "discovery.hibp.domain",
            4_096,
            1_048_576,
            "ANY",
            "NONE",
            "USER_GESTURE",
        ),
        ("post", "/v1/discovery/investigation/plan"): (
            "discovery.investigation.plan",
            40_960,
            262_144,
            "ANY",
            "NONE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/findings/list"): (
            "phase5.findings.list",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/findings/detail"): (
            "phase5.findings.detail",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/findings/manual"): (
            "phase5.findings.manual.create",
            4_096,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/evidence/manual-import"): (
            "phase5.evidence.manual_import",
            14_000_000,
            4_096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/evidence/redacted-derivative"): (
            "phase5.evidence.redacted_derivative.create",
            14_000_000,
            4_096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase5/attribution/decision"): (
            "phase5.attribution.decision.append",
            512,
            4_096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/audits/local-checkpoint"): (
            "phase6.audits.local_checkpoint.create",
            50_000,
            4_096,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/audits/list"): (
            "phase6.audits.list",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/audits/compare"): (
            "phase6.audits.compare",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/list"): (
            "phase6.remediation.list",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/detail"): (
            "phase6.remediation.detail",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/create"): (
            "phase6.remediation.create",
            50_000,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/draft"): (
            "phase6.remediation.draft.update",
            50_000,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/require-approval"): (
            "phase6.remediation.approval.require",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/status"): (
            "phase6.remediation.status.transition",
            6_144,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/deadline"): (
            "phase6.remediation.deadline.update",
            512,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/evidence"): (
            "phase6.remediation.evidence.link",
            4_096,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/provider-response"): (
            "phase6.remediation.provider_response.record",
            12_288,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/phase6/remediation/reappearance"): (
            "phase6.remediation.reappearance.record",
            4_096,
            1_048_576,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
        ("post", "/v1/reports/generate"): (
            "reports.generate",
            1_024,
            1_000_000,
            "UNLOCKED",
            "PROFILE",
            "USER_GESTURE",
        ),
    }
    actual = {
        (method, path) for path, path_item in document["paths"].items() for method in path_item
    }
    assert actual == set(expected)
    for (method, path), (
        route_id,
        maximum,
        maximum_response,
        lock_state,
        scope,
        authorization,
    ) in expected.items():
        capability = document["paths"][path][method]["x-ariadne-capability"]
        assert capability == {
            "authorizationClass": authorization,
            "maxRequestBytes": maximum,
            "maxResponseBytes": maximum_response,
            "requiredLockState": lock_state,
            "revealClass": "NONE",
            "routeId": route_id,
            "scopeClass": scope,
        }
    assert set(ROUTE_POLICIES) == {(method.upper(), path) for method, path in expected}
    for (method, path), (_, maximum, *_rest) in expected.items():
        assert ROUTE_POLICIES[(method.upper(), path)].maximum_body_bytes == maximum


def test_schema_contains_no_runtime_token_host_path_or_examples() -> None:
    encoded = json.dumps(create_contract_app().openapi(), sort_keys=True)

    assert "session_token" not in encoded
    assert "127.0.0.1:1" not in encoded
    assert str(ROOT) not in encoded
    assert '"example"' not in encoded
    assert '"examples"' not in encoded


def test_generated_contracts_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "packages" / "contracts" / "generate.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_generated_allowlists_contain_only_route_specific_boundaries() -> None:
    typescript = (ROOT / "packages/contracts/src/generated/api.ts").read_text()
    rust = (ROOT / "packages/contracts/src/generated/route_allowlist.rs").read_text()

    for route in (
        "/v1/session",
        "/v1/system/capabilities",
        "/v1/events/replay",
        "/v1/vaults",
        "/v1/vaults/current/unlock",
        "/v1/vaults/current/lock",
        "/v1/profiles",
        "/v1/intake/paste",
        "/v1/intake/file",
        "/v1/intake/review",
        "/v1/entities/origins",
        "/v1/entities/decision",
        "/v1/graph/snapshot",
        "/v1/local-ai/settings",
        "/v1/local-ai/models",
        "/v1/local-ai/test",
        "/v1/local-ai/workspace/analyze",
        "/v1/local-ai/corpus/analyze",
        "/v1/query/providers",
        "/v1/query/plans",
        "/v1/query/dry-run",
        "/v1/discovery/public/search",
        "/v1/discovery/public/capture",
        "/v1/discovery/hibp/account",
        "/v1/discovery/hibp/domain",
        "/v1/discovery/investigation/plan",
        "/v1/phase5/findings/list",
        "/v1/phase5/findings/detail",
        "/v1/phase5/findings/manual",
        "/v1/phase5/evidence/manual-import",
        "/v1/phase5/evidence/redacted-derivative",
        "/v1/phase5/attribution/decision",
        "/v1/phase6/audits/local-checkpoint",
        "/v1/phase6/audits/list",
        "/v1/phase6/audits/compare",
        "/v1/phase6/remediation/list",
        "/v1/phase6/remediation/detail",
        "/v1/phase6/remediation/create",
        "/v1/phase6/remediation/draft",
        "/v1/phase6/remediation/require-approval",
        "/v1/phase6/remediation/status",
        "/v1/phase6/remediation/deadline",
        "/v1/phase6/remediation/evidence",
        "/v1/phase6/remediation/provider-response",
        "/v1/phase6/remediation/reappearance",
        "/v1/reports/generate",
    ):
        assert route in typescript
        assert route in rust
    assert typescript.count('"method": "GET"') == 4
    assert rust.count('method: "GET"') == 4
    assert typescript.count('"method": "POST"') == 44
    assert rust.count('method: "POST"') == 44
    assert "/v1/vaults/current/descriptor" not in typescript
    assert "/v1/providers" not in rust
