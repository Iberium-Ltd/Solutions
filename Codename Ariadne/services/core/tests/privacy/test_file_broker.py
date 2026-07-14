from __future__ import annotations

from pathlib import Path

import pytest

from ariadne_core.security.file_broker import BrokerOperation, FileBroker, FileBrokerError


def test_file_capability_is_one_time_operation_bound_and_expiring(tmp_path) -> None:
    now = [10.0]
    broker = FileBroker(clock=lambda: now[0])
    destination = tmp_path / "synthetic-backup.bin"
    token = broker.issue(BrokerOperation.BACKUP_WRITE, destination, ttl_seconds=5)
    assert broker.consume(token, BrokerOperation.BACKUP_WRITE) == destination
    with pytest.raises(FileBrokerError):
        broker.consume(token, BrokerOperation.BACKUP_WRITE)

    expired = broker.issue(BrokerOperation.RESTORE_READ, destination, ttl_seconds=5)
    now[0] = 20.0
    with pytest.raises(FileBrokerError):
        broker.consume(expired, BrokerOperation.RESTORE_READ)


def test_file_broker_rejects_relative_and_symlink_paths(tmp_path) -> None:
    broker = FileBroker()
    with pytest.raises(FileBrokerError):
        broker.issue(BrokerOperation.IMPORT_READ, Path("relative-file"))
    target = tmp_path / "target"
    target.write_text("synthetic")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileBrokerError):
        broker.issue(BrokerOperation.IMPORT_READ, link)
