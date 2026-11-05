import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Dict, Optional

_FALLBACK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloudstream-compat", "generic-fallbacks.json")


def load_generic_fallbacks() -> Dict[str, str]:
    """Loads the shared generic-selector sets (also used by the validator to detect template-only conversions)."""
    try:
        with open(_FALLBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "search_item": "div.film_list-wrap div.flw-item, article.bs, ul.items li, .result-item",
            "search_title": "h3 a, .film-name a, .title, a",
            "episode_list": "ul.episodes li a, div.eplister ul li a, .ep-item a, a.ep-link",
            "server_link": "iframe[src], div.server-item[data-embed], a[data-video], source[src]",
            "search_url_pattern": "/search?keyword={query}",
        }

@dataclass
class ParsedProviderAST:
    class_name: str
    main_url: str
    name: str
    lang: str
    has_dub_support: bool
    tv_types: List[str]
    search_url_pattern: str
    search_item_selector: str
    search_title_selector: str
    search_href_selector: str
    episode_list_selector: str
    episode_href_selector: str
    episode_num_selector: str
    server_link_selector: str
    direct_regex_patterns: List[str]
    extractor_hosts: List[str]
    custom_headers: Dict[str, str]
    is_torrent_provider: bool
    raw_methods: Dict[str, str] = field(default_factory=dict)
    uses_webview_captcha: bool = False
    uses_generic_selectors: bool = True
    recovered_methods: List[str] = field(default_factory=list)

_META_SELECTOR_RE = re.compile(r"^(h[1-6]|img|p|span|a|title|time|meta)(\s|$|\.|#|\[|:)")
_URL_RE = re.compile(r"^https?://[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}(?:[/?#]|$)")


_NON_SITE_HOSTS = (
    "mp4upload.com", "streamwish.com", "streamtape.com", "dood.", "filemoon.", "vidhide.",
    "voe.sx", "kwik.", "gogocdn.", "vidstreaming.", "sibnet.", "ok.ru", "rapidcloud.",
    "google.com", "googleapis.com", "gstatic.com", "cloudflare.com", "jsdelivr.net",
    "jquery.com", "w3.org", "schemas.android.com", "discord.gg", "discord.com",
    "github.com", "githubusercontent.com", "youtube.com", "youtu.be", "twitter.com",
    "facebook.com", "t.me", "whatsapp.com", "cloudfront.net", "akamaihd.net",
)


def _is_real_url(value: str) -> bool:
    """Rejects string-pool noise like "http:" or "https://cdn" that is not a site base URL."""
    return bool(value) and bool(_URL_RE.match(value))


