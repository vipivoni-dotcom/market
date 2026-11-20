"""Offline structural check. Does not import the bot, read secrets or contact services."""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> dict:
    paths = [root / "run.py", root / "tools.py"]
    for folder in ("arb", "tests", "scripts", "deploy", ".codex/hooks"):
        paths.extend((root / folder).rglob("*.py"))
    paths.extend((root / ".codex").rglob("*.toml"))
    paths += [root / ".codex/hooks.json", root / "arb/covers3d/games.json"]
    errors, checked = [], 0
    for path in sorted(set(paths)):
        if not path.is_file():
            errors.append({"file": path.relative_to(root).as_posix(), "line": 0, "kind": "MissingFile"})
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
            if path.suffix == ".py":
                ast.parse(source, filename=str(path))
            elif path.suffix == ".toml":
                tomllib.loads(source)
            else:
                json.loads(source)
            checked += 1
        except (SyntaxError, ValueError, OSError) as exc:
            # Exception text can contain source snippets. Report location/type only.
            errors.append({"file": path.relative_to(root).as_posix(),
                           "line": getattr(exc, "lineno", 0), "kind": type(exc).__name__})
    return {"ok": not errors, "checked": checked, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Machine-readable result")
    args = parser.parse_args()
    result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print(f"Offline structure: {result['checked']} files, {len(result['errors'])} errors")
        for error in result["errors"]:
            print(f"{error['file']}:{error['line']}: {error['kind']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
