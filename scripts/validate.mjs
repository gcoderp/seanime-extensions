#!/usr/bin/env node
// Repository artifact validator.
//   1. every generated code.js must parse under Node (same grammar family as Goja)
//   2. every manifest.json must be complete and point at its own code.js
//   3. marketplace.json must be a de-duplicated subset of src/ and must only contain
//      extensions whose conversion-report says SUCCESS
// Exit code 1 on any failure.

import { readFileSync, readdirSync, statSync, existsSync } from "fs";
import { join } from "path";
import { execFileSync } from "child_process";

const ROOT = process.cwd();
const PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"];
const errors = [];

const walkExtensions = () => {
    const found = [];
    for (const type of PROVIDER_TYPES) {
        const dir = join(ROOT, "src", type);
        if (!existsSync(dir)) continue;
        for (const name of readdirSync(dir)) {
            const extDir = join(dir, name);
            if (!statSync(extDir).isDirectory()) continue;
            found.push({ type, name, dir: extDir });
        }
    }
    return found;
};

const extensions = walkExtensions();
let parsedCount = 0;

for (const ext of extensions) {
    const jsPath = join(ext.dir, "code.js");
    const manifestPath = join(ext.dir, "manifest.json");

    if (!existsSync(jsPath)) {
        errors.push(`${ext.type}/${ext.name}: missing code.js`);
        continue;
    }

    try {
        execFileSync(process.execPath, ["--check", jsPath], { stdio: "pipe" });
        parsedCount++;
    } catch (err) {
        const msg = String(err.stderr || err.message).split("\n").slice(0, 2).join(" ");
        errors.push(`${ext.type}/${ext.name}: code.js does not parse -- ${msg.trim()}`);
    }

    if (!existsSync(manifestPath)) {
        errors.push(`${ext.type}/${ext.name}: missing manifest.json`);
        continue;
    }

    let manifest;
    try {
        manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    } catch (err) {
        errors.push(`${ext.type}/${ext.name}: manifest.json is not valid JSON`);
        continue;
    }

    for (const key of ["id", "name", "manifestURI", "payloadURI", "version", "type", "language", "lang"]) {
        if (!manifest[key]) errors.push(`${ext.type}/${ext.name}: manifest missing "${key}"`);
    }
    if (manifest.type && manifest.type !== ext.type) {
        errors.push(`${ext.type}/${ext.name}: manifest type "${manifest.type}" does not match its directory`);
    }
    if (manifest.payloadURI && !String(manifest.payloadURI).endsWith("/code.js")) {
        errors.push(`${ext.type}/${ext.name}: payloadURI must end with /code.js`);
    }
    if (manifest.version && !/^\d+\.\d+\.\d+$/.test(String(manifest.version))) {
        errors.push(`${ext.type}/${ext.name}: version "${manifest.version}" is not semver`);
    }
}

// ---------------------------------------------------------------- marketplace
const marketplacePath = join(ROOT, "marketplace.json");
if (!existsSync(marketplacePath)) {
    errors.push("marketplace.json is missing at the repository root");
} else {
    const marketplace = JSON.parse(readFileSync(marketplacePath, "utf8"));
    if (!Array.isArray(marketplace)) {
        errors.push("marketplace.json must be a JSON array");
    } else {
        const seen = new Set();
        for (const item of marketplace) {
            if (!item.id || !item.name || !item.manifestURI || !item.payloadURI || !item.type) {
                errors.push(`marketplace entry incomplete: ${JSON.stringify(item).slice(0, 120)}`);
                continue;
            }
            if (seen.has(item.id)) errors.push(`duplicate marketplace id: ${item.id}`);
            seen.add(item.id);

            if (String(item.manifestURI).includes("/OWNER/")) {
                errors.push(`${item.id}: manifestURI still contains the OWNER placeholder -- set github_owner in config/settings.json`);
            }

            // Resolve by payloadURI first: two provider types can produce the same id, and
            // matching on id alone used to check a different bundle than the one published.
            const manifestOf = (e) => {
                const mPath = join(e.dir, "manifest.json");
                return existsSync(mPath) ? JSON.parse(readFileSync(mPath, "utf8")) : null;
            };
            const ext = extensions.find((e) => {
                const m = manifestOf(e);
                return m && m.payloadURI && m.payloadURI === item.payloadURI;
            }) || extensions.find((e) => {
                const m = manifestOf(e);
                return m && m.id === item.id;
            });
            if (!ext) {
                errors.push(`${item.id}: published in marketplace but no matching extension under src/`);
                continue;
            }
            const reportPath = join(ext.dir, "conversion-report.json");
            if (existsSync(reportPath)) {
                const report = JSON.parse(readFileSync(reportPath, "utf8"));
                if (report.overall_status !== "SUCCESS") {
                    errors.push(`${item.id}: published although its conversion report says ${report.overall_status}`);
                }
            } else {
                errors.push(`${item.id}: published without a conversion-report.json`);
            }
        }
    }
}

if (errors.length > 0) {
    console.error(`Validation failed with ${errors.length} problem(s):`);
    for (const e of errors) console.error(`  - ${e}`);
    process.exit(1);
}

console.log(`Validated ${extensions.length} extension bundle(s); ${parsedCount} code.js file(s) parse; marketplace OK.`);
