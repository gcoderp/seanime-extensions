#!/usr/bin/env python3
"""Schema and consistency checks for generated manifests, metadata and the marketplace index.

Complements scripts/validate.mjs (which checks that JavaScript parses): this one is about
the Seanime manifest contract and cross-file consistency.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"]
REQUIRED = ["id", "name", "description", "manifestURI", "version", "author", "type", "language", "lang", "payloadURI"]

errors = []
manifests = {}


def fail(msg: str) -> None:
    errors.append(msg)


def main() -> int:
    for p_type in PROVIDER_TYPES:
        type_dir = os.path.join(ROOT, "src", p_type)
        if not os.path.isdir(type_dir):
            continue
        for ext_id in sorted(os.listdir(type_dir)):
            ext_dir = os.path.join(type_dir, ext_id)
            m_path = os.path.join(ext_dir, "manifest.json")
            if not os.path.isdir(ext_dir):
                continue
            if not os.path.exists(m_path):
                fail(f"{p_type}/{ext_id}: missing manifest.json")
                continue
            try:
                with open(m_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception as exc:
                fail(f"{p_type}/{ext_id}: manifest.json invalid ({exc})")
                continue

            for key in REQUIRED:
                if not manifest.get(key):
                    fail(f"{p_type}/{ext_id}: manifest missing '{key}'")

            if manifest.get("type") and manifest["type"] != p_type:
                fail(f"{p_type}/{ext_id}: manifest type '{manifest['type']}' != directory '{p_type}'")

            version = str(manifest.get("version", ""))
            parts = version.split(".")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                fail(f"{p_type}/{ext_id}: version '{version}' is not semver (X.Y.Z)")

            if not str(manifest.get("payloadURI", "")).endswith("/code.js"):
                fail(f"{p_type}/{ext_id}: payloadURI must point at code.js")

            for fname in ("code.ts", "code.js", "metadata.json", "README.md", "conversion-report.json"):
                if not os.path.exists(os.path.join(ext_dir, fname)):
                    fail(f"{p_type}/{ext_id}: missing {fname}")

            meta_path = os.path.join(ext_dir, "metadata.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception as exc:
                    fail(f"{p_type}/{ext_id}: metadata.json invalid ({exc})")
                    meta = {}
                if meta and meta.get("extensionId") != manifest.get("id"):
                    fail(f"{p_type}/{ext_id}: metadata extensionId does not match manifest id")
                download_url = str(meta.get("originalDownloadUrl", ""))
                if download_url.startswith("/") or "\\" in download_url:
                    fail(f"{p_type}/{ext_id}: metadata leaks a local filesystem path ({download_url})")

            manifests.setdefault(manifest.get("id"), []).append((p_type, ext_dir, manifest))

    mkt_path = os.path.join(ROOT, "marketplace.json")
    if not os.path.exists(mkt_path):
        fail("marketplace.json missing")
    else:
        with open(mkt_path, "r", encoding="utf-8") as f:
            marketplace = json.load(f)
        if not isinstance(marketplace, list):
            fail("marketplace.json must be an array")
            marketplace = []
        seen = set()
        for item in marketplace:
            ext_id = item.get("id")
            if ext_id in seen:
                fail(f"marketplace: duplicate id {ext_id}")
            seen.add(ext_id)
            if ext_id not in manifests:
                fail(f"marketplace: {ext_id} has no extension under src/")
                continue
            # Two provider types can share a kebab-case id: pick the bundle whose payloadURI
            # matches the published entry, then the one that passed validation.
            candidates = manifests[ext_id]
            match = [c for c in candidates if c[2].get("payloadURI") == item.get("payloadURI")]
            if match:
                p_type, ext_dir, manifest = match[0]
            else:
                passed = [c for c in candidates
                          if os.path.exists(os.path.join(c[1], "conversion-report.json"))
                          and json.load(open(os.path.join(c[1], "conversion-report.json"), encoding="utf-8")).get("overall_status") == "SUCCESS"]
                p_type, ext_dir, manifest = (passed or candidates)[0]
            if item.get("manifestURI") != manifest.get("manifestURI"):
                fail(f"marketplace: {ext_id} manifestURI differs from its manifest.json")
            if "/OWNER/" in str(item.get("manifestURI", "")):
                fail(f"marketplace: {ext_id} manifestURI still uses the OWNER placeholder")
            report_path = os.path.join(ext_dir, "conversion-report.json")
            if os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    report = json.load(f)
                if report.get("overall_status") != "SUCCESS":
                    fail(f"marketplace: {ext_id} published but report status is {report.get('overall_status')}")

    if errors:
        print(f"Schema validation failed with {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    duplicates = {k: v for k, v in manifests.items() if len(v) > 1}
    if duplicates:
        print(f"note: {len(duplicates)} id(s) exist under more than one provider type: "
              f"{', '.join(sorted(duplicates))} (see reports/duplicate-ids.json)")
    print(f"Schema OK: {len(manifests)} extension manifest(s), marketplace consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
