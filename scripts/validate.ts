// Seanime Extension & Marketplace Schema Validator
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const rootMkt = join(process.cwd(), "marketplace.json");
if (!existsSync(rootMkt)) {
    throw new Error("marketplace.json is missing at repository root!");
}

const entries = JSON.parse(readFileSync(rootMkt, "utf-8"));
if (!Array.isArray(entries)) {
    throw new Error("marketplace.json must be a JSON array of extension manifests.");
}

const ids = new Set<string>();
for (const item of entries) {
    if (!item.id || !item.name || !item.manifestURI || !item.payloadURI || !item.type) {
        throw new Error(`Invalid manifest entry in marketplace.json: ${JSON.stringify(item)}`);
    }
    if (ids.has(item.id)) {
        throw new Error(`Duplicate extension ID detected: ${item.id}`);
    }
    ids.add(item.id);
    if (!item.payloadURI.endsWith("/code.js")) {
        throw new Error(`Extension ${item.id} payloadURI must point to compiled code.js, got: ${item.payloadURI}`);
    }
}

console.log(`Validated ${entries.length} published extension(s) in marketplace.json.`);
