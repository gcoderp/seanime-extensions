// Standalone Marketplace Index Regenerator
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync, mkdirSync } from "fs";
import { join } from "path";

const PROVIDER_TYPES = ["onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"];
const manifests: any[] = [];
const seen = new Set<string>();

for (const pType of PROVIDER_TYPES) {
    const pDir = join(process.cwd(), "src", pType);
    if (!existsSync(pDir)) continue;
    for (const folder of readdirSync(pDir).sort()) {
        const extDir = join(pDir, folder);
        if (!statSync(extDir).isDirectory()) continue;
        const mPath = join(extDir, "manifest.json");
        const jsPath = join(extDir, "code.js");
        if (existsSync(mPath) && existsSync(jsPath)) {
            const data = JSON.parse(readFileSync(mPath, "utf-8"));
            if (data.id && !seen.has(data.id) && String(data.payloadURI).endsWith("/code.js")) {
                seen.add(data.id);
                manifests.push(data);
            }
        }
    }
}

writeFileSync(join(process.cwd(), "marketplace.json"), JSON.stringify(manifests, null, 2) + "\n", "utf-8");
mkdirSync(join(process.cwd(), "generated"), { recursive: true });
writeFileSync(join(process.cwd(), "generated", "marketplace.json"), JSON.stringify(manifests, null, 2) + "\n", "utf-8");
console.log(`Updated marketplace.json with ${manifests.length} valid extension(s).`);
