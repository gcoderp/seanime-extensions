// Bun / TypeScript build verifier & compiler for Seanime extensions
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";
import ts from "typescript";

const SRC_ROOT = join(process.cwd(), "src");
const PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"];

let compiledCount = 0;

for (const pType of PROVIDER_TYPES) {
    const dir = join(SRC_ROOT, pType);
    if (!existsSync(dir)) continue;

    for (const extFolder of readdirSync(dir)) {
        const extPath = join(dir, extFolder);
        if (!statSync(extPath).isDirectory()) continue;

        const tsFile = join(extPath, "code.ts");
        const jsFile = join(extPath, "code.js");
        if (!existsSync(tsFile)) continue;

        const sourceText = readFileSync(tsFile, "utf-8");
        const result = ts.transpileModule(sourceText, {
            compilerOptions: {
                target: ts.ScriptTarget.ES2020,
                module: ts.ModuleKind.None,
                removeComments: false,
                strict: false,
            },
        });

        writeFileSync(jsFile, result.outputText, "utf-8");
        compiledCount++;
    }
}

console.log(`Successfully compiled ${compiledCount} Seanime TypeScript extension(s) to Goja JavaScript.`);
