# Extension checker

Downloads every extension published in a Seanime marketplace, runs it inside a
Seanime-compatible runtime, drives it with real AniList metadata, and writes
`working-extensions.json` with the verdict.

This answers the question the converter cannot: **does the extension actually work in
Seanime?** The converter proves an extension compiles and satisfies the provider contract.
The checker proves a search finds the right show, that show has episodes, an episode yields a
playable URL, and that URL responds.

## What it does per extension

```
marketplace.json
   -> manifest / payload (code.js or a .ts payload, transpiled with the repo's TypeScript)
   -> load into a function scope whose parameters are Seanime's globals
        fetch, LoadDoc, Doc, console, $sleep, $getUserPreference,
        $isOffline, $toString, CryptoJS, $scannerUtils, Buffer
   -> getSettings()          contract shape check
   -> search({ media, query, dub, year })     with real AniList metadata
   -> findEpisodes(best.id)                   picks the AniList match, not result[0]
   -> findEpisodeServer(episode, "default")
   -> GET the video URL                       HLS must return a real #EXTM3U manifest
```

Torrent providers take the other branch: `search` → `getTorrentMagnetLink` /
`getTorrentInfoHash`, and "working" means a usable magnet or a valid info hash.

## Fidelity to the app

The runtime mirrors Seanime's own source rather than an idealised API:

| Behaviour | Source of truth |
| --- | --- |
| `Media` is flattened (`romajiTitle`, `englishTitle`, `synonyms`, `startDate`) | `internal/extension/hibike/onlinestream/types.go` |
| `LoadDoc(html)` returns a **function**, not a selection object | `internal/goja/goja_bindings/document.go` |
| `year` is top-level on `SearchOptions` | same file, `SearchOptions` |
| `VideoSourceType` is `mp4 \| m3u8 \| unknown` — no `dash` | `goja_onlinestream_test/onlinestream-provider.d.ts` |
| Synonyms passed to providers are only the ones containing a season marker | `GetSynonymsContainingSeason()` |
| Torrent providers must implement `getLatest()` | `internal/extension_repo/goja_anime_torrent_provider.go` |
| TypeScript payloads are transpiled before running | `internal/extension_repo/goja.go` (esbuild) |

`checker/lib/` vendors the dependency-free compatibility modules from
`seanime-api-netlify` (`compat-document`, `compat-crypto`, `compat-buffer`,
`compat-scanner-utils`) so the HTML adapter matches the one already used in production.

## Usage

```bash
node checker/run.mjs                       # check this repository's marketplace
node checker/run.mjs --limit 20 --concurrency 6
node checker/run.mjs --ids 154587,21       # pin specific AniList IDs
node checker/run.mjs --type all --verbose  # include torrent providers
node checker/selftest.mjs                  # offline harness test (no network)
```

`npm ci` first: the TypeScript package is used to transpile `.ts` payloads, the same job
esbuild does inside Seanime.

## AniList targets

`checker/targets.json` decides which media each extension is tested against. By default it
resolves targets live from AniList — no hardcoded IDs to go stale:

```json
{ "mode": "anilist", "queries": [ { "name": "trending", "sort": ["TRENDING_DESC"], "perPage": 3 } ] }
```

To pin IDs instead:

```json
{ "mode": "ids", "ids": [154587, 21, 151807] }
```

or pass `--ids 154587,21` on the command line, or the `ids` input on the workflow. Titles,
synonyms, year and format are always resolved from AniList, so a wrong ID fails loudly at the
start of the run instead of silently testing nothing.

Each extension is tried against every target until one works — a provider that covers only
one genre is still working, it just does not have the first title we tried.

## Output

`working-extensions.json`:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-11-04T09:12:44.000Z",
  "marketplace": "https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/marketplace.json",
  "runtime": "seanime-goja-compat/1",
  "targets": [{ "anilistId": 154587, "title": "Sousou no Frieren", "year": 2023 }],
  "summary": { "checked": 291, "working": 42, "failed": 249, "byStatus": { "working": 42, "no_search_results": 180 } },
  "working": [{ "id": "gogo-anime-provider", "matchedTitle": "Sousou no Frieren", "stream": { "source": { "url": "https://…", "type": "m3u8", "quality": "1080p" } } }],
  "failed": [{ "id": "…", "status": "no_search_results", "error": null }],
  "results": []
}
```

Statuses: `working`, `no_search_results`, `no_episodes`, `no_stream`, `stream_unreachable`,
`no_magnet`, `contract_error`, `load_error`, `unsupported_payload`, `search_error`,
`episodes_error`, `stream_error`, `torrent_error`, `timeout`, `error`.

The run exits 0 even when most extensions fail — a broken provider is data, not a build
error. Pass `--fail-on-empty` if you want CI to fail when nothing works.

## Workflow

`.github/workflows/checker.yml` runs daily at 09:00 UTC (after `update.yml`) or on demand,
then commits `working-extensions.json` with a message like
`chore(checker): 42/291 extensions verified against AniList`. It never converts and never
writes to `src/`.

## Known limits

- `$torrentUtils` is not implemented; a provider that calls it reports an error rather than a
  false pass.
- Only the first three video sources per episode are probed.
- A site that blocks datacentre IPs will fail here and may still work for a home user.
- `liveTestStatus` in the conversion reports is separate: the checker's verdict lives in
  `working-extensions.json`.
