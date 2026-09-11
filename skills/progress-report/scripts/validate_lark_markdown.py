#!/usr/bin/env python3
"""Reject or normalize ASCII tildes before Markdown is sent to Lark."""

from __future__ import annotations

import argparse
from pathlib import Path


SAFE_RANGE_SEPARATOR = "–"


def tilde_locations(content: str) -> list[tuple[int, int]]:
    locations = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        start = 0
        while (column := line.find("~", start)) != -1:
            locations.append((line_number, column + 1))
            start = column + 1
    return locations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prevent Lark from interpreting ASCII '~' as strikethrough markup."
    )
    parser.add_argument("markdown_file", type=Path)
    parser.add_argument(
        "--fix",
        action="store_true",
        help=f"replace every ASCII '~' with '{SAFE_RANGE_SEPARATOR}' before validating",
    )
    args = parser.parse_args()

    content = args.markdown_file.read_text(encoding="utf-8")
    locations = tilde_locations(content)
    if not locations:
        print(f"OK: {args.markdown_file} contains no ASCII tildes")
        return 0

    if args.fix:
        args.markdown_file.write_text(
            content.replace("~", SAFE_RANGE_SEPARATOR), encoding="utf-8"
        )
        print(
            f"Normalized {len(locations)} ASCII tilde(s) in {args.markdown_file} "
            f"to '{SAFE_RANGE_SEPARATOR}'"
        )
        return 0

    preview = ", ".join(f"{line}:{column}" for line, column in locations[:10])
    suffix = " ..." if len(locations) > 10 else ""
    print(
        f"ERROR: {args.markdown_file} contains {len(locations)} ASCII tilde(s) "
        f"at {preview}{suffix}. Run again with --fix before Lark delivery."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
