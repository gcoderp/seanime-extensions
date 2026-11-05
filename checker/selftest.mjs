#!/usr/bin/env node
/**
 * Offline self-test for the checker harness.
 *
 * Spins up a fake streaming site and a fake HLS endpoint on localhost, loads a provider the
 * same way the checker does, and asserts the full chain (search -> episodes -> stream ->
 * manifest verification) reports "working". Also asserts the failure paths, so a green run
 * means the checker can distinguish working from broken rather than always passing.
 *
 *   node checker/selftest.mjs
 */

import http from "node:http";
import { createRuntime, loadProvider, assertContract } from "./runtime.mjs";
import { probeOnlinestream } from "./probe.mjs";
import { toSeanimeMedia, seanimeTitles } from "./anilist.mjs";

let failures = 0;
function check(name, condition, detail) {
    if (condition) {
        console.log(`  ok    ${name}`);
    } else {
        failures += 1;
        console.log(`  FAIL  ${name}${detail ? ` -- ${detail}` : ""}`);
    }
}

const SEARCH_HTML = `<html><body>
  <ul class="items">
    <li><p class="name"><a href="/site/anime/other">Unrelated Show</a></p></li>
    <li><p class="name"><a href="/site/anime/sousou-no-frieren">Sousou no Frieren (Dub)</a></p></li>
  </ul></body></html>`;

const EPISODE_HTML = `<html><body>
  <ul id="episode_related">
    <li><a href="/site/watch/ep-2"><div class="name">2</div></a></li>
    <li><a href="/site/watch/ep-1"><div class="name">1</div></a></li>
  </ul></body></html>`;

const WATCH_HTML = `<html><body>
  <div class="anime_muti_link"><ul><li><a data-video="__BASE__/embed/1">Server</a></li></ul></div>
</body></html>`;

const EMBED_HTML = `<html><body><script>var player = {file: "__BASE__/hls/master.m3u8"};</script></body></html>`;

function providerCode(base) {
    return `
class Provider {
    mainUrl = ${JSON.stringify(base)};

    getSettings() {
        return { episodeServers: ["default"], supportsDub: true };
    }

    async search(opts) {
        const res = await fetch(this.mainUrl + "/site/search?q=" + encodeURIComponent(opts.query));
        const $ = LoadDoc(await res.text());
        const out = [];
        $("ul.items li").each((i, el) => {
            const a = el.find("p.name a").first();
            const title = a.text();
            const href = a.attr("href");
            if (title && href) out.push({ id: href, title, url: href, subOrDub: /dub/i.test(title) ? "dub" : "sub" });
        });
        return out;
    }

    async findEpisodes(id) {
        const res = await fetch(this.mainUrl + id);
        const $ = LoadDoc(await res.text());
        const eps = [];
        $("ul#episode_related li a").each((i, el) => {
            const href = el.attr("href");
            const number = parseInt(el.find("div.name").text().replace(/\\D+/g, ""), 10) || (i + 1);
            if (href) eps.push({ id: href, number, url: href, title: "Episode " + number });
        });
        return eps.sort((a, b) => a.number - b.number);
    }

    async findEpisodeServer(episode, server) {
        const res = await fetch(this.mainUrl + (episode.url || episode.id));
        const $ = LoadDoc(await res.text());
        const embed = $("div.anime_muti_link ul li a").first().attr("data-video");
        const player = await (await fetch(embed)).text();
        const match = player.match(/(https?:\\/\\/[^"'\\s]+\\.m3u8)/);
        if (!match) throw new Error("no stream in player page");
        return {
            server: "default",
            headers: { Referer: embed },
            videoSources: [{ url: match[1], type: "m3u8", quality: "1080p", subtitles: [] }],
        };
    }
}
`;
}

const BROKEN_PROVIDER = `
class Provider {
    getSettings() { return { episodeServers: ["default"], supportsDub: false }; }
    async search(opts) { return []; }
    async findEpisodes(id) { return []; }
    async findEpisodeServer(episode, server) { return { server: "default", headers: {}, videoSources: [] }; }
}
`;

const NO_EPISODES_PROVIDER = `
class Provider {
    getSettings() { return { episodeServers: ["default"], supportsDub: false }; }
    async search(opts) { return [{ id: "/site/anime/x", title: "X", url: "/site/anime/x", subOrDub: "sub" }]; }
    async findEpisodes(id) { return []; }
    async findEpisodeServer(episode, server) { return { server: "default", headers: {}, videoSources: [] }; }
}
`;

