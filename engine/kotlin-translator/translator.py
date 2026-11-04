import json
import os
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Any


@dataclass
class TranslationResult:
    strategy_used: str
    provider_type: str
    typescript_code: str
    episode_servers: List[str]
    supports_dub: bool
    warnings: List[str]


TOKEN_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")


class CloudstreamToSeanimeTranslator:
    """Multi-strategy AST & IR translator (Kotlin AST -> JADX Java AST -> Smali IR) to Seanime TypeScript.

    The translator emits TypeScript only. JavaScript is produced by a real compiler
    (engine/ts-compiler) -- never by string surgery. See translator notes in FIXES.md.

    All emitted code is assembled with token substitution (``__TOKEN__``) instead of
    f-strings, because the generated source is full of regex literals whose ``{n}``
    quantifiers f-strings silently destroy.
    """

    def __init__(
        self,
        compat_shim_path: str = "seanime/compatibility/cloudstream-runtime-shim.ts",
        templates_dir: str = "seanime/templates",
        env_types_path: str = "../../../seanime/types/seanime-env.d.ts",
        anilist_resolver_path: str = "seanime/compatibility/anilist-resolver.ts"
    ):
        self.compat_shim_path = compat_shim_path
        self.templates_dir = templates_dir
        self.env_types_path = env_types_path
        self.anilist_resolver_path = anilist_resolver_path

    # ------------------------------------------------------------------ helpers

    def _read_compat_shim(self) -> str:
        if os.path.exists(self.compat_shim_path):
            with open(self.compat_shim_path, "r", encoding="utf-8") as f:
                return f.read().replace("export class CsCompat", "class CsCompat")
        return ""

    def _read_anilist_resolver(self) -> str:
        """Seanime is an AniList client; every provider matches results against AniList metadata."""
        if os.path.exists(self.anilist_resolver_path):
            with open(self.anilist_resolver_path, "r", encoding="utf-8") as f:
                return f.read().replace("export class AniListResolver", "class AniListResolver")
        return ""

    def _load_template(self, name: str) -> str:
        path = os.path.join(self.templates_dir, name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Extension template missing: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _fill(template: str, mapping: Dict[str, str]) -> str:
        out = template
        for key, value in mapping.items():
            out = out.replace(key, value)
        leftovers = sorted(set(TOKEN_RE.findall(out)))
        if leftovers:
            raise ValueError(f"Unsubstituted template tokens remain: {leftovers}")
        return out

    # ------------------------------------------------------------------ public API

    def translate_ast_to_seanime(
        self,
        plugin_id: str,
        ast_model: Any,
        extractor_runtime_ts: str,
        strategy_label: str,
        mirror_domains: Optional[List[str]] = None
    ) -> TranslationResult:
        shim_code = self._read_compat_shim()
        mirrors = list(mirror_domains or [ast_model.main_url])
        if ast_model.main_url not in mirrors:
            mirrors.insert(0, ast_model.main_url)

        warnings: List[str] = []
        if getattr(ast_model, "uses_webview_captcha", False):
            warnings.append("Upstream plugin references WebViewResolver/CloudflareKiller; only mirror fallback is available in Goja.")
        if getattr(ast_model, "uses_generic_selectors", False):
            warnings.append("No provider-specific CSS selectors were recovered; generic fallbacks are in use.")

        if ast_model.is_torrent_provider:
            return self._generate_torrent_provider(plugin_id, ast_model, shim_code, strategy_label, warnings)
        return self._generate_onlinestream_provider(
            plugin_id, ast_model, shim_code, extractor_runtime_ts, strategy_label, mirrors, warnings
        )

    # ------------------------------------------------------------------ onlinestream

    SEARCH_SITE_BODY = r"""        const queryEncoded = encodeURIComponent((query || "").trim());
        const searchPath = __SEARCH_URL_PATTERN__.replace("{query}", queryEncoded);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            searchPath,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const itemSelector = __SEARCH_ITEM_SELECTOR__;
        const titleSelector = __SEARCH_TITLE_SELECTOR__;
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

        return results;"""

    SEARCH_BODY = r"""        // AniList is the source of truth: Seanime passes the AniList media object, so the
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

        const year = media && typeof media.year === "number" ? media.year : undefined;
        results = AniListResolver.rank(results, (r: SearchResult) => r.title, media, year);

        if (opts.dub) {
            const dubs = results.filter((r: SearchResult) => r.subOrDub === "dub");
            if (dubs.length > 0) {
                results = dubs.concat(results.filter((r: SearchResult) => r.subOrDub !== "dub"));
            }
        }

        return results;"""

    FIND_EPISODES_BODY = r"""        const targetUrl = CsCompat.fixUrl(id, this.mainUrl);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            targetUrl,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const episodes: EpisodeDetails[] = [];
        const epSelector = __EPISODE_LIST_SELECTOR__;
        const epNumSelector = __EPISODE_NUM_SELECTOR__;

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
        return episodes;"""

    FIND_EPISODE_SERVER_BODY = r"""        const epUrl = CsCompat.fixUrl(episode.url || episode.id, this.mainUrl);
        const { text: html } = await CsCompat.fetchWithMirrorFallback(
            epUrl,
            this.mirrorDomains,
            { headers: this.defaultHeaders }
        );

        const $ = LoadDoc(html);
        const serverSelector = __SERVER_LINK_SELECTOR__;
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

        const requestedServer = (server && server !== "default") ? server.toLowerCase() : __DEFAULT_SERVER__;
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
        };"""

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

        template = self._load_template("onlinestream.template.ts")
        ts_code = self._fill(template, {
            "__ENV_TYPES_PATH__": self.env_types_path,
            "__ANILIST_RESOLVER__": self._read_anilist_resolver().strip(),
            "__PLUGIN_ID__": plugin_id,
            "__ORIGINAL_CLASS__": ast_model.class_name,
            "__CONVERSION_STRATEGY__": strategy_label,
            "__COMPAT_SHIM__": shim_code.strip(),
            "__EXTRACTOR_HELPERS__": extractor_runtime_ts.strip(),
            "__MAIN_URL__": json.dumps(ast_model.main_url),
            "__MIRROR_DOMAINS__": json.dumps(mirrors),
            "__DEFAULT_HEADERS__": json.dumps(ast_model.custom_headers),
            "__EPISODE_SERVERS__": json.dumps(servers),
            "__SUPPORTS_DUB__": "true" if ast_model.has_dub_support else "false",
            "__SEARCH_SITE_BODY__": self._fill(self.SEARCH_SITE_BODY, {
                "__SEARCH_URL_PATTERN__": json.dumps(ast_model.search_url_pattern),
                "__SEARCH_ITEM_SELECTOR__": json.dumps(ast_model.search_item_selector),
                "__SEARCH_TITLE_SELECTOR__": json.dumps(ast_model.search_title_selector),
            }),
            "__SEARCH_BODY__": self.SEARCH_BODY,
            "__FIND_EPISODES_BODY__": self._fill(self.FIND_EPISODES_BODY, {
                "__EPISODE_LIST_SELECTOR__": json.dumps(ast_model.episode_list_selector),
                "__EPISODE_NUM_SELECTOR__": json.dumps(ast_model.episode_num_selector),
            }),
            "__FIND_EPISODE_SERVER_BODY__": self._fill(self.FIND_EPISODE_SERVER_BODY, {
                "__SERVER_LINK_SELECTOR__": json.dumps(ast_model.server_link_selector),
                "__DEFAULT_SERVER__": json.dumps(str(servers[0])),
            }),
        })

        return TranslationResult(
            strategy_used=strategy_label,
            provider_type="onlinestream-provider",
            typescript_code=ts_code,
            episode_servers=servers,
            supports_dub=ast_model.has_dub_support,
            warnings=warnings
        )

    # ------------------------------------------------------------------ torrent

    TORRENT_SEARCH_BODY = r"""        // Query by the AniList title so the tracker is searched for the exact show Seanime
        // is displaying, not for whatever string the caller happened to pass in.
        const media = opts.media;
        const fallbackQuery = (opts.query || "").trim();
        const candidates = AniListResolver.queries(media, fallbackQuery, 2);
        const q = encodeURIComponent(candidates[0] || fallbackQuery);
        const searchUrl = CsCompat.fixUrl(__SEARCH_URL_PATTERN__.replace("{query}", q), this.mainUrl);
        const res = await fetch(searchUrl, { headers: this.defaultHeaders });
        if (!res || res.status >= 400) {
            return [];
        }

        const html = await res.text();
        const $ = LoadDoc(html);
        const torrents: AnimeTorrent[] = [];

        $(__TORRENT_ROW_SELECTOR__).each((_: number, el: GojaDocElement) => {
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

        return torrents;"""

    TORRENT_SMART_SEARCH_BODY = r"""        // AniList title first, then the episode/resolution filters Seanime collected.
        const baseQuery = AniListResolver.queries(opts.media, (opts.query || "").trim(), 1)[0] || (opts.query || "");
        const epTag = opts.episodeNumber > 0 ? (" " + String(opts.episodeNumber).padStart(2, "0")) : "";
        const resTag = opts.resolution ? (" " + opts.resolution) : "";
        const combinedQuery = (baseQuery + epTag + resTag).trim();
        const results = await this.search({ media: opts.media, query: combinedQuery });
        if (!opts.episodeNumber || opts.episodeNumber <= 0) {
            return results;
        }
        const matching = results.filter((t: AnimeTorrent) => t.episodeNumber === opts.episodeNumber);
        return matching.length > 0 ? matching : results;"""

    def _generate_torrent_provider(
        self,
        plugin_id: str,
        ast_model: Any,
        shim_code: str,
        strategy_label: str,
        warnings: List[str]
    ) -> TranslationResult:
        template = self._load_template("torrent.template.ts")
        ts_code = self._fill(template, {
            "__ENV_TYPES_PATH__": self.env_types_path,
            "__ANILIST_RESOLVER__": self._read_anilist_resolver().strip(),
            "__PLUGIN_ID__": plugin_id,
            "__ORIGINAL_CLASS__": ast_model.class_name,
            "__CONVERSION_STRATEGY__": strategy_label,
            "__COMPAT_SHIM__": shim_code.strip(),
            "__MAIN_URL__": json.dumps(ast_model.main_url),
            "__DEFAULT_HEADERS__": json.dumps(ast_model.custom_headers),
            "__TORRENT_SEARCH_BODY__": self._fill(self.TORRENT_SEARCH_BODY, {
                "__SEARCH_URL_PATTERN__": json.dumps(ast_model.search_url_pattern),
                "__TORRENT_ROW_SELECTOR__": json.dumps("table.torrent-list tbody tr, table tbody tr, div.torrent-item, ul.list li"),
            }),
            "__TORRENT_SMART_SEARCH_BODY__": self.TORRENT_SMART_SEARCH_BODY,
        })

        warnings.append("Torrent row selectors are heuristic; live verification against the tracker is required.")
        return TranslationResult(
            strategy_used=strategy_label,
            provider_type="anime-torrent-provider",
            typescript_code=ts_code,
            episode_servers=[],
            supports_dub=True,
            warnings=warnings
        )
