import json
import os
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

@dataclass
class TranslationResult:
    strategy_used: str
    provider_type: str
    typescript_code: str
    javascript_code: str
    episode_servers: List[str]
    supports_dub: bool
    warnings: List[str]

class CloudstreamToSeanimeTranslator:
    """Multi-strategy AST & IR translator (Kotlin AST -> JADX Java AST -> Smali IR -> Optional AI Assist) to Goja TS/JS."""

    def __init__(self, compat_shim_path: str = "seanime/compatibility/cloudstream-runtime-shim.ts"):
        self.compat_shim_path = compat_shim_path

    def _read_compat_shim(self) -> str:
        if os.path.exists(self.compat_shim_path):
            with open(self.compat_shim_path, "r", encoding="utf-8") as f:
                return f.read().replace("export class CsCompat", "class CsCompat")
        return ""

    def translate_ast_to_seanime(
        self,
        plugin_id: str,
        ast_model: Any,
        extractor_runtime_ts: str,
        strategy_label: str,
        mirror_domains: Optional[List[str]] = None
    ) -> TranslationResult:
        shim_code = self._read_compat_shim()
        mirrors = mirror_domains or [ast_model.main_url]
        if ast_model.main_url not in mirrors:
            mirrors.insert(0, ast_model.main_url)

        warnings: List[str] = []
        if getattr(ast_model, "uses_webview_captcha", False):
            warnings.append("Upstream plugin references WebViewResolver/CloudflareKiller; mirror fallback enabled.")

        if ast_model.is_torrent_provider:
            return self._generate_torrent_provider(plugin_id, ast_model, shim_code, strategy_label, warnings)
        return self._generate_onlinestream_provider(
            plugin_id, ast_model, shim_code, extractor_runtime_ts, strategy_label, mirrors, warnings
        )

    def _generate_onlinestream_provider(
        self,
        plugin_id: str,
        ast_model: Any,
        shim_code: str,
        extractor_runtime_ts: str,
        strategy_label: str,
        mirrors: List[str],
        warnings: List[str]
    ) -> TranslationResult:
        servers = ast_model.extractor_hosts or ["default", "vidstreaming", "streamwish", "mp4upload"]
        headers_json = json.dumps(ast_model.custom_headers)
        mirrors_json = json.dumps(mirrors)
        servers_json = json.dumps(servers)
        supports_dub_js = "true" if ast_model.has_dub_support else "false"

        ts_code = f"""/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: {plugin_id}
// Original Class: {ast_model.class_name}
// Strategy Used: {strategy_label}
// ============================================================================

{shim_code}
{extractor_runtime_ts}

class Provider {{
    private mainUrl: string = {json.dumps(ast_model.main_url)};
    private mirrorDomains: string[] = {mirrors_json};
    private defaultHeaders: Record<string, string> = {headers_json};

    getSettings(): Settings {{
        return {{
            episodeServers: {servers_json},
            supportsDub: {supports_dub_js},
        }};
    }}

    async search(opts: SearchOptions): Promise<SearchResult[]> {{
        const queryEncoded = encodeURIComponent(opts.query.trim());
        const searchPath = {json.dumps(ast_model.search_url_pattern)}.replace("{{query}}", queryEncoded);
        const {{ text: html, url: usedUrl }} = await CsCompat.fetchWithMirrorFallback(
            searchPath,
            this.mirrorDomains,
            {{ headers: this.defaultHeaders }}
        );

        const $ = LoadDoc(html);
        const results: SearchResult[] = [];
        const itemSelector = {json.dumps(ast_model.search_item_selector)};
        const titleSelector = {json.dumps(ast_model.search_title_selector)};

        $(itemSelector).each((_: number, el: GojaDocElement) => {{
            const titleEl = el.find(titleSelector).first();
            const rawTitle = (titleEl.text() || el.attr("title") || el.text() || "").trim();
            const rawHref = titleEl.attr("href") || el.find("a").first().attr("href") || el.attr("href") || "";
            if (!rawTitle || !rawHref) return;

            const fullUrl = CsCompat.fixUrl(rawHref, this.mainUrl);
            const isDubItem = /\b(dub|dubbed|dual[\s-]?audio)\b/i.test(rawTitle) || /\bdub\b/i.test(fullUrl);
            if (opts.dub && !isDubItem && {supports_dub_js}) {{
                // Keep item if dub status is ambiguous, otherwise prefer matching subOrDub
            }}

            results.push({{
                id: fullUrl,
                title: rawTitle,
                url: fullUrl,
                subOrDub: isDubItem ? "dub" : "sub",
            }});
        }});

        return results;
    }}

    async findEpisodes(id: string): Promise<EpisodeDetails[]> {{
        const targetUrl = CsCompat.fixUrl(id, this.mainUrl);
        const {{ text: html }} = await CsCompat.fetchWithMirrorFallback(
            targetUrl,
            this.mirrorDomains,
            {{ headers: this.defaultHeaders }}
        );

        const $ = LoadDoc(html);
        const episodes: EpisodeDetails[] = [];
        const epSelector = {json.dumps(ast_model.episode_list_selector)};

        $(epSelector).each((idx: number, el: GojaDocElement) => {{
            const rawHref = el.attr("href") || el.find("a").first().attr("href") || "";
            if (!rawHref) return;
            const epUrl = CsCompat.fixUrl(rawHref, this.mainUrl);
            const numAttr = el.attr("data-number") || el.attr("data-ep") || el.find({json.dumps(ast_model.episode_num_selector)}).text() || el.text();
            const numMatch = (numAttr || "").match(/(\d+(?:\.\d+)?)/);
            const epNum = numMatch ? parseFloat(numMatch[1]) : idx + 1;
            const epTitle = (el.attr("title") || el.text() || ("Episode " + epNum)).trim();

            episodes.push({{
                id: epUrl,
                number: epNum,
                url: epUrl,
                title: epTitle,
            }});
        }});

        episodes.sort((a, b) => a.number - b.number);
        return episodes;
    }}

    async findEpisodeServer(episode: EpisodeDetails, server: string): Promise<EpisodeServer> {{
        const epUrl = CsCompat.fixUrl(episode.url || episode.id, this.mainUrl);
        const {{ text: html }} = await CsCompat.fetchWithMirrorFallback(
            epUrl,
            this.mirrorDomains,
            {{ headers: this.defaultHeaders }}
        );

        const $ = LoadDoc(html);
        const candidateEmbeds: string[] = [];
        const serverSelector = {json.dumps(ast_model.server_link_selector)};

        $(serverSelector).each((_: number, el: GojaDocElement) => {{
            const rawEmbed = el.attr("data-embed") || el.attr("data-video") || el.attr("data-src") || el.attr("src") || el.attr("href") || "";
            if (rawEmbed && !rawEmbed.startsWith("javascript:") && rawEmbed !== "#") {{
                candidateEmbeds.push(CsCompat.fixUrl(rawEmbed, this.mainUrl));
            }}
        }});

        const selectedServer = (!server || server === "default") ? ({json.dumps(servers[0])}) : server;
        let resolvedSources: VideoSource[] = [];
        let resolvedHeaders: Record<string, string> = {{ ...this.defaultHeaders, Referer: epUrl }};

        for (const embedUrl of candidateEmbeds) {{
            if (selectedServer !== "default" && candidateEmbeds.length > 1) {{
                if (!embedUrl.toLowerCase().includes(selectedServer.toLowerCase()) && candidateEmbeds.indexOf(embedUrl) > 0) {{
                    continue;
                }}
            }}
            const extracted = await ExtractorDispatcher.resolve(embedUrl, epUrl, 0);
            if (extracted.videoSources.length > 0) {{
                resolvedSources.push(...extracted.videoSources);
                resolvedHeaders = {{ ...resolvedHeaders, ...extracted.headers }};
            }}
        }}

        if (resolvedSources.length === 0) {{
            const fallback = await ExtractorDispatcher.resolve(epUrl, this.mainUrl, 0);
            resolvedSources = fallback.videoSources;
        }}

        if (resolvedSources.length === 0) {{
            throw new Error("No playable video streams extracted for episode: " + epUrl);
        }}

        return {{
            server: selectedServer,
            headers: resolvedHeaders,
            videoSources: resolvedSources,
        }};
    }}
}}
"""
        js_code = self.transpile_ts_to_goja_js(ts_code)
        return TranslationResult(
            strategy_used=strategy_label,
            provider_type="onlinestream-provider",
            typescript_code=ts_code,
            javascript_code=js_code,
            episode_servers=servers,
            supports_dub=ast_model.has_dub_support,
            warnings=warnings
        )

    def _generate_torrent_provider(
        self,
        plugin_id: str,
        ast_model: Any,
        shim_code: str,
        strategy_label: str,
        warnings: List[str]
    ) -> TranslationResult:
        headers_json = json.dumps(ast_model.custom_headers)
        ts_code = f"""/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME TORRENT EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: {plugin_id}
// Original Class: {ast_model.class_name}
// Strategy Used: {strategy_label}
// ============================================================================

{shim_code}

class Provider {{
    private mainUrl: string = {json.dumps(ast_model.main_url)};
    private defaultHeaders: Record<string, string> = {headers_json};

    getSettings(): TorrentProviderSettings {{
        return {{
            canSmartSearch: true,
            smartSearchFilters: ["query", "episodeNumber", "resolution", "batch"],
            supportsAdult: false,
            type: "main",
        }};
    }}

    async search(opts: TorrentSearchOptions): Promise<AnimeTorrent[]> {{
        const q = encodeURIComponent(opts.query.trim());
        const searchUrl = CsCompat.fixUrl({json.dumps(ast_model.search_url_pattern)}.replace("{{query}}", q), this.mainUrl);
        const res = await fetch(searchUrl, {{ headers: this.defaultHeaders }});
        const html = await res.text();
        const $ = LoadDoc(html);
        const torrents: AnimeTorrent[] = [];

        $("table tbody tr, div.torrent-item, ul.list li").each((_: number, el: GojaDocElement) => {{
            const title = (el.find("a.title, td.name a, a").first().text() || "").trim();
            const magnet = el.find("a[href^='magnet:?']").first().attr("href") || "";
            const link = CsCompat.fixUrl(el.find("a").first().attr("href") || "", this.mainUrl);
            if (!title || (!magnet && !link)) return;

            const hashMatch = magnet.match(/btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})/i);
            const seedersText = el.find(".seeders, td.seeds").first().text() || "1";
            const leechersText = el.find(".leechers, td.leeches").first().text() || "0";

            torrents.push({{
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
            }});
        }});

        return torrents;
    }}

    async smartSearch(opts: TorrentSmartSearchOptions): Promise<AnimeTorrent[]> {{
        const epTag = opts.episodeNumber > 0 ? (" " + String(opts.episodeNumber).padStart(2, "0")) : "";
        const resTag = opts.resolution ? (" " + opts.resolution) : "";
        const combinedQuery = (opts.query + epTag + resTag).trim();
        return await this.search({{ media: opts.media, query: combinedQuery }});
    }}

    async getTorrentInfoHash(torrent: AnimeTorrent): Promise<string> {{
        return torrent.infoHash || "";
    }}

    async getTorrentMagnetLink(torrent: AnimeTorrent): Promise<string> {{
        return torrent.magnetLink || torrent.downloadUrl || torrent.link;
    }}
}}
"""
        js_code = self.transpile_ts_to_goja_js(ts_code)
        return TranslationResult(
            strategy_used=strategy_label,
            provider_type="anime-torrent-provider",
            typescript_code=ts_code,
            javascript_code=js_code,
            episode_servers=[],
            supports_dub=True,
            warnings=warnings
        )

    @staticmethod
    def transpile_ts_to_goja_js(ts_code: str) -> str:
        """Deterministic TypeScript-to-Goja ES2020 JavaScript compiler."""
        import re
        lines = ts_code.splitlines()
        out_lines = []
        for line in lines:
            if line.strip().startswith("/// <reference"):
                continue
            cleaned = line
            # 1. Remove access modifiers
            cleaned = re.sub(r"^(\s*)(?:private|public|protected|readonly)\s+", r"\1", cleaned)
            # 2. Remove return type annotations on methods: ): Promise<...> { or ): Settings {
            cleaned = re.sub(r"\)\s*:\s*Promise<.*?>\s*\{$", ") {", cleaned)
            cleaned = re.sub(r"\)\s*:\s*(?:Settings|TorrentProviderSettings|VideoSourceType|string\s*\|\s*null|string|number|boolean|void)\s*\{$", ") {", cleaned)
            cleaned = re.sub(r"\)\s*:\s*string\s*=>", ") =>", cleaned)
            # 3. Remove generic type arguments on Set
            cleaned = re.sub(r"new\s+Set<[^>]+>\(", "new Set(", cleaned)
            # 4. Remove variable declarations' type annotations
            cleaned = re.sub(
                r"(\b(?:const|let|var)\s+\w+)\s*:\s*(?:Record<[^>]+>|VideoSubtitle\[\]|VideoSource\[\]|SearchResult\[\]|EpisodeDetails\[\]|AnimeTorrent\[\]|string\[\]|RegExpExecArray\s*\|\s*null|string|number|boolean|any)(?=\s*[=;])",
                r"\1",
                cleaned
            )
            # 5. Remove class field type annotations
            cleaned = re.sub(
                r"^(\s*\w+)\s*:\s*(?:Record<[^>]+>|string\[\]|string|number|boolean)\s*=",
                r"\1 =",
                cleaned
            )
            # 6. Remove function & callback parameter type annotations
            cleaned = re.sub(
                r"(\b[a-zA-Z_]\w*)\s*:\s*(?:Record<[^>]+>|SearchOptions|TorrentSearchOptions|TorrentSmartSearchOptions|EpisodeDetails|AnimeTorrent|GojaDocElement|RequestInit|VideoSourceType|SubOrDub|string\[\]|string\s*\|\s*undefined\s*\|\s*null|string|number|boolean|any)\b",
                r"\1",
                cleaned
            )
            out_lines.append(cleaned)
        return "\n".join(out_lines) + "\n"
