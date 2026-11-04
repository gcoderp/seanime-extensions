/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME TORRENT EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: ViStreamProvider
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

class Provider {
    private mainUrl: string = "https://streameeeeee.site";
    private defaultHeaders: Record<string, string> = {"Referer": "https://streameeeeee.site/"};

    getSettings(): TorrentProviderSettings {
        return {
            canSmartSearch: true,
            smartSearchFilters: ["query", "episodeNumber", "resolution", "batch"],
            supportsAdult: false,
            type: "main",
        };
    }

    async search(opts: TorrentSearchOptions): Promise<AnimeTorrent[]> {
        const q = encodeURIComponent((opts.query || "").trim());
        const searchUrl = CsCompat.fixUrl("/search?keyword={query}".replace("{query}", q), this.mainUrl);
        const res = await fetch(searchUrl, { headers: this.defaultHeaders });
        if (!res || res.status >= 400) {
            return [];
        }

        const html = await res.text();
        const $ = LoadDoc(html);
        const torrents: AnimeTorrent[] = [];

        $("table.torrent-list tbody tr, table tbody tr, div.torrent-item, ul.list li").each((_: number, el: GojaDocElement) => {
            const titleEl = el.find("a.title, td.name a, td:nth-child(2) a, a").first();
            const title = (titleEl.text() || "").trim();
            if (!title) return;

            const magnet = el.find("a[href^='magnet:?']").first().attr("href") || "";
            const pageHref = el.find("a[href*='/view/'], td:nth-child(2) a").first().attr("href")
                || titleEl.attr("href") || "";
            const pageUrl = pageHref ? CsCompat.fixUrl(pageHref, this.mainUrl) : "";
            if (!magnet && !pageUrl) return;

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
                confirmed: !!magnet,
            });
        });

        return torrents;
    }

    async smartSearch(opts: TorrentSmartSearchOptions): Promise<AnimeTorrent[]> {
        const epTag = opts.episodeNumber > 0 ? (" " + String(opts.episodeNumber).padStart(2, "0")) : "";
        const resTag = opts.resolution ? (" " + opts.resolution) : "";
        const combinedQuery = ((opts.query || "") + epTag + resTag).trim();
        const results = await this.search({ media: opts.media, query: combinedQuery });
        if (!opts.episodeNumber || opts.episodeNumber <= 0) {
            return results;
        }
        const matching = results.filter((t: AnimeTorrent) => t.episodeNumber === opts.episodeNumber);
        return matching.length > 0 ? matching : results;
    }

    async getTorrentInfoHash(torrent: AnimeTorrent): Promise<string> {
        if (torrent.infoHash) return torrent.infoHash;
        const m = (torrent.magnetLink || "").match(/btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})/i);
        return m ? m[1].toLowerCase() : "";
    }

    async getTorrentMagnetLink(torrent: AnimeTorrent): Promise<string> {
        return torrent.magnetLink || torrent.downloadUrl || torrent.link;
    }
}
