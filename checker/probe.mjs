// Probes one converted extension the way Seanime drives it:
//   search -> findEpisodes -> findEpisodeServer -> verify the stream is actually reachable
// and, for torrent providers, search -> getTorrentMagnetLink / getTorrentInfoHash.
//
// "working" means a playable URL (or magnet) came back and the network agreed, not merely that
// the methods returned without throwing.

const SEARCH_TIMEOUT_MS = 30000;
const STEP_TIMEOUT_MS = 25000;
const STREAM_TIMEOUT_MS = 15000;

function withTimeout(promise, ms, label) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function normalizeTitle(value) {
    return String(value || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[([{][^)\]}]*[)\]}]/g, " ")
        .replace(/[^a-z0-9]+/g, " ")
        .trim();
}

function similarity(a, b) {
    if (!a || !b) return 0;
    if (a === b) return 1;
    if (a.length >= 4 && b.length >= 4 && (a.includes(b) || b.includes(a))) return 0.9;
    const ta = a.split(" ").filter(Boolean);
    const tb = b.split(" ").filter(Boolean);
    if (!ta.length || !tb.length) return 0;
    const pool = tb.slice();
    let hits = 0;
    for (const token of ta) {
        const idx = pool.indexOf(token);
        if (idx !== -1) {
            hits += 1;
            pool.splice(idx, 1);
        }
    }
    return (2 * hits) / (ta.length + tb.length);
}

/** Picks the result Seanime would most likely settle on (GetBestSearchResult equivalent). */
function bestMatch(results, titles) {
    let best = null;
    let bestScore = -1;
    results.forEach((result, index) => {
        const name = normalizeTitle(result && result.title);
        let score = 0;
        for (const title of titles) score = Math.max(score, similarity(name, normalizeTitle(title)));
        if (score > bestScore) {
            bestScore = score;
            best = { result, index, score };
        }
    });
    return best;
}

async function verifyStream(source) {
    const url = String(source && source.url ? source.url : "");
    if (!url) return { reachable: false, reason: "empty url" };
    if (url.startsWith("data:")) return { reachable: true, reason: "inline data uri", status: 200 };

    const headers = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36" };
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);

    try {
        if (source.type === "m3u8" || /\.m3u8(\?|$)/i.test(url)) {
            const res = await fetch(url, { headers, signal: controller.signal, redirect: "follow" });
            const body = await res.text();
            return {
                reachable: res.ok && body.includes("#EXTM3U"),
                status: res.status,
                contentType: res.headers.get("content-type") || undefined,
                reason: res.ok ? (body.includes("#EXTM3U") ? "valid HLS manifest" : "200 but not an HLS manifest") : `HTTP ${res.status}`,
            };
        }

        const head = await fetch(url, { method: "HEAD", headers, signal: controller.signal, redirect: "follow" });
        if (head.status >= 200 && head.status < 400) {
            return { reachable: true, status: head.status, contentType: head.headers.get("content-type") || undefined, reason: "HEAD ok" };
        }
        const get = await fetch(url, { headers: { ...headers, Range: "bytes=0-1024" }, signal: controller.signal, redirect: "follow" });
        return {
            reachable: get.status >= 200 && get.status < 400,
            status: get.status,
            contentType: get.headers.get("content-type") || undefined,
            reason: get.ok ? "range request ok" : `HTTP ${get.status}`,
        };
    } catch (err) {
        return { reachable: false, reason: String(err && err.message ? err.message : err).slice(0, 160) };
    } finally {
        clearTimeout(timer);
    }
}

function describeSource(source) {
    return {
        url: source && source.url,
        type: source && source.type,
        quality: source && source.quality,
        label: source && source.label,
        subtitles: Array.isArray(source && source.subtitles) ? source.subtitles.length : 0,
    };
}

/**
 * Full online-stream chain for one extension against one AniList target.
 * Returns a result object; never throws.
 */
