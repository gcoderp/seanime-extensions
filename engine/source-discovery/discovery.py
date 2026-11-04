import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class RecoveredKotlinSource:
    found: bool
    strategy: str
    repository_url: Optional[str] = None
    license_spdx: str = "UNKNOWN"
    main_provider_code: str = ""
    helper_files: Dict[str, str] = field(default_factory=dict)
    provider_class_name: str = ""

class SourceDiscoveryEngine:
    """Recovers original Kotlin source code from embedded .cs3 sources, declared repositoryUrl, or GitHub search."""

    def __init__(self, github_token: Optional[str] = None, timeout: int = 15, cache_path: Optional[str] = None, offline: bool = False):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout
        self.offline = offline
        self.cache_path = cache_path
        self._license_cache: Dict[str, str] = {}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    self._license_cache = json.load(f)
            except Exception:
                self._license_cache = {}

    def _save_license_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._license_cache, f, indent=2, sort_keys=True)
        except Exception:
            pass

    def detect_license(self, repository_url: Optional[str]) -> str:
        """Resolves the upstream SPDX id via the GitHub licence API. Returns UNKNOWN when unverifiable.

        A public repository is not by itself permission to redistribute derived code, so an
        unverifiable licence is never assumed to be acceptable -- callers treat UNKNOWN as
        NEEDS_REVIEW.
        """
        if self.offline:
            return "UNKNOWN"
        if not repository_url or "github.com/" not in repository_url:
            return "UNKNOWN"
        try:
            parsed = urllib.parse.urlparse(repository_url)
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) < 2:
                return "UNKNOWN"
            key = f"{parts[0]}/{parts[1].replace('.git', '')}"
        except Exception:
            return "UNKNOWN"

        if key in self._license_cache:
            return self._license_cache[key]

        spdx = "UNKNOWN"
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{key}/license", headers=self._headers())
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                spdx = (data.get("license") or {}).get("spdx_id") or "UNKNOWN"
                if spdx in ("NOASSERTION", "None"):
                    spdx = "UNKNOWN"
        except Exception:
            spdx = "UNKNOWN"

        self._license_cache[key] = spdx
        self._save_license_cache()
        return spdx

    def _headers(self) -> Dict[str, str]:
        h = {
            "User-Agent": "Cloudstream-Seanime-Converter/2.4",
            "Accept": "application/vnd.github+json"
        }
        if self.github_token:
            h["Authorization"] = f"Bearer {self.github_token}"
        return h

    def verify_kotlin_source_matches_plugin(
        self,
        kotlin_code: str,
        expected_internal_name: str,
        expected_package: str
    ) -> bool:
        if "MainAPI" not in kotlin_code and "ExtractorApi" not in kotlin_code:
            return False
        if expected_internal_name.lower() in kotlin_code.lower():
            return True
        if expected_package and expected_package in kotlin_code:
            return True
        return bool(re.search(r"override\s+var\s+mainUrl\s*=", kotlin_code))

    def recover_source(
        self,
        plugin_id: str,
        plugin_class_name: str,
        package_name: str,
        repository_url: Optional[str],
        embedded_sources: List[str]
    ) -> RecoveredKotlinSource:
        # 1. Check embedded .kt sources inside the .cs3 archive
        if embedded_sources:
            main_code = ""
            helpers: Dict[str, str] = {}
            for src_path in embedded_sources:
                try:
                    with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    fname = os.path.basename(src_path)
                    if "MainAPI" in content or "override var mainUrl" in content:
                        main_code = content
                    else:
                        helpers[fname] = content
                except Exception:
                    continue
            if main_code and self.verify_kotlin_source_matches_plugin(main_code, plugin_id, package_name):
                cls_match = re.search(r"class\s+(\w+)\s*[:(].*MainAPI", main_code)
                cls_name = cls_match.group(1) if cls_match else plugin_id
                return RecoveredKotlinSource(
                    found=True,
                    strategy="EMBEDDED_KOTLIN_SOURCE",
                    repository_url=repository_url or "embedded://cs3-package",
                    license_spdx=self.detect_license(repository_url),
                    main_provider_code=main_code,
                    helper_files=helpers,
                    provider_class_name=cls_name
                )

        # 2. Query GitHub repository if repository_url is a GitHub URL
        if not self.offline and repository_url and "github.com/" in repository_url:
            try:
                parsed = urllib.parse.urlparse(repository_url)
                parts = [p for p in parsed.path.strip("/").split("/") if p]
                if len(parts) >= 2:
                    owner, repo = parts[0], parts[1].replace(".git", "")
                    search_q = urllib.parse.quote(f"repo:{owner}/{repo} {plugin_id} MainAPI language:Kotlin")
                    api_url = f"https://api.github.com/search/code?q={search_q}"
                    req = urllib.request.Request(api_url, headers=self._headers())
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        for item in data.get("items", [])[:3]:
                            raw_url = item.get("html_url", "").replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                            if raw_url:
                                raw_req = urllib.request.Request(raw_url, headers={"User-Agent": "Cloudstream-Seanime-Converter/2.4"})
                                with urllib.request.urlopen(raw_req, timeout=self.timeout) as raw_resp:
                                    kt_text = raw_resp.read().decode("utf-8", errors="ignore")
                                    if self.verify_kotlin_source_matches_plugin(kt_text, plugin_id, package_name):
                                        return RecoveredKotlinSource(
                                            found=True,
                                            strategy="GITHUB_SOURCE_RECOVERY",
                                            repository_url=repository_url,
                                            license_spdx=self.detect_license(repository_url),
                                            main_provider_code=kt_text,
                                            provider_class_name=plugin_id
                                        )
            except Exception:
                pass

        return RecoveredKotlinSource(found=False, strategy="NONE", license_spdx=self.detect_license(repository_url))
