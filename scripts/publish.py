#!/usr/bin/env python3
"""Safe Git publisher for validated Seanime extensions and reports.

Dry-run by default: it prints exactly what would be committed. Pass --push to commit and
push. Before touching git it re-runs the artifact checks, so a bundle whose JavaScript
does not parse can never be published from here.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = ["src", "generated", "marketplace.json", "reports", "config/license-cache.json"]
COMMIT_USER = "seanime-converter[bot]"
COMMIT_EMAIL = "seanime-converter@users.noreply.github.com"


def run(args, check=False):
    proc = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish validated Seanime extensions")
    ap.add_argument("--push", action="store_true", help="commit and push instead of a dry run")
    ap.add_argument("--message", default="", help="commit message override")
    args = ap.parse_args()

    print("Running pre-publish checks...")
    for cmd in (["node", "scripts/validate.mjs"], [sys.executable, "scripts/check_schema.py"]):
        code, out, err = run(cmd)
        if code != 0:
            print(out)
            print(err, file=sys.stderr)
            print("Pre-publish checks failed; nothing was committed.", file=sys.stderr)
            return 1
        print(f"  ok: {' '.join(cmd)}")

    existing = [p for p in TRACKED if os.path.exists(os.path.join(ROOT, p))]
    code, out, _ = run(["git", "status", "--porcelain"] + existing)
    if not out:
        print("No validated changes to commit.")
        return 0

    print("Changes staged for review:\n" + out)

    if not args.push:
        print("\nDry run only. Re-run with --push to commit and push these files.")
        return 0

    run(["git", "config", "user.name", COMMIT_USER], check=True)
    run(["git", "config", "user.email", COMMIT_EMAIL], check=True)
    run(["git", "add", "-A"] + existing, check=True)

    code, _, _ = run(["git", "diff", "--cached", "--quiet"])
    if code == 0:
        print("Nothing staged after add; nothing to publish.")
        return 0

    message = args.message or "chore(convert): publish validated Seanime extensions"
    run(["git", "commit", "-m", message], check=True)
    run(["git", "push"], check=True)
    print("Published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
