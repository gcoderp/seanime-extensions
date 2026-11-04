#!/usr/bin/env python3
"""Safe Git publisher script for validated Seanime extensions and reports."""
import subprocess
import sys

def run_cmd(args):
    res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def main():
    code, out, _ = run_cmd(["git", "status", "--porcelain", "src/", "marketplace.json", "generated/", "reports/"])
    if not out:
        print("No new validated extension changes to commit.")
        return 0
    print("Validated changes ready for commit:\n" + out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
