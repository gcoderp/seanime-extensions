#!/usr/bin/env python3
"""Upgrades already-generated extension bundles to the corrected Seanime contract.

Why this exists
---------------
The generated bundles under src/ were produced against an earlier, wrong copy of
seanime/types/seanime-env.d.ts. Seanime's real contract (internal/extension_repo/*.d.ts)
differs in three ways that the type-checker now flags:

  1. `Media` has no `year`; the release year arrives as `opts.year`
     -> TS2339 "Property 'year' does not exist on type 'Media'"   (2 per online-stream bundle)
  2. `VideoSourceType` is "mp4" | "m3u8" | "unknown"; there is no "dash"
     -> TS2322 Type '"dash"' is not assignable to type 'VideoSourceType'
  3. `AnimeTorrent.isBestRelease` is required
     -> TS2345 object literal is not assignable to type 'AnimeTorrent'

The bundles also embed the old AniListResolver, which read `media.title.romaji` — a field
Seanime never sends, so it type-checked as `any` and silently fell back to opts.query.

This script rewrites those four things in place, recompiles the TypeScript with the real
compiler, and refreshes reports/marketplace/README. It does not download or re-convert
anything, so it is safe to run when upstream packages are unreachable.

Usage:
    python3 scripts/migrate-contract.py [--dry-run] [--no-reindex]
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PROVIDER_TYPES = ("onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source")

OLD_YEAR_LINE = re.compile(
    r"^[ \t]*const year = media && typeof media\.year === \"number\" \? media\.year : undefined;[ \t]*$",
    re.M,
)
NEW_YEAR_LINE = (
    "        // Seanime passes the release year at the top level of SearchOptions.\n"
    "        const year = AniListResolver.yearOf(opts);"
)

OLD_DASH_LINE = re.compile(r'^([ \t]*)if \(/\\\.mpd\(\\\?\|\$\)/i\.test\(url\)\) return "dash";[ \t]*$', re.M)
OLD_DASH_ANY = re.compile(r'return "dash";')

# The resolver is emitted as a top-level class whose closing brace is the only line that
# consists of "}" at column zero. Counting braces instead would break on the regex literals
# inside it (e.g. /[([{][^)\]}]*[)\]}]/g).
RESOLVER_BLOCK = re.compile(r"^class AniListResolver \{.*?^\}[ \t]*$", re.M | re.S)


def load_resolver() -> str:
    path = os.path.join(ROOT, "seanime/compatibility/anilist-resolver.ts")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().replace("export class AniListResolver", "class AniListResolver")
    # Keep only the class: the explanatory comment above it already exists in every bundle,
    # and re-inserting it would duplicate the header on every run (breaking idempotency).
    return text[text.index("class AniListResolver"):].strip()


def replace_resolver(source: str, resolver: str) -> tuple[str, bool]:
    """Swaps the embedded AniListResolver class for the current one."""
    if not RESOLVER_BLOCK.search(source):
        return source, False
    return RESOLVER_BLOCK.sub(lambda _m: resolver, source, count=1), True


def migrate_source(source: str, resolver: str) -> tuple[str, list[str]]:
    applied: list[str] = []

    new_source, replaced = replace_resolver(source, resolver)
    if replaced and new_source != source:
        source = new_source
        applied.append("anilist-resolver")

    if OLD_YEAR_LINE.search(source):
        source = OLD_YEAR_LINE.sub(NEW_YEAR_LINE, source)
        applied.append("year")
    elif "media.year" in source:
        # Defensive: an inline occurrence the line regex missed
        source = source.replace(
            "media && typeof media.year === \"number\" ? media.year : undefined",
            "AniListResolver.yearOf(opts)",
        )
        applied.append("year-inline")

    if OLD_DASH_ANY.search(source):
        source = OLD_DASH_ANY.sub('return "unknown";', source)
        applied.append("video-type")

    if "getTorrentMagnetLink" in source and "isBestRelease" not in source:
            source = source.replace(
                "                confirmed:",
                "                isBestRelease: false,\n                confirmed:",
            )
            if "isBestRelease" in source:
                applied.append("isBestRelease")

    return source, applied


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate generated bundles to the corrected Seanime contract")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    ap.add_argument("--no-reindex", action="store_true", help="skip marketplace/README regeneration")
    args = ap.parse_args()

    resolver = load_resolver()
    touched: list[tuple[str, list[str]]] = []
    ts_paths: list[str] = []

    for p_type in PROVIDER_TYPES:
        type_dir = os.path.join(ROOT, "src", p_type)
        if not os.path.isdir(type_dir):
            continue
        for ext_id in sorted(os.listdir(type_dir)):
            ext_dir = os.path.join(type_dir, ext_id)
            ts_path = os.path.join(ext_dir, "code.ts")
            if not os.path.exists(ts_path):
                continue
            with open(ts_path, "r", encoding="utf-8") as f:
                source = f.read()

            migrated, applied = migrate_source(source, resolver)
            if not applied:
                continue
            touched.append((os.path.relpath(ts_path, ROOT), applied))
            ts_paths.append(ts_path)
            if not args.dry_run:
                with open(ts_path, "w", encoding="utf-8") as f:
                    f.write(migrated)

    print(f"Bundles needing migration: {len(touched)}")
    for rel, applied in touched[:15]:
        print(f"  {rel}: {', '.join(applied)}")
    if len(touched) > 15:
        print(f"  ... and {len(touched) - 15} more")

    if args.dry_run or not ts_paths:
        return 0

    # Recompile with the real TypeScript compiler, in batches.
    compiler_mod = _load("ts_compiler", "engine/ts-compiler/compiler.py")
    compiler = compiler_mod.TypeScriptCompiler(repo_root=ROOT)
    ok, reason = compiler.is_available()
    if not ok:
        print(f"Cannot recompile: {reason}", file=sys.stderr)
        return 1

    failures: list[str] = []
    batch_size = 40
    for i in range(0, len(ts_paths), batch_size):
        batch = ts_paths[i: i + batch_size]
        try:
            js_paths = compiler.compile_files(batch)
        except Exception as exc:
            failures.append(str(exc)[:400])
            continue
        bad = compiler.check_js_syntax(js_paths)
        failures.extend(bad)
        print(f"  compiled {min(i + batch_size, len(ts_paths))}/{len(ts_paths)}")

    if failures:
        print("\nRecompilation problems:", file=sys.stderr)
        for failure in failures[:20]:
            print(f"  {failure}", file=sys.stderr)
        return 1

    if not args.no_reindex:
        reindex = os.path.join(ROOT, "scripts", "reindex.py")
        if os.path.exists(reindex):
            print("\nRefreshing reports, marketplace and README...")
            subprocess.run([sys.executable, reindex], cwd=ROOT, check=False)

    print("\nMigration complete. Run `node scripts/typecheck.mjs` to confirm.")
    return 0


def _load(name: str, rel_path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    sys.exit(main())