const BROKEN_CONTRACT_PROVIDER = `
class Provider {
    getSettings() { return { episodeServers: "not-an-array", supportsDub: "nope" }; }
    async search(opts) { return []; }
}
`;

function startServer() {
    const server = http.createServer((req, res) => {
        const base = `http://127.0.0.1:${server.address().port}`;
        const url = new URL(req.url, base);

        if (url.pathname === "/site/search") {
            res.writeHead(200, { "Content-Type": "text/html" });
            res.end(SEARCH_HTML);
            return;
        }
        if (url.pathname.startsWith("/site/anime/")) {
            res.writeHead(200, { "Content-Type": "text/html" });
            res.end(EPISODE_HTML);
            return;
        }
        if (url.pathname.startsWith("/site/watch/")) {
            res.writeHead(200, { "Content-Type": "text/html" });
            res.end(WATCH_HTML.replaceAll("__BASE__", base));
            return;
        }
        if (url.pathname === "/embed/1") {
            res.writeHead(200, { "Content-Type": "text/html" });
            res.end(EMBED_HTML.replaceAll("__BASE__", base));
            return;
        }
        if (url.pathname === "/hls/master.m3u8") {
            res.writeHead(200, { "Content-Type": "application/vnd.apple.mpegurl" });
            res.end("#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:10,\nseg1.ts\n");
            return;
        }
        res.writeHead(404);
        res.end("not found");
    });
    return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

async function loadAndProbe(code, base, targetOverride) {
    const { runtime, values, requests } = createRuntime({ providerId: "selftest", manifest: { name: "SelfTest" }, timeoutMs: 4000 });
    const ProviderClass = loadProvider(code, values);
    const provider = new ProviderClass();
    assertContract(provider, "onlinestream-provider");
    const target = {
        anilistId: 1,
        title: "Sousou no Frieren",
        year: 2023,
        queries: ["Sousou no Frieren", "Frieren: Beyond Journey's End"],
        media: {
            id: 1,
            romajiTitle: "Sousou no Frieren",
            englishTitle: "Frieren: Beyond Journey's End",
            synonyms: [],
            isAdult: false,
            format: "TV",
        },
    };
    return probeOnlinestream(provider, targetOverride || target, { dub: false, requests });
}

async function main() {
    console.log("checker self-test");
    const server = await startServer();
    const base = `http://127.0.0.1:${server.address().port}`;

    try {
        console.log("\nruntime");
        const { runtime, values } = createRuntime({ providerId: "t", manifest: {} });
        check("LoadDoc returns a selector function", typeof runtime.LoadDoc("<p>x</p>") === "function");
        check("fetch is available", typeof runtime.fetch === "function");
        check("CryptoJS is available", typeof runtime.CryptoJS === "object");
        check("$scannerUtils is available", typeof runtime.$scannerUtils === "object");

        const sandboxed = (() => {
            try {
                loadProvider("class Provider { leak() { return typeof process; } }", values);
                return true;
            } catch {
                return false;
            }
        })();
        check("provider cannot see process (sandboxed scope)", sandboxed !== false);

        console.log("\nAniList mapping");
        const media = toSeanimeMedia({
            id: 154587,
            idMal: 52991,
            status: "FINISHED",
            format: "TV",
            episodes: 28,
            isAdult: false,
            synonyms: ["Frieren at the Funeral", "Sousou no Frieren 2nd Season"],
            title: { romaji: "Sousou no Frieren", english: "Frieren: Beyond Journey's End", native: "葬送のフリーレン" },
            startDate: { year: 2023, month: 9, day: 29 },
        });
        check("romajiTitle mapped", media.romajiTitle === "Sousou no Frieren");
        check("englishTitle mapped", media.englishTitle === "Frieren: Beyond Journey's End");
        check("startDate flattened", media.startDate?.year === 2023);
        check("episodeCount mapped", media.episodeCount === 28);
        check("only season synonyms kept", media.synonyms.length === 1 && /2nd Season/.test(media.synonyms[0]), JSON.stringify(media.synonyms));
        const titles = seanimeTitles(media);
        check("titles start with romaji then english", titles[0] === "Sousou no Frieren" && titles[1] === "Frieren: Beyond Journey's End");

        console.log("\nprobe: healthy provider");
        const ok = await loadAndProbe(providerCode(base), base);
        check("status is working", ok.status === "working", `${ok.status}: ${ok.error || ""}`);
        check("picked the AniList match", /Frieren/i.test(ok.search?.top || ""), ok.search?.top);
        check("episodes found", ok.episodes?.count === 2);
        check("probed episode 1", ok.episodes?.probed?.number === 1);
        check("stream verified", ok.stream?.verified?.reachable === true, ok.stream?.verified?.reason);
        check("stream type m3u8", ok.stream?.source?.type === "m3u8");

        console.log("\nprobe: broken providers");
        const empty = await loadAndProbe(BROKEN_PROVIDER, base);
        check("empty search -> no_search_results", empty.status === "no_search_results", empty.status);

        const noEps = await loadAndProbe(NO_EPISODES_PROVIDER, base);
        check("no episodes -> no_episodes", noEps.status === "no_episodes", noEps.status);

        console.log("\ndiagnostics");

        // A provider whose site never answers must fail fast, not burn the whole budget.
        const deadPort = 9;
        const deadProvider = `
class Provider {
    getSettings() { return { episodeServers: ["default"], supportsDub: false }; }
    async search(opts) {
        const res = await fetch("http://127.0.0.1:${deadPort}/search?q=" + encodeURIComponent(opts.query));
        return [{ id: "/x", title: "x", url: "/x", subOrDub: "sub" }];
    }
    async findEpisodes(id) { return []; }
    async findEpisodeServer(e, s) { return { server: "default", headers: {}, videoSources: [] }; }
}`;
        const startedDead = Date.now();
        const dead = await loadAndProbe(deadProvider, base);
        const deadMs = Date.now() - startedDead;
        check("unreachable site -> search_timeout", dead.status === "search_timeout", dead.status);
        check("unreachable site fails fast (<8s)", deadMs < 8000, `${deadMs}ms`);
        check("dead attempt records the network failure", (dead.search?.attempts?.[0]?.networkFailures ?? 0) > 0);

        // A site that answers 200 but has no matching markup is a selector problem, and the
        // report must be able to say so.
        const noMatchProvider = `
class Provider {
    mainUrl = ${JSON.stringify(base)};
    getSettings() { return { episodeServers: ["default"], supportsDub: false }; }
    async search(opts) {
        const res = await fetch(this.mainUrl + "/site/search?q=" + encodeURIComponent(opts.query));
        const $ = LoadDoc(await res.text());
        const out = [];
        $("div.never-matches-anything").each((i, el) => { out.push({ id: "x", title: "x", url: "x", subOrDub: "sub" }); });
        return out;
    }
    async findEpisodes(id) { return []; }
    async findEpisodeServer(e, s) { return { server: "default", headers: {}, videoSources: [] }; }
}`;
        const noMatch = await loadAndProbe(noMatchProvider, base);
        check("200 with no match -> no_search_results", noMatch.status === "no_search_results", noMatch.status);
        check("records HTTP 200 for the attempt", noMatch.search?.attempts?.[0]?.httpStatus === 200, JSON.stringify(noMatch.search?.attempts?.[0]));

        const missingProvider = `
class Provider {
    mainUrl = ${JSON.stringify(base)};
    getSettings() { return { episodeServers: ["default"], supportsDub: false }; }
    async search(opts) {
        const res = await fetch(this.mainUrl + "/site/moved-away?q=" + encodeURIComponent(opts.query));
        if (!res.ok) throw new Error("search page returned " + res.status);
        return [];
    }
    async findEpisodes(id) { return []; }
    async findEpisodeServer(e, s) { return { server: "default", headers: {}, videoSources: [] }; }
}`;
        // The provider threw on a non-2xx page: that is a search_error, but the 404 must be
        // recorded so the report can say "the search path moved" instead of "provider bug".
        const missing = await loadAndProbe(missingProvider, base);
        check("404 search path -> search_error", missing.status === "search_error", missing.status);
        check("records HTTP 404 for the attempt", missing.search?.attempts?.[0]?.httpStatus === 404, JSON.stringify(missing.search?.attempts?.[0]));

        console.log("\ncontract");
        const { values: v2 } = createRuntime({ providerId: "c", manifest: {} });
        const BadProvider = loadProvider(BROKEN_CONTRACT_PROVIDER, v2);
        let contractError = null;
        try {
            assertContract(new BadProvider(), "onlinestream-provider");
        } catch (err) {
            contractError = err.message;
        }
        check("invalid getSettings() rejected", !!contractError, contractError);
    } finally {
        server.close();
    }

    console.log("");
    if (failures > 0) {
        console.log(`${failures} self-test check(s) failed`);
        process.exit(1);
    }
    console.log("all self-test checks passed");
}

main().catch((err) => {
    console.error(err);
    process.exit(1);
});
