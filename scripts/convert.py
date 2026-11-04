#!/usr/bin/env python3
"""End-to-end Cloudstream .cs3 to Seanime TypeScript/JavaScript conversion pipeline.

Two modes:
  live      (default) discover plugins from config/repositories.json, download the real
            .cs3 packages, verify checksums and convert them.
  fixtures  convert the local packages listed in tests/fixtures/plugins.json (offline).

JavaScript is produced by the TypeScript compiler, never by string rewriting, and a
bundle is only written when the compiled JavaScript actually parses.
"""
import argparse
import importlib.util
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parser_mod = load_mod("manifest_parser", "engine/manifest-parser/parser.py")
dl_mod = load_mod("downloader", "engine/downloader/downloader.py")
ext_mod = load_mod("cs3_extractor", "engine/cs3-extractor/extractor.py")
src_mod = load_mod("source_discovery", "engine/source-discovery/discovery.py")
dex_mod = load_mod("dex_analyzer", "engine/dex-analyzer/analyzer.py")
smali_mod = load_mod("smali_analyzer", "engine/smali-analyzer/smali.py")
ast_mod = load_mod("kotlin_parser", "engine/kotlin-parser/parser.py")
extr_mod = load_mod("extractor_translator", "engine/extractor-translator/extractors.py")
trans_mod = load_mod("kotlin_translator", "engine/kotlin-translator/translator.py")
tsc_mod = load_mod("ts_compiler", "engine/ts-compiler/compiler.py")
gen_mod = load_mod("seanime_generator", "engine/seanime-generator/generator.py")
val_mod = load_mod("validator", "engine/validator/validator.py")
disc_mod = load_mod("discover_script", "scripts/discover.py")


