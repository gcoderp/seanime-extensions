import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

class SeanimeExtensionGenerator:
    """Generates and atomically updates Seanime extension directories, manifests, metadata, and marketplace.json."""

    def __init__(self, repo_root: str = ".", settings_path: str = "config/settings.json"):
        self.repo_root = repo_root
        self.settings = self._load_settings(settings_path)

    def _load_settings(self, path: str) -> Dict[str, Any]:
        full = os.path.join(self.repo_root, path)
        if os.path.exists(full):
            with open(full, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "github_owner": "OWNER",
            "github_repo": "cloudstream-seanime-converter",
            "github_branch": "main",
            "converter_version": "2.4.0"
        }

    @staticmethod
    def public_url(url: str) -> str:
        """Never publish local filesystem paths in manifests or metadata."""
        if not url:
            return ""
        if str(url).startswith(("http://", "https://")):
            return str(url)
        return os.path.basename(str(url))

    def _resolve_owner(self) -> str:
        """GITHUB_REPOSITORY_OWNER / GITHUB_REPOSITORY win over config, so Actions needs no editing."""
        repo_slug = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo_slug:
            owner, _, repo = repo_slug.partition("/")
            if owner and repo:
                self.settings.setdefault("github_owner", owner)
                self.settings["github_owner"] = owner
                self.settings["github_repo"] = repo
                return owner
        owner_env = os.environ.get("GITHUB_REPOSITORY_OWNER")
        if owner_env:
            return owner_env
        return self.settings.get("github_owner", "OWNER")

    @staticmethod
    def to_kebab_id(raw_name: str) -> str:
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", raw_name)
        s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
        return s or "converted-extension"

    def generate_extension_bundle(
        self,
        plugin_meta: Any,
        translation: Any,
        javascript_code: str,
        sha256_hex: str,
        validation_report: Dict[str, Any],
        source_info: Any
    ) -> Dict[str, Any]:
        ext_id = self.to_kebab_id(plugin_meta.internal_name)
        provider_type = translation.provider_type

        # An unconfigured owner would publish URLs that 404 for every Seanime user.
        if self._resolve_owner() in ("OWNER", "", "owner"):
            validation_report = dict(validation_report)
            validation_report["overall_status"] = "NEEDS_REVIEW"
            validation_report["passed"] = False
            validation_report.setdefault("review_reasons", []).append(
                "github_owner is still the OWNER placeholder; set it in config/settings.json "
                "(or run in Actions, where GITHUB_REPOSITORY is provided) before publishing."
            )
        ext_dir = os.path.join(self.repo_root, "src", provider_type, ext_id)
        backup_dir = os.path.join(self.repo_root, ".cache", "rollback", provider_type, ext_id)

        # Atomic rollback protection: if a valid extension already exists and the new
        # conversion failed, keep the previously published bundle untouched.
        existing_manifest = os.path.join(ext_dir, "manifest.json")
        if validation_report.get("overall_status") == "FAILED":
            if os.path.exists(existing_manifest):
                return {
                    "id": ext_id,
                    "status": "PRESERVED_PREVIOUS_VALID",
                    "directory": ext_dir
                }
            return {
                "id": ext_id,
                "status": "FAILED_NOT_PUBLISHED",
                "directory": None
            }

        if os.path.exists(ext_dir):
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            shutil.copytree(ext_dir, backup_dir)

        os.makedirs(ext_dir, exist_ok=True)
        owner = self._resolve_owner()
        repo = self.settings.get("github_repo", "cloudstream-seanime-converter")
        branch = self.settings.get("github_branch", "main")

        base_raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/src/{provider_type}/{ext_id}"
        base_blob = f"https://github.com/{owner}/{repo}/blob/{branch}/src/{provider_type}/{ext_id}"

        semver = f"1.{plugin_meta.version}.0"
        author_str = ", ".join(plugin_meta.authors) if plugin_meta.authors else "Cloudstream Community"
        lang_code = plugin_meta.language if plugin_meta.language else "multi"

        manifest_payload = {
            "id": ext_id,
            "name": plugin_meta.name,
            "description": plugin_meta.description or f"Automatically converted Cloudstream {plugin_meta.name} extension",
            "manifestURI": f"{base_raw}/manifest.json",
            "version": semver,
            "author": author_str,
            "type": provider_type,
            "language": "typescript",
            "lang": lang_code,
            "readme": f"{base_blob}/README.md",
            "notes": f"Automatically converted via strategy {translation.strategy_used}; validation status {validation_report.get('overall_status')}.",
            "payloadURI": f"{base_raw}/code.js"
        }
        if plugin_meta.icon_url:
            manifest_payload["icon"] = plugin_meta.icon_url

        metadata_payload = {
            "extensionId": ext_id,
            "originalPluginName": plugin_meta.name,
            "originalInternalName": plugin_meta.internal_name,
            "originalVersion": plugin_meta.version,
            "originalDownloadUrl": self.public_url(plugin_meta.url),
            "originalRepositoryUrl": plugin_meta.repository_url or source_info.repository_url,
            "originalAuthors": plugin_meta.authors,
            "license": source_info.license_spdx,
            "cs3Sha256": sha256_hex,
            "converterVersion": self.settings.get("converter_version", "2.4.0"),
            "conversionStrategy": translation.strategy_used,
            "validationStatus": validation_report.get("overall_status"),
            "liveTestStatus": validation_report.get("live_test_status", "NOT_RUN"),
            "reviewReasons": validation_report.get("review_reasons", []),
            "convertedAt": datetime.now(timezone.utc).isoformat()
        }

        readme_md = f"""# {plugin_meta.name} (`{ext_id}`)

Automatically converted Seanime `{provider_type}` extension from Cloudstream `.cs3` package.

## Overview
- **Extension ID:** `{ext_id}`
- **Provider Type:** `{provider_type}`
- **Version:** `{semver}` (Upstream CS3 v{plugin_meta.version})
- **Language:** `{lang_code}`
- **Original Author(s):** {author_str}
- **Conversion Strategy:** `{translation.strategy_used}`
- **CS3 SHA-256:** `{sha256_hex}`

## Installation in Seanime
Use the direct manifest URL below in Seanime's Extension settings:
```text
{base_raw}/manifest.json
```
"""

        with open(os.path.join(ext_dir, "code.ts"), "w", encoding="utf-8") as f:
            f.write(translation.typescript_code)
        with open(os.path.join(ext_dir, "code.js"), "w", encoding="utf-8") as f:
            f.write(javascript_code)
        with open(os.path.join(ext_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2)
        with open(os.path.join(ext_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata_payload, f, indent=2)
        with open(os.path.join(ext_dir, "conversion-report.json"), "w", encoding="utf-8") as f:
            json.dump(validation_report, f, indent=2)
        with open(os.path.join(ext_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(readme_md)

        return {
            "id": ext_id,
            "status": validation_report.get("overall_status", "NEEDS_REVIEW"),
            "directory": ext_dir,
            "manifest": manifest_payload
        }

    def scan_bundles(self) -> List[Dict[str, Any]]:
        """Every extension directory on disk, with its validation status."""
        provider_types = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"]
        bundles: List[Dict[str, Any]] = []
        for p_type in provider_types:
            type_dir = os.path.join(self.repo_root, "src", p_type)
            if not os.path.exists(type_dir):
                continue
            for folder in sorted(os.listdir(type_dir)):
                ext_dir = os.path.join(type_dir, folder)
                if not os.path.isdir(ext_dir):
                    continue
                manifest_path = os.path.join(ext_dir, "manifest.json")
                code_js_path = os.path.join(ext_dir, "code.js")
                report_path = os.path.join(ext_dir, "conversion-report.json")
                if not (os.path.exists(manifest_path) and os.path.exists(code_js_path)):
                    continue
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        manifest = json.load(mf)
                except Exception:
                    continue
                status = None
                if os.path.exists(report_path):
                    try:
                        with open(report_path, "r", encoding="utf-8") as rf:
                            status = json.load(rf).get("overall_status")
                    except Exception:
                        status = None
                bundles.append({
                    "type": p_type,
                    "dir": ext_dir,
                    "relative": os.path.relpath(ext_dir, self.repo_root).replace(os.sep, "/"),
                    "manifest": manifest,
                    "status": status,
                })
        return bundles

    def regenerate_marketplace(self) -> List[Dict[str, Any]]:
        """Writes marketplace.json and generated/marketplace.json from the bundles on disk.

        Two different provider types can produce the same kebab-case id (for example a plugin
        listed as both Anime and Torrent), so ids are resolved deterministically: the bundle
        that passed validation wins, and the collision is recorded in
        reports/duplicate-ids.json. Publishing used to depend on directory order, which made
        the published payload and the report that validate.mjs checked disagree.
        """
        bundles = self.scan_bundles()
        by_id: Dict[str, List[Dict[str, Any]]] = {}
        for bundle in bundles:
            ext_id = bundle["manifest"].get("id")
            if not ext_id:
                continue
            by_id.setdefault(ext_id, []).append(bundle)

        entries: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []

        for ext_id in sorted(by_id):
            group = by_id[ext_id]
            if len(group) > 1:
                duplicates.append({
                    "id": ext_id,
                    "paths": [b["relative"] for b in group],
                    "statuses": [b["status"] for b in group],
                })
            passed = [b for b in group if b["status"] == "SUCCESS"]
            if not passed:
                continue
            chosen = passed[0]
            manifest = chosen["manifest"]
            if not str(manifest.get("payloadURI", "")).endswith("/code.js"):
                continue
            entries.append(manifest)

        entries.sort(key=lambda x: (x.get("type", ""), x.get("id", "")))

        root_mkt = os.path.join(self.repo_root, "marketplace.json")
        gen_mkt = os.path.join(self.repo_root, "generated", "marketplace.json")
        os.makedirs(os.path.dirname(gen_mkt), exist_ok=True)

        with open(root_mkt, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        with open(gen_mkt, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

        reports_dir = os.path.join(self.repo_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        with open(os.path.join(reports_dir, "duplicate-ids.json"), "w", encoding="utf-8") as f:
            json.dump(duplicates, f, indent=2)
            f.write("\n")

        return entries
