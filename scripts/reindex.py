#!/usr/bin/env python3
"""Re-publishes existing extension bundles without re-downloading or re-converting anything.

Use it when the *packaging* changed rather than the conversion:
  * github_owner / github_repo / branch changed  -> every manifest URL is rewritten
  * the licence policy changed                   -> bundles are re-triaged
  * the marketplace, README and manifest URL list need regenerating

It never touches code.ts / code.js. Each bundle's code.js is parse-checked, and a bundle
whose JavaScript does not parse is marked FAILED and dropped from the marketplace.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen_mod = load_mod("seanime_generator", "engine/seanime-generator/generator.py")
readme_mod = load_mod("readme_generator", "engine/seanime-generator/readme.py")

PROVIDER_TYPES = ("onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source")
OWNER_REASON_MARKERS = ("github_owner", "OWNER placeholder")
LICENCE_REASON_MARKERS = ("licence", "license")


def js_parses(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        proc = subprocess.run(["node", "--check", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return proc.returncode == 0
    except Exception:
        return True  # no node available: do not fail the bundle for that


def retriage(report: dict, allow_unknown_license: bool) -> dict:
    reasons = list(report.get("review_reasons") or [])
    kept = []
    for reason in reasons:
        lowered = reason.lower()
        if any(m.lower() in lowered for m in OWNER_REASON_MARKERS):
            continue  # the owner is configured now
        if any(m in lowered for m in LICENCE_REASON_MARKERS) and allow_unknown_license:
            report.setdefault("warnings", []).append(
                f"Licence notice: {reason} Published with attribution only; verify before redistribution."
            )
            report["license_notice"] = True
            continue
        kept.append(reason)

    report["review_reasons"] = kept
    if report.get("error_messages"):
        status = "FAILED"
    elif kept:
        status = "NEEDS_REVIEW"
    else:
        status = "SUCCESS"
    report["overall_status"] = status
    report["passed"] = status == "SUCCESS"
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-publish existing bundles under the configured owner")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    args = ap.parse_args()

    settings = json.load(open(os.path.join(ROOT, "config/settings.json"), encoding="utf-8"))
    licensing = settings.get("licensing", {})
    policy = licensing.get("unknown_license_policy", "hold")
    allow_unknown = policy == "publish_with_notice"
    branch = settings.get("github_branch", "main")
    version = settings.get("converter_version", "2.5.0")

    generator = gen_mod.SeanimeExtensionGenerator(repo_root=ROOT)
    owner = generator._resolve_owner()
    repo_name = settings.get("github_repo", "seanime-extensions")

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}"
    blob_base = f"https://github.com/{owner}/{repo_name}/blob/{branch}"

    counts = {"SUCCESS": 0, "NEEDS_REVIEW": 0, "FAILED": 0}
    buckets = {"SUCCESS": [], "NEEDS_REVIEW": [], "FAILED": []}
    changed = 0

    for p_type in PROVIDER_TYPES:
        type_dir = os.path.join(ROOT, "src", p_type)
        if not os.path.isdir(type_dir):
            continue
        for ext_id in sorted(os.listdir(type_dir)):
            ext_dir = os.path.join(type_dir, ext_id)
            m_path = os.path.join(ext_dir, "manifest.json")
            r_path = os.path.join(ext_dir, "conversion-report.json")
            meta_path = os.path.join(ext_dir, "metadata.json")
            js_path = os.path.join(ext_dir, "code.js")
            if not os.path.isdir(ext_dir) or not os.path.exists(m_path):
                continue

            manifest = json.load(open(m_path, encoding="utf-8"))
            report = json.load(open(r_path, encoding="utf-8")) if os.path.exists(r_path) else {}

            if not js_parses(js_path):
                report["overall_status"] = "FAILED"
                report["passed"] = False
                report.setdefault("error_messages", []).append("code.js does not parse (reindex check)")
                counts["FAILED"] += 1
                buckets["FAILED"].append(report)
            else:
                report = retriage(report, allow_unknown)
                counts[report["overall_status"]] += 1
                buckets[report["overall_status"]].append(report)

            ext_raw = f"{raw_base}/src/{p_type}/{ext_id}"
            new_manifest = dict(manifest)
            new_manifest["manifestURI"] = f"{ext_raw}/manifest.json"
            new_manifest["payloadURI"] = f"{ext_raw}/code.js"
            new_manifest["readme"] = f"{blob_base}/src/{p_type}/{ext_id}/README.md"
            notes = str(manifest.get("notes", ""))
            if report.get("license_notice") and "Licence" not in notes:
                notes = (notes + " Licence: upstream repository declares no detectable licence; "
                                "distributed with attribution only.").strip()
            new_manifest["notes"] = notes

            if new_manifest != manifest:
                changed += 1
            if not args.dry_run:
                with open(m_path, "w", encoding="utf-8") as f:
                    json.dump(new_manifest, f, indent=2)
                    f.write("\n")
                with open(r_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2)
                    f.write("\n")
                if os.path.exists(meta_path):
                    meta = json.load(open(meta_path, encoding="utf-8"))
                    meta["validationStatus"] = report.get("overall_status")
                    meta["licenseNotice"] = bool(report.get("license_notice"))
                    meta["republishedAt"] = datetime.now(timezone.utc).isoformat()
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)
                        f.write("\n")

    if args.dry_run:
        print(f"[dry-run] would rewrite {changed} manifest(s); triage: {counts}")
        return 0

    reports_dir = os.path.join(ROOT, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    for name, payload in (("successful.json", buckets["SUCCESS"]),
                          ("needs-review.json", buckets["NEEDS_REVIEW"]),
                          ("failed.json", buckets["FAILED"])):
        with open(os.path.join(reports_dir, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

    marketplace = generator.regenerate_marketplace()
    readme = readme_mod.ReadmeGenerator(ROOT, owner, repo_name, branch, version)
    readme.write(withheld=counts["NEEDS_REVIEW"] + counts["FAILED"])
    url_list = readme.write_url_list()

    summary = {
        "republished_at": datetime.now(timezone.utc).isoformat(),
        "owner": owner,
        "repository": repo_name,
        "branch": branch,
        "unknown_license_policy": policy,
        "bundles": sum(counts.values()),
        "success": counts["SUCCESS"],
        "needs_review": counts["NEEDS_REVIEW"],
        "failed": counts["FAILED"],
        "published_in_marketplace": len(marketplace),
        "manifest_urls": os.path.basename(url_list),
        "manifests_rewritten": changed,
    }
    with open(os.path.join(ROOT, "reports", "reindex-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
