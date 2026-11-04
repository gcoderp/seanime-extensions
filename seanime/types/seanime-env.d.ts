// Seanime extension API — authoritative shapes.
//
// Transcribed from the Seanime application source so a converted extension is type-checked
// against what the app actually sends and expects:
//   internal/extension_repo/goja_onlinestream_test/onlinestream-provider.d.ts
//   internal/extension_repo/goja_torrent_test/anime-torrent-provider.d.ts
//   internal/extension_repo/goja_manga_test/manga-provider.d.ts
//   internal/extension/hibike/{onlinestream,torrent,manga}/types.go
//   internal/goja/goja_bindings/*.go  (the globals below)
//
// Notable consequences for converted Cloudstream providers:
//   * AniList titles arrive as `media.romajiTitle` / `media.englishTitle` / `media.synonyms`,
//     NOT as `media.title.romaji`.
//   * The release year is `opts.year` (top level), with `media.startDate.year` as backup.
//   * VideoSourceType is "mp4" | "m3u8" | "unknown" — there is no "dash".
//   * LoadDoc(html) returns a *function*: `const $ = LoadDoc(html); $("a")`.
//   * A torrent provider must implement getLatest(), Seanime calls it.

declare type SubOrDub = "sub" | "dub" | "both";
declare type VideoSourceType = "mp4" | "m3u8" | "unknown";

declare interface Media {
    id: number;
    idMal?: number;
    status?: string;
    format?: string;
    englishTitle?: string;
    romajiTitle?: string;
    episodeCount?: number;
    absoluteSeasonOffset?: number;
    synonyms: string[];
    isAdult: boolean;
    startDate?: FuzzyDate;
}

declare interface FuzzyDate {
    year: number;
    month?: number;
    day?: number;
}

declare type SearchOptions = {
    media: Media;
    query: string;
    dub: boolean;
    year?: number;
};

declare type SearchResult = {
    id: string;
    title: string;
    url: string;
    subOrDub: SubOrDub;
};

declare type EpisodeDetails = {
    id: string;
    number: number;
    url: string;
    title?: string;
};

declare type VideoSubtitle = {
    id: string;
    url: string;
    language: string;
    isDefault: boolean;
};

declare type VideoSource = {
    url: string;
    type: VideoSourceType;
    // Quality or label, should be unique (e.g. "1080p", "1080p - English")
    quality: string;
    label?: string;
    subtitles: VideoSubtitle[];
};

declare type EpisodeServer = {
    server: string;
    headers: { [key: string]: string };
    videoSources: VideoSource[];
};

declare type Settings = {
    episodeServers: string[];
    supportsDub: boolean;
};

// ---------------------------------------------------------------- anime torrent

declare type AnimeProviderSmartSearchFilter = "batch" | "episodeNumber" | "resolution" | "query" | "bestReleases";
declare type AnimeProviderType = "main" | "special";

declare interface AnimeProviderSettings {
    canSmartSearch: boolean;
    smartSearchFilters: AnimeProviderSmartSearchFilter[];
    supportsAdult: boolean;
    type: AnimeProviderType;
}

declare interface AnimeSearchOptions {
    media: Media;
    query: string;
}

declare interface AnimeSmartSearchOptions {
    media: Media;
    query: string;
    batch: boolean;
    episodeNumber: number;
    resolution: string;
    anidbAID: number;
    anidbEID: number;
    bestReleases: boolean;
}

declare interface AnimeTorrent {
    name: string;
    date: string;
    size: number;
    formattedSize: string;
    seeders: number;
    leechers: number;
    downloadCount: number;
    link: string;
    downloadUrl: string;
    magnetLink?: string;
    infoHash?: string;
    resolution?: string;
    isBatch?: boolean;
    episodeNumber?: number;
    releaseGroup?: string;
    isBestRelease: boolean;
    confirmed: boolean;
}

// Aliases kept so generated code and older manifests keep compiling.
declare type TorrentProviderSettings = AnimeProviderSettings;
declare type TorrentSearchOptions = AnimeSearchOptions;
declare type TorrentSmartSearchOptions = AnimeSmartSearchOptions;

// ---------------------------------------------------------------- manga

declare type MangaSearchResult = {
    id: string;
    title: string;
    synonyms?: string[];
    year?: number;
    image?: string;
    imageHeaders?: { [key: string]: string };
};

declare type ChapterDetails = {
    id: string;
    url: string;
    title: string;
    chapter: string;
    index: number;
    scanlator?: string;
    language?: string;
    rating?: number;
    updatedAt?: string;
};

declare type ChapterPage = {
    url: string;
    index: number;
    headers: { [key: string]: string };
};

declare type QueryOptions = {
    query: string;
    year?: number;
};

declare type MangaSettings = {
    supportsMultiLanguage?: boolean;
    supportsMultiScanlator?: boolean;
};

// ---------------------------------------------------------------- Goja globals

interface GojaDocElement {
    text(): string;
    attr(name: string): string | undefined;
    html(): string;
    find(selector: string): GojaDocSelection;
    children(): GojaDocSelection;
    parent(): GojaDocSelection;
    parents(): GojaDocSelection;
    closest(selector: string): GojaDocSelection;
    hasClass(className: string): boolean;
    is(selector: string): boolean;
    length: number;
}

interface GojaDocSelection extends GojaDocElement {
    each(callback: (index: number, element: GojaDocElement) => void): void;
    map<T>(callback: (index: number, element: GojaDocElement) => T): T[];
    first(): GojaDocElement;
    last(): GojaDocElement;
    eq(index: number): GojaDocElement;
    filter(selector: string): GojaDocSelection;
    next(): GojaDocSelection;
    prev(): GojaDocSelection;
    siblings(): GojaDocSelection;
    data(key: string): string | undefined;
}

/** LoadDoc(html) returns a selector function, exactly like Seanime's Goja binding. */
declare function LoadDoc(html: string): (selector: string) => GojaDocSelection;

declare class Doc {
    constructor(html: string);
    find(selector: string): GojaDocSelection;
    text(): string;
    html(): string;
    length: number;
}

declare function fetch(url: string, init?: any): Promise<any>;
declare const console: {
    log(...args: any[]): void;
    info(...args: any[]): void;
    debug(...args: any[]): void;
    warn(...args: any[]): void;
    error(...args: any[]): void;
};

declare function $sleep(ms: number): Promise<void>;
declare function $getUserPreference(key: string, fallback?: any): any;
declare function $isOffline(): boolean;
declare function $toString(value: any): string;

declare const $scannerUtils: {
    normalizeTitle(title: string): string;
    buildSmartSearchTitles(input: any): string[];
};

declare const $torrentUtils: {
    getMagnetLinkFromTorrentData(data: string): string;
};

declare const Buffer: any;

declare namespace CryptoJS {
    namespace AES {
        function decrypt(cipherText: string, key: any, cfg?: any): { toString(encoder?: any): string };
        function encrypt(message: string, key: any, cfg?: any): { toString(): string };
    }
    namespace enc {
        const Utf8: any;
        const Base64: {
            parse(base64Str: string): any;
            stringify(wordArray: any): string;
        };
        const Hex: any;
    }
    namespace mode {
        const CBC: any;
        const ECB: any;
    }
    namespace pad {
        const Pkcs7: any;
    }
    function MD5(message: string): { toString(): string };
    function SHA256(message: string): { toString(): string };
}
