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
    def to_kebab_id(raw_name: str) -> str:
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", raw_name)
        s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
        return s or "converted-extension"

    def generate_extension_bundle(
        self,
        plugin_meta: Any,
        translation: Any,
        sha256_hex: str,
        validation_report: Dict[str, Any],
        source_info: Any
    ) -> Dict[str, Any]:
        ext_id = self.to_kebab_id(plugin_meta.internal_name)
        provider_type = translation.provider_type
        ext_dir = os.path.join(self.repo_root, "src", provider_type, ext_id)
        backup_dir = os.path.join(self.repo_root, ".cache", "rollback", provider_type, ext_id)

        # Atomic rollback protection: if valid extension already exists and new validation failed, keep existing!
        existing_manifest = os.path.join(ext_dir, "manifest.json")
        if not validation_report.get("passed", False):
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
        owner = self.settings.get("github_owner", "OWNER")
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
            "notes": f"Automatically converted via strategy {translation.strategy_used} and validated for Seanime Goja.",
            "payloadURI": f"{base_raw}/code.js"
        }
        if plugin_meta.icon_url:
            manifest_payload["icon"] = plugin_meta.icon_url

        metadata_payload = {
            "extensionId": ext_id,
            "originalPluginName": plugin_meta.name,
            "originalInternalName": plugin_meta.internal_name,
            "originalVersion": plugin_meta.version,
            "originalDownloadUrl": plugin_meta.url,
            "originalRepositoryUrl": plugin_meta.repository_url or source_info.repository_url,
            "originalAuthors": plugin_meta.authors,
            "license": source_info.license_spdx,
            "cs3Sha256": sha256_hex,
            "converterVersion": self.settings.get("converter_version", "2.4.0"),
            "conversionStrategy": translation.strategy_used,
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
            f.write(translation.javascript_code)
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
            "status": "SUCCESS",
            "directory": ext_dir,
            "manifest": manifest_payload
        }

    def regenerate_marketplace(self) -> List[Dict[str, Any]]:
        """Scans all valid extension manifests under src/ and writes both marketplace.json and generated/marketplace.json."""
        provider_types = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"]
        entries: List[Dict[str, Any]] = []
        seen_ids = set()

        for p_type in provider_types:
            type_dir = os.path.join(self.repo_root, "src", p_type)
            if not os.path.exists(type_dir):
                continue
            for folder in sorted(os.listdir(type_dir)):
                ext_dir = os.path.join(type_dir, folder)
                manifest_path = os.path.join(ext_dir, "manifest.json")
                code_js_path = os.path.join(ext_dir, "code.js")
                report_path = os.path.join(ext_dir, "conversion-report.json")
                if not (os.path.exists(manifest_path) and os.path.exists(code_js_path)):
                    continue

                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        manifest = json.load(mf)
                    if os.path.exists(report_path):
                        with open(report_path, "r", encoding="utf-8") as rf:
                            rep = json.load(rf)
                        if rep.get("overall_status") not in ("SUCCESS", None):
                            continue
                    ext_id = manifest.get("id")
                    if not ext_id or ext_id in seen_ids:
                        continue
                    if not manifest.get("payloadURI", "").endswith("/code.js"):
                        continue
                    seen_ids.add(ext_id)
                    entries.append(manifest)
                except Exception:
                    continue

        entries.sort(key=lambda x: (x.get("type", ""), x.get("id", "")))

        root_mkt = os.path.join(self.repo_root, "marketplace.json")
        gen_mkt = os.path.join(self.repo_root, "generated", "marketplace.json")
        os.makedirs(os.path.dirname(gen_mkt), exist_ok=True)

        with open(root_mkt, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        with open(gen_mkt, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

        return entries
