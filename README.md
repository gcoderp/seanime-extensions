# Cloudstream `.cs3` to Seanime TypeScript/Goja Universal Converter

An automated reverse-engineering, AST reconstruction, and code-generation pipeline that converts compiled **Cloudstream `.cs3` extensions** into native, validated **Seanime TypeScript (`.ts`) and Goja JavaScript (`.js`) extensions**.

## Key Features
1. **Zero-Touch GitHub Actions Pipeline:** Add any Cloudstream `repo.json` URL to `config/repositories.json` and push. GitHub Actions discovers `plugins.json`, downloads `.cs3` archives, converts them, validates them in a Goja sandbox, and updates `marketplace.json`.
2. **4-Tier Logic Recovery & Decompilation Engine:**
   - **Strategy 1 (`engine/source-discovery/`):** Recovers original Kotlin source code from embedded `.cs3` sources or upstream GitHub repositories (`MainAPI` verification).
   - **Strategy 2 (`engine/dex-analyzer/`):** Decompiles `classes.dex` via JADX CLI into Java AST and reconstructs scraper selectors, endpoints, and headers.
   - **Strategy 3 (`engine/smali-analyzer/`):** Native Dalvik `.dex` binary string/method-table parser and Smali instruction analyzer fallback when JADX fails on complex Kotlin coroutines.
   - **Strategy 4 (`config/settings.json`):** Optional AI-assisted AST repair via `OPENAI_API_KEY` secret with strict Goja validation.
3. **Seanime Goja Compatibility Layer (`seanime/compatibility/cloudstream-runtime-shim.ts`):**
   - Pure-TypeScript `p,a,c,k,e,r` script unpacker (no `eval()`), multi-mirror domain auto-failover (`CsCompat.fetchWithMirrorFallback`), URL normalization, and multi-host video extraction (`ExtractorDispatcher`).
4. **Atomic Rollback Protection (`engine/seanime-generator/`):**
   - Never overwrites a previously working extension if an upstream `.cs3` update fails validation.

## Seanime Marketplace URL
```text
https://raw.githubusercontent.com/OWNER/cloudstream-seanime-converter/main/marketplace.json
```
