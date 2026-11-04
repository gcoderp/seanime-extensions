/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: GuardaPlay
// Original Class: ConvertedCloudstreamProvider
// Strategy Used: STRATEGY_2_JADX_JAVA_AST
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
        if (/\.mpd(\?|$)/i.test(url)) return "dash";
        if (/\.mp4(\?|$)/i.test(url)) return "mp4";
        return "m3u8";
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
    private mainUrl: string = "https://guardaplay.store";
    private mirrorDomains: string[] = ["https://guardaplay.store", "https://guardaplay.store"];
    private defaultHeaders: Record<string, string> = {"Referer": "https://guardaplay.store/"};

    getSettings(): Settings {
        return {
            episodeServers: ["default", "vidstreaming", "streamwish", "mp4upload"],
            supportsDub: false,
        };
    }

    async search(opts: SearchOptions): Promise<SearchResult[]> {
        const queryEncoded = encodeURIComponent((opts.query || "").trim());
        const searchPath = "/search?keyword={query}".replace("{query}", queryEncoded);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            searchPath,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const itemSelector = "li.post-lst > li, ul.post-lst > li";
        const titleSelector = "a.lnk-blk";
        const dubResults: SearchResult[] = [];
        const subResults: SearchResult[] = [];

        $(itemSelector).each((_: number, el: GojaDocElement) => {
            const titleEl = el.find(titleSelector).first();
            const rawTitle = (titleEl.text() || el.attr("title") || el.text() || "").trim();
            const rawHref = titleEl.attr("href") || el.find("a").first().attr("href") || el.attr("href") || "";
            if (!rawTitle || !rawHref) return;

            const fullUrl = CsCompat.fixUrl(rawHref, this.mainUrl);
            const isDubItem = /\b(dub|dubbed|dual[\s-]?audio)\b/i.test(rawTitle)
                || /(^|[-/])dub([-/]|$)/i.test(fullUrl);

            const result: SearchResult = {
                id: fullUrl,
                title: rawTitle,
                url: fullUrl,
                subOrDub: isDubItem ? "dub" : "sub",
            };
            if (isDubItem) {
                dubResults.push(result);
            } else {
                subResults.push(result);
            }
        });

        // Honour opts.dub by ordering matching entries first rather than dropping results.
        return opts.dub ? dubResults.concat(subResults) : subResults.concat(dubResults);
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
        const epSelector = "li.post-lst > li, ul.post-lst > li";
        const epNumSelector = "article";

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
        const serverSelector = "li.post-lst > li, ul.post-lst > li";
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
