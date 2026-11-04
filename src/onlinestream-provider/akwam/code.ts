/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: Akwam
// Original Class: Akwam
// Strategy Used: STRATEGY_1_GITHUB_SOURCE_RECOVERY
// ============================================================================

// Cloudstream-to-Seanime Goja Runtime Compatibility Layer
// Injected into converted TypeScript extensions to bridge Cloudstream Kotlin idioms cleanly inside Goja.

class CsCompat {
    static fixUrl(url: string, baseUrl: string): string {
        if (!url) return "";
        if (url.startsWith("http://") || url.startsWith("https://")) return url;
        if (url.startsWith("//")) return "https:" + url;
        const cleanBase = baseUrl.replace(/\/+$/, "");
        if (url.startsWith("/")) return cleanBase + url;
        return cleanBase + "/" + url;
    }

    static fixUrlNull(url: string | undefined | null, baseUrl: string): string | null {
        if (!url) return null;
        return CsCompat.fixUrl(url, baseUrl);
    }

    static base64Decode(input: string): string {
        try {
            if (typeof atob === "function") return atob(input);
            return CryptoJS.enc.Base64.parse(input).toString(CryptoJS.enc.Utf8);
        } catch {
            return "";
        }
    }

    static base64Encode(input: string): string {
        try {
            if (typeof btoa === "function") return btoa(input);
            return CryptoJS.enc.Base64.stringify(CryptoJS.enc.Utf8.parse(input));
        } catch {
            return "";
        }
    }

    static unpackJs(packed: string): string {
        // Unpacks Dean Edwards p,a,c,k,e,r obfuscated JS blocks without dynamic code execution
        const match = packed.match(/\x7d\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)/s);
        if (!match) return packed;
        let payload = match[1];
        const radix = parseInt(match[2], 10);
        const count = parseInt(match[3], 10);
        const symtab = match[4].split("|");

