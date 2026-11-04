import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_bundle(root, provider_type, ext_id, status="SUCCESS", name="Sample"):
    ext = root / "src" / provider_type / ext_id
    ext.mkdir(parents=True)
    (ext / "manifest.json").write_text(json.dumps({
        "id": ext_id, "name": name, "type": provider_type, "version": "1.1.0",
        "manifestURI": "https://raw.githubusercontent.com/OWNER/repo/main/x/manifest.json",
        "payloadURI": "https://raw.githubusercontent.com/OWNER/repo/main/x/code.js",
    }), encoding="utf-8")
    (ext / "conversion-report.json").write_text(json.dumps({
        "overall_status": status, "strategy": "STRATEGY_2_JADX_JAVA_AST",
        "live_test_status": "NOT_RUN",
    }), encoding="utf-8")


def test_readme_lists_only_published_extensions(tmp_path):
    readme_mod = load_mod("readme_generator", "engine/seanime-generator/readme.py")
    _make_bundle(tmp_path, "onlinestream-provider", "alpha", "SUCCESS", "Alpha")
    _make_bundle(tmp_path, "onlinestream-provider", "beta", "NEEDS_REVIEW", "Beta")
    (tmp_path / "README.md").write_text("# My repo\n\nHand-written docs.\n", encoding="utf-8")

    gen = readme_mod.ReadmeGenerator(str(tmp_path), "gcoderp", "seanime-extensions", "main", "2.5.0")
    gen.write(withheld=1)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Hand-written docs." in text, "existing documentation must survive"
    assert "## Extensions (1)" in text
    assert "https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/src/onlinestream-provider/alpha/manifest.json" in text
    assert "onlinestream-provider/beta" not in text, "held bundles must not be listed"
    assert readme_mod.BEGIN in text and readme_mod.END in text


def test_readme_regeneration_is_idempotent(tmp_path):
    readme_mod = load_mod("readme_generator", "engine/seanime-generator/readme.py")
    _make_bundle(tmp_path, "onlinestream-provider", "alpha")
    (tmp_path / "README.md").write_text("# Repo\n\ndocs\n", encoding="utf-8")
    gen = readme_mod.ReadmeGenerator(str(tmp_path), "gcoderp", "seanime-extensions")
    gen.write()
    first = (tmp_path / "README.md").read_text(encoding="utf-8")
    gen.write()
    second = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert first.count(readme_mod.BEGIN) == 1
    assert second.count(readme_mod.BEGIN) == 1
    assert first.split(readme_mod.BEGIN)[1].split(readme_mod.END)[0][:200] == \
           second.split(readme_mod.BEGIN)[1].split(readme_mod.END)[0][:200]


def test_manifest_url_list_matches_marketplace(tmp_path):
    readme_mod = load_mod("readme_generator", "engine/seanime-generator/readme.py")
    _make_bundle(tmp_path, "anime-torrent-provider", "one")
    _make_bundle(tmp_path, "onlinestream-provider", "two")
    _make_bundle(tmp_path, "onlinestream-provider", "held", status="NEEDS_REVIEW")
    gen = readme_mod.ReadmeGenerator(str(tmp_path), "gcoderp", "seanime-extensions")
    path = gen.write_url_list()
    urls = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    assert len(urls) == 2
    assert all(u.endswith("/manifest.json") for u in urls)


def test_retriage_applies_licence_policy():
    reindex = load_mod("reindex", "scripts/reindex.py")
    report = {
        "overall_status": "NEEDS_REVIEW",
        "passed": False,
        "review_reasons": ["Upstream licence 'UNKNOWN' is not on the redistribution allowlist."],
        "warnings": [],
    }
    held = reindex.retriage(dict(report, review_reasons=list(report["review_reasons"])), allow_unknown_license=False)
    assert held["overall_status"] == "NEEDS_REVIEW"

    published = reindex.retriage(dict(report, review_reasons=list(report["review_reasons"]), warnings=[]), allow_unknown_license=True)
    assert published["overall_status"] == "SUCCESS"
    assert published["passed"] is True
    assert published["license_notice"] is True
    assert any("Licence notice" in w for w in published["warnings"])


def test_retriage_still_holds_unrecoverable_bundles():
    reindex = load_mod("reindex", "scripts/reindex.py")
    report = {
        "overall_status": "NEEDS_REVIEW",
        "review_reasons": [
            "Upstream licence 'UNKNOWN' is not on the redistribution allowlist.",
            "All CSS selectors are generic fallbacks; no provider-specific selectors were recovered.",
        ],
        "warnings": [],
    }
    out = reindex.retriage(dict(report, review_reasons=list(report["review_reasons"]), warnings=[]), allow_unknown_license=True)
    assert out["overall_status"] == "NEEDS_REVIEW", "generic selectors must keep blocking publication"
