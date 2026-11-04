# FIXES — 2.4.0 → 2.5.0

Every item below was reproduced against the uploaded ZIP before it was changed, and
re-checked afterwards. Nothing here is a rewrite for its own sake: the goal was to make
the pipeline produce loadable, honest output and to make failures visible.

## 1. The generated JavaScript did not parse (all 3 of 3 files)

`transpile_ts_to_goja_js` stripped TypeScript types with six regexes. Rule 6 listed
`string\[\]` before `string` but ended with `\b`; there is no word boundary between `]`
and `,`, so the engine backtracked to the bare `string` alternative and deleted only that,
leaving `domains[],` in the output. `node --check` failed on all three bundles, so no
Seanime/Goja runtime could load them — while every `conversion-report.json` claimed
`SUCCESS`.

- Removed the transpiler entirely. `engine/ts-compiler/` now drives the real TypeScript
  compiler (`ts.transpileModule`, target ES2020, module none) through
  `engine/ts-compiler/compile.mjs`.
- `scripts/convert.py` refuses to continue if compilation fails, and the validator adds
  `node --check` as a hard gate.
- Result: 3/3 bundles parse. `npm run typecheck` style checks run per file (each extension
  declares a global `class Provider`, so one shared program reports bogus duplicate
  identifiers — that was a real false alarm in the old setup).

## 2. f-strings were corrupting generated regexes

`translator.py` built the extension source with f-strings, so any `{n}` quantifier inside
a regex was interpolated as a format field. The magnet hash matcher shipped as
`/btih:([a-fA-F0-9]40|[a-zA-Z2-7]32)/i` — no hash was ever extracted.

- Templates are now real files (`seanime/templates/*.ts`) filled by token substitution
  (`__TOKEN__`), with an assertion that no token survives substitution.
- The magnet regex is correct again (`{40}` / `{32}`), and a regression test asserts the
  quantifiers survive code generation.

## 3. The stream extractor could never match a URL

In `extractors.py` the media regex was emitted as `/(https?:\?\/\?\/…)/gi` (`\?` is an
escaped literal `?`), and `m[1].replace(/\\//g, "/")` parsed as *regex divided by an
undefined identifier `g`*. Two escaping bugs, both fatal, both invisible to the old
validator.

- Both fixed (`https?:\/\/`, `.replace(/\\\//g, "/")`); regression test asserts the emitted
  pattern.
- Also: `fetch` failures and 4xx/5xx responses now return an empty source list instead of
  being parsed as HTML; packer unpacking no longer appends the packed script to itself.

## 4. Validation said SUCCESS for extensions that could not work

The HiAnime bundle pointed at `https://example.com` with all-generic selectors and still
reported `SUCCESS` / `PASS` on search, episodes and extractors. The mock harness returns
`"Sample Anime Title"` for *any* selector, so it could only prove "the code runs".

- Three outcomes now: `FAILED` (hard gates), `NEEDS_REVIEW` (soft gates), `SUCCESS`.
- New soft gates: placeholder host, all-generic selectors, unknown licence,
  `STRATEGY_3` string-pool reconstruction, unconfigured `github_owner`.
- `live_test_status` is reported honestly as `NOT_RUN`, and the report says so.
- Removed the naive brace counter: it flagged any regex containing a literal `}` (such as
  `/btih:[a-f0-9]{40}/`) as unbalanced. `node --check` is the authoritative parse gate.
- Removed the hardcoded `GPL-3.0` assumption in source discovery: licences are resolved
  through the GitHub licence API and cached in `config/license-cache.json`. `UNKNOWN` is
  no longer on the redistribution allowlist, so unlicensed upstreams cannot be published.

Current triage of the three sample bundles: `gogo-anime-provider` and
`nyaa-torrent-provider` publish; `hi-anime-provider` is held in `reports/needs-review.json`
with the reason recorded.

## 5. Discovery was never wired to conversion

`scripts/convert.py` read `tests/fixtures/plugins.json` unconditionally and never touched
the downloader or `discover.py`; the ZIP also contained no `.cs3` fixtures, so the pipeline
could not run at all (1 failing test).

- `convert.py` now runs live by default: discover → download (SHA-256 verified) → extract →
  convert. `--fixtures` is opt-in, plus `--limit`, `--only`, `--skip-download`.
- The downloader is actually used, including its cache (unchanged version + hash = skip).
- `tests/fixtures/build_fixtures.py` builds three synthetic `.cs3` packages so the offline
  path is reproducible; the missing-fixture test failure is gone.
- **Both configured repository URLs were dead** (`recloudstream/cloudstream-extensions` does
  not exist; the hexated `repo.json` path 404s). Replaced with two verified sources, and
  `discover.py` now accepts a direct `plugins.json` URL. Verified: 74 plugins discovered.

## 6. GitHub Actions and publishing were missing

- Added `convert.yml`, `update.yml`, `validate.yml`, `publish.yml` (pinned action versions,
  explicit permissions, concurrency groups, workflow summaries).
