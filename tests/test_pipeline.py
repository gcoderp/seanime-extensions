import importlib.util
import json
import os
import subprocess
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
NODE = subprocess.run(["which", "node"], stdout=subprocess.PIPE, text=True).stdout.strip()


def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- parsing


def test_manifest_parser_resolves_relative_urls():
    parser_mod = load_mod("parser", "engine/manifest-parser/parser.py")
    p = parser_mod.CloudstreamManifestParser()
    urls = p.parse_repo_manifest({"pluginLists": ["plugins.json"]}, "https://example.com/repo/repo.json")
    assert urls == ["https://example.com/repo/plugins.json"]


def test_manifest_parser_accepts_a_bare_plugins_list():
    parser_mod = load_mod("parser", "engine/manifest-parser/parser.py")
    p = parser_mod.CloudstreamManifestParser()
    # A plugins.json passed where a repo.json was expected must not raise
    assert p.parse_repo_manifest([{"name": "x"}], "https://example.com/plugins.json") == []


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
    ext_mod = load_mod("extractor", "engine/cs3-extractor/extractor.py")
    analyzer = dex_mod.DexAnalyzer()
    pkg = ext_mod.CS3Extractor(work_dir=os.path.join(ROOT, ".cache/test-extract")).extract_package(
        os.path.join(FIXTURES, "HiAnimeProvider.cs3"), "HiAnimeProvider"
    )
    res = analyzer.analyze_dex_files(pkg.dex_files, pkg.extract_dir)
    assert "https://hianime.to" in res.discovered_urls
    assert any("flw-item" in s for s in res.css_selectors)


def test_dex_analyzer_survives_a_corrupt_header(tmp_path):
    dex_mod = load_mod("analyzer", "engine/dex-analyzer/analyzer.py")
    analyzer = dex_mod.DexAnalyzer()
    bad = tmp_path / "corrupt.dex"
    bad.write_bytes(b"dex\n035\x00" + b"\x00" * 8 + b"https://example.test\n" + b"\xff" * 200)
    strings, _, _ = analyzer.parse_dex_binary_strings_and_types(str(bad))
    assert any("example.test" in s for s in strings), "must fall back to a string scan, not raise"


def test_selector_heuristics_ignore_page_headings():
    parser_mod = load_mod("parser", "engine/kotlin-parser/parser.py")
    fixtures_mod = load_mod("build_fixtures", "tests/fixtures/build_fixtures.py")
    ast = parser_mod.KotlinJavaASTParser().parse_source(fixtures_mod.GOGO_KOTLIN)
    assert ast.search_item_selector == "ul.items li"
    assert ast.search_title_selector == "p.name a"
    # "h1" is the page title, not the episode list
    assert ast.episode_list_selector == "ul#episode_related li a"
    assert ast.uses_generic_selectors is False


def test_site_url_guessing_ignores_player_hosts():
    parser_mod = load_mod("parser", "engine/kotlin-parser/parser.py")
    guess = parser_mod._guess_site_url([
        "http://mp4upload.com",
        "https://anitaku.pe/anime/x",
        "https://anitaku.pe",
        "https://fonts.googleapis.com/css",
    ])
    assert guess == "https://anitaku.pe"


# --------------------------------------------------------------------------- codegen


def test_translator_leaves_no_tokens_and_preserves_regex_quantifiers():
    trans_mod = load_mod("translator", "engine/kotlin-translator/translator.py")
    parser_mod = load_mod("parser", "engine/kotlin-parser/parser.py")
    extr_mod = load_mod("extractor_translator", "engine/extractor-translator/extractors.py")
    ast = parser_mod.KotlinJavaASTParser().parse_source('class X : MainAPI() { override var mainUrl = "https://x.test" }')
    ast.is_torrent_provider = True
    translator = trans_mod.CloudstreamToSeanimeTranslator(
        compat_shim_path=os.path.join(ROOT, "seanime/compatibility/cloudstream-runtime-shim.ts"),
        templates_dir=os.path.join(ROOT, "seanime/templates"),
        anilist_resolver_path=os.path.join(ROOT, "seanime/compatibility/anilist-resolver.ts"),
    )
    result = translator.translate_ast_to_seanime(
        "X", ast, extr_mod.ExtractorTranslator.generate_extractor_runtime_ts(), "STRATEGY_1_TEST"
    )
    # Regression: an f-string once turned {40} into 40, silently breaking magnet hashing.
    assert "{40}" in result.typescript_code
    assert "{32}" in result.typescript_code
    assert not trans_mod.TOKEN_RE.findall(result.typescript_code)


