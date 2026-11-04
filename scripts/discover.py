#!/usr/bin/env python3
"""Discovers Cloudstream plugins from configured repositories.json and outputs discovered_plugins.json."""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

parser_mod = load_module("manifest_parser", "engine/manifest-parser/parser.py")
dl_mod = load_module("downloader", "engine/downloader/downloader.py")

def discover_all_repositories(config_path: str = "config/repositories.json", offline_fixtures: bool = False):
    full_cfg = os.path.join(ROOT, config_path)
    with open(full_cfg, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    manifest_parser = parser_mod.CloudstreamManifestParser()
    downloader = dl_mod.SecureCS3Downloader(cache_dir=os.path.join(ROOT, ".cache/packages"))
    discovered = []

    if offline_fixtures:
        fixtures_dir = os.path.join(ROOT, "tests/fixtures")
        fixture_plugins = os.path.join(fixtures_dir, "plugins.json")
        if os.path.exists(fixture_plugins):
            with open(fixture_plugins, "r", encoding="utf-8") as pf:
                raw_list = json.load(pf)
            entries = manifest_parser.parse_plugins_list(raw_list, fixture_plugins, "Local Fixture Repo")
            for e in entries:
                discovered.append(e.__dict__)
        return discovered

    for repo in cfg.get("repositories", []):
        if not repo.get("enabled", True):
            continue
        repo_url = repo["url"]
        repo_name = repo.get("name", repo_url)
        categories = repo.get("categories")
        try:
            repo_json = downloader.fetch_json(repo_url)
            plugin_list_urls = manifest_parser.parse_repo_manifest(repo_json, repo_url)
            for pl_url in plugin_list_urls:
                try:
                    raw_plugins = downloader.fetch_json(pl_url)
                    entries = manifest_parser.parse_plugins_list(raw_plugins, pl_url, repo_name, categories)
                    for e in entries:
                        discovered.append(e.__dict__)
                except Exception as ex:
                    print(f"[WARN] Failed to parse plugin list {pl_url}: {ex}")
        except Exception as ex:
            print(f"[WARN] Failed to fetch repository {repo_url}: {ex}")

    out_file = os.path.join(ROOT, ".cache/discovered_plugins.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(discovered, f, indent=2)
    return discovered

if __name__ == "__main__":
    use_fixtures = "--fixtures" in sys.argv
    plugins = discover_all_repositories(offline_fixtures=use_fixtures)
    print(f"Discovered {len(plugins)} Cloudstream plugin(s).")
