import importlib.util
import json
import os
import zipfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_manifest_parser_resolves_relative_urls():
    parser_mod = load_mod("parser", "engine/manifest-parser/parser.py")
    p = parser_mod.CloudstreamManifestParser()
    urls = p.parse_repo_manifest({"pluginLists": ["plugins.json"]}, "https://example.com/repo/repo.json")
    assert urls == ["https://example.com/repo/plugins.json"]

def test_ssrf_protection_blocks_localhost_and_private_ips():
    dl_mod = load_mod("downloader", "engine/downloader/downloader.py")
    dl = dl_mod.SecureCS3Downloader()
    with pytest.raises(ValueError):
        dl.validate_url_security("http://127.0.0.1/malicious.cs3")
    with pytest.raises(ValueError):
        dl.validate_url_security("http://localhost:8080/repo.json")
    with pytest.raises(ValueError):
        dl.validate_url_security("file:///etc/passwd")

def test_cs3_extractor_blocks_zip_path_traversal(tmp_path):
    ext_mod = load_mod("extractor", "engine/cs3-extractor/extractor.py")
    extractor = ext_mod.CS3Extractor(work_dir=str(tmp_path))
    bad_cs3 = tmp_path / "malicious.cs3"
    with zipfile.ZipFile(bad_cs3, "w") as zf:
        zf.writestr("../../evil.sh", "echo pwned")
    with pytest.raises(ValueError, match="path traversal"):
        extractor.extract_package(str(bad_cs3), "MaliciousPlugin")

def test_dex_analyzer_extracts_urls_and_selectors():
    dex_mod = load_mod("analyzer", "engine/dex-analyzer/analyzer.py")
    analyzer = dex_mod.DexAnalyzer()
    fixture_cs3 = os.path.join(ROOT, "tests/fixtures/HiAnimeProvider.cs3")
    ext_mod = load_mod("extractor", "engine/cs3-extractor/extractor.py")
    pkg = ext_mod.CS3Extractor().extract_package(fixture_cs3, "HiAnimeProvider")
    res = analyzer.analyze_dex_files(pkg.dex_files, pkg.extract_dir)
    assert "https://hianime.to" in res.discovered_urls
    assert any("flw-item" in s for s in res.css_selectors)

def test_end_to_end_marketplace_and_converted_extensions():
    with open(os.path.join(ROOT, "marketplace.json"), "r", encoding="utf-8") as f:
        mkt = json.load(f)
    assert len(mkt) == 3
    ids = {item["id"] for item in mkt}
    assert {"gogo-anime-provider", "hi-anime-provider", "nyaa-torrent-provider"} == ids
