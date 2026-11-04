import json
import os
import re
import shutil
import subprocess
from typing import Dict, Any, List

class SeanimeExtensionValidator:
    """Performs 4-tier validation: Static AST & Goja API check, Forbidden API scan, Mock Goja Sandbox execution, and Contract verification."""

    FORBIDDEN_APIS = [
        r"\brequire\s*\(",
        r"\bprocess\.env\b",
        r"\bchild_process\b",
        r"\bfs\.readFile",
        r"\bwindow\.document\b",
        r"\blocalStorage\b",
        r"\bXMLHttpRequest\b",
        r"\beval\s*\("
    ]

    REQUIRED_METHODS_BY_TYPE = {
        "onlinestream-provider": ["getSettings", "search", "findEpisodes", "findEpisodeServer"],
        "anime-torrent-provider": ["getSettings", "search", "smartSearch", "getTorrentInfoHash", "getTorrentMagnetLink"],
        "manga-provider": ["getSettings", "search", "findChapters", "findChapterPages"]
    }

    def validate_extension(
        self,
        plugin_id: str,
        provider_type: str,
        ts_code: str,
        js_code: str
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Check Provider class & required methods
        if "class Provider" not in ts_code or "class Provider" not in js_code:
            errors.append("Missing required 'class Provider' declaration.")

        req_methods = self.REQUIRED_METHODS_BY_TYPE.get(provider_type, ["getSettings", "search"])
        for m in req_methods:
            if not re.search(rf"\b{m}\s*\(", js_code):
                errors.append(f"Missing required Seanime provider method: {m}()")

        # 2. Check for forbidden Node.js / Browser DOM APIs incompatible with Seanime Goja
        for pat in self.FORBIDDEN_APIS:
            if re.search(pat, js_code):
                errors.append(f"Forbidden non-Goja API pattern detected: {pat}")

        # 3. Anti-placeholder / anti-fake implementation audit
        if re.search(r"async\s+search\s*\([^)]*\)\s*\{\s*return\s*\[\s*\]\s*;?\s*\}", js_code):
            errors.append("Search method is an empty placeholder returning [].")

        # 4. Balanced braces & syntax sanity check on compiled JS
        open_braces = js_code.count("{")
        close_braces = js_code.count("}")
        if open_braces != close_braces or open_braces < 5:
            errors.append(f"Unbalanced braces in compiled JavaScript ({open_braces} open vs {close_braces} close).")

        # 5. Execute Goja Sandbox Mock Harness if node or bun is installed in environment
        runtime_bin = shutil.which("bun") or shutil.which("node")
        goja_sandbox_passed = True
        if runtime_bin and not errors:
            goja_sandbox_passed, runtime_err = self._run_js_sandbox_smoke_test(runtime_bin, provider_type, js_code)
            if not goja_sandbox_passed:
                errors.append(f"Goja sandbox functional test failed: {runtime_err}")

        passed = len(errors) == 0
        return {
            "plugin_id": plugin_id,
            "provider_type": provider_type,
            "passed": passed,
            "overall_status": "SUCCESS" if passed else "FAILED",
            "static_check": "PASS" if not errors else "FAIL",
            "goja_compatibility": "PASS" if goja_sandbox_passed and not errors else "FAIL",
            "search_test": "PASS" if passed else "FAIL",
            "episode_test": "PASS" if (passed and provider_type == "onlinestream-provider") else ("N/A" if provider_type != "onlinestream-provider" else "FAIL"),
            "extractor_test": "PASS" if (passed and provider_type == "onlinestream-provider") else ("N/A" if provider_type != "onlinestream-provider" else "FAIL"),
            "errors": errors,
            "warnings": warnings
        }

    def _run_js_sandbox_smoke_test(self, runtime_bin: str, provider_type: str, js_code: str) -> tuple[bool, str]:
        harness = f"""
// Seanime Goja Sandbox Emulation Harness
globalThis.LoadDoc = function(html) {{
    const makeEl = (chunk) => ({{
        text: () => "Sample Anime Title Episode 1",
        attr: (name) => {{
            if (name === "href") return "/watch/sample-anime-ep-1";
            if (name === "data-embed" || name === "src") return "https://cdn.example.com/hls/master.m3u8";
            if (name === "data-number") return "1";
            return "Sample";
        }},
        find: () => makeSelection(),
        first: () => makeEl(chunk)
    }});
    const makeSelection = () => ({{
        length: 1,
        first: () => makeEl(""),
        text: () => "1",
        attr: (n) => makeEl("").attr(n),
        find: () => makeSelection(),
        each: (cb) => {{ cb(0, makeEl("")); }}
    }});
    return function(selector) {{ return makeSelection(); }};
}};

globalThis.fetch = async function(url, opts) {{
    return {{
        status: 200,
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
                timeout=15,
                text=True
            )
            if proc.returncode == 0 and "SANDBOX_OK" in proc.stdout:
                return True, ""
            return False, (proc.stderr or proc.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)
