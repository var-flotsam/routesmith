"""Write the OpenAPI spec: `uv run python -m starboard.api.openapi apps/web/openapi.json`.

The web app's API types are generated from this file, and CI checks both are current.
"""

import json
import sys
from pathlib import Path

from starboard.api.app import create_app


def main(argv: list[str]) -> int:
    spec = create_app().openapi()
    text = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    Path(argv[1]).write_text(text, encoding="utf-8", newline="\n")  # the same file on any OS
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