def _registrable_host(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""
    parts = [p for p in host.lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _filter_mirrors(discovered_urls, main_url: str, limit: int = 3):
    """Keeps only URLs that plausibly belong to the provider's own site.

    The DEX string pool is full of CDN, analytics and asset URLs; using those as
    'mirrors' silently pointed the fetch fallback at unrelated hosts.
    """
    base_host = _registrable_host(main_url)
    out = []
    for url in discovered_urls or []:
        if not url.startswith(("http://", "https://")):
            continue
        if base_host and _registrable_host(url) == base_host and url not in out:
            out.append(url.rstrip("/"))
        if len(out) >= limit:
            break
    return out


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def run_pipeline(mode: str = "live", limit: int = 0, only: str = "", skip_download: bool = False) -> dict:
    settings = _load_json(os.path.join(ROOT, "config/settings.json"), {})
    licensing = settings.get("licensing", {})
    allowed_licenses = licensing.get("allowed_spdx", [])
    security = settings.get("security", {})

    manifest_parser = parser_mod.CloudstreamManifestParser()
    downloader = dl_mod.SecureCS3Downloader(cache_dir=os.path.join(ROOT, ".cache/packages"))
    extractor = ext_mod.CS3Extractor(
        work_dir=os.path.join(ROOT, ".cache/extracted"),
        max_entries=int(security.get("max_zip_entries", 2500)),
        max_uncompressed_bytes=int(security.get("max_uncompressed_bytes", 52_428_800)),
        max_ratio=float(security.get("max_compression_ratio", 80.0)),
    )
    source_discovery = src_mod.SourceDiscoveryEngine(
        cache_path=os.path.join(ROOT, "config/license-cache.json"),
        offline=(mode == "fixtures"),
    )
    dex_analyzer = dex_mod.DexAnalyzer()
    smali_analyzer = smali_mod.SmaliAnalyzer()
    ast_parser = ast_mod.KotlinJavaASTParser()
    translator = trans_mod.CloudstreamToSeanimeTranslator(
        compat_shim_path=os.path.join(ROOT, "seanime/compatibility/cloudstream-runtime-shim.ts"),
        templates_dir=os.path.join(ROOT, "seanime/templates"),
    )
    compiler = tsc_mod.TypeScriptCompiler(repo_root=ROOT)
    generator = gen_mod.SeanimeExtensionGenerator(repo_root=ROOT)
    validator = val_mod.SeanimeExtensionValidator(repo_root=ROOT, allowed_licenses=allowed_licenses)

    build_dir = os.path.join(ROOT, ".cache/build")
    os.makedirs(build_dir, exist_ok=True)

    # ---------------------------------------------------------------- discovery
    fixtures_dir = os.path.join(ROOT, "tests/fixtures")
    if mode == "fixtures":
        raw_plugins = _load_json(os.path.join(fixtures_dir, "plugins.json"), [])
        plugin_entries = manifest_parser.parse_plugins_list(raw_plugins, os.path.join(fixtures_dir, "plugins.json"), "Local Fixture Repo")
        print(f"[discover] fixtures mode: {len(plugin_entries)} plugin(s)")
    else:
        raw_entries = disc_mod.discover_all_repositories()
        plugin_entries = [parser_mod.CloudstreamPluginEntry(**e) for e in raw_entries]
        print(f"[discover] live mode: {len(plugin_entries)} plugin(s) discovered")

    if only:
        wanted = {o.strip().lower() for o in only.split(",") if o.strip()}
        plugin_entries = [e for e in plugin_entries if e.internal_name.lower() in wanted or e.name.lower() in wanted]
    if limit and limit > 0:
        plugin_entries = plugin_entries[:limit]

    successful, failed, needs_review, skipped = [], [], [], []

    for entry in plugin_entries:
        ts_now = datetime.now(timezone.utc).isoformat()
        try:
            # ---------------------------------------------------------- acquire
            if os.path.exists(entry.url):
                local_cs3 = entry.url
            elif mode == "fixtures":
                local_cs3 = os.path.join(fixtures_dir, os.path.basename(entry.url))
            elif skip_download:
                skipped.append({"plugin_name": entry.name, "original_plugin_id": entry.internal_name,
                                "reason": "download skipped (--skip-download)", "conversion_timestamp": ts_now})
                continue
            else:
                local_cs3, digest, cached = downloader.download_cs3(
                    entry.url, entry.internal_name, entry.version, expected_sha256=entry.sha256
                )
                if cached:
                    print(f"[download] {entry.internal_name}: cache hit ({digest[:12]})")

            pkg = extractor.extract_package(local_cs3, entry.internal_name)

            # ---------------------------------------------------------- recover
            recovered = source_discovery.recover_source(
                plugin_id=entry.internal_name,
                plugin_class_name=pkg.plugin_class_name,
                package_name=pkg.package_name,
                repository_url=entry.repository_url,
                embedded_sources=pkg.embedded_kotlin_sources,
            )

            dex_res = dex_analyzer.analyze_dex_files(pkg.dex_files, pkg.extract_dir)
            smali_ir = smali_analyzer.reconstruct_from_dex_strings(dex_res.string_pool, dex_res.method_names)

            if recovered.found:
                strategy = f"STRATEGY_1_{recovered.strategy}"
                ast_model = ast_parser.parse_source(
                    recovered.main_provider_code,
                    fallback_urls=dex_res.discovered_urls,
                    fallback_selectors=dex_res.css_selectors,
                )
            elif dex_res.jadx_available and dex_res.decompiled_java_files:
                strategy = "STRATEGY_2_JADX_JAVA_AST"
                combined_java = "\n".join(dex_res.decompiled_java_files.values())
                ast_model = ast_parser.parse_source(
                    combined_java,
                    fallback_urls=dex_res.discovered_urls,
                    fallback_selectors=dex_res.css_selectors,
                )
            else:
                strategy = "STRATEGY_3_DEX_STRING_IR"
                ast_model = ast_parser.parse_source(
                    "\n".join(smali_ir.const_strings),
                    fallback_urls=dex_res.discovered_urls,
                    fallback_selectors=dex_res.css_selectors,
                )
                ast_model.class_name = pkg.plugin_class_name.split(".")[-1]
                ast_model.name = entry.name
                ast_model.lang = entry.language
                ast_model.is_torrent_provider = "Torrent" in entry.tv_types

            # ---------------------------------------------------------- translate
            translation = translator.translate_ast_to_seanime(
                plugin_id=entry.internal_name,
                ast_model=ast_model,
                extractor_runtime_ts=extr_mod.ExtractorTranslator.generate_extractor_runtime_ts(),
                strategy_label=strategy,
                mirror_domains=[ast_model.main_url] + _filter_mirrors(dex_res.discovered_urls, ast_model.main_url),
            )

            # ---------------------------------------------------------- compile
            ext_id = generator.to_kebab_id(entry.internal_name)
            stage = os.path.join(build_dir, ext_id)
            os.makedirs(stage, exist_ok=True)
            ts_path = os.path.join(stage, "code.ts")
            with open(ts_path, "w", encoding="utf-8") as f:
                f.write(translation.typescript_code)
            js_paths = compiler.compile_files([ts_path])
            with open(js_paths[0], "r", encoding="utf-8") as f:
                js_code = f.read()

            # An explicit declaration beats inference; inference beats nothing at all.
            license_spdx = entry.license or recovered.license_spdx or "UNKNOWN"

            # ---------------------------------------------------------- validate
            val_res = validator.validate_extension(
                plugin_id=entry.internal_name,
                provider_type=translation.provider_type,
                ts_code=translation.typescript_code,
                js_code=js_code,
                main_url=ast_model.main_url,
                license_spdx=license_spdx,
                js_path=js_paths[0],
                strategy=strategy,
            )

            full_report = {
                "plugin_name": entry.name,
                "original_plugin_id": entry.internal_name,
                "original_author": ", ".join(entry.authors),
                "original_repository": entry.repository_url or entry.source_repo_name,
                "original_download_url": generator.public_url(entry.url),
                "original_version": entry.version,
                "sha256_checksum": pkg.sha256,
                "license_spdx": license_spdx,
                "detected_provider_type": translation.provider_type,
                "source_recovery_status": "RECOVERED" if recovered.found else "DEX_FALLBACK",
                "decompilation_status": "JADX_OK" if dex_res.jadx_available else "BINARY_DEX_IR_OK",
                "kotlin_reconstruction_status": "SUCCESS" if recovered.found else "PARTIAL",
                "translation_status": "SUCCESS",
                "typescript_compilation_status": "SUCCESS",
                "seanime_compatibility_status": val_res["goja_compatibility"],
                "js_parse_status": val_res["js_parse_status"],
                "live_test_status": val_res["live_test_status"],
                "search_test_status": val_res["search_test"],
                "episode_test_status": val_res["episode_test"],
                "extractor_test_status": val_res["extractor_test"],
                "overall_status": val_res["overall_status"],
                "review_reasons": val_res["review_reasons"],
                "known_unsupported_methods": [],
                "warnings": translation.warnings + val_res["warnings"],
                "error_messages": val_res["errors"],
                "conversion_timestamp": ts_now,
                "passed": val_res["passed"],
            }

            # ---------------------------------------------------------- emit
            bundle = generator.generate_extension_bundle(
                plugin_meta=entry,
                translation=translation,
                javascript_code=js_code,
                sha256_hex=pkg.sha256,
                validation_report=full_report,
                source_info=recovered,
            )
            print(f"[convert] {entry.internal_name}: {val_res['overall_status']} ({strategy}, {bundle.get('status')})")

            if val_res["overall_status"] == "SUCCESS":
                successful.append(full_report)
            elif val_res["overall_status"] == "NEEDS_REVIEW":
                needs_review.append(full_report)
            else:
                failed.append(full_report)

        except Exception as ex:
            print(f"[convert] {entry.internal_name}: FAILED ({ex})")
            failed.append({
                "plugin_name": entry.name,
                "original_plugin_id": entry.internal_name,
                "overall_status": "FAILED",
                "error_messages": [str(ex)],
                "conversion_timestamp": ts_now,
            })

    # ---------------------------------------------------------------- reporting
    marketplace_entries = generator.regenerate_marketplace()

    reports_dir = os.path.join(ROOT, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    for name, payload in (
        ("successful.json", successful),
        ("failed.json", failed),
        ("needs-review.json", needs_review),
        ("skipped.json", skipped),
    ):
        with open(os.path.join(reports_dir, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    summary = {
        "last_run_timestamp": datetime.now(timezone.utc).isoformat(),
        "converter_version": settings.get("converter_version", "2.5.0"),
        "mode": mode,
        "total_processed": len(successful) + len(failed) + len(needs_review) + len(skipped),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "needs_review_count": len(needs_review),
        "skipped_count": len(skipped),
        "published_in_marketplace": len(marketplace_entries),
    }
    with open(os.path.join(reports_dir, "conversion-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    history_path = os.path.join(reports_dir, "history.json")
    history = _load_json(history_path, [])
    if not isinstance(history, list):
        history = []
    history.append(summary)
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history[-50:], f, indent=2)

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Cloudstream .cs3 -> Seanime extension converter")
    ap.add_argument("--fixtures", action="store_true", help="convert local test fixtures instead of live repositories")
    ap.add_argument("--limit", type=int, default=0, help="process at most N plugins")
    ap.add_argument("--only", default="", help="comma-separated internal plugin names to process")
    ap.add_argument("--skip-download", action="store_true", help="discover only; do not download packages")
    args = ap.parse_args()

    summary = run_pipeline(
        mode="fixtures" if args.fixtures else "live",
        limit=args.limit,
        only=args.only,
        skip_download=args.skip_download,
    )
    print("Conversion pipeline completed:", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
