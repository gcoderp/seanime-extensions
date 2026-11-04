#!/usr/bin/env node
// Type-checks every generated extension TypeScript file individually.
//
// Why individually: each extension declares a global `class Provider` (that is what the
// Seanime Goja loader expects), so type-checking them in one program reports bogus
// "duplicate identifier" errors. Each file is its own compilation unit here.

import { readdirSync, statSync, existsSync } from "fs";
import { join } from "path";
import { execFileSync } from "child_process";

const ROOT = process.cwd();
const PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"];
const TSC = join(ROOT, "node_modules", "typescript", "bin", "tsc");

if (!existsSync(TSC)) {
    console.error("typescript is not installed. Run: npm ci");
    process.exit(1);
}

const files = [];
for (const type of PROVIDER_TYPES) {
    const dir = join(ROOT, "src", type);
    if (!existsSync(dir)) continue;
    for (const name of readdirSync(dir)) {
        const file = join(dir, name, "code.ts");
        if (statSync(join(dir, name)).isDirectory() && existsSync(file)) files.push(file);
    }
}

let failed = 0;
for (const file of files) {
    try {
        execFileSync(process.execPath, [
            TSC,
            "--noEmit",
            "--strict",
            "--skipLibCheck",
            "--target", "ES2020",
            "--lib", "ES2020,DOM",
            file,
        ], { stdio: "pipe" });
    } catch (err) {
        failed++;
        const out = String(err.stdout || err.stderr || err.message).trim();
        console.error(`\n${file.replace(ROOT + "/", "")}:`);
        console.error(out.split("\n").slice(0, 12).join("\n"));
    }
}

if (files.length === 0) {
    console.log("No extension TypeScript files found.");
} else if (failed > 0) {
    console.error(`\nType-check failed for ${failed}/${files.length} extension(s).`);
    process.exit(1);
} else {
    console.log(`Type-checked ${files.length} extension(s) successfully.`);
}
