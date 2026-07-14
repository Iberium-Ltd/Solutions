from __future__ import annotations

from ariadne_core.privacy.validation import safe_field_path


def test_safe_field_path_keeps_only_schema_locations() -> None:
    assert safe_field_path(("body", "display_name", 2)) == "body.display_name.2"
    assert safe_field_path(("body", "not a schema field")) == "body.field"
    assert safe_field_path(()) == "request"
