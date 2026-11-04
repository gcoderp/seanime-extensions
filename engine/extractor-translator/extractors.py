class ExtractorTranslator:
    """Generates reusable, Goja-compatible multi-host stream extractors for Seanime extensions.

    NOTE: this module deliberately uses plain strings + token substitution instead of
    f-strings. The generated code is full of regex literals containing `{n}` quantifiers,
    and f-strings silently mangle those (`{40}` -> `40`). Token substitution keeps every
    character of the emitted JavaScript exactly as written here.
    """

    RUNTIME_TEMPLATE = r"""
class ExtractorDispatcher {
    static MAX_DEPTH = __MAX_DEPTH__;

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
"""

    @staticmethod
    def generate_extractor_runtime_ts(max_recursion: int = 3) -> str:
        return ExtractorTranslator.RUNTIME_TEMPLATE.replace("__MAX_DEPTH__", str(int(max_recursion)))
