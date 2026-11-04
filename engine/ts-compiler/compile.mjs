// TypeScript -> ES2020 JavaScript emitter for Seanime Goja extensions.
// Uses the real TypeScript compiler API (transpileModule) instead of hand-written
// string surgery. Invoked by engine/ts-compiler/compiler.py, which sets NODE_PATH
// so `require("typescript")` resolves from the repository's node_modules.
//
// Usage: node compile.mjs <file.ts> [more.ts ...]
// Writes <file.js> next to each input. Exit codes: 0 ok, 2 syntax diagnostics, 3 typescript missing.

import { readFileSync, writeFileSync } from "fs";
import { createRequire } from "module";

const require = createRequire(import.meta.url);

let ts;
try {
    ts = require("typescript");
} catch (err) {
    console.error("TYPESCRIPT_NOT_INSTALLED");
    process.exit(3);
}

const files = process.argv.slice(2);
if (files.length === 0) {
    console.error("usage: node compile.mjs <file.ts> [...]");
    process.exit(1);
}

let failed = 0;

for (const file of files) {
    const source = readFileSync(file, "utf8");
    const result = ts.transpileModule(source, {
        fileName: file,
        reportDiagnostics: true,
        compilerOptions: {
            target: ts.ScriptTarget.ES2020,
            module: ts.ModuleKind.None,
            removeComments: false,
            newLine: ts.NewLineKind.LineFeed,
            alwaysStrict: false,
        },
    });

    const diagnostics = (result.diagnostics || []).filter((d) => d.category === ts.DiagnosticCategory.Error);
    if (diagnostics.length > 0) {
        failed += 1;
        for (const d of diagnostics) {
            const pos = d.file && d.start !== undefined
                ? `${file}:${d.file.getLineAndCharacterOfPosition(d.start).line + 1}`
                : file;
            console.error(`${pos}: ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`);
        }
        continue;
    }

    writeFileSync(file.replace(/\.ts$/, ".js"), result.outputText, "utf8");
}

process.exit(failed > 0 ? 2 : 0);
