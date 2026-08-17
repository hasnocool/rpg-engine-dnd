# .github/scripts/pytest_annotations.py
"""Convert pytest failure summaries into GitHub Actions annotations."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SUMMARY = re.compile(
    r"^(?P<level>FAILED|ERROR) (?P<nodeid>tests/[^ ]+?)(?: - (?P<message>.*))?$"
)
COLLECTION = re.compile(r"^ERROR collecting (?P<path>tests/[^ ]+)$")
TRACE_LOCATION = re.compile(r"^(?P<path>tests/[^:]+):(?P<line>\d+):")


def _escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def _file_from_nodeid(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: pytest_annotations.py <pytest-output-file>")

    lines = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    emitted = 0

    for line in lines:
        match = SUMMARY.match(line)
        if match is None:
            continue
        path = _file_from_nodeid(match["nodeid"])
        message = match["message"] or match["nodeid"]
        print(f"::error file={_escape(path, property_value=True)}::{_escape(message)}")
        emitted += 1

    if emitted:
        return 0

    for index, line in enumerate(lines):
        match = COLLECTION.match(line)
        if match is None:
            continue
        path = match["path"]
        details = "pytest collection failed"
        for candidate in lines[index + 1 : index + 15]:
            if candidate.startswith("E   "):
                details = candidate[4:]
                break
        print(f"::error file={_escape(path, property_value=True)}::{_escape(details)}")
        emitted += 1

    if emitted:
        return 0

    for line in lines:
        location = TRACE_LOCATION.match(line)
        if location is None:
            continue
        print(
            f"::error file={_escape(location['path'], property_value=True)},"
            f"line={location['line']}::pytest failed; inspect the job output for traceback details"
        )
        return 0

    print("::error::pytest failed; inspect the job output for traceback details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
