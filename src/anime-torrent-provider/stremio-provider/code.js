/// <reference path="../../../seanime/types/seanime-env.d.ts" />
// ============================================================================
// AUTO-GENERATED SEANIME TORRENT EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: StremioProvider
// Original Class: ConvertedCloudstreamProvider
// Strategy Used: STRATEGY_2_JADX_JAVA_AST
// ============================================================================
// Cloudstream-to-Seanime Goja Runtime Compatibility Layer
// Injected into converted TypeScript extensions to bridge Cloudstream Kotlin idioms cleanly inside Goja.
class CsCompat {
    static fixUrl(url, baseUrl) {
        if (!url)
            return "";
        if (url.startsWith("http://") || url.startsWith("https://"))
            return url;
        if (url.startsWith("//"))
            return "https:" + url;
        const cleanBase = baseUrl.replace(/\/+$/, "");
        if (url.startsWith("/"))
            return cleanBase + url;
        return cleanBase + "/" + url;
    }
    static fixUrlNull(url, baseUrl) {
        if (!url)
            return null;
        return CsCompat.fixUrl(url, baseUrl);
    }
    static base64Decode(input) {
        try {
            if (typeof atob === "function")
                return atob(input);
            return CryptoJS.enc.Base64.parse(input).toString(CryptoJS.enc.Utf8);
        }
        catch {
            return "";
        }
    }
    static base64Encode(input) {
        try {
            if (typeof btoa === "function")
                return btoa(input);
            return CryptoJS.enc.Base64.stringify(CryptoJS.enc.Utf8.parse(input));
        }
        catch {
            return "";
        }
    }
    static unpackJs(packed) {
        // Unpacks Dean Edwards p,a,c,k,e,r obfuscated JS blocks without dynamic code execution
        const match = packed.match(/\x7d\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)/s);
        if (!match)
            return packed;
        let payload = match[1];
        const radix = parseInt(match[2], 10);
        const count = parseInt(match[3], 10);
        const symtab = match[4].split("|");
        const encodeBase = (num, base) => {
            const chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
            if (num < base)
                return num < 36 ? num.toString(36) : chars[num];
            return encodeBase(Math.floor(num / base), base) + (num % base < 36 ? (num % base).toString(36) : chars[num % base]);
        };
        for (let i = count - 1; i >= 0; i--) {
            if (symtab[i]) {
                const token = encodeBase(i, radix);
                payload = payload.replace(new RegExp("\\b" + token + "\\b", "g"), symtab[i]);
            }
        }
        return payload;
    }
    static async fetchWithMirrorFallback(pathOrUrl, domains, options = {}) {
        let lastErr = null;
        for (const domain of domains) {
            const targetUrl = pathOrUrl.startsWith("http") ? pathOrUrl : CsCompat.fixUrl(pathOrUrl, domain);
            try {
                const res = await fetch(targetUrl, options);
                const text = await res.text();
                if (res.status < 500 && !text.includes("cf-browser-verification")) {
                    return { text, url: targetUrl, status: res.status };
                }
            }
            catch (e) {
                lastErr = e;
            }
        }
        throw lastErr || new Error("All mirror domains failed for " + pathOrUrl);
    }
    static inferQuality(labelOrUrl) {
        const m = labelOrUrl.match(/(2160|1440|1080|720|480|360)p?/i);
        if (m)
            return m[1] + "p";
        if (/4k|uhd/i.test(labelOrUrl))
            return "2160p";
        if (/fhd/i.test(labelOrUrl))
            return "1080p";
        if (/hd/i.test(labelOrUrl))
            return "720p";
        return "auto";
    }
    static inferVideoType(url) {
        if (/\.m3u8(\?|$)/i.test(url) || url.includes("hls"))
            return "m3u8";
        if (/\.mpd(\?|$)/i.test(url))
            return "unknown";
        if (/\.mp4(\?|$)/i.test(url))
            return "mp4";
        return "m3u8";
    }
}
// AniList-driven matching for converted Seanime providers.
//
// Seanime is an AniList client: it never hands a provider a bare search string in isolation,
// it hands it the AniList media object (id, idMal, english/romaji/native titles, synonyms,
// year, format). A converted Cloudstream provider that searches by `opts.query` alone picks
// whatever the site's own ranking returns, which is frequently the wrong season, the wrong
// adaptation, or a sequel. This resolver makes the AniList metadata the source of truth:
// query by the AniList titles, then rank the site's results against the same titles.
class AniListResolver {
    /** Lowercase, de-accent, drop bracketed qualifiers, collapse punctuation. */
    static normalize(value) {
        if (!value)
            return "";
        let s = String(value).toLowerCase();
        if (typeof s.normalize === "function") {
            s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        }
        // (Dub), [1080p], {TV} and similar qualifiers differ per site; drop them entirely
        s = s.replace(/[([{][^)\]}]*[)\]}]/g, " ");
        s = s.replace(/[^a-z0-9]+/g, " ");
        return s.trim();
    }
    /** Removes release noise that sites add but AniList titles never contain. */
    static stripNoise(value) {
        let s = AniListResolver.normalize(value);
        s = s.replace(/\b(season|s)\s*\d+\b/g, " ");
        s = s.replace(/\b(part|cour)\s*\d+\b/g, " ");
        s = s.replace(/\b(sub|subbed|dub|dubbed|eng|english|jpn|japanese|raw)\b/g, " ");
        s = s.replace(/\b(tv|series|movie|ova|ona|special)\b/g, " ");
        s = s.replace(/\s+/g, " ").trim();
        return s;
    }
    /** Which season/part a title claims. 1 when the title says nothing. */
    static seasonOf(value) {
        const s = AniListResolver.normalize(value);
        const numbered = s.match(/\b(?:season|part|cour|s)\s*(\d{1,2})\b/);
        if (numbered)
            return parseInt(numbered[1], 10);
        const roman = s.match(/\b(ii|iii|iv|v)\b/);
        if (roman) {
            const map = { ii: 2, iii: 3, iv: 4, v: 5 };
            return map[roman[1]] || 1;
        }
        return 1;
    }
    /** Dice coefficient over word tokens, with exact/containment shortcuts. */
    static similarity(a, b) {
        if (!a || !b)
            return 0;
        if (a === b)
            return 1;
        if (a.length >= 4 && b.length >= 4 && (a.indexOf(b) !== -1 || b.indexOf(a) !== -1)) {
            return 0.9;
        }
        const ta = a.split(" ").filter((t) => t.length > 0);
        const tb = b.split(" ").filter((t) => t.length > 0);
        if (ta.length === 0 || tb.length === 0)
            return 0;
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
    /**
     * Every title AniList knows for this media, in Seanime's GetAllTitles() order:
     * romaji, english, then synonyms. De-duplicated case-insensitively.
     */
    static titles(media, fallback) {
        const out = [];
        const push = (value) => {
            if (value && String(value).trim().length > 0)
                out.push(String(value).trim());
        };
        if (media) {
            push(media.romajiTitle);
            push(media.englishTitle);
            if (media.synonyms && media.synonyms.length) {
                for (const synonym of media.synonyms)
                    push(synonym);
            }
        }
        push(fallback);
        const seen = new Set();
        const unique = [];
        for (const title of out) {
            const key = title.toLowerCase();
            if (!seen.has(key)) {
                seen.add(key);
                unique.push(title);
            }
        }
        return unique;
    }
    /** 0..1 confidence that `resultTitle` is the AniList media. */
    static score(resultTitle, media, year) {
        const target = AniListResolver.stripNoise(resultTitle);
        if (!target)
            return 0;
        let best = 0;
        const candidates = AniListResolver.titles(media, "");
        for (const candidate of candidates) {
            const plain = AniListResolver.similarity(target, AniListResolver.normalize(candidate));
            const stripped = AniListResolver.similarity(target, AniListResolver.stripNoise(candidate));
            const value = plain > stripped ? plain : stripped;
            if (value > best)
                best = value;
        }
        // Season disambiguation: "Season 2" must not resolve to the season 1 page, which is
        // the single most common wrong match for AniList-driven providers.
        const primary = AniListResolver.titles(media, "")[0] || "";
        const mediaSeason = AniListResolver.seasonOf(primary);
        const resultSeason = AniListResolver.seasonOf(resultTitle);
        if (mediaSeason !== resultSeason) {
            best -= 0.2;
        }
        else if (mediaSeason > 1) {
            best += 0.1;
        }
        // A year printed in the result title is strong evidence when it matches AniList.
        if (year && year > 0) {
            const match = String(resultTitle).match(/\b(19|20)\d{2}\b/);
            if (match) {
                best += String(year) === match[0] ? 0.1 : -0.05;
            }
        }
        // Movie/series hints only break ties; they never rescue a bad title match.
        if (media && media.format) {
            const format = String(media.format).toUpperCase();
            const looksMovie = /\b(movie|film)\b/i.test(resultTitle);
            if (format === "MOVIE" && looksMovie)
                best += 0.05;
            if (format !== "MOVIE" && looksMovie && best > 0)
                best -= 0.05;
        }
        return best;
    }
    /** Stable sort by AniList confidence, preserving site order for equal scores. */
    static rank(items, titleOf, media, year) {
        const scored = items.map((item, index) => ({
            item,
            index,
            score: AniListResolver.score(titleOf(item), media, year),
        }));
        scored.sort((a, b) => (b.score - a.score) || (a.index - b.index));
        return scored.map((entry) => entry.item);
    }
    /**
     * Query strings to try, best first. Seanime's own title for this call wins because that
     * is the one the app selected; the remaining AniList titles are fallbacks for sites that
     * index a different language.
     */
    static queries(media, fallback, limit = 3) {
        const ordered = [];
        const seen = new Set();
        const add = (value) => {
            if (!value)
                return;
            const trimmed = String(value).trim();
            const key = trimmed.toLowerCase();
            if (trimmed && !seen.has(key)) {
                seen.add(key);
                ordered.push(trimmed);
            }
        };
        add(fallback);
        for (const title of AniListResolver.titles(media, ""))
            add(title);
        return ordered.slice(0, limit);
    }
    /** Release year: Seanime passes it at the top level, with startDate as the fallback. */
    static yearOf(opts) {
        if (opts && typeof opts.year === "number" && opts.year > 0)
            return opts.year;
        const media = opts && opts.media;
        if (media && media.startDate && typeof media.startDate.year === "number")
            return media.startDate.year;
        return undefined;
    }
}
class Provider {
    constructor() {
        this.mainUrl = "https://api.themoviedb.org";
        this.defaultHeaders = { "Referer": "https://api.themoviedb.org/" };
    }
    getSettings() {
        return {
            canSmartSearch: true,
            smartSearchFilters: ["query", "episodeNumber", "resolution", "batch"],
            supportsAdult: false,
            type: "main",
        };
    }
    async search(opts) {
        // Query by the AniList title so the tracker is searched for the exact show Seanime
        // is displaying, not for whatever string the caller happened to pass in.
        const media = opts.media;
        const fallbackQuery = (opts.query || "").trim();
        const candidates = AniListResolver.queries(media, fallbackQuery, 2);
        const q = encodeURIComponent(candidates[0] || fallbackQuery);
        const searchUrl = CsCompat.fixUrl("/search?keyword={query}".replace("{query}", q), this.mainUrl);
        const res = await fetch(searchUrl, { headers: this.defaultHeaders });
        if (!res || res.status >= 400) {
            return [];
        }
        const html = await res.text();
        const $ = LoadDoc(html);
        const torrents = [];
        $("table.torrent-list tbody tr, table tbody tr, div.torrent-item, ul.list li").each((_, el) => {
            const titleEl = el.find("a.title, td.name a, td:nth-child(2) a, a").first();
            const title = (titleEl.text() || "").trim();
            if (!title)
                return;
            const magnet = el.find("a[href^='magnet:?']").first().attr("href") || "";
            const pageHref = el.find("a[href*='/view/'], td:nth-child(2) a").first().attr("href")
                || titleEl.attr("href") || "";
            const pageUrl = pageHref ? CsCompat.fixUrl(pageHref, this.mainUrl) : "";
            if (!magnet && !pageUrl)
                return;
            const hashMatch = magnet.match(/btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})/i);
            const seedersText = el.find("td:nth-child(6), .seeders, td.seeds").first().text() || "";
            const leechersText = el.find("td:nth-child(7), .leechers, td.leeches").first().text() || "";
            const sizeText = el.find("td:nth-child(4), .size, td.size").first().text() || "";
            const dateText = el.find("td:nth-child(5), .date").first().text() || "";
            const epMatch = title.match(/(?:^|[\s\-_])S\d{1,2}E(\d{1,4})|(?:^|[\s\-_])E(?:p(?:isode)?)?\.?\s?(\d{1,4})(?:\D|$)/i);
            const epNum = epMatch ? parseInt(epMatch[1] || epMatch[2], 10) : 0;
            torrents.push({
                name: title,
                date: dateText.trim(),
                size: 0,
                formattedSize: sizeText.trim() || "Unknown",
                seeders: parseInt(seedersText, 10) || 0,
                leechers: parseInt(leechersText, 10) || 0,
                downloadCount: 0,
                link: pageUrl || magnet,
                downloadUrl: magnet || pageUrl,
                magnetLink: magnet,
                infoHash: hashMatch ? hashMatch[1].toLowerCase() : "",
                resolution: CsCompat.inferQuality(title),
                isBatch: /batch|complete|\bS\d{1,2}\b(?!E)/i.test(title),
                episodeNumber: epNum > 0 ? epNum : undefined,
                isBestRelease: false,
                confirmed: !!magnet,
            });
        });
        return torrents;
    }
    async smartSearch(opts) {
        // AniList title first, then the episode/resolution filters Seanime collected.
        const baseQuery = AniListResolver.queries(opts.media, (opts.query || "").trim(), 1)[0] || (opts.query || "");
        const epTag = opts.episodeNumber > 0 ? (" " + String(opts.episodeNumber).padStart(2, "0")) : "";
        const resTag = opts.resolution ? (" " + opts.resolution) : "";
        const combinedQuery = (baseQuery + epTag + resTag).trim();
        const results = await this.search({ media: opts.media, query: combinedQuery });
        if (!opts.episodeNumber || opts.episodeNumber <= 0) {
            return results;
        }
        const matching = results.filter((t) => t.episodeNumber === opts.episodeNumber);
        return matching.length > 0 ? matching : results;
    }
    async getTorrentInfoHash(torrent) {
        if (torrent.infoHash)
            return torrent.infoHash;
        const m = (torrent.magnetLink || "").match(/btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})/i);
        return m ? m[1].toLowerCase() : "";
    }
    async getTorrentMagnetLink(torrent) {
        return torrent.magnetLink || torrent.downloadUrl || torrent.link;
    }
}
