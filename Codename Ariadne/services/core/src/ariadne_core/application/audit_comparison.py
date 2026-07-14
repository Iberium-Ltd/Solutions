"""Side-effect-free application service for audit snapshot comparison."""

from __future__ import annotations

from ariadne_core.domain.audit_comparison import (
    AuditComparison,
    AuditRunSnapshot,
    compare_audit_snapshots,
)


class AuditComparisonService:
    def compare(
        self,
        snapshots: tuple[AuditRunSnapshot, ...],
        *,
        baseline_run_id: str | None = None,
        current_run_id: str | None = None,
    ) -> AuditComparison:
        return compare_audit_snapshots(
            snapshots,
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
        )
