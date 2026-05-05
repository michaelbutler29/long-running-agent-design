#!/usr/bin/env python3
"""
Submit a paired policy proposal to the incorporation pipeline.

A proposal has two parts:
    --cedar          Path to a file containing the Cedar policy fragment.
    --justification  Path to a file containing the structured justification
                     (typically JSON; format consumed by your evaluator).

Both are required. The script reads each file, packages them into a
single payload, and hands the payload off to the incorporation pipeline.

[ORG: This is a stub. Replace the body of `submit_proposal` with your
real incorporation logic. Examples: write to S3, post to a queue, open
a ticket, append to an audit log. The agent only sees the exit code
and stderr; design accordingly.]
"""

import argparse
import json
import sys
from pathlib import Path


def submit_proposal(cedar: str, justification: str) -> None:
    """Hand a paired proposal off to the incorporation pipeline. Stub implementation."""
    # [ORG: Replace this stub with real incorporation logic.]
    payload = {
        "cedar": cedar,
        "justification": justification,
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cedar",
        required=True,
        type=Path,
        help="Path to the Cedar policy fragment file.",
    )
    parser.add_argument(
        "--justification",
        required=True,
        type=Path,
        help="Path to the structured justification file.",
    )
    args = parser.parse_args()

    if not args.cedar.is_file():
        print(f"ERROR: cedar file not found: {args.cedar}", file=sys.stderr)
        return 1
    if not args.justification.is_file():
        print(f"ERROR: justification file not found: {args.justification}", file=sys.stderr)
        return 1

    cedar = args.cedar.read_text()
    justification = args.justification.read_text()

    if not cedar.strip():
        print("ERROR: cedar file is empty", file=sys.stderr)
        return 1
    if not justification.strip():
        print("ERROR: justification file is empty", file=sys.stderr)
        return 1

    submit_proposal(cedar, justification)
    return 0


if __name__ == "__main__":
    sys.exit(main())
