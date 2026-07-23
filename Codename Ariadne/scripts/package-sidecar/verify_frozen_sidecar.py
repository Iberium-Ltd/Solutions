#!/usr/bin/env python3
"""Exercise the frozen sidecar through the same bounded contract as the shell.

The probe uses synthetic records and validates responses rather than trusting a
successful HTTP status. TCP proves the development transport; UDS plus the key
lease proves the packaged boundary and cleanup behavior.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from ariadne_core.application.reporting import (  # type: ignore[import-untyped]
    REDACTION_POLICY_VERSION,
)
from ariadne_core.application.vault import VaultManifest  # type: ignore[import-untyped]
from ariadne_core.security.key_lease import (  # type: ignore[import-untyped]
    FrameKind,
    GrantFrame,
    KEY_LEASE_FD,
    HelloFrame,
    LeaseBinding,
    LeaseOperation,
    RequestFrame,
    TransactionFrame,
    binding_digest,
    receive_frame,
    send_frame,
)

_POSITIVE_ATTRIBUTION_SIGNALS = {
    "CHRONOLOGICAL_COMPATIBILITY",
    "EXACT_EMAIL",
    "EXACT_LEGAL_NAME",
    "IMMUTABLE_PLATFORM_ID_CONTINUITY",
    "RECOVERY_RELATIONSHIP",
    "SAME_EDUCATION",
    "SAME_LINKED_DOMAIN",
    "SAME_LOCATION",
    "SAME_ORGANISATION",
    "SAME_PHOTOGRAPH",
    "SAME_PROJECT",
    "SAME_UNCOMMON_USERNAME",
    "SAME_WRITING_PROFILE_LINKS",
    "USER_CONFIRMATION",
}


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(f"frozen {label} is invalid")
    return value


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(f"frozen {label} is invalid")
    return value


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"frozen {label} is invalid")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise RuntimeError(f"frozen {label} is invalid") from error
    if str(parsed) != value:
        raise RuntimeError(f"frozen {label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise RuntimeError(f"frozen {label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"frozen {label} is invalid")
    return value


def _validate_manual_finding(
    value: object,
    *,
    profile_id: str,
    title: str,
    summary: str,
    provider_label: str,
) -> str:
    body = _mapping(value, "manual finding response")
    finding = _mapping(body.get("finding"), "manual finding summary")
    assessment = _mapping(body.get("assessment"), "manual finding assessment")
    finding_id = _canonical_uuid(finding.get("findingId"), "manual finding id")
    _canonical_uuid(assessment.get("assessmentId"), "manual assessment id")
    missing = _sequence(
        assessment.get("missingEvidence"),
        "manual assessment missing evidence",
    )
    missing_signals = {
        str(_mapping(item, "manual missing-evidence item").get("signal"))
        for item in missing
    }
    if (
        body.get("profileId") != profile_id
        or finding.get("title") != title
        or finding.get("summary") != summary
        or finding.get("outcome") != "MANUAL_REVIEW_REQUIRED"
        or finding.get("severity") != "LOW"
        or finding.get("visibility") != "UNKNOWN"
        or finding.get("providerLabel") != provider_label
        or finding.get("attributionState") is not None
        or finding.get("score") != 0
        or finding.get("confidenceBand") != "LOW"
        or finding.get("artifactCount") != 0
        or finding.get("humanReviewRequired") is not True
        or assessment.get("caseId") != finding_id
        or assessment.get("weightProfileVersion") != "ariadne-core-attribution-v1"
        or assessment.get("score") != 0
        or assessment.get("confidenceBand") != "LOW"
        or assessment.get("contributingSignals") != []
        or assessment.get("contradictions") != []
        or missing_signals != _POSITIVE_ATTRIBUTION_SIGNALS
        or assessment.get("recommendedNextEvidence")
        != [
            "IMMUTABLE_PLATFORM_ID_CONTINUITY",
            "USER_CONFIRMATION",
            "EXACT_EMAIL",
        ]
        or assessment.get("humanReviewRequired") is not True
        or body.get("artifacts") != []
        or body.get("humanDecision") is not None
    ):
        raise RuntimeError("frozen manual finding response is incompatible")
    _positive_integer(finding.get("updatedAtUs"), "manual finding timestamp")
    return finding_id


def _validate_checkpoint(
    value: object,
    *,
    profile_id: str,
    expected_sequence: int,
) -> tuple[str, int]:
    body = _mapping(value, "local checkpoint response")
    run_id = _canonical_uuid(body.get("runId"), "local checkpoint run id")
    captured_at_us = _positive_integer(
        body.get("capturedAtUs"),
        "local checkpoint timestamp",
    )
    if (
        body.get("profileId") != profile_id
        or body.get("sequence") != expected_sequence
        or body.get("runState") != "COMPLETED"
        or body.get("findingCount") != 1
        or body.get("providerCount") != 1
        or body.get("localOnly") is not True
    ):
        raise RuntimeError("frozen local checkpoint response is incompatible")
    return run_id, captured_at_us


def _validate_redacted_json_report(
    value: object,
    *,
    profile_id: str,
    baseline_run_id: str,
    current_run_id: str,
    finding_id: str,
    sensitive_values: tuple[str, ...],
) -> None:
    body = _mapping(value, "report response")
    artifact = _mapping(body.get("artifact"), "report artifact")
    manifest = _mapping(body.get("manifest"), "report manifest")
    content = artifact.get("content")
    if not isinstance(content, str):
        raise RuntimeError("frozen report content is invalid")
    encoded = content.encode("utf-8")
    if (
        body.get("profileId") != profile_id
        or body.get("baselineRunId") != baseline_run_id
        or body.get("currentRunId") != current_run_id
        or body.get("localOnly") is not True
        or artifact.get("filename") != "report.json"
        or artifact.get("mediaType") != "application/json"
        or artifact.get("schema") != "ariadne.local-report"
        or artifact.get("version") != 1
        or artifact.get("mode") != "REDACTED"
        or artifact.get("byteCount") != len(encoded)
        or artifact.get("sha256") != hashlib.sha256(encoded).hexdigest()
        or manifest.get("schema") != "ariadne.local-report"
        or manifest.get("version") != 1
        or manifest.get("mode") != "REDACTED"
        or manifest.get("fullExportApprovalId") is not None
    ):
        raise RuntimeError("frozen report artifact binding is incompatible")
    _positive_integer(manifest.get("generatedAtUs"), "report generation timestamp")

    descriptors = _sequence(manifest.get("artifacts"), "report artifact manifest")
    if len(descriptors) != 2:
        raise RuntimeError("frozen report artifact manifest is incompatible")
    by_filename = {
        str(descriptor.get("filename")): descriptor
        for item in descriptors
        if (descriptor := _mapping(item, "report artifact descriptor"))
    }
    json_descriptor = by_filename.get("report.json")
    markdown_descriptor = by_filename.get("report.md")
    if (
        len(by_filename) != 2
        or json_descriptor is None
        or markdown_descriptor is None
        or json_descriptor.get("mediaType") != "application/json"
        or json_descriptor.get("byteCount") != len(encoded)
        or json_descriptor.get("sha256") != hashlib.sha256(encoded).hexdigest()
        or markdown_descriptor.get("mediaType") != "text/markdown; charset=utf-8"
    ):
        raise RuntimeError("frozen report artifact manifest is incompatible")
    _positive_integer(
        markdown_descriptor.get("byteCount"), "Markdown report byte count"
    )
    _sha256(markdown_descriptor.get("sha256"), "Markdown report digest")

    try:
        document = _mapping(json.loads(content), "JSON report document")
    except json.JSONDecodeError as error:
        raise RuntimeError("frozen JSON report content is invalid") from error
    if set(document) != {
        "comparison",
        "constraints",
        "findings",
        "manifest",
        "profile",
        "remediations",
        "summary",
    }:
        raise RuntimeError("frozen JSON report schema is incompatible")
    document_manifest = _mapping(document.get("manifest"), "JSON report manifest")
    constraints = _mapping(document.get("constraints"), "JSON report constraints")
    summary = _mapping(document.get("summary"), "JSON report summary")
    comparison = _mapping(document.get("comparison"), "JSON report comparison")
    findings = _sequence(document.get("findings"), "JSON report findings")
    if len(findings) != 1:
        raise RuntimeError("frozen JSON report finding projection is incompatible")
    report_finding = _mapping(findings[0], "JSON report finding")
    attribution = _mapping(report_finding.get("attribution"), "JSON report attribution")
    coverage = _sequence(comparison.get("coverage"), "JSON report coverage")
    diffs = _sequence(comparison.get("diffs"), "JSON report diffs")
    if (
        document_manifest.get("schema") != "ariadne.local-report"
        or document_manifest.get("version") != 1
        or document_manifest.get("mode") != "REDACTED"
        or document_manifest.get("full_export_approval_id") is not None
        or document_manifest.get("redaction_policy_version") != REDACTION_POLICY_VERSION
        or constraints
        != {
            "active_content_included": False,
            "evidence_bytes_included": False,
            "filesystem_writes_performed": False,
            "network_access_performed": False,
            "outbound_actions_performed": False,
        }
        or summary.get("finding_count") != 1
        or summary.get("evidence_metadata_count") != 0
        or summary.get("provider_coverage_count") != 1
        or summary.get("remediation_count") != 0
        or len(coverage) != 1
        or len(diffs) != 1
        or _mapping(coverage[0], "JSON report coverage item").get("baseline_state")
        != "COMPLETE"
        or _mapping(coverage[0], "JSON report coverage item").get("current_state")
        != "COMPLETE"
        or _mapping(diffs[0], "JSON report diff").get("state") != "UNCHANGED"
        or comparison.get("incomplete") is not False
        or comparison.get("incomplete_reasons") != []
        or comparison.get("baseline_run_id") == baseline_run_id
        or comparison.get("current_run_id") == current_run_id
        or comparison.get("baseline_run_id") == comparison.get("current_run_id")
        or report_finding.get("finding_id") == finding_id
        or report_finding.get("evidence") != []
        or attribution.get("score") != 0
        or attribution.get("confidence_band") != "LOW"
        or document.get("remediations") != []
    ):
        raise RuntimeError("frozen JSON report projection is incompatible")
    if any(value in content for value in sensitive_values):
        raise RuntimeError(
            "frozen redacted report retained unredacted synthetic values"
        )


def _request_headers(
    token: str, origin: str, request_id: str | None = None
) -> dict[str, str]:
    return {
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": request_id or str(uuid4()),
        "Ariadne-Session": token,
        "Origin": origin,
    }


def _clone_binding(binding: LeaseBinding) -> LeaseBinding:
    return LeaseBinding(
        startup_nonce=binding.startup_nonce,
        lease_nonce=bytearray(binding.lease_nonce),
        transaction_id=binding.transaction_id,
        vault_id=binding.vault_id,
        manifest_digest=bytearray(binding.manifest_digest),
        reference=binding.reference,
        key_version=binding.key_version,
        operation=binding.operation,
    )


def _serve_create_lease(
    peer: socket.socket,
    key: bytearray,
    *,
    vault_id: UUID,
    manifest_digest: bytes,
    database_key_ref: str,
    errors: list[BaseException],
) -> None:
    request: RequestFrame | None = None
    try:
        received = receive_frame(peer)
        if not isinstance(received, RequestFrame):
            raise RuntimeError("frozen create sent an unexpected lease frame")
        request = received
        binding = request.binding
        if (
            binding.vault_id != vault_id
            or binding.manifest_digest != manifest_digest
            or binding.reference != database_key_ref
            or binding.key_version != 1
            or binding.operation is not LeaseOperation.DATABASE_CREATE_V1
        ):
            raise RuntimeError("frozen create lease binding is incompatible")
        grant = GrantFrame(_clone_binding(binding), bytearray(key))
        try:
            send_frame(peer, grant)
        finally:
            grant.zeroize()
        prepared = receive_frame(peer)
        if (
            not isinstance(prepared, TransactionFrame)
            or prepared.kind is not FrameKind.PREPARED
        ):
            raise RuntimeError("frozen create did not prepare the lease")
        expected_digest = binding_digest(binding)
        if prepared.binding_digest != expected_digest:
            raise RuntimeError("frozen create prepared the wrong lease binding")
        expected_digest[:] = b"\x00" * len(expected_digest)
        commit = TransactionFrame(
            kind=FrameKind.COMMIT,
            startup_nonce=prepared.startup_nonce,
            lease_nonce=bytearray(prepared.lease_nonce),
            transaction_id=prepared.transaction_id,
            binding_digest=bytearray(prepared.binding_digest),
        )
        prepared.zeroize()
        try:
            send_frame(peer, commit)
        finally:
            commit.zeroize()
        committed = receive_frame(peer)
        if (
            not isinstance(committed, TransactionFrame)
            or committed.kind is not FrameKind.COMMITTED
        ):
            raise RuntimeError("frozen create did not commit the lease")
        committed.zeroize()
    except BaseException as error:
        errors.append(error)
    finally:
        if request is not None:
            request.zeroize()


def _exercise(binary: Path, transport: str) -> dict[str, object]:
    """Run one isolated vault lifecycle; no state is shared between transports."""
    token = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    startup_nonce = uuid4()
    bootstrap = {
        "contract_version": 1,
        "parent_pid": os.getpid(),
        "protocol_version": 1,
        "session_token": token,
        "startup_nonce": str(startup_nonce),
    }
    started = time.monotonic()
    isolated_home = tempfile.TemporaryDirectory(prefix="afh-", dir="/tmp")
    child_environment = {**os.environ, "HOME": isolated_home.name}
    database_key = bytearray(range(32))
    vault_create_status: int | None = None
    profile_create_status: int | None = None
    intake_paste_status: int | None = None
    entity_review_status: int | None = None
    manual_finding_status: int | None = None
    baseline_checkpoint_status: int | None = None
    current_checkpoint_status: int | None = None
    report_generate_status: int | None = None
    intake_quarantine_count: int | None = None
    migration_revision: str | None = None
    lease_peer: socket.socket | None = None
    if transport == "uds":
        lease_peer, child_endpoint = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_STREAM
        )
        lease_peer.settimeout(20)
        child_fd = child_endpoint.fileno()
        launcher = (
            "import os,sys;"
            "source=int(sys.argv[1]);target=int(sys.argv[2]);"
            "os.set_inheritable(source,True) if source==target "
            "else os.dup2(source,target,inheritable=True);"
            "os.close(source) if source!=target else None;"
            "os.execv(sys.argv[3],[sys.argv[3],*sys.argv[4:]])"
        )
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    launcher,
                    str(child_fd),
                    str(KEY_LEASE_FD),
                    str(binary),
                    "serve",
                    "--bootstrap-stdin",
                    "--transport",
                    transport,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=(child_fd,),
                env=child_environment,
            )
        except BaseException:
            lease_peer.close()
            child_endpoint.close()
            raise
        child_endpoint.close()
    else:
        process = subprocess.Popen(
            [str(binary), "serve", "--bootstrap-stdin", "--transport", transport],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_environment,
        )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise RuntimeError("frozen sidecar pipes are unavailable")
    socket_path: Path | None = None
    try:
        process.stdin.write(json.dumps(bootstrap, separators=(",", ":")) + "\n")
        process.stdin.flush()
        if lease_peer is not None:
            hello = receive_frame(lease_peer)
            if not isinstance(hello, HelloFrame) or hello.startup_nonce != UUID(
                str(bootstrap["startup_nonce"])
            ):
                raise RuntimeError("frozen key-lease HELLO is incompatible")
            hello.lease_nonce[:] = b"\x00" * len(hello.lease_nonce)
        ready, _, _ = select.select([process.stdout], [], [], 20)
        if not ready:
            raise RuntimeError("frozen sidecar readiness timed out")
        readiness_line = process.stdout.readline()
        if not readiness_line:
            raise RuntimeError("frozen sidecar exited before readiness")
        readiness = json.loads(readiness_line)
        if (
            readiness.get("status") != "ready"
            or readiness.get("transport") != transport
        ):
            raise RuntimeError("frozen sidecar readiness is incompatible")

        if transport == "tcp":
            base_url = f"http://127.0.0.1:{int(readiness['port'])}"
            client = httpx.Client(base_url=base_url, timeout=30.0)
            origin = "http://127.0.0.1:1420"
        else:
            socket_path = Path(str(readiness["socket_path"]))
            client = httpx.Client(
                transport=httpx.HTTPTransport(uds=str(socket_path)),
                base_url="http://ariadne.local",
                timeout=30.0,
            )
            origin = "tauri://localhost"

        with client:
            capabilities = client.get(
                "/v1/system/capabilities", headers=_request_headers(token, origin)
            )
            session = client.get("/v1/session", headers=_request_headers(token, origin))
            replay_id = str(uuid4())
            replay_headers = _request_headers(token, origin, replay_id)
            first = client.get("/v1/session", headers=replay_headers)
            replay = client.get("/v1/session", headers=replay_headers)
            wrong_token = client.get(
                "/v1/session",
                headers=_request_headers(
                    base64.urlsafe_b64encode(os.urandom(32))
                    .rstrip(b"=")
                    .decode("ascii"),
                    origin,
                ),
            )
            wrong_origin = client.get(
                "/v1/session",
                headers=_request_headers(token, "https://outside.invalid"),
            )
            if lease_peer is not None:
                vault_id = uuid4()
                database_key_ref = f"kc:v1:{uuid4()}"
                manifest = VaultManifest(
                    vault_id=str(vault_id),
                    format_version=1,
                    database_key_ref=database_key_ref,
                    backup_key_ref=f"kc:v1:{uuid4()}",
                    database_key_version=1,
                )
                lease_errors: list[BaseException] = []
                lease_thread = threading.Thread(
                    target=_serve_create_lease,
                    args=(lease_peer, database_key),
                    kwargs={
                        "vault_id": vault_id,
                        "manifest_digest": manifest.digest(),
                        "database_key_ref": database_key_ref,
                        "errors": lease_errors,
                    },
                    daemon=True,
                )
                lease_thread.start()
                create = client.post(
                    "/v1/vaults",
                    json={
                        "displayName": "Synthetic frozen migration vault",
                        "transactionId": str(uuid4()),
                        "vaultId": manifest.vault_id,
                        "manifestDigest": manifest.digest().hex(),
                        "databaseKeyRef": manifest.database_key_ref,
                        "backupKeyRef": manifest.backup_key_ref,
                        "formatVersion": manifest.format_version,
                        "databaseKeyVersion": manifest.database_key_version,
                    },
                    headers=_request_headers(token, origin),
                )
                lease_thread.join(timeout=20)
                if lease_thread.is_alive() or lease_errors:
                    raise RuntimeError("frozen create lease did not complete") from (
                        lease_errors[0] if lease_errors else None
                    )
                vault_create_status = create.status_code
                if create.status_code != 200:
                    raise RuntimeError("frozen vault creation failed")
                profile = client.post(
                    "/v1/profiles",
                    json={
                        "idempotencyKey": str(uuid4()),
                        "displayLabel": "Synthetic frozen profile",
                        "purpose": "Synthetic frozen intake verification",
                    },
                    headers=_request_headers(token, origin),
                )
                profile_create_status = profile.status_code
                if profile.status_code != 200:
                    raise RuntimeError("frozen profile creation failed")
                profile_id = str(profile.json()["profileId"])
                restricted_canary = "synthetic-frozen-secret"
                intake = client.post(
                    "/v1/intake/paste",
                    json={
                        "idempotencyKey": str(uuid4()),
                        "profileId": profile_id,
                        "displayName": "Synthetic frozen pasted source",
                        "content": (
                            "Morgan Vale uses @night_orbit.\n"
                            "Contact: frozen.person@example.invalid.\n"
                            f"Password: {restricted_canary}"
                        ),
                        "consentConfirmed": True,
                        "retainRawSource": False,
                        "semanticEnrichmentEnabled": True,
                    },
                    headers=_request_headers(token, origin),
                )
                intake_paste_status = intake.status_code
                if intake.status_code != 200 or restricted_canary in intake.text:
                    raise RuntimeError("frozen isolated intake failed")
                intake_body = intake.json()
                intake_quarantine_count = int(intake_body["quarantineCount"])
                if intake_quarantine_count < 1:
                    raise RuntimeError("frozen restricted-value quarantine failed")
                review = client.post(
                    "/v1/intake/review",
                    json={
                        "profileId": profile_id,
                        "sourceId": intake_body["sourceId"],
                        "limit": 100,
                    },
                    headers=_request_headers(token, origin),
                )
                entity_review_status = review.status_code
                if (
                    review.status_code != 200
                    or not review.json()["entities"]
                    or restricted_canary in review.text
                ):
                    raise RuntimeError("frozen entity review failed")

                manual_title = "Synthetic frozen manual finding"
                manual_summary = (
                    "Synthetic local checkpoint material with no evidence artifacts."
                )
                manual_provider_id = "manual.frozen"
                manual_provider_label = "Synthetic frozen provider"
                manual_finding = client.post(
                    "/v1/phase5/findings/manual",
                    json={
                        "profileId": profile_id,
                        "title": manual_title,
                        "summary": manual_summary,
                        "outcome": "MANUAL_REVIEW_REQUIRED",
                        "severity": "LOW",
                        "visibility": "UNKNOWN",
                        "providerId": manual_provider_id,
                        "providerLabel": manual_provider_label,
                    },
                    headers=_request_headers(token, origin),
                )
                manual_finding_status = manual_finding.status_code
                if manual_finding.status_code != 200:
                    raise RuntimeError("frozen manual finding creation failed")
                finding_id = _validate_manual_finding(
                    manual_finding.json(),
                    profile_id=profile_id,
                    title=manual_title,
                    summary=manual_summary,
                    provider_label=manual_provider_label,
                )

                checkpoint_payload = {
                    "profileId": profile_id,
                    "runState": "COMPLETED",
                    "providerCoverage": [
                        {
                            "providerId": manual_provider_id,
                            "state": "COMPLETE",
                        }
                    ],
                }
                baseline_checkpoint = client.post(
                    "/v1/phase6/audits/local-checkpoint",
                    json=checkpoint_payload,
                    headers=_request_headers(token, origin),
                )
                baseline_checkpoint_status = baseline_checkpoint.status_code
                if baseline_checkpoint.status_code != 200:
                    raise RuntimeError("frozen baseline checkpoint creation failed")
                baseline_run_id, baseline_captured_at_us = _validate_checkpoint(
                    baseline_checkpoint.json(),
                    profile_id=profile_id,
                    expected_sequence=1,
                )

                current_checkpoint = client.post(
                    "/v1/phase6/audits/local-checkpoint",
                    json=checkpoint_payload,
                    headers=_request_headers(token, origin),
                )
                current_checkpoint_status = current_checkpoint.status_code
                if current_checkpoint.status_code != 200:
                    raise RuntimeError("frozen current checkpoint creation failed")
                current_run_id, current_captured_at_us = _validate_checkpoint(
                    current_checkpoint.json(),
                    profile_id=profile_id,
                    expected_sequence=2,
                )
                if (
                    current_run_id == baseline_run_id
                    or current_captured_at_us <= baseline_captured_at_us
                ):
                    raise RuntimeError("frozen checkpoint ordering is incompatible")

                report = client.post(
                    "/v1/reports/generate",
                    json={
                        "profileId": profile_id,
                        "baselineRunId": baseline_run_id,
                        "currentRunId": current_run_id,
                        "artifactFormat": "JSON",
                        "mode": "REDACTED",
                        "fullExportApprovalId": None,
                    },
                    headers=_request_headers(token, origin),
                )
                report_generate_status = report.status_code
                if report.status_code != 200:
                    raise RuntimeError("frozen redacted report generation failed")
                _validate_redacted_json_report(
                    report.json(),
                    profile_id=profile_id,
                    baseline_run_id=baseline_run_id,
                    current_run_id=current_run_id,
                    finding_id=finding_id,
                    sensitive_values=(
                        profile_id,
                        baseline_run_id,
                        current_run_id,
                        finding_id,
                        manual_title,
                        manual_summary,
                        manual_provider_id,
                        manual_provider_label,
                        "Synthetic frozen profile",
                    ),
                )

        expected_transport = "DEV_LOOPBACK" if transport == "tcp" else "UNIX_SOCKET"
        if (
            capabilities.status_code != 200
            or capabilities.json()["transport"] != expected_transport
        ):
            raise RuntimeError("frozen capabilities request failed")
        if session.status_code != 200 or first.status_code != 200:
            raise RuntimeError("frozen session request failed")
        if replay.status_code != 409 or wrong_token.status_code != 401:
            raise RuntimeError("frozen authentication/replay policy failed")
        if wrong_origin.status_code != 403:
            raise RuntimeError("frozen origin policy failed")
    finally:
        try:
            process.terminate()
            try:
                _stdout, stderr = process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                _stdout, stderr = process.communicate(timeout=5)
            if token in stderr:
                raise RuntimeError("session credential appeared in frozen stderr")
            if socket_path is not None and socket_path.exists():
                raise RuntimeError("frozen Unix socket was not cleaned up")
            if lease_peer is not None:
                try:
                    if lease_peer.recv(1) != b"":
                        raise RuntimeError("frozen key-lease channel remained writable")
                finally:
                    lease_peer.close()

            if vault_create_status == 200:
                from pysqlcipher3 import dbapi2  # type: ignore[import-untyped]

                database = (
                    Path(isolated_home.name)
                    / "Library/Application Support/app.codenameariadne.desktop/vault/vault.db"
                )
                if not database.is_file() or database.read_bytes().startswith(
                    b"SQLite format 3\x00"
                ):
                    raise RuntimeError("frozen vault database is missing or plaintext")
                connection = dbapi2.connect(str(database))
                try:
                    connection.set_raw_key(memoryview(database_key))
                    migration_revision = str(
                        connection.execute(
                            "SELECT version_num FROM alembic_version"
                        ).fetchone()[0]
                    )
                    dependency_table = int(
                        connection.execute(
                            "SELECT count(*) FROM sqlite_master "
                            "WHERE type='table' AND name='job_dependencies'"
                        ).fetchone()[0]
                    )
                    intake_identity_tables = int(
                        connection.execute(
                            "SELECT count(*) FROM sqlite_master WHERE type='table' "
                            "AND name IN ("
                            "'intake_sources','intake_segments','quarantine_items',"
                            "'extraction_runs','entities','entity_variants',"
                            "'entity_variant_decisions','entity_origins','entity_decisions',"
                            "'graph_nodes','graph_edges','graph_edge_origins',"
                            "'graph_edge_decisions'"
                            ")"
                        ).fetchone()[0]
                    )
                    phase5_tables = int(
                        connection.execute(
                            "SELECT count(*) FROM sqlite_master WHERE type='table' "
                            "AND name IN ("
                            "'phase5_findings','phase5_evidence_originals',"
                            "'phase5_finding_evidence','phase5_evidence_derivatives',"
                            "'phase5_attribution_assessments','phase5_attribution_signals',"
                            "'phase5_attribution_signal_evidence',"
                            "'phase5_attribution_missing_evidence',"
                            "'phase5_attribution_decisions'"
                            ")"
                        ).fetchone()[0]
                    )
                    phase6_tables = int(
                        connection.execute(
                            "SELECT count(*) FROM sqlite_master WHERE type='table' "
                            "AND name IN ("
                            "'phase6_audit_snapshots','phase6_audit_snapshot_findings',"
                            "'phase6_audit_snapshot_coverage',"
                            "'phase6_remediation_revisions','phase6_remediation_findings',"
                            "'phase6_remediation_evidence',"
                            "'phase6_remediation_provider_responses',"
                            "'phase6_remediation_provider_response_evidence',"
                            "'phase6_remediation_history',"
                            "'phase6_remediation_history_evidence'"
                            ")"
                        ).fetchone()[0]
                    )
                    restricted_storage_hits = int(
                        connection.execute(
                            "SELECT "
                            "(SELECT count(*) FROM intake_segments "
                            " WHERE instr(coalesce(content_text,''), ?) > 0) + "
                            "(SELECT count(*) FROM entities "
                            " WHERE instr(canonical_value, ?) > 0)",
                            ("synthetic-frozen-secret", "synthetic-frozen-secret"),
                        ).fetchone()[0]
                    )
                finally:
                    connection.close()
                if (
                    migration_revision != "0011_profile_purge"
                    or dependency_table != 1
                    or intake_identity_tables != 13
                    or phase5_tables != 9
                    or phase6_tables != 10
                    or restricted_storage_hits != 0
                ):
                    raise RuntimeError(
                        "frozen vault did not reach the supported migration head"
                    )
        finally:
            database_key[:] = b"\x00" * len(database_key)
            isolated_home.cleanup()

    return {
        "capabilities_status": capabilities.status_code,
        "exit_code": process.returncode,
        "origin_denial_status": wrong_origin.status_code,
        "replay_status": replay.status_code,
        "session_status": session.status_code,
        "startup_ms": round((time.monotonic() - started) * 1_000),
        "transport": transport,
        "vault_create_status": vault_create_status,
        "migration_revision": migration_revision,
        "profile_create_status": profile_create_status,
        "intake_paste_status": intake_paste_status,
        "entity_review_status": entity_review_status,
        "manual_finding_status": manual_finding_status,
        "baseline_checkpoint_status": baseline_checkpoint_status,
        "current_checkpoint_status": current_checkpoint_status,
        "report_generate_status": report_generate_status,
        "intake_quarantine_count": intake_quarantine_count,
        "wrong_token_status": wrong_token.status_code,
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_frozen_sidecar.py FROZEN_BINARY")
    binary = Path(sys.argv[1]).resolve(strict=True)
    results = [_exercise(binary, transport) for transport in ("tcp", "uds")]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
