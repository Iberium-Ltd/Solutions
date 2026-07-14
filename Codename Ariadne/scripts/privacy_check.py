#!/usr/bin/env python3
"""Fail closed on private-reference paths, likely secrets, and unsafe demo PII.

The optional local collision scan derives high-signal markers from ignored private
references in memory. It never writes or prints a matched value.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git",
    ".privacy",
    ".venv",
    "artifacts",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
}
DENIED_PATH_PARTS = {"private_reference"}
DENIED_FILENAME_PATTERNS = (
    re.compile(r"digital_footprint_audit_findings_.*\.md$", re.IGNORECASE),
    re.compile(r"digital_footprint_audit_methodology_.*\.md$", re.IGNORECASE),
)
EMAIL_RE = re.compile(
    r"(?<![\w.+-])([\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}))(?![\w.-])"
)
URL_RE = re.compile(r"https?://[^\s<>\])}\"']+", re.IGNORECASE)
SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("generic bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}", re.IGNORECASE)),
)
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".scss",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {"Makefile", ".gitignore", ".npmrc", ".python-version"}


def git_candidates(staged_only: bool) -> list[Path] | None:
    """Return Git candidate paths, or None when no repository exists."""
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None

    command = ["git", "diff", "--cached", "--name-only", "-z"] if staged_only else [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("Unable to enumerate Git candidates")
    return [ROOT / item.decode("utf-8", "surrogateescape") for item in result.stdout.split(b"\0") if item]


def filesystem_candidates() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not (set(path.relative_to(ROOT).parts) & SKIP_PARTS)
        and not (
            {part.casefold() for part in path.relative_to(ROOT).parts}
            & DENIED_PATH_PARTS
        )
        and not any(
            pattern.search(path.name) for pattern in DENIED_FILENAME_PATTERNS
        )
    ]


def is_text_candidate(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def read_text(path: Path) -> str | None:
    if not is_text_candidate(path):
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if b"\0" in payload[:8192]:
        return None
    return payload.decode("utf-8", "replace")


def derive_private_markers() -> set[str]:
    """Extract high-signal local markers without persisting them.

    The derivation intentionally avoids printing or serialising marker values.
    """
    reference_dir = ROOT / "Instructions" / "private_reference"
    if not reference_dir.is_dir():
        return set()

    markers: set[str] = set()
    for path in reference_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")

        subject = re.search(r"^\*\*Subject:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
        if subject and len(subject.group(1).strip()) >= 5:
            markers.add(subject.group(1).strip().casefold())

        markers.update(match.group(1).casefold() for match in EMAIL_RE.finditer(text))
        markers.update(match.group(0).rstrip(".,").casefold() for match in URL_RE.finditer(text))

        seed_section = re.search(
            r"# 4\. Seed collection(?P<body>.*?)(?:\n# 5\.|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if seed_section:
            for value in re.findall(r"^\s*-\s+`?([^`\n]+?)`?\.?\s*$", seed_section.group("body"), re.MULTILINE):
                cleaned = value.strip().rstrip(".")
                if len(cleaned) >= 5:
                    markers.add(cleaned.casefold())

        example_config = re.search(
            r"## 14\.3 Example identity configuration(?P<body>.*?)(?:\n## 14\.4|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if example_config:
            for value in re.findall(r"^\s+-\s+([^\n#]+?)\s*$", example_config.group("body"), re.MULTILINE):
                cleaned = value.strip().strip("'\"")
                if len(cleaned) >= 5:
                    markers.add(cleaned.casefold())

    return markers


def scan(paths: list[Path], include_local_markers: bool) -> list[str]:
    failures: list[str] = []
    private_markers = derive_private_markers() if include_local_markers else set()

    for path in sorted(set(paths)):
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if not path.exists() or not path.is_file():
            continue

        lower_parts = {part.casefold() for part in relative.parts}
        if lower_parts & DENIED_PATH_PARTS:
            failures.append(f"{relative}: denied confidential path")
            continue
        if any(pattern.search(relative.name) for pattern in DENIED_FILENAME_PATTERNS):
            failures.append(f"{relative}: denied confidential filename")
            continue

        text = read_text(path)
        if text is None:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for email_match in EMAIL_RE.finditer(line):
                if re.fullmatch(
                    r"\d+x\d+@\d+x\.png",
                    email_match.group(1),
                    re.IGNORECASE,
                ):
                    continue
                domain = email_match.group(2).casefold()
                if not domain.endswith(".invalid") and domain != "example.invalid":
                    failures.append(f"{relative}:{line_number}: non-reserved email address")

            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    failures.append(f"{relative}:{line_number}: likely {label}")

        if private_markers and relative.parts[0] != "Instructions":
            folded = text.casefold()
            if any(marker in folded for marker in private_markers):
                failures.append(f"{relative}: private-reference collision (value suppressed)")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="scan staged paths only")
    parser.add_argument(
        "--no-local-reference-scan",
        action="store_true",
        help="skip the optional in-memory collision scan",
    )
    args = parser.parse_args()

    candidates = git_candidates(args.staged)
    if candidates is None:
        candidates = filesystem_candidates()
    failures = scan(candidates, include_local_markers=not args.no_local_reference_scan)

    if failures:
        print("Privacy check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    mode = "staged" if args.staged else "repository"
    print(f"Privacy check passed ({mode}; {len(candidates)} candidate files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
