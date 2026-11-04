import json
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class CloudstreamPluginEntry:
    name: str
    internal_name: str
    url: str
    version: int
    api_version: int
    status: int
    tv_types: List[str]
    authors: List[str]
    description: str
    language: str
    icon_url: Optional[str]
    repository_url: Optional[str]
    file_size: Optional[int]
    sha256: Optional[str]
    source_repo_name: str

class CloudstreamManifestParser:
    """Parses Cloudstream repo.json and plugins.json manifests across v1, v2, and v3 formats."""

    SUPPORTED_TV_TYPES = {
        "Anime", "AnimeMovie", "OVA", "Torrent", "Manga", "AsianDrama", "TvSeries", "Movie"
    }

    @staticmethod
    def resolve_relative_url(base_url: str, target_url: str) -> str:
        if target_url.startswith(("http://", "https://")):
            return target_url
        return urllib.parse.urljoin(base_url, target_url)

    def parse_repo_manifest(self, raw_json: Dict[str, Any], repo_url: str) -> List[str]:
        plugin_lists = raw_json.get("pluginLists", [])
        if isinstance(plugin_lists, str):
            plugin_lists = [plugin_lists]
        resolved = []
        for item in plugin_lists:
            if isinstance(item, str) and item.strip():
                resolved.append(self.resolve_relative_url(repo_url, item.strip()))
        return resolved

    def parse_plugins_list(
        self,
        raw_plugins: Any,
        plugins_url: str,
        repo_name: str,
        allowed_categories: Optional[List[str]] = None
    ) -> List[CloudstreamPluginEntry]:
        if isinstance(raw_plugins, dict) and "plugins" in raw_plugins:
            items = raw_plugins["plugins"]
        elif isinstance(raw_plugins, list):
            items = raw_plugins
        else:
            return []

        results: List[CloudstreamPluginEntry] = []
        seen_urls = set()

        for entry in items:
            if not isinstance(entry, dict):
                continue
            dl_url = entry.get("url") or entry.get("downloadUrl")
            if not dl_url:
                continue
            resolved_dl_url = self.resolve_relative_url(plugins_url, str(dl_url))
            if resolved_dl_url in seen_urls:
                continue

            status = int(entry.get("status", 1))
            if status == 0:  # 0 = Down in Cloudstream
                continue

            tv_types = entry.get("tvTypes") or ["Anime"]
            if allowed_categories:
                allowed_lower = {c.lower() for c in allowed_categories}
                if not any(t.lower() in allowed_lower for t in tv_types):
                    continue

            internal_name = entry.get("internalName") or entry.get("name") or "UnknownProvider"
            name = entry.get("name") or internal_name
            authors = entry.get("authors") or []
            if isinstance(authors, str):
                authors = [authors]

            seen_urls.add(resolved_dl_url)
            results.append(CloudstreamPluginEntry(
                name=str(name),
                internal_name=str(internal_name),
                url=resolved_dl_url,
                version=int(entry.get("version", 1)),
                api_version=int(entry.get("apiVersion", 1)),
                status=status,
                tv_types=[str(t) for t in tv_types],
                authors=[str(a) for a in authors] if authors else ["Cloudstream Community"],
                description=str(entry.get("description", f"Converted from {name}")),
                language=str(entry.get("language", "en")),
                icon_url=entry.get("iconUrl"),
                repository_url=entry.get("repositoryUrl"),
                file_size=entry.get("fileSize"),
                sha256=entry.get("sha256") or entry.get("hash"),
                source_repo_name=repo_name
            ))

        return results
