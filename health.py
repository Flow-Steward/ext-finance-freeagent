"""Offline module and operation catalog health; no OAuth or provider requests."""

from __future__ import annotations

import json

from freeagent.catalog import OPERATIONS
from freeagent.runtime import handle

EXPECTED_OPERATIONS = 166


def main() -> int:
    valid = len(OPERATIONS) == EXPECTED_OPERATIONS and handle({})["ok"] is False
    print(
        json.dumps(
            {
                "ok": valid,
                "result": {
                    "status": "ok" if valid else "invalid",
                    "operation_count": len(OPERATIONS),
                },
            }
        )
    )
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
