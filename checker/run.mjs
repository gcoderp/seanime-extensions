#!/usr/bin/env node
/**
 * Seanime extension checker.
 *
 * Downloads every extension listed in a Seanime marketplace, runs it inside a
 * Seanime-compatible runtime, drives it with real AniList metadata (search -> episodes ->
 * stream) and writes `working-extensions.json` describing what actually works.
 *
 * Usage:
 *   node checker/run.mjs --marketplace https://raw.githubusercontent.com/OWNER/REPO/main/marketplace.json
 *   node checker/run.mjs --limit 20 --concurrency 6
 *   node checker/run.mjs --ids 154587,21            # explicit AniList IDs
 *   node checker/run.mjs --type all --verbose
 *
 * Exit code is 0 even when extensions fail: a broken provider is data, not a build error.
 * Pass --fail-on-empty to exit 1 when nothing works at all.
 */

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveTargets } from "./anilist.mjs";
import { createRuntime, loadProvider, assertContract, RUNTIME_VERSION } from "./runtime.mjs";
import { probeOnlinestream, probeTorrent } from "./probe.mjs";
import { buildReport, writeReport, toMarkdown } from "./report.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));

const DEFAULTS = {
    marketplace: "https://raw.githubusercontent.com/gcoderp/seanime-extensions/main/marketplace.json",
    out: "working-extensions.json",
    targetsFile: path.join(HERE, "targets.json"),
    concurrency: 4,
    limit: 0,
    type: "onlinestream-provider",
    dub: false,
    timeoutMs: 20000,
    extensionTimeoutMs: 150000,
    retries: 2,
    verbose: false,
    failOnEmpty: false,
};

function parseArgs(argv) {
    const opts = { ...DEFAULTS, ids: [] };
    for (let i = 0; i < argv.length; i += 1) {
        const arg = argv[i];
        const next = () => argv[++i];
        switch (arg) {
            case "--marketplace": opts.marketplace = next(); break;
            case "--out": opts.out = next(); break;
            case "--targets": opts.targetsFile = next(); break;
            case "--ids": opts.ids = String(next() || "").split(",").map((s) => s.trim()).filter(Boolean); break;
            case "--concurrency": opts.concurrency = Math.max(1, Number(next()) || 1); break;
            case "--limit": opts.limit = Math.max(0, Number(next()) || 0); break;
            case "--type": opts.type = next(); break;
            case "--timeout-ms": opts.timeoutMs = Math.max(1000, Number(next()) || 20000); break;
            case "--extension-timeout-ms": opts.extensionTimeoutMs = Math.max(5000, Number(next()) || 150000); break;
            case "--dub": opts.dub = true; break;
            case "--verbose": opts.verbose = true; break;
            case "--fail-on-empty": opts.failOnEmpty = true; break;
            case "--help":
            case "-h":
                console.log(`usage: node checker/run.mjs [options]

  --marketplace <url|file>   marketplace.json to check (default: this repo's raw URL)
  --out <file>               output report (default: working-extensions.json)
  --targets <file>           AniList target config (default: checker/targets.json)
  --ids 1,2,3                explicit AniList IDs, overrides the target config
  --type <type|all>          onlinestream-provider (default) | anime-torrent-provider | all
  --limit <n>                check at most n extensions
  --concurrency <n>          parallel extensions (default 4)
  --dub                      search for dubs
  --timeout-ms <n>           per network call (default 20000)
  --extension-timeout-ms <n> per extension ceiling (default 150000)
  --verbose                  log provider console output
  --fail-on-empty            exit 1 when no extension works`);
                process.exit(0);
                break;
            default:
                if (arg.startsWith("--")) {
                    console.error(`unknown option: ${arg}`);
                    process.exit(2);
                }
        }
    }
    return opts;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(url, { retries = 2, timeoutMs = 20000 } = {}) {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(url, {
                signal: controller.signal,
                redirect: "follow",
                headers: { "User-Agent": "seanime-extension-checker/1.0" },
            });
            if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
            return { json: await res.json(), text: null };
        } catch (err) {
            lastError = err;
            if (attempt < retries) await sleep(1000 * (attempt + 1));
        } finally {
            clearTimeout(timer);
        }
    }
    throw lastError || new Error(`failed to fetch ${url}`);
}

