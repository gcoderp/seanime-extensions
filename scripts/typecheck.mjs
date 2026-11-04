#!/usr/bin/env node
// Type-checks every generated extension against seanime/types/seanime-env.d.ts.
//
// Two things this script does deliberately:
//
// 1. Each extension is its own compilation unit. Every bundle declares a global
//    `class Provider` (that is what Seanime's Goja loader expects), so compiling them in one
//    program reports bogus "duplicate identifier" errors.
//
// 2. It drives the TypeScript compiler API in this process instead of spawning `tsc` per
//    file. Spawning cost ~0.8s per bundle, so a 380-bundle repo took five minutes and the
//    CI job looked hung. The lib and .d.ts files are parsed once and shared across programs,
//    which brings the same work down to a few seconds.
//
// Exit code 1 on any error. When the failures match a known stale-contract signature it
// prints the command that fixes them in place.

import { readdirSync, statSync, existsSync } from "fs";
import { join } from "path";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const ROOT = process.cwd();
const PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"];

let ts;
try {
    ts = require("typescript");
} catch {
    console.error("typescript is not installed. Run: npm ci");
    process.exit(1);
}

const files = [];
for (const type of PROVIDER_TYPES) {
    const dir = join(ROOT, "src", type);
    if (!existsSync(dir)) continue;
    for (const name of readdirSync(dir).sort()) {
        const extDir = join(dir, name);
        const file = join(extDir, "code.ts");
        if (statSync(extDir).isDirectory() && existsSync(file)) files.push(file);
    }
}

if (files.length === 0) {
    console.log("No extension TypeScript files found.");
    process.exit(0);
}

const options = {
    noEmit: true,
    strict: true,
    skipLibCheck: true,
    target: ts.ScriptTarget.ES2020,
    lib: ["lib.es2020.d.ts", "lib.dom.d.ts"],
    types: [],
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    module: ts.ModuleKind.ESNext,
    allowJs: false,
    noResolve: false,
};

// Parse lib.d.ts / the Seanime env types once and reuse them for every program.
const host = ts.createCompilerHost(options, true);
const sourceCache = new Map();
const originalGetSourceFile = host.getSourceFile.bind(host);
host.getSourceFile = (fileName, languageVersion, onError, shouldCreateNewSourceFile) => {
    const key = `${fileName}|${languageVersion}`;
    if (!sourceCache.has(key)) {
        sourceCache.set(key, originalGetSourceFile(fileName, languageVersion, onError, shouldCreateNewSourceFile));
    }
    return sourceCache.get(key);
};

const STALE_CONTRACT_PATTERNS = [
    "Property 'year' does not exist on type 'Media'",
    "is not assignable to type 'VideoSourceType'",
    "Property 'isBestRelease' is missing",
];

function formatDiagnostic(diagnostic) {
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
    if (!diagnostic.file || diagnostic.start === undefined) {
        return `error TS${diagnostic.code}: ${message}`;
    }
    const { line, character } = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start);
    return `${diagnostic.file.fileName}(${line + 1},${character + 1}): error TS${diagnostic.code}: ${message}`;
}

let failed = 0;
const staleBundles = [];
const startedAt = Date.now();

for (const file of files) {
    const program = ts.createProgram({ rootNames: [file], options, host });
    const errors = ts.getPreEmitDiagnostics(program)
        .filter((d) => d.category === ts.DiagnosticCategory.Error)
        .map(formatDiagnostic);

    if (errors.length === 0) continue;

    failed += 1;
    if (STALE_CONTRACT_PATTERNS.some((pattern) => errors.some((e) => e.includes(pattern)))) {
        staleBundles.push(file.replace(ROOT + "/", ""));
    }
    console.error(`\n${file.replace(ROOT + "/", "")}:`);
    console.error(errors.slice(0, 12).join("\n"));
}

const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);

if (failed === 0) {
    console.log(`Type-checked ${files.length} extension(s) successfully in ${seconds}s.`);
    process.exit(0);
}

console.error(`\nType-check failed for ${failed}/${files.length} extension(s) in ${seconds}s.`);
if (staleBundles.length > 0) {
    console.error(
        `\n${staleBundles.length} of them were generated against an older Seanime contract ` +
        `(media.year, VideoSourceType "dash", missing isBestRelease).\n` +
        `They are stale artifacts, not new bugs. They are upgraded automatically by any ` +
        `conversion run, or on demand:\n\n    python3 scripts/convert.py --fixtures\n` +
        `    python3 scripts/migrate-contract.py\n`
    );
}
process.exit(1);