export async function probeOnlinestream(provider, target, { dub = false } = {}) {
    const result = { status: "error", error: null, target: target.anilistId, search: null, episodes: null, stream: null };

    let results = [];
    const attempts = [];
    try {
        for (const query of target.queries.slice(0, 3)) {
            const res = await withTimeout(
                Promise.resolve(provider.search({ media: target.media, query, dub, year: target.year ?? undefined })),
                SEARCH_TIMEOUT_MS,
                "search()"
            );
            const list = Array.isArray(res) ? res : [];
            attempts.push({ query, results: list.length });
            if (list.length > 0) {
                results = list;
                break;
            }
        }
    } catch (err) {
        result.status = "search_error";
        result.error = String(err && err.message ? err.message : err).slice(0, 300);
        result.search = { attempts };
        return result;
    }

    result.search = { attempts, count: results.length };
    if (results.length === 0) {
        result.status = "no_search_results";
        return result;
    }

    const best = bestMatch(results, target.queries);
    result.search.top = best.result && best.result.title;
    result.search.score = Number(best.score.toFixed(3));

    let episodes = [];
    try {
        const res = await withTimeout(
            Promise.resolve(provider.findEpisodes(best.result.id)),
            STEP_TIMEOUT_MS,
            "findEpisodes()"
        );
        episodes = Array.isArray(res) ? res : [];
    } catch (err) {
        result.status = "episodes_error";
        result.error = String(err && err.message ? err.message : err).slice(0, 300);
        return result;
    }

    result.episodes = { count: episodes.length };
    if (episodes.length === 0) {
        result.status = "no_episodes";
        return result;
    }

    const episode = episodes.find((e) => Number(e && e.number) === 1) || episodes[0];
    result.episodes.probed = { number: episode && episode.number, title: episode && episode.title };

    let server;
    try {
        server = await withTimeout(
            Promise.resolve(provider.findEpisodeServer(episode, "default")),
            STEP_TIMEOUT_MS,
            "findEpisodeServer()"
        );
    } catch (err) {
        result.status = "stream_error";
        result.error = String(err && err.message ? err.message : err).slice(0, 300);
        return result;
    }

    const sources = Array.isArray(server && server.videoSources) ? server.videoSources : [];
    if (sources.length === 0) {
        result.status = "no_stream";
        result.stream = { server: server && server.server, sources: 0 };
        return result;
    }

    for (const source of sources.slice(0, 3)) {
        const verification = await verifyStream(source);
        result.stream = {
            server: server.server,
            source: describeSource(source),
            verified: verification,
        };
        if (verification.reachable) {
            result.status = "working";
            return result;
        }
    }

    result.status = "stream_unreachable";
    result.error = result.stream?.verified?.reason || null;
    return result;
}

/** Torrent chain: search -> magnet/info hash. */
export async function probeTorrent(provider, target) {
    const result = { status: "error", error: null, target: target.anilistId, search: null, torrent: null };

    let results = [];
    const attempts = [];
    try {
        for (const query of target.queries.slice(0, 2)) {
            const res = await withTimeout(
                Promise.resolve(provider.search({ media: target.media, query })),
                SEARCH_TIMEOUT_MS,
                "search()"
            );
            const list = Array.isArray(res) ? res : [];
            attempts.push({ query, results: list.length });
            if (list.length > 0) {
                results = list;
                break;
            }
        }
    } catch (err) {
        result.status = "search_error";
        result.error = String(err && err.message ? err.message : err).slice(0, 300);
        result.search = { attempts };
        return result;
    }

    result.search = { attempts, count: results.length };
    if (results.length === 0) {
        result.status = "no_search_results";
        return result;
    }

    const torrent = results[0];
    result.torrent = {
        name: torrent && torrent.name,
        seeders: torrent && torrent.seeders,
        size: torrent && torrent.formattedSize,
        resolution: torrent && torrent.resolution,
    };

    try {
        const magnet = await withTimeout(
            Promise.resolve(provider.getTorrentMagnetLink(torrent)),
            STEP_TIMEOUT_MS,
            "getTorrentMagnetLink()"
        );
        const infoHash = await withTimeout(
            Promise.resolve(provider.getTorrentInfoHash(torrent)),
            STEP_TIMEOUT_MS,
            "getTorrentInfoHash()"
        );
        const magnetOk = typeof magnet === "string" && magnet.startsWith("magnet:") && /btih:[a-z0-9]{32,40}/i.test(magnet);
        const hashOk = typeof infoHash === "string" && /^[a-z0-9]{32,40}$/i.test(infoHash);
        result.torrent.magnet = magnetOk ? `${magnet.slice(0, 80)}…` : (magnet || null);
        result.torrent.infoHash = hashOk ? infoHash : (infoHash || null);
        if (magnetOk || hashOk) {
            result.status = "working";
        } else {
            result.status = "no_magnet";
            result.error = "no usable magnet link or info hash";
        }
    } catch (err) {
        result.status = "torrent_error";
        result.error = String(err && err.message ? err.message : err).slice(0, 300);
    }

    return result;
}