def _guess_site_url(candidates: List[str]) -> str:
    """Picks the most frequently referenced plausible site host from a string pool.

    The first URL in a DEX string pool is usually a CDN or player host, not the provider's
    own domain, so frequency is a far better signal than position.
    """
    counts: Dict[str, int] = {}
    schemes: Dict[str, str] = {}
    for url in candidates or []:
        if not _is_real_url(url):
            continue
        host = urllib.parse.urlparse(url).hostname or ""
        if not host:
            continue
        lowered = host.lower()
        if any(lowered == bad or lowered.endswith("." + bad) or bad in lowered for bad in _NON_SITE_HOSTS):
            continue
        counts[lowered] = counts.get(lowered, 0) + 1
        schemes.setdefault(lowered, "https" if url.startswith("https://") else "http")
    if not counts:
        return ""
    best = max(counts.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
    return f"{schemes.get(best, 'https')}://{best}"


def _is_meta_selector(selector: str) -> bool:
    """True for selectors that target a page heading/poster/link rather than a list of items.

    Cloudstream providers commonly select the page title before the episode list, so
    "first .select() in load()" is not a reliable way to find the episode selector.
    """
    if not selector:
        return True
    lowered = selector.lower()
    if any(token in lowered for token in ("episode", "epl", "ep-", "item", "result", "list")):
        return False
    return bool(_META_SELECTOR_RE.match(lowered))


_INTERP = re.compile(r"\$\{[^}]*\}|\$query\b|\$q\b")


def _finish_search_path(literal: str, param_key: str = None) -> str:
    """Normalises a captured path fragment into a URL pattern containing {query}.

    `param_key` is the name the provider passes the query under (mapOf("q" to query)); it is
    the only reliable source when the path itself carries no placeholder.
    """
    value = _INTERP.sub("{query}", literal)
    # JADX leaves the Kotlin method call behind: "/search/$query.encodeUri()}"
    value = re.sub(r"\.encodeU\w*\(\)\}?", "", value)
    value = value.strip()

    if "{query}" in value:
        return value
    if param_key:
        return value + ("&" if "?" in value else "?") + f"{param_key}={{query}}"
    if value.endswith(("=", "/")):
        return value + "{query}"
    if "?" in value:
        return value + "&q={query}"
    return value + "?q={query}"


_SEARCH_TOKENS = ("search", "find", "?q=", "?s=", "keyword", "query=")
_PAGINATION = re.compile(r"page=|/page/", re.I)
_PLAYER = re.compile(r"player|embed|proxy|ajax|csrf", re.I)


def _candidate_score(literal: str) -> int:
    """How likely this string literal is the search endpoint rather than a homepage,
    a pagination link or an embed player URL."""
    low = literal.lower()
    score = 0
    if any(token in low for token in _SEARCH_TOKENS):
        score += 100
    if "{query}" in literal or "$query" in literal or "${query}" in literal:
        score += 40
    if _PAGINATION.search(low):
        score -= 60
    if _PLAYER.search(low):
        score -= 50
    if literal.strip() in ("/", ""):
        score -= 100
    return score


def _extract_search_url(block: str, generic_pattern: str) -> str:
    """Finds the search URL a provider uses, across Kotlin and JADX-decompiled Java.

    The old version only recognised one Kotlin shape, `app.get("$mainUrl...")`. JADX output
    never looks like that -- it becomes `app.get(this.mainUrl + "/search?q=" + str, ...)` --
    so every strategy-2 provider silently fell back to `/search?keyword={query}`, which 404s
    on most sites. That single miss affected 365 of 383 bundles.
    """
    if not block:
        return generic_pattern

    # A query parameter map is the strongest hint when the path has no placeholder:
    # params = mapOf("q" to query)  /  ImmutableMap.of("q", str)
    param_key = None
    match = re.search(r'mapOf\(\s*"([\w\[\]]+)"\s+to\s+', block)
    if match:
        param_key = match.group(1)
    else:
        match = re.search(r'(?:ImmutableMap|HashMap|LinkedHashMap)\.of\(\s*"([\w\[\]]+)"\s*,\s*', block)
        if match:
            param_key = match.group(1)

    # Collect every plausible candidate instead of taking the first one. The search block is
    # often the whole file (method extraction can fail on decompiled Java), and the first
    # `$mainUrl` literal in a provider file is usually the homepage -- which produced
    # "/{query}" for 79 bundles and a pagination link for 24 more.
    candidates = []
    for match in re.finditer(r'"\$mainUrl([^"]*)"', block):
        if match.group(1).strip():
            candidates.append(match.group(1))
    # JADX renders the property as a field (this.mainUrl) or as a getter (getMainUrl())
    for match in re.finditer(r'(?:this\.)?(?:mainUrl|getMainUrl\(\))\s*\+\s*"([^"]*)"', block):
        if match.group(1).strip():
            candidates.append(match.group(1))
    for literal in re.findall(r'"([^"]{2,160})"', block):
        if literal.startswith("/") and ("{query}" in literal or "$query" in literal or "${query}" in literal):
            candidates.append(literal)

    if candidates:
        best = max(candidates, key=_candidate_score)
        if _candidate_score(best) > 0:
            return _finish_search_path(best, param_key)

    if param_key:
        return f"/search?{param_key}={{query}}"

    return generic_pattern


class KotlinJavaASTParser:
    """Extracts structural AST semantics from Cloudstream Kotlin source or JADX Java decompilation."""

    def parse_source(self, source_code: str, fallback_urls: List[str] = None, fallback_selectors: List[str] = None) -> ParsedProviderAST:
        fallback_urls = fallback_urls or []
        fallback_selectors = fallback_selectors or []
        generic = load_generic_fallbacks()

        cls_m = re.search(r"class\s+(\w+)\s*(?:[:(]|extends\s+MainAPI)", source_code)
        class_name = cls_m.group(1) if cls_m else "ConvertedCloudstreamProvider"

        url_m = re.search(r'(?:mainUrl|MAIN_URL)\s*=\s*"(https?://[^"]+)"', source_code)
        if url_m and _is_real_url(url_m.group(1)):
            main_url = url_m.group(1).rstrip("/")
        else:
            main_url = _guess_site_url(fallback_urls)

        name_m = re.search(r'override\s+var\s+name\s*=\s*"([^"]+)"', source_code)
        name = name_m.group(1) if name_m else class_name

        lang_m = re.search(r'override\s+var\s+lang\s*=\s*"([^"]+)"', source_code)
        lang = lang_m.group(1) if lang_m else "en"

        has_dub = "DubStatus.Dubbed" in source_code or "dub" in source_code.lower()
        is_torrent = "TvType.Torrent" in source_code or "magnet:?" in source_code or "seeders" in source_code.lower()

        tv_types = re.findall(r"TvType\.(\w+)", source_code)
        if not tv_types:
            tv_types = ["Torrent"] if is_torrent else ["Anime"]

        # Extract method blocks
        raw_methods: Dict[str, str] = {}
        for m_name in ("search", "load", "loadLinks"):
            pat = re.compile(rf"(?:override\s+suspend\s+fun|public\s+Object)\s+{m_name}\s*\([^)]*\)[^{{]*\{{", re.S)
            m = pat.search(source_code)
            if m:
                start = m.end()
                depth = 1
                idx = start
                while idx < len(source_code) and depth > 0:
                    if source_code[idx] == "{":
                        depth += 1
                    elif source_code[idx] == "}":
                        depth -= 1
                    idx += 1
                raw_methods[m_name] = source_code[start:idx - 1]

        search_block = raw_methods.get("search", source_code)
        load_block = raw_methods.get("load", source_code)
        links_block = raw_methods.get("loadLinks", source_code)

        # Discover search URL pattern (Kotlin templates and JADX Java concatenation)
        search_url_pattern = _extract_search_url(search_block, generic["search_url_pattern"])

        # Discover Jsoup selectors in search, load, loadLinks
        search_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', search_block)
        load_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', load_block)
        link_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', links_block)

        search_primary = [s for s in search_sels if not _is_meta_selector(s)]
        search_meta = [s for s in search_sels if _is_meta_selector(s)]
        load_primary = [s for s in load_sels if not _is_meta_selector(s)]
        load_meta = [s for s in load_sels if _is_meta_selector(s)]

        search_item_sel = (search_primary[0] if search_primary
                           else (fallback_selectors[0] if fallback_selectors else generic["search_item"]))
        if search_meta:
            search_title_sel = search_meta[0]
        elif len(search_primary) > 1:
            search_title_sel = search_primary[1]
        else:
            search_title_sel = generic["search_title"]
        search_href_sel = "a"

        ep_list_sel = (load_primary[0] if load_primary
                       else (fallback_selectors[1] if len(fallback_selectors) > 1 else generic["episode_list"]))
        ep_href_sel = "a"
        ep_num_sel = next((s for s in load_primary if s != ep_list_sel), None) or (load_meta[1] if len(load_meta) > 1 else ".epl-num, .ep-num")

        srv_sel = link_sels[0] if link_sels else generic["server_link"]

        recovered = [
            s for s, is_recovered in (
                (search_item_sel, bool(search_primary)),
                (search_title_sel, bool(search_meta) or len(search_primary) > 1),
                (ep_list_sel, bool(load_primary)),
                (srv_sel, bool(link_sels)),
            ) if is_recovered and s
        ]
        uses_generic_selectors = len(recovered) == 0

        regexes = re.findall(r'Regex\(\s*"([^"]+)"\s*\)', links_block)
        if not regexes:
            regexes = [r'(https?://[^"\'\s]+\.(?:m3u8|mp4)(?:\?[^"\'\s]+)?)']

        extractors = re.findall(r"(Vidstream|StreamTape|Mp4Upload|Dood|Filemoon|StreamWish|VidHide|Voe|KwIk|GogoCDN|Sibnet|OkRu)", source_code, re.I)
        uses_cf = "CloudflareKiller" in source_code or "WebViewResolver" in source_code

        headers: Dict[str, str] = {"Referer": main_url + "/"} if main_url else {}
        for hm in re.finditer(r'"(Referer|Origin|User-Agent|X-Requested-With)"\s+to\s+"([^"]+)"', source_code):
            headers[hm.group(1)] = hm.group(2)

        return ParsedProviderAST(
            class_name=class_name,
            main_url=main_url,
            name=name,
            lang=lang,
            has_dub_support=has_dub,
            tv_types=tv_types,
            search_url_pattern=search_url_pattern,
            search_item_selector=search_item_sel,
            search_title_selector=search_title_sel,
            search_href_selector=search_href_sel,
            episode_list_selector=ep_list_sel,
            episode_href_selector=ep_href_sel,
            episode_num_selector=ep_num_sel,
            server_link_selector=srv_sel,
            direct_regex_patterns=regexes,
            extractor_hosts=list(dict.fromkeys([e.lower() for e in extractors])) or ["default", "vidstreaming", "streamwish", "mp4upload"],
            custom_headers=headers,
            is_torrent_provider=is_torrent,
            raw_methods=raw_methods,
            uses_webview_captcha=uses_cf,
            uses_generic_selectors=uses_generic_selectors,
            recovered_methods=sorted(raw_methods.keys())
        )
