import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, Any, List, Optional

from pathlib import Path

_FALLBACK_FILE = Path(__file__).resolve().parent.parent / "cloudstream-compat" / "generic-fallbacks.json"

PLACEHOLDER_HOSTS = {
    "example.com", "example.org", "example.net", "test.com", "yoursite.com",
    "localhost", "127.0.0.1", "0.0.0.0", "site.com", "domain.com",
}


def _load_generic_fallbacks() -> Dict[str, str]:
    try:
        with open(_FALLBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class SeanimeExtensionValidator:
    """Validation with three honest outcomes: SUCCESS (publishable), NEEDS_REVIEW, FAILED.

    Hard gates (FAILED): provider contract, forbidden Goja APIs, placeholder implementations,
    brace balance, real JavaScript parse via `node --check`, mock-contract smoke run.

    Soft gates (NEEDS_REVIEW -- blocked from the marketplace, kept on disk):
    placeholder/unrecovered main URL, template-only generic selectors, licence not on the
    allowlist, and the fact that no live end-to-end test has been executed.

    The smoke run below is a MOCK. It proves the emitted JavaScript parses and its provider
    contract is reachable; it cannot prove the CSS selectors match the live site. That is
    what `live_test_status: NOT_RUN` records, and why such conversions are not published
    as working extensions.
    """

    FORBIDDEN_APIS = [
        r"\brequire\s*\(",
        r"\bprocess\.env\b",
        r"\bchild_process\b",
        r"\bfs\.readFile",
        r"\bwindow\.document\b",
        r"\blocalStorage\b",
        r"\bXMLHttpRequest\b",
        r"\beval\s*\(",
    ]

    REQUIRED_METHODS_BY_TYPE = {
        "onlinestream-provider": ["getSettings", "search", "findEpisodes", "findEpisodeServer"],
        "anime-torrent-provider": ["getSettings", "search", "smartSearch", "getTorrentInfoHash", "getTorrentMagnetLink"],
        "manga-provider": ["getSettings", "search", "findChapters", "findChapterPages"],
    }

    def __init__(self, repo_root: str = ".", allowed_licenses: Optional[List[str]] = None):
        self.repo_root = os.path.abspath(repo_root)
        self.allowed_licenses = allowed_licenses or []
        self.generic = _load_generic_fallbacks()

    # ------------------------------------------------------------------ public

    def validate_extension(
        self,
        plugin_id: str,
        provider_type: str,
        ts_code: str,
        js_code: str,
        main_url: str = "",
        license_spdx: str = "",
        js_path: Optional[str] = None,
        strategy: str = ""
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        review_reasons: List[str] = []

        # 1. Provider contract --------------------------------------------------
        if "class Provider" not in ts_code or "class Provider" not in js_code:
            errors.append("Missing required 'class Provider' declaration.")

        for m in self.REQUIRED_METHODS_BY_TYPE.get(provider_type, ["getSettings", "search"]):
            if not re.search(rf"\b{m}\s*\(", js_code):
                errors.append(f"Missing required Seanime provider method: {m}()")

        # 2. Forbidden runtime APIs --------------------------------------------
        for pat in self.FORBIDDEN_APIS:
            if re.search(pat, js_code):
                errors.append(f"Forbidden non-Goja API pattern detected: {pat}")

        # 3. Placeholder implementations ---------------------------------------
        if re.search(r"async\s+search\s*\([^)]*\)\s*\{\s*return\s*\[\s*\]\s*;?\s*\}", js_code):
            errors.append("Search method is an empty placeholder returning [].")

        # 4. Real JavaScript parse check ---------------------------------------
        # (A naive brace counter used to live here. It reported false failures for any
        # regex containing a literal brace, e.g. /btih:[a-f0-9]{40}/. `node --check`
        # below is the authoritative parse gate.)
        syntax_failures = self._check_js_parse(js_code, js_path)
        for failure in syntax_failures:
            errors.append(f"Compiled JavaScript does not parse: {failure}")

        # 6. Mock-contract smoke run -------------------------------------------
        mock_passed = False
        mock_detail = ""
        runtime_bin = shutil.which("node") or shutil.which("bun")
        if runtime_bin and not errors:
            mock_passed, mock_detail = self._run_js_sandbox_smoke_test(runtime_bin, provider_type, js_code)
            if not mock_passed:
                errors.append(f"Mock contract smoke test failed: {mock_detail}")

        # 7. Soft gates: recoverability ----------------------------------------
        detected_url = main_url or self._extract_main_url(ts_code)
        if not detected_url:
            review_reasons.append("No upstream base URL could be recovered.")
        else:
            host = re.sub(r"^https?://", "", detected_url).split("/")[0].split(":")[0].lower()
            if host in PLACEHOLDER_HOSTS:
                review_reasons.append(f"Base URL is a placeholder ({host}); scraper logic was not recovered.")

        if strategy.startswith("STRATEGY_3"):
            review_reasons.append(
                "Only DEX string-pool reconstruction was possible (STRATEGY_3); the scraper's control "
                "flow was not recovered, so the emitted selectors are guesses."
            )

        if provider_type == "onlinestream-provider" and self._uses_only_generic_selectors(ts_code):
            review_reasons.append("All CSS selectors are generic fallbacks; no provider-specific selectors were recovered.")

        # 8. Soft gate: licence -------------------------------------------------
        if license_spdx and self.allowed_licenses:
            if license_spdx not in self.allowed_licenses:
                review_reasons.append(f"Upstream licence '{license_spdx}' is not on the redistribution allowlist.")

        warnings.append("Live end-to-end test against the upstream site has NOT been run (live_test_status=NOT_RUN).")

        if errors:
            status = "FAILED"
        elif review_reasons:
            status = "NEEDS_REVIEW"
        else:
            status = "SUCCESS"

        return {
            "plugin_id": plugin_id,
            "provider_type": provider_type,
            "strategy": strategy,
            "passed": status == "SUCCESS",
            "overall_status": status,
            "static_check": "PASS" if not errors else "FAIL",
            "js_parse_status": "PASS" if not syntax_failures else "FAIL",
            "goja_compatibility": "PASS" if mock_passed else "FAIL",
            "mock_contract_status": "PASS" if mock_passed else "FAIL",
            "live_test_status": "NOT_RUN",
            "search_test": "MOCK_PASS" if mock_passed else "FAIL",
            "episode_test": ("MOCK_PASS" if mock_passed else "FAIL") if provider_type == "onlinestream-provider" else "N/A",
            "extractor_test": ("MOCK_PASS" if mock_passed else "FAIL") if provider_type == "onlinestream-provider" else "N/A",
            "review_reasons": review_reasons,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _extract_main_url(code: str) -> str:
        m = re.search(r'mainUrl[^=\n]*=\s*"(https?://[^"]+)"', code)
        return m.group(1) if m else ""

    def _uses_only_generic_selectors(self, ts_code: str) -> bool:
        if not self.generic:
            return False
        found = 0
        for key in ("search_item", "search_title", "episode_list", "server_link"):
            value = self.generic.get(key)
            if value and json.dumps(value) in ts_code:
                found += 1
        return found >= 4

    def _check_js_parse(self, js_code: str, js_path: Optional[str]) -> List[str]:
        runtime_bin = shutil.which("node")
        if not runtime_bin:
            return []
        temp_created = False
        if not js_path or not os.path.exists(js_path):
            fd, js_path = tempfile.mkstemp(suffix=".js")
            os.close(fd)
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(js_code)
            temp_created = True
        try:
            proc = subprocess.run(
                [runtime_bin, "--check", js_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )
            if proc.returncode == 0:
                return []
            lines = (proc.stderr or proc.stdout or "").strip().splitlines()
            return [lines[0] if lines else "unknown syntax error"]
        except Exception as exc:
            return [str(exc)]
        finally:
            if temp_created:
                try:
                    os.remove(js_path)
                except OSError:
                    pass

    def _run_js_sandbox_smoke_test(self, runtime_bin: str, provider_type: str, js_code: str) -> tuple[bool, str]:
        harness = f"""
// Seanime Goja Sandbox Emulation Harness (MOCK -- not a live site test)
globalThis.LoadDoc = function(html) {{
    const makeEl = () => ({{
        text: () => "Sample Anime Title Episode 1",
        attr: (name) => {{
            if (name === "href") return "/watch/sample-anime-ep-1";
            if (name === "data-embed" || name === "src") return "https://cdn.example.com/hls/master.m3u8";
            if (name === "data-number") return "1";
            return "Sample";
        }},
        find: () => makeSelection(),
        first: () => makeEl()
    }});
    const makeSelection = () => ({{
        length: 1,
        first: () => makeEl(),
        text: () => "1",
        attr: (n) => makeEl().attr(n),
        find: () => makeSelection(),
        each: (cb) => {{ cb(0, makeEl()); }}
    }});
    return function(selector) {{ return makeSelection(); }};
}};

globalThis.fetch = async function(url, opts) {{
    return {{
        status: 200,
        ok: true,
        text: async () => '<html><body><div class="flw-item"><a href="/anime/1">Sample</a></div><iframe src="https://cdn.example.com/stream.m3u8"></iframe><a href="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567">Magnet</a></body></html>'
    }};
}};

{js_code}

(async () => {{
    const p = new Provider();
    const settings = p.getSettings();
    if (!settings) throw new Error("getSettings returned null");
    const searchRes = await p.search({{ query: "Frieren", dub: false, media: {{ id: 1, title: {{ romaji: "Frieren" }} }} }});
    if (!Array.isArray(searchRes) || searchRes.length === 0) throw new Error("search returned empty array");
    if ("{provider_type}" === "onlinestream-provider") {{
        const eps = await p.findEpisodes(searchRes[0].id);
        if (!Array.isArray(eps) || eps.length === 0) throw new Error("findEpisodes returned empty array");
        const srv = await p.findEpisodeServer(eps[0], "default");
        if (!srv || !Array.isArray(srv.videoSources) || srv.videoSources.length === 0) throw new Error("findEpisodeServer returned no videoSources");
    }}
    console.log("SANDBOX_OK");
}})().catch(err => {{
    console.error(err);
    process.exit(1);
}});
"""
        try:
            proc = subprocess.run(
                [runtime_bin, "-e", harness],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True
            )
            if proc.returncode == 0 and "SANDBOX_OK" in proc.stdout:
                return True, ""
            return False, (proc.stderr or proc.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)