async function fetchText(url, { retries = 2, timeoutMs = 20000 } = {}) {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(url, {
                signal: controller.signal,
                redirect: "follow",
                headers: { "User-Agent": "seanime-extension-checker/1.0" },
            });
            if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
            return await res.text();
        } catch (err) {
            lastError = err;
            if (attempt < retries) await sleep(1000 * (attempt + 1));
        } finally {
            clearTimeout(timer);
        }
    }
    throw lastError || new Error(`failed to fetch ${url}`);
}

/** Seanime transpiles TypeScript payloads with esbuild; we use the repo's typescript devDependency. */
let tsModule = null;
async function transpileTypeScript(source) {
    if (tsModule === null) {
        try {
            tsModule = await import("typescript");
        } catch {
            tsModule = false;
        }
    }
    if (!tsModule) return null;
    const result = tsModule.transpileModule(source, {
        compilerOptions: {
            target: tsModule.ScriptTarget.ES2020,
            module: tsModule.ModuleKind.None,
            removeComments: false,
        },
    });
    return result.outputText;
}

function withCeiling(promise, ms, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms}ms`)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function checkExtension(entry, targets, opts) {
    const started = Date.now();
    const record = {
        id: entry.id,
        name: entry.name,
        type: entry.type,
        version: entry.version,
        manifestURI: entry.manifestURI,
        payloadURI: entry.payloadURI,
        status: "error",
        error: null,
        target: null,
        search: null,
        episodes: null,
        stream: null,
        torrent: null,
        durationMs: 0,
    };

    try {
        const payloadSource = await fetchText(entry.payloadURI, { retries: opts.retries, timeoutMs: opts.timeoutMs });
        let code = payloadSource;
        if (/\.ts(\?|$)/i.test(entry.payloadURI) || entry.language === "typescript" && !/\.js(\?|$)/i.test(entry.payloadURI)) {
            const transpiled = await transpileTypeScript(payloadSource);
            if (transpiled === null) {
                record.status = "unsupported_payload";
                record.error = "TypeScript payload and the typescript package is not installed (run npm ci)";
                record.durationMs = Date.now() - started;
                return record;
            }
            code = transpiled;
        }

        const { runtime, values, logs } = createRuntime({
            providerId: entry.id,
            manifest: entry,
            timeoutMs: opts.timeoutMs,
            log: opts.verbose ? (level, line) => console.log(`  [${entry.id}:${level}] ${line}`) : undefined,
        });

        let ProviderClass;
        try {
            ProviderClass = loadProvider(code, values);
        } catch (err) {
            record.status = "load_error";
            record.error = String(err && err.message ? err.message : err).slice(0, 300);
            record.durationMs = Date.now() - started;
            return record;
        }

        const provider = new ProviderClass();
        try {
            assertContract(provider, entry.type);
        } catch (err) {
            record.status = "contract_error";
            record.error = String(err && err.message ? err.message : err).slice(0, 300);
            record.durationMs = Date.now() - started;
            return record;
        }

        // Try each AniList target until one works: a provider that only covers one genre is
        // still working, it just does not have the first title we tried.
        let lastResult = null;
        for (const target of targets) {
            const result = entry.type === "anime-torrent-provider"
                ? await probeTorrent(provider, target)
                : await probeOnlinestream(provider, target, { dub: opts.dub });

            lastResult = result;
            if (result.status === "working") break;
            if (opts.verbose) console.log(`  [${entry.id}] ${target.title}: ${result.status}`);
        }

        Object.assign(record, lastResult || {});
        if (logs.some((l) => l.level === "error")) {
            record.providerErrors = logs.filter((l) => l.level === "error").map((l) => l.line).slice(0, 3);
        }
    } catch (err) {
        record.status = "error";
        record.error = String(err && err.message ? err.message : err).slice(0, 300);
    }

    record.durationMs = Date.now() - started;
    return record;
}

async function main() {
    const opts = parseArgs(process.argv.slice(2));
    const startedAt = new Date().toISOString();

    const targetsConfig = JSON.parse(await readFile(opts.targetsFile, "utf8"));
    let targets;
    try {
        targets = await resolveTargets(targetsConfig, { ids: opts.ids });
    } catch (err) {
        console.error(`Failed to resolve AniList targets: ${err.message}`);
        process.exit(2);
    }
    if (targets.length === 0) {
        console.error("No AniList targets resolved.");
        process.exit(2);
    }
    console.log(`AniList targets: ${targets.map((t) => `${t.title} (${t.anilistId})`).join(", ")}`);

    let marketplace;
    if (/^https?:\/\//i.test(opts.marketplace)) {
        const { json } = await fetchJson(opts.marketplace, { timeoutMs: opts.timeoutMs });
        marketplace = json;
    } else {
        marketplace = JSON.parse(await readFile(opts.marketplace, "utf8"));
    }
    if (!Array.isArray(marketplace)) {
        console.error("marketplace must be a JSON array");
        process.exit(2);
    }

    const types = opts.type === "all"
        ? ["onlinestream-provider", "anime-torrent-provider"]
        : [opts.type];
    let entries = marketplace.filter((e) => types.includes(e.type) && e.manifestURI && e.payloadURI);
    if (opts.limit > 0) entries = entries.slice(0, opts.limit);

    console.log(`Checking ${entries.length} extension(s) of type ${types.join(", ")}`);
    if (entries.length === 0) {
        console.error("Nothing to check.");
        process.exit(2);
    }

    const results = [];
    let cursor = 0;
    let done = 0;

    const worker = async () => {
        while (cursor < entries.length) {
            const entry = entries[cursor];
            cursor += 1;
            let record;
            try {
                record = await withCeiling(checkExtension(entry, targets, opts), opts.extensionTimeoutMs, "extension check");
            } catch (err) {
                record = {
                    id: entry.id,
                    name: entry.name,
                    type: entry.type,
                    version: entry.version,
                    manifestURI: entry.manifestURI,
                    payloadURI: entry.payloadURI,
                    status: "timeout",
                    error: String(err && err.message ? err.message : err).slice(0, 300),
                    durationMs: opts.extensionTimeoutMs,
                };
            }
            results.push(record);
            done += 1;
            const seconds = (record.durationMs / 1000).toFixed(1);
            console.log(`[${String(done).padStart(String(entries.length).length)}/${entries.length}] ${record.status.padEnd(18)} ${record.id} (${seconds}s)`);
        }
    };

    await Promise.all(Array.from({ length: Math.min(opts.concurrency, entries.length) }, worker));

    const finishedAt = new Date().toISOString();
    const report = buildReport({
        marketplaceUrl: opts.marketplace,
        targets,
        results,
        startedAt,
        finishedAt,
        runtimeVersion: RUNTIME_VERSION,
        options: { types, dub: opts.dub, targetMode: opts.ids.length > 0 ? "ids" : targetsConfig.mode || "queries" },
    });

    const outPath = path.resolve(opts.out);
    await writeReport(outPath, report);

    const markdown = toMarkdown(report);
    console.log("");
    console.log(markdown);
    console.log(`\nWrote ${outPath} (${report.summary.working}/${report.summary.checked} working)`);

    if (process.env.GITHUB_STEP_SUMMARY) {
        const { appendFile } = await import("node:fs/promises");
        await appendFile(process.env.GITHUB_STEP_SUMMARY, `${markdown}\n`);
    }

    if (opts.failOnEmpty && report.summary.working === 0) {
        console.error("No extension worked.");
        process.exit(1);
    }
}

main().catch((err) => {
    console.error(err && err.stack ? err.stack : err);
    process.exit(1);
});