def test_extractor_runtime_emits_valid_regexes():
    extr_mod = load_mod("extractor_translator", "engine/extractor-translator/extractors.py")
    runtime = extr_mod.ExtractorTranslator.generate_extractor_runtime_ts()
    # Regression: the escaping once produced a regex that could never match http(s)://
    assert r"https?:\/\/" in runtime
    assert r"(https?:\?\/\?\/" not in runtime


@pytest.mark.skipif(not NODE, reason="node is required")
def test_generated_javascript_parses(sample_bundle):
    proc = subprocess.run([NODE, "--check", sample_bundle["js_path"]],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------- validation gates


def _validator():
    val_mod = load_mod("validator", "engine/validator/validator.py")
    return val_mod.SeanimeExtensionValidator(
        repo_root=ROOT,
        allowed_licenses=["GPL-3.0", "MIT", "TEST_FIXTURE"],
    )


def test_validator_accepts_a_recovered_extension(sample_bundle):
    result = _validator().validate_extension(
        "gogo", "onlinestream-provider", sample_bundle["ts"], sample_bundle["js"],
        main_url=sample_bundle["main_url"], license_spdx="TEST_FIXTURE",
        strategy="STRATEGY_1_EMBEDDED_KOTLIN_SOURCE",
    )
    assert result["overall_status"] == "SUCCESS"
    assert result["passed"] is True
    assert result["live_test_status"] == "NOT_RUN"


def test_validator_flags_placeholder_host(sample_bundle):
    result = _validator().validate_extension(
        "x", "onlinestream-provider", sample_bundle["ts"], sample_bundle["js"],
        main_url="https://example.com", license_spdx="TEST_FIXTURE",
        strategy="STRATEGY_1_EMBEDDED_KOTLIN_SOURCE",
    )
    assert result["overall_status"] == "NEEDS_REVIEW"
    assert any("placeholder" in r for r in result["review_reasons"])


def test_validator_flags_string_pool_reconstruction(sample_bundle):
    result = _validator().validate_extension(
        "x", "onlinestream-provider", sample_bundle["ts"], sample_bundle["js"],
        main_url=sample_bundle["main_url"], license_spdx="TEST_FIXTURE",
        strategy="STRATEGY_3_DEX_STRING_IR",
    )
    assert result["overall_status"] == "NEEDS_REVIEW"


def test_validator_flags_unlicensed_upstream(sample_bundle):
    result = _validator().validate_extension(
        "x", "onlinestream-provider", sample_bundle["ts"], sample_bundle["js"],
        main_url=sample_bundle["main_url"], license_spdx="UNKNOWN",
        strategy="STRATEGY_1_EMBEDDED_KOTLIN_SOURCE",
    )
    assert result["overall_status"] == "NEEDS_REVIEW"
    assert any("licence" in r for r in result["review_reasons"])


def test_validator_rejects_broken_javascript(sample_bundle):
    broken = sample_bundle["js"] + "\nconst = 1;\n"
    result = _validator().validate_extension(
        "x", "onlinestream-provider", sample_bundle["ts"], broken,
        main_url=sample_bundle["main_url"], license_spdx="TEST_FIXTURE",
        strategy="STRATEGY_1_EMBEDDED_KOTLIN_SOURCE",
    )
    assert result["overall_status"] == "FAILED"
    assert any("does not parse" in e for e in result["errors"])


def test_licence_notice_policy_publishes_with_a_recorded_notice(sample_bundle):
    val_mod = load_mod("validator", "engine/validator/validator.py")
    validator = val_mod.SeanimeExtensionValidator(
        repo_root=ROOT, allowed_licenses=["GPL-3.0"], allow_unknown_license=True
    )
    result = validator.validate_extension(
        "x", "onlinestream-provider", sample_bundle["ts"], sample_bundle["js"],
        main_url=sample_bundle["main_url"], license_spdx="UNKNOWN",
        strategy="STRATEGY_1_EMBEDDED_KOTLIN_SOURCE",
    )
    assert result["overall_status"] == "SUCCESS"
    assert result["license_notice"] is True
    assert any("licence" in w.lower() for w in result["warnings"])


# --------------------------------------------------------------------------- regressions


def test_marketplace_prefers_the_validated_bundle_when_ids_collide(tmp_path):
    """A plugin listed as both Anime and Torrent produces the same kebab-case id.

    Publishing used to depend on directory order, so the marketplace could point at one
    bundle while the report that validate.mjs checked belonged to another. That is the
    failure that stopped the 2.6.0 workflow on `cine-stream`.
    """
    gen_mod = load_mod("seanime-generator", "engine/seanime-generator/generator.py")
    for p_type, status in (("onlinestream-provider", "NEEDS_REVIEW"), ("anime-torrent-provider", "SUCCESS")):
        ext = tmp_path / "src" / p_type / "cine-stream"
        ext.mkdir(parents=True)
        (ext / "manifest.json").write_text(json.dumps({
            "id": "cine-stream", "name": "CineStream", "type": p_type, "version": "1.1.0",
            "manifestURI": f"https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/src/{p_type}/cine-stream/manifest.json",
            "payloadURI": f"https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/src/{p_type}/cine-stream/code.js",
        }), encoding="utf-8")
        (ext / "conversion-report.json").write_text(json.dumps({"overall_status": status}), encoding="utf-8")
        (ext / "code.js").write_text("class Provider {}\n", encoding="utf-8")

    generator = gen_mod.SeanimeExtensionGenerator(repo_root=str(tmp_path))
    marketplace = generator.regenerate_marketplace()

    assert len(marketplace) == 1
    assert "anime-torrent-provider/cine-stream/code.js" in marketplace[0]["payloadURI"]
    duplicates = json.loads((tmp_path / "reports" / "duplicate-ids.json").read_text(encoding="utf-8"))
    assert duplicates and duplicates[0]["id"] == "cine-stream"
    assert set(duplicates[0]["statuses"]) == {"NEEDS_REVIEW", "SUCCESS"}


def test_marketplace_skips_a_bundle_that_did_not_pass(tmp_path):
    gen_mod = load_mod("seanime-generator", "engine/seanime-generator/generator.py")
    ext = tmp_path / "src" / "onlinestream-provider" / "held"
    ext.mkdir(parents=True)
    (ext / "manifest.json").write_text(json.dumps({
        "id": "held", "name": "Held", "type": "onlinestream-provider", "version": "1.0.0",
        "payloadURI": "https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/src/onlinestream-provider/held/code.js",
    }), encoding="utf-8")
    (ext / "conversion-report.json").write_text(json.dumps({"overall_status": "NEEDS_REVIEW"}), encoding="utf-8")
    (ext / "code.js").write_text("class Provider {}\n", encoding="utf-8")

    assert gen_mod.SeanimeExtensionGenerator(repo_root=str(tmp_path)).regenerate_marketplace() == []


def test_template_guard_ignores_provider_identifiers_that_look_like_tokens():
    """__NUXT_DATA__ is a real Nuxt global used as a selector, not an unsubstituted token."""
    trans_mod = load_mod("translator", "engine/kotlin-translator/translator.py")
    filled = trans_mod.CloudstreamToSeanimeTranslator._fill(
        "const sel = __SELECTOR__;",
        {"__SELECTOR__": json.dumps("script#__NUXT_DATA__")},
    )
    assert "__NUXT_DATA__" in filled

    with pytest.raises(ValueError, match="Unsubstituted template tokens"):
        trans_mod.CloudstreamToSeanimeTranslator._fill("const a = __MISSING__;", {})


def test_downloader_encodes_spaces_in_package_urls():
    dl_mod = load_mod("downloader", "engine/downloader/downloader.py")
    encoded = dl_mod.SecureCS3Downloader.normalize_url(
        "https://raw.githubusercontent.com/Abodabodd/re-3arabi/builds/Aia2tv 2.cs3"
    )
    assert " " not in encoded
    assert encoded.endswith("Aia2tv%202.cs3")
    # an already-encoded URL must not be encoded twice
    assert dl_mod.SecureCS3Downloader.normalize_url("https://x.test/a%20b.cs3") == "https://x.test/a%20b.cs3"


# --------------------------------------------------------------------------- repository state


def test_marketplace_only_contains_validated_extensions():
    with open(os.path.join(ROOT, "marketplace.json"), encoding="utf-8") as f:
        marketplace = json.load(f)
    assert isinstance(marketplace, list)
    ids = {item["id"] for item in marketplace}
    assert len(ids) == len(marketplace), "duplicate marketplace ids"

    for item in marketplace:
        assert item["payloadURI"].endswith("/code.js")
        assert "/OWNER/" not in item["manifestURI"]

    index = {}
    for root, _, files in os.walk(os.path.join(ROOT, "src")):
        if "manifest.json" in files and "conversion-report.json" in files:
            with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
                index[json.load(f).get("id")] = os.path.join(root, "conversion-report.json")

    for item in marketplace:
        report_path = index.get(item["id"])
        assert report_path, f"{item['id']} published without a bundle"
        with open(report_path, encoding="utf-8") as f:
            assert json.load(f)["overall_status"] == "SUCCESS"
