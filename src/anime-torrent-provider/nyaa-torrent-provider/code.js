
// ============================================================================
// AUTO-GENERATED SEANIME TORRENT EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: NyaaTorrentProvider
// Original Class: NyaaTorrentProvider
// Strategy Used: STRATEGY_1_EMBEDDED_KOTLIN_SOURCE
// ============================================================================

// Cloudstream-to-Seanime Goja Runtime Compatibility Layer
// Injected into converted TypeScript extensions to bridge Cloudstream Kotlin idioms cleanly inside Goja.

class CsCompat {
    static fixUrl(url, baseUrl) {
        if (!url) return "";
        if (url.startsWith("http://") || url.startsWith("https://")) return url;
        if (url.startsWith("//")) return "https:" + url;
        const cleanBase = baseUrl.replace(/\/+$/, "");
        if (url.startsWith("/")) return cleanBase + url;
        return cleanBase + "/" + url;
    }

    static fixUrlNull(url, baseUrl) {
        if (!url) return null;
        return CsCompat.fixUrl(url, baseUrl);
    }

    static base64Decode(input) {
        try {
            if (typeof atob === "function") return atob(input);
            return CryptoJS.enc.Base64.parse(input).toString(CryptoJS.enc.Utf8);
        } catch {
            return "";
        }
    }

    static base64Encode(input) {
        try {
            if (typeof btoa === "function") return btoa(input);
            return CryptoJS.enc.Base64.stringify(CryptoJS.enc.Utf8.parse(input));
        } catch {
            return "";
        }
    }

    static unpackJs(packed) {
        // Unpacks Dean Edwards p,a,c,k,e,r obfuscated JS blocks without dynamic code execution
        const match = packed.match(/\x7d\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)/s);
        if (!match) return packed;
        let payload = match[1];
        const radix = parseInt(match[2], 10);
        const count = parseInt(match[3], 10);
        const symtab = match[4].split("|");

        const encodeBase = (num, base) => {
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
        pathOrUrl,
        domains[],
        options = {}
    ) {
        let lastErr = null;
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

    static inferQuality(labelOrUrl) {
        const m = labelOrUrl.match(/(2160|1440|1080|720|480|360)p?/i);
        if (m) return m[1] + "p";
        if (/4k|uhd/i.test(labelOrUrl)) return "2160p";
        if (/fhd/i.test(labelOrUrl)) return "1080p";
        if (/hd/i.test(labelOrUrl)) return "720p";
        return "auto";
    }

    static inferVideoType(url) {
        if (/\.m3u8(\?|$)/i.test(url) || url.includes("hls")) return "m3u8";
        if (/\.mpd(\?|$)/i.test(url)) return "dash";
        if (/\.mp4(\?|$)/i.test(url)) return "mp4";
        return "m3u8";
    }
}


class Provider {
    mainUrl = "https://nyaa.si";
    defaultHeaders = {"Referer": "https://nyaa.si/"};

    getSettings() {
        return {
            canSmartSearch: true,
            smartSearchFilters: ["query", "episodeNumber", "resolution", "batch"],
            supportsAdult: false,
            type: "main",
        };
    }

    async search(opts) {
        const q = encodeURIComponent(opts.query.trim());
        const searchUrl = CsCompat.fixUrl("/?f=0&c=1_2&q={query}".replace("{query}", q), this.mainUrl);
        const res = await fetch(searchUrl, { headers: this.defaultHeaders });
        const html = await res.text();
        const $ = LoadDoc(html);
        const torrents = [];

        $("table tbody tr, div.torrent-item, ul.list li").each((_, el) => {
            const title = (el.find("a.title, td.name a, a").first().text() || "").trim();
            const magnet = el.find("a[href^='magnet:?']").first().attr("href") || "";
            const link = CsCompat.fixUrl(el.find("a").first().attr("href") || "", this.mainUrl);
            if (!title || (!magnet && !link)) return;

            const hashMatch = magnet.match(/btih:([a-fA-F0-9]40|[a-zA-Z2-7]32)/i);
            const seedersText = el.find(".seeders, td.seeds").first().text() || "1";
            const leechersText = el.find(".leechers, td.leeches").first().text() || "0";

            torrents.push({
                name: title,
                date: new Date().toISOString(),
                size: 0,
                formattedSize: el.find(".size, td.size").first().text() || "Unknown",
                seeders: parseInt(seedersText, 10) || 1,
                leechers: parseInt(leechersText, 10) || 0,
                downloadCount: 0,
                link: link || magnet,
                downloadUrl: magnet || link,
                magnetLink: magnet,
                infoHash: hashMatch ? hashMatch[1].toLowerCase() : "",
                resolution: CsCompat.inferQuality(title),
                isBatch: /batch|complete/i.test(title),
                confirmed: true,
            });
        });

        return torrents;
    }

    async smartSearch(opts) {
        const epTag = opts.episodeNumber > 0 ? (" " + String(opts.episodeNumber).padStart(2, "0")) : "";
        const resTag = opts.resolution ? (" " + opts.resolution) : "";
        const combinedQuery = (opts.query + epTag + resTag).trim();
        return await this.search({ media: opts.media, query: combinedQuery });
    }

    async getTorrentInfoHash(torrent) {
        return torrent.infoHash || "";
    }

    async getTorrentMagnetLink(torrent) {
        return torrent.magnetLink || torrent.downloadUrl || torrent.link;
    }
}
