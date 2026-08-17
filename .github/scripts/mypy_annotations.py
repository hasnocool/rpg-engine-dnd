# .github/scripts/mypy_annotations.py
"""Convert mypy's text diagnostics into GitHub Actions workflow annotations."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<level>error|warning|note): (?P<message>.*)$"
)


def _escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: mypy_annotations.py <mypy-output-file>")

    for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        match = DIAGNOSTIC.match(raw_line)
        if match is None or match["level"] == "note":
            continue
        level = "warning" if match["level"] == "warning" else "error"
        properties = (
            f"file={_escape(match['file'], property_value=True)},"
            f"line={match['line']},col={match['column']}"
        )
        print(f"::{level} {properties}::{_escape(match['message'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
