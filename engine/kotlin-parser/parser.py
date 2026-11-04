import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

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

class KotlinJavaASTParser:
    """Extracts structural AST semantics from Cloudstream Kotlin source or JADX Java decompilation."""

    def parse_source(self, source_code: str, fallback_urls: List[str] = None, fallback_selectors: List[str] = None) -> ParsedProviderAST:
        fallback_urls = fallback_urls or []
        fallback_selectors = fallback_selectors or []

        cls_m = re.search(r"class\s+(\w+)\s*(?:[:(]|extends\s+MainAPI)", source_code)
        class_name = cls_m.group(1) if cls_m else "ConvertedCloudstreamProvider"

        url_m = re.search(r'(?:mainUrl|MAIN_URL)\s*=\s*"(https?://[^"]+)"', source_code)
        main_url = url_m.group(1).rstrip("/") if url_m else (fallback_urls[0].rstrip("/") if fallback_urls else "https://example.com")

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

        # Discover search URL pattern
        search_url_m = re.search(r'app\.get\(\s*"\$mainUrl([^"]+)"', search_block)
        if search_url_m:
            raw_p = search_url_m.group(1)
            search_url_pattern = re.sub(r"\$\{?query\}?", "{query}", raw_p)
        else:
            search_url_pattern = "/search?keyword={query}"

        # Discover Jsoup selectors in search, load, loadLinks
        search_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', search_block)
        load_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', load_block)
        link_sels = re.findall(r'\.select(?:First)?\(\s*"([^"]+)"\s*\)', links_block)

        search_item_sel = search_sels[0] if len(search_sels) >= 1 else (fallback_selectors[0] if fallback_selectors else "div.film_list-wrap div.flw-item, article.bs, ul.items li, .result-item")
        search_title_sel = search_sels[1] if len(search_sels) >= 2 else "h3 a, .film-name a, .title, a"
        search_href_sel = "a"

        ep_list_sel = load_sels[0] if len(load_sels) >= 1 else (fallback_selectors[1] if len(fallback_selectors) > 1 else "ul.episodes li a, div.eplister ul li a, .ep-item a, a.ep-link")
        ep_href_sel = "a"
        ep_num_sel = load_sels[1] if len(load_sels) >= 2 else ".epl-num, .ep-num"

        srv_sel = link_sels[0] if link_sels else "iframe[src], div.server-item[data-embed], a[data-video], source[src]"

        regexes = re.findall(r'Regex\(\s*"([^"]+)"\s*\)', links_block)
        if not regexes:
            regexes = [r'(https?://[^"\'\s]+\.(?:m3u8|mp4)(?:\?[^"\'\s]+)?)']

        extractors = re.findall(r"(Vidstream|StreamTape|Mp4Upload|Dood|Filemoon|StreamWish|VidHide|Voe|KwIk|GogoCDN|Sibnet|OkRu)", source_code, re.I)
        uses_cf = "CloudflareKiller" in source_code or "WebViewResolver" in source_code

        headers: Dict[str, str] = {"Referer": main_url + "/"}
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
            uses_webview_captcha=uses_cf
        )
