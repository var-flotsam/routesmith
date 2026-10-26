"""Fail if any tracked text file is not valid UTF-8 (`python scripts/check-utf8.py`)."""

import subprocess
import sys

BINARY = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pbf", ".woff", ".woff2")


def main() -> int:
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    bad = []
    for name in files.stdout.splitlines():
        if name.lower().endswith(BINARY):
            continue
        try:
            with open(name, "rb") as handle:
                handle.read().decode("utf-8")
        except UnicodeDecodeError as error:
            bad.append(f"{name}: byte {error.start}")
    for line in bad:
        print(f"not UTF-8: {line}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
