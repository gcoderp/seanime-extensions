// Report assembly for the extension checker.
// The output file is what the repository publishes, so it is written deterministically:
// sorted keys where order matters, stable sorting of extensions, no timestamps inside entries.

import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

export const SCHEMA_VERSION = 1;

const STATUS_ORDER = [
    "working",
    "no_search_results",
    "search_timeout",
    "no_episodes",
    "no_stream",
    "stream_unreachable",
    "no_magnet",
    "contract_error",
    "load_error",
    "unsupported_payload",
    "search_error",
    "episodes_error",
    "stream_error",
    "torrent_error",
    "timeout",
    "error",
];

export function buildReport({ marketplaceUrl, targets, results, startedAt, finishedAt, runtimeVersion, options }) {
    const byStatus = {};
    for (const status of STATUS_ORDER) byStatus[status] = 0;
    for (const result of results) {
        byStatus[result.status] = (byStatus[result.status] || 0) + 1;
    }

    const working = results
        .filter((r) => r.status === "working")
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((r) => ({
            id: r.id,
            name: r.name,
            type: r.type,
            version: r.version,
            manifestURI: r.manifestURI,
            payloadURI: r.payloadURI,
            anilistId: r.target ?? null,
            matchedTitle: r.search?.top ?? null,
            stream: r.stream ?? null,
            torrent: r.torrent ?? null,
            durationMs: r.durationMs,
        }));

    const failed = results
        .filter((r) => r.status !== "working")
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((r) => ({
            id: r.id,
            name: r.name,
            type: r.type,
            status: r.status,
            error: r.error ?? null,
            durationMs: r.durationMs,
        }));

    return {
        schemaVersion: SCHEMA_VERSION,
        generatedAt: finishedAt,
        marketplace: marketplaceUrl,
        runtime: runtimeVersion,
        options: {
            types: options.types,
            dub: options.dub,
            targets: options.targetMode,
        },
        targets: targets.map((t) => ({
            anilistId: t.anilistId,
            title: t.title,
            year: t.year,
            format: t.format,
            label: t.label,
        })),
        summary: {
            checked: results.length,
            working: working.length,
            failed: failed.length,
            durationMs: new Date(finishedAt).getTime() - new Date(startedAt).getTime(),
            byStatus,
        },
        working,
        failed,
        results: results.slice().sort((a, b) => a.id.localeCompare(b.id)),
    };
}

export async function writeReport(filePath, report) {
    await mkdir(path.dirname(path.resolve(filePath)), { recursive: true });
    await writeFile(filePath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    return filePath;
}

const MARK = {
    working: "PASS",
    no_search_results: "no search results",
    search_timeout: "site unreachable / timed out",
    no_episodes: "no episodes",
    no_stream: "no stream",
    stream_unreachable: "stream unreachable",
    no_magnet: "no magnet",
    contract_error: "contract error",
    load_error: "load error",
    unsupported_payload: "unsupported payload",
};

export function toMarkdown(report) {
    const lines = [];
    lines.push("## Extension check");
    lines.push("");
    lines.push(`Marketplace: \`${report.marketplace}\``);
    lines.push("");
    lines.push("| metric | value |");
    lines.push("| --- | --- |");
    lines.push(`| checked | ${report.summary.checked} |`);
    lines.push(`| working | ${report.summary.working} |`);
    lines.push(`| failed | ${report.summary.failed} |`);
    lines.push(`| duration | ${Math.round(report.summary.durationMs / 1000)}s |`);
    lines.push(`| AniList targets | ${report.targets.map((t) => `${t.title} (${t.anilistId})`).join(", ")} |`);
    lines.push("");

    if (report.working.length > 0) {
        lines.push("### Working");
        lines.push("");
        lines.push("| extension | matched | quality | type |");
        lines.push("| --- | --- | --- | --- |");
        for (const w of report.working) {
            const stream = w.stream?.source || {};
            lines.push(`| \`${w.id}\` | ${w.matchedTitle ?? "-"} | ${stream.quality ?? "-"} | ${stream.type ?? "torrent"} |`);
        }
        lines.push("");
    }

    // Distinguishes "the site answered but our selectors matched nothing" from
    // "the site refused or never answered", which are completely different problems.
    const answered = report.results.filter((r) =>
        ["no_search_results", "search_error", "search_timeout"].includes(r.status));
    const withHttp = answered.flatMap((r) =>
        (r.search?.attempts || []).map((a) => a.httpStatus).filter((s) => typeof s === "number"));
    if (withHttp.length > 0) {
        const ok = withHttp.filter((s) => s === 200).length;
        const blocked = withHttp.filter((s) => s === 403 || s === 401).length;
        const missing = withHttp.filter((s) => s === 404).length;
        lines.push("### Why searches came back empty");
        lines.push("");
        lines.push("| the site answered with | attempts |");
        lines.push("| --- | --- |");
        lines.push(`| HTTP 200 (page loaded, no match -> selector problem) | ${ok} |`);
        lines.push(`| HTTP 403/401 (blocked) | ${blocked} |`);
        lines.push(`| HTTP 404 (search path moved) | ${missing} |`);
        lines.push(`| other | ${withHttp.length - ok - blocked - missing} |`);
        lines.push("");
    }

    const failures = Object.entries(report.summary.byStatus)
        .filter(([status, count]) => status !== "working" && count > 0)
        .sort((a, b) => b[1] - a[1]);
    if (failures.length > 0) {
        lines.push("### Failures by reason");
        lines.push("");
        lines.push("| reason | count |");
        lines.push("| --- | --- |");
        for (const [status, count] of failures) {
            lines.push(`| ${MARK[status] || status} | ${count} |`);
        }
        lines.push("");
    }

    return lines.join("\n");
}
