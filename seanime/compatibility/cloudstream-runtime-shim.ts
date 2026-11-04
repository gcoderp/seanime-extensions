// Cloudstream-to-Seanime Goja Runtime Compatibility Layer
// Injected into converted TypeScript extensions to bridge Cloudstream Kotlin idioms cleanly inside Goja.

export class CsCompat {
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