- Conversion and publishing are separate jobs; only the publish job can write.
- `scripts/publish.py` now actually commits and pushes (dry-run unless `--push`) and
  re-runs the artifact checks first.

## 7. Smaller correctness fixes

- Base URL recovery: the first URL in a DEX string pool is usually a CDN or player host.
  It is now chosen by frequency with a non-site host blocklist, and `"http:"`-style noise is
  rejected. If nothing plausible is found the URL is left empty and the validator flags it.
- Mirror domains are filtered to the provider's own registrable domain; previously the
  "mirrors" were arbitrary strings from the DEX pool.
- Episode selector heuristics no longer pick the page `<h1>`; obvious title/poster
  selectors are separated from list selectors.
- DEX header parsing tolerates truncated/corrupt headers instead of raising
  `struct.error` and killing the plugin.
- `search()` dub handling is no longer an empty `if` block with a comment; it orders
  dub-tagged results first instead of dropping results.
- Nyaa: torrent dates/sizes are read from the row instead of being fabricated with
  `new Date()`; `infoHash` is only set from a real magnet; `confirmed` reflects whether a
  magnet exists.
- Local filesystem paths no longer leak into `metadata.json` / reports.
- Manifests and metadata record `validationStatus`, `liveTestStatus` and `reviewReasons`.
- `UNKNOWN_PUBLIC_REPO` removed from the licence allowlist; `security` and `licensing`
  settings are now actually read by the extractor and validator.

## Verified on a real package

`python3 scripts/convert.py --only Anichi --limit 1` downloaded a real 210 KB `.cs3` from
the Phisher repository, parsed its DEX, generated TypeScript, compiled it to
JavaScript that passes `node --check`, and returned `NEEDS_REVIEW` with three recorded
reasons (strategy 3 only, generic selectors, unknown upstream licence). That is the
correct outcome: the package ships no source and no JADX output was available, so the
scraper logic genuinely could not be recovered.

## 2.6.0 — AniList-driven matching

Seanime only speaks AniList. The previous `search()` used `opts.query` as-is, so a provider
returned whatever the site's own ranking produced: the wrong season, the wrong adaptation, or
a special. Every generated provider now resolves through `seanime/compatibility/anilist-resolver.ts`:

- `search()` queries by the AniList english → romaji → native title (max three requests,
  stopping at the first non-empty result) instead of the raw query.
- Results are ranked against every AniList title and synonym with a Dice coefficient over
  normalised tokens; `(Dub)`, `[1080p]`, `(TV)` qualifiers are stripped before comparison.
- Season/part markers are compared explicitly: a mismatch costs 0.2, a season-2+ match earns
  0.1, which stops "Season 2" resolving to the season 1 page.
- Year and format are tie-breakers only.
- `opts.dub` orders dub-tagged results first without dropping the subbed ones.
- Torrent providers query by the AniList title, then apply Seanime's episode/resolution
  filters in `smartSearch`.
- Five behavioural tests compile the resolver with the real TypeScript compiler and assert
  the ranking in Node (`tests/test_anilist.py`).

## Added after the first 2.5.0 drop

- **`scripts/reindex.py`** (`npm run reindex`): re-publishes existing bundles without
  re-downloading or re-converting. It rewrites every manifest/metadata URL to the configured
  owner, re-triages each bundle against the current licence policy, re-checks that each
  `code.js` parses, rewrites `reports/{successful,needs-review,failed}.json`, rebuilds
  `marketplace.json`, regenerates the README section and writes `manifest-urls.txt`.
- **`engine/seanime-generator/readme.py`**: generates the README block that lists every
  published extension with its `manifest.json` link, plus the marketplace URL and the
  install steps. It is delimited by `<!-- BEGIN GENERATED:EXTENSIONS -->` markers, so
  hand-written documentation above and below survives every run.
- **`licensing.unknown_license_policy`**: `hold` (default) or `publish_with_notice`. The
  second publishes conversions whose upstream declares no detectable licence and records a
  notice in the manifest, the metadata and the report.
- README generation is wired into `scripts/convert.py`, so a normal conversion run keeps the
  extension table current.
- The workflows and `publish.py` now commit `README.md` and `manifest-urls.txt` alongside
  `src/` and `marketplace.json`.

## Still missing (the honest list)

1. **Live testing.** No conversion is verified against a live site; `live_test_status` is
   always `NOT_RUN`. This is the highest-value next step — a Playground-style harness that
   runs search → episodes → streams against the real site and fails the bundle when the
   selectors return nothing.
2. **Real Kotlin → TypeScript translation.** Strategy 1 currently extracts a *structure*
   (URL, selectors, servers) and re-emits it through a template. Translating the actual
   `search`/`load`/`loadLinks` bodies (conditionals, pagination, POST payloads, crypto) is
   not implemented.
3. **Smali control-flow reconstruction.** Strategy 3 harvests strings only.
4. **AI-assisted repair.** Configured but unimplemented; it stays disabled.
5. Torrent parsing remains tracker-specific heuristics.
