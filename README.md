# Cloudstream `.cs3` → Seanime TypeScript converter

Converts compiled Cloudstream `.cs3` extension packages into Seanime extensions
(`code.ts`, compiled `code.js`, `manifest.json`, `metadata.json`, `conversion-report.json`)
and maintains a Seanime marketplace index.

**Status: 2.5.0 — pipeline is honest, coverage is still limited.** Read
[FIXES.md](FIXES.md) for exactly what changed in this version and what is still missing.
Nothing is published as "working" without a live end-to-end test; the marketplace only
contains bundles that passed every automated gate, and each bundle carries its
`live_test_status`.

## How it works

```
config/repositories.json
        │  discover.py ── repo.json → plugins.json → CloudstreamPluginEntry
        ▼
   download .cs3 (SHA-256 verified, SSRF-guarded, size/zip-bomb limits)
        ▼
   extract (ZIP-slip guarded) ── manifest.json, classes.dex, embedded .kt
        ▼
   strategy 1: embedded / upstream Kotlin source          ← real logic
   strategy 2: JADX decompiled Java AST                   ← real logic
   strategy 3: DEX string-pool heuristics                 ← guesses, never published
        ▼
   AST model (base URL, search pattern, selectors, servers, headers)
        ▼
   translate → TypeScript (token-substituted templates, never f-strings)
        ▼
   compile → ES2020 JavaScript with the real TypeScript compiler
        ▼
   validate → FAILED / NEEDS_REVIEW / SUCCESS
        ▼
   bundle + conversion report + marketplace.json
```

## Validation statuses

| Status | Meaning | Published |
| --- | --- | --- |
| `SUCCESS` | Parses, contract-complete, no placeholder data, known licence, provider-specific selectors | yes |
| `NEEDS_REVIEW` | Parses but is not trustworthy: strategy 3 only, placeholder base URL, generic selectors, unknown licence, unconfigured owner | no |
| `FAILED` | Does not parse, breaks the provider contract, or hits a forbidden API | no |

`NEEDS_REVIEW` bundles are still written to `src/` with a full report, so a human can
inspect and fix them. A previously published bundle is never overwritten by a failing
conversion.

## Commands

```bash
npm ci                                   # TypeScript compiler (required)
pip install -r requirements.txt

python3 scripts/discover.py              # list plugins from configured repositories
python3 scripts/convert.py               # live: download + convert real .cs3 packages
python3 scripts/convert.py --fixtures    # offline: convert tests/fixtures/*.cs3
python3 scripts/convert.py --only Anichi --limit 1

node scripts/validate.mjs                # every code.js parses, marketplace consistent
python3 scripts/check_schema.py          # manifest + metadata + marketplace schema
node scripts/typecheck.mjs               # type-check each extension individually
python3 -m pytest tests/ -q              # 15 tests
python3 scripts/publish.py --push        # commit validated output
```

## Setup (one line)

`config/settings.json` → `github_owner` / `github_repo` control the `raw.githubusercontent.com`
URLs inside every manifest. It is currently set to `ghanshyam501cg` (assumed from your
account — change it if your GitHub handle differs). In GitHub Actions the owner is taken
from `GITHUB_REPOSITORY` automatically, so CI needs no editing. While the owner is still
the literal `OWNER`, bundles are forced to `NEEDS_REVIEW` and never published.

Then add the marketplace to Seanime:

```text
https://raw.githubusercontent.com/<owner>/<repo>/main/marketplace.json
```

## GitHub Actions

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `convert.yml` | push to config/engine, manual, weekly | discover → download → convert → validate → publish |
| `update.yml` | daily | re-check upstream versions, reprocess only what changed |
| `validate.yml` | PR, push to main, manual | tests, type-check, parse check, schema, fixture rebuild |
| `publish.yml` | manual (typed confirmation) | re-validate then commit; never converts |

Conversion runs with a read-only token in one job; only the separate publish job holds
`contents: write`, so third-party `.cs3` content is never executed next to a write token.

## Known limitations

- **Strategy 3 is not real reconstruction.** When neither embedded Kotlin nor JADX output
  is available, only the DEX string pool is usable. Selectors and URLs are then guesses.
  These conversions are always `NEEDS_REVIEW`.
- **No live site testing yet.** `live_test_status` is always `NOT_RUN`. The mock harness
  proves the code parses and its contract is reachable — not that the selectors match the
  live HTML. That is the single biggest gap.
- **No AI-assisted repair** (`ai_fallback` is disabled and unimplemented).
- Torrent row parsing is heuristic and tracker-specific.
