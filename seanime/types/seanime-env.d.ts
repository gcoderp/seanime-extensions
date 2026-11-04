// Official Seanime Goja Runtime & Extension API Type Definitions
declare type SubOrDub = "sub" | "dub" | "both";
declare type VideoSourceType = "m3u8" | "mp4" | "dash" | "unknown";

interface Settings {
    episodeServers: string[];
    supportsDub: boolean;
}

interface SearchOptions {
    media: {
        id: number;
        idMal?: number;
        title: {
            romaji?: string;
            english?: string;
            native?: string;
        };
        synonyms?: string[];
        year?: number;
        format?: string;
    };
    query: string;
    dub: boolean;
    year?: number;
}

interface SearchResult {
    id: string;
    title: string;
    url: string;
    subOrDub: SubOrDub;
}

interface EpisodeDetails {
    id: string;
    number: number;
    url: string;
    title?: string;
}

interface VideoSubtitle {
    id: string;
    url: string;
    language: string;
    isDefault: boolean;
}

interface VideoSource {
    url: string;
    type: VideoSourceType;
    quality: string;
    subtitles: VideoSubtitle[];
}

interface EpisodeServer {
    server: string;
    headers: Record<string, string>;
    videoSources: VideoSource[];
}

// Anime Torrent Provider Types
interface AnimeTorrent {
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
    isBestRelease?: boolean;
    confirmed: boolean;
}

interface TorrentSearchOptions {
    media: SearchOptions["media"];
    query: string;
}

interface TorrentSmartSearchOptions extends TorrentSearchOptions {
    batch: boolean;
    episodeNumber: number;
    resolution: string;
    anidbAID?: number;
    anidbEID?: number;
    bestReleases: boolean;
}

interface TorrentProviderSettings {
    canSmartSearch: boolean;
    smartSearchFilters: ("batch" | "episodeNumber" | "resolution" | "query" | "bestReleases")[];
    supportsAdult: boolean;
    type: "main" | "special";
}

// Manga Provider Types
interface MangaSearchOptions {
    query: string;
    year?: number;
}

interface MangaSearchResult {
    id: string;
    title: string;
    synonyms?: string[];
    year?: number;
    image?: string;
}

interface ChapterDetails {
    id: string;
    url: string;
    title: string;
    chapter: string;
    index: number;
}

interface ChapterPage {
    url: string;
    index: number;
    headers: Record<string, string>;
}

// Seanime Goja Built-in Globals
interface GojaDocElement {
    text(): string;
    attr(name: string): string | undefined;
    html(): string;
    find(selector: string): GojaDocSelection;
    children(): GojaDocSelection;
    parent(): GojaDocSelection;
    hasClass(className: string): boolean;
}

interface GojaDocSelection extends GojaDocElement {
    length: number;
    each(callback: (index: number, element: GojaDocElement) => void): void;
    map<T>(callback: (index: number, element: GojaDocElement) => T): T[];
    first(): GojaDocElement;
    last(): GojaDocElement;
    eq(index: number): GojaDocElement;
}

declare function LoadDoc(html: string): (selector: string) => GojaDocSelection;

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