        const encodeBase = (num: number, base: number): string => {
            const chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
            if (num < base) return num < 36 ? num.toString(36) : chars[num];
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

    static async fetchWithMirrorFallback(
        pathOrUrl: string,
        domains: string[],
        options: RequestInit = {}
    ): Promise<{ text: string; url: string; status: number }> {
        let lastErr: any = null;
        for (const domain of domains) {
            const targetUrl = pathOrUrl.startsWith("http") ? pathOrUrl : CsCompat.fixUrl(pathOrUrl, domain);
            try {
                const res = await fetch(targetUrl, options);
                const text = await res.text();
                if (res.status < 500 && !text.includes("cf-browser-verification")) {
                    return { text, url: targetUrl, status: res.status };
                }
            } catch (e) {
                lastErr = e;
            }
        }
        throw lastErr || new Error("All mirror domains failed for " + pathOrUrl);
    }

    static inferQuality(labelOrUrl: string): string {
        const m = labelOrUrl.match(/(2160|1440|1080|720|480|360)p?/i);
        if (m) return m[1] + "p";
        if (/4k|uhd/i.test(labelOrUrl)) return "2160p";
        if (/fhd/i.test(labelOrUrl)) return "1080p";
        if (/hd/i.test(labelOrUrl)) return "720p";
        return "auto";
    }

    static inferVideoType(url: string): VideoSourceType {
        if (/\.m3u8(\?|$)/i.test(url) || url.includes("hls")) return "m3u8";
        if (/\.mpd(\?|$)/i.test(url)) return "unknown";
        if (/\.mp4(\?|$)/i.test(url)) return "mp4";
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
    static normalize(value: string): string {
        if (!value) return "";
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
    static stripNoise(value: string): string {
        let s = AniListResolver.normalize(value);
        s = s.replace(/\b(season|s)\s*\d+\b/g, " ");
        s = s.replace(/\b(part|cour)\s*\d+\b/g, " ");
        s = s.replace(/\b(sub|subbed|dub|dubbed|eng|english|jpn|japanese|raw)\b/g, " ");
        s = s.replace(/\b(tv|series|movie|ova|ona|special)\b/g, " ");
        s = s.replace(/\s+/g, " ").trim();
        return s;
    }

    /** Which season/part a title claims. 1 when the title says nothing. */
    static seasonOf(value: string): number {
        const s = AniListResolver.normalize(value);
        const numbered = s.match(/\b(?:season|part|cour|s)\s*(\d{1,2})\b/);
        if (numbered) return parseInt(numbered[1], 10);
        const roman = s.match(/\b(ii|iii|iv|v)\b/);
        if (roman) {
            const map: Record<string, number> = { ii: 2, iii: 3, iv: 4, v: 5 };
            return map[roman[1]] || 1;
        }
        return 1;
    }

    /** Dice coefficient over word tokens, with exact/containment shortcuts. */
    static similarity(a: string, b: string): number {
        if (!a || !b) return 0;
        if (a === b) return 1;
        if (a.length >= 4 && b.length >= 4 && (a.indexOf(b) !== -1 || b.indexOf(a) !== -1)) {
            return 0.9;
        }
        const ta = a.split(" ").filter((t: string) => t.length > 0);
        const tb = b.split(" ").filter((t: string) => t.length > 0);
        if (ta.length === 0 || tb.length === 0) return 0;
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
    static titles(media: any, fallback?: string): string[] {
        const out: string[] = [];
        const push = (value?: string) => {
            if (value && String(value).trim().length > 0) out.push(String(value).trim());
        };

        if (media) {
            push(media.romajiTitle);
            push(media.englishTitle);
            if (media.synonyms && media.synonyms.length) {
                for (const synonym of media.synonyms) push(synonym);
            }
        }
        push(fallback);

        const seen = new Set<string>();
        const unique: string[] = [];
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
    static score(resultTitle: string, media: any, year?: number): number {
        const target = AniListResolver.stripNoise(resultTitle);
        if (!target) return 0;

        let best = 0;
        const candidates = AniListResolver.titles(media, "");
        for (const candidate of candidates) {
            const plain = AniListResolver.similarity(target, AniListResolver.normalize(candidate));
            const stripped = AniListResolver.similarity(target, AniListResolver.stripNoise(candidate));
            const value = plain > stripped ? plain : stripped;
            if (value > best) best = value;
        }

        // Season disambiguation: "Season 2" must not resolve to the season 1 page, which is
        // the single most common wrong match for AniList-driven providers.
        const primary = AniListResolver.titles(media, "")[0] || "";
        const mediaSeason = AniListResolver.seasonOf(primary);
        const resultSeason = AniListResolver.seasonOf(resultTitle);
        if (mediaSeason !== resultSeason) {
            best -= 0.2;
        } else if (mediaSeason > 1) {
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
            if (format === "MOVIE" && looksMovie) best += 0.05;
            if (format !== "MOVIE" && looksMovie && best > 0) best -= 0.05;
        }

        return best;
    }

    /** Stable sort by AniList confidence, preserving site order for equal scores. */
    static rank<T>(items: T[], titleOf: (item: T) => string, media: any, year?: number): T[] {
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
    static queries(media: any, fallback?: string, limit: number = 3): string[] {
        const ordered: string[] = [];
        const seen = new Set<string>();
        const add = (value?: string) => {
            if (!value) return;
            const trimmed = String(value).trim();
            const key = trimmed.toLowerCase();
            if (trimmed && !seen.has(key)) {
                seen.add(key);
                ordered.push(trimmed);
            }
        };

        add(fallback);
        for (const title of AniListResolver.titles(media, "")) add(title);

        return ordered.slice(0, limit);
    }

    /** Release year: Seanime passes it at the top level, with startDate as the fallback. */
    static yearOf(opts: any): number | undefined {
        if (opts && typeof opts.year === "number" && opts.year > 0) return opts.year;
        const media = opts && opts.media;
        if (media && media.startDate && typeof media.startDate.year === "number") return media.startDate.year;
        return undefined;
    }
}

class ExtractorDispatcher {
    static MAX_DEPTH = 3;

    static async resolve(
        embedUrl: string,
        referer: string,
        depth: number = 0
    ): Promise<{ videoSources: VideoSource[]; headers: Record<string, string> }> {
        if (!embedUrl || depth > ExtractorDispatcher.MAX_DEPTH) {
            return { videoSources: [], headers: { Referer: referer } };
        }

        const headers: Record<string, string> = {
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        };

        // 1. Direct stream link check (.m3u8 / .mp4 / .mpd)
        if (/\.(m3u8|mp4|mpd)(\?|$)/i.test(embedUrl)) {
            return {
                headers,
                videoSources: [{
                    url: embedUrl,
                    type: CsCompat.inferVideoType(embedUrl),
                    quality: CsCompat.inferQuality(embedUrl),
                    subtitles: []
                }]
            };
        }

        const res = await fetch(embedUrl, { headers });
        if (!res || res.status >= 400) {
            return { videoSources: [], headers };
        }
        let body = await res.text();

        // 2. Unpack p,a,c,k,e,r obfuscated scripts if present
        if (body.indexOf("function(p,a,c,k,e") !== -1) {
            const unpacked = CsCompat.unpackJs(body);
            if (unpacked !== body) {
                body = unpacked;
            }
        }

        const subtitles: VideoSubtitle[] = [];
        const subRegex = /["']?file["']?\s*:\s*["'](https?:\/\/[^"']+\.(?:vtt|srt|ass))["'](?:[^}]*?["']?label["']?\s*:\s*["']([^"']+)["'])?/gi;
        let subMatch: RegExpExecArray | null;
        let subIdx = 0;
        while ((subMatch = subRegex.exec(body)) !== null) {
            subtitles.push({
                id: "sub-" + (subIdx++),
                url: subMatch[1],
                language: subMatch[2] || "English",
                isDefault: subIdx === 1
            });
        }

        const sources: VideoSource[] = [];
        const seenUrls = new Set<string>();

        // 3. Extract HLS (.m3u8) and MP4 links from player configuration or JSON payloads
        const mediaRegex = /(https?:\/\/[^"'\s<>]+?\.(?:m3u8|mp4)(?:\?[^"'\s<>]*)?)/gi;
        let m: RegExpExecArray | null;
        while ((m = mediaRegex.exec(body)) !== null) {
            const cleanUrl = m[1].replace(/\\\//g, "/");
            if (!seenUrls.has(cleanUrl)) {
                seenUrls.add(cleanUrl);
                sources.push({
                    url: cleanUrl,
                    type: CsCompat.inferVideoType(cleanUrl),
                    quality: CsCompat.inferQuality(cleanUrl),
                    subtitles
                });
            }
        }

        // 4. StreamTape custom token reconstruction
        if (sources.length === 0 && /streamtape\./i.test(embedUrl)) {
            const stMatch = body.match(/getElementById\(['"]robotlink['"]\)\.innerHTML\s*=\s*['"]([^'"]+)['"]\s*\+\s*\(['"]([^'"]+)['"]\)\.substring\((\d+)\)/i);
            if (stMatch) {
                const streamUrl = "https:" + stMatch[1] + stMatch[2].substring(parseInt(stMatch[3], 10));
                sources.push({
                    url: streamUrl,
                    type: "mp4",
                    quality: "720p",
                    subtitles
                });
            }
        }

        // 5. Recursive nested iframe resolution
        if (sources.length === 0 && depth < ExtractorDispatcher.MAX_DEPTH) {
            const $ = LoadDoc(body);
            const nestedIframe = $("iframe[src]").first().attr("src");
            if (nestedIframe) {
                const nextUrl = CsCompat.fixUrl(nestedIframe, embedUrl);
                if (nextUrl !== embedUrl) {
                    return await ExtractorDispatcher.resolve(nextUrl, embedUrl, depth + 1);
                }
            }
        }

        return { videoSources: sources, headers };
    }
}

class Provider {
    private mainUrl: string = "https://akwam.ss";
    private mirrorDomains: string[] = ["https://akwam.ss", "https://akwam.ss"];
    private defaultHeaders: Record<string, string> = {"Referer": "https://akwam.ss/", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"};

    getSettings(): Settings {
        return {
            episodeServers: ["default", "vidstreaming", "streamwish", "mp4upload"],
            supportsDub: false,
        };
    }

    private async searchSite(query: string): Promise<SearchResult[]> {
        const queryEncoded = encodeURIComponent((query || "").trim());
        const searchPath = "/search?keyword={query}".replace("{query}", queryEncoded);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            searchPath,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const itemSelector = "div.col-lg-auto.col-md-4.col-6";
        const titleSelector = "h3.entry-title a";
        const results: SearchResult[] = [];

        $(itemSelector).each((_: number, el: GojaDocElement) => {
            const titleEl = el.find(titleSelector).first();
            const rawTitle = (titleEl.text() || el.attr("title") || el.text() || "").trim();
            const rawHref = titleEl.attr("href") || el.find("a").first().attr("href") || el.attr("href") || "";
            if (!rawTitle || !rawHref) return;

            const fullUrl = CsCompat.fixUrl(rawHref, this.mainUrl);
            const isDubItem = /\b(dub|dubbed|dual[\s-]?audio)\b/i.test(rawTitle)
                || /(^|[-/])dub([-/]|$)/i.test(fullUrl);

            results.push({
                id: fullUrl,
                title: rawTitle,
                url: fullUrl,
                subOrDub: isDubItem ? "dub" : "sub",
            });
        });

        return results;
    }

    async search(opts: SearchOptions): Promise<SearchResult[]> {
        // AniList is the source of truth: Seanime passes the AniList media object, so the
        // provider searches by the AniList titles and then ranks what the site returned
        // against the same metadata. This is what keeps season 2 from resolving to season 1.
        const media = opts.media;
        const fallbackQuery = (opts.query || "").trim();
        const candidates = AniListResolver.queries(media, fallbackQuery, 3);

        let results: SearchResult[] = [];
        for (const candidate of candidates) {
            results = await this.searchSite(candidate);
            if (results.length > 0) break;
        }

        if (results.length === 0 && fallbackQuery && candidates.indexOf(fallbackQuery) === -1) {
            results = await this.searchSite(fallbackQuery);
        }

        // Seanime passes the release year at the top level of SearchOptions.
        const year = AniListResolver.yearOf(opts);
        results = AniListResolver.rank(results, (r: SearchResult) => r.title, media, year);

        if (opts.dub) {
            const dubs = results.filter((r: SearchResult) => r.subOrDub === "dub");
            if (dubs.length > 0) {
                results = dubs.concat(results.filter((r: SearchResult) => r.subOrDub !== "dub"));
            }
        }

        return results;
    }

    async findEpisodes(id: string): Promise<EpisodeDetails[]> {
        const targetUrl = CsCompat.fixUrl(id, this.mainUrl);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            targetUrl,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const episodes: EpisodeDetails[] = [];
        const epSelector = "div.font-size-16.text-white a[href*='/genre/'], div.font-size-16.text-white a[href*='/category/']";
        const epNumSelector = "div.font-size-16.text-white a[href*='/year/']";

        $(epSelector).each((idx: number, el: GojaDocElement) => {
            const rawHref = el.attr("href") || el.find("a").first().attr("href") || "";
            if (!rawHref) return;

            const epUrl = CsCompat.fixUrl(rawHref, this.mainUrl);
            const numAttr = el.attr("data-number") || el.attr("data-ep")
                || el.find(epNumSelector).text() || el.text() || "";
            const numMatch = String(numAttr).match(/(\d+(?:\.\d+)?)/);
            const epNum = numMatch ? parseFloat(numMatch[1]) : idx + 1;

            episodes.push({
                id: epUrl,
                number: epNum,
                url: epUrl,
                title: (el.attr("title") || el.text() || ("Episode " + epNum)).trim(),
            });
        });

        episodes.sort((a, b) => a.number - b.number);
        return episodes;
    }

    async findEpisodeServer(episode: EpisodeDetails, server: string): Promise<EpisodeServer> {
        const epUrl = CsCompat.fixUrl(episode.url || episode.id, this.mainUrl);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            epUrl,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const serverSelector = "a.link-download, a[href*='/download/']";
        const candidateEmbeds: string[] = [];

        $(serverSelector).each((_: number, el: GojaDocElement) => {
            const rawEmbed = el.attr("data-embed") || el.attr("data-video") || el.attr("data-src")
                || el.attr("src") || el.attr("href") || "";
            if (!rawEmbed || rawEmbed.indexOf("javascript:") === 0 || rawEmbed === "#") return;
            const embedUrl = CsCompat.fixUrl(rawEmbed, this.mainUrl);
            if (candidateEmbeds.indexOf(embedUrl) === -1) {
                candidateEmbeds.push(embedUrl);
            }
        });

        const requestedServer = (server && server !== "default") ? server.toLowerCase() : "default";
        const preferred = candidateEmbeds.filter((u: string) => u.toLowerCase().indexOf(requestedServer) !== -1);
        const ordered = preferred.concat(candidateEmbeds.filter((u: string) => preferred.indexOf(u) === -1));

        const videoSources: VideoSource[] = [];
        let headers: Record<string, string> = { ...this.defaultHeaders, Referer: epUrl };

        for (const embedUrl of ordered) {
            const extracted = await ExtractorDispatcher.resolve(embedUrl, epUrl, 0);
            if (extracted.videoSources.length > 0) {
                videoSources.push(...extracted.videoSources);
                headers = { ...headers, ...extracted.headers };
            }
        }

        if (videoSources.length === 0) {
            const fallback = await ExtractorDispatcher.resolve(epUrl, this.mainUrl, 0);
            videoSources.push(...fallback.videoSources);
            headers = { ...headers, ...fallback.headers };
        }

        if (videoSources.length === 0) {
            throw new Error("No playable video streams extracted for episode: " + epUrl);
        }

        return {
            server: requestedServer,
            headers,
            videoSources,
        };
    }
}
