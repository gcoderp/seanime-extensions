/// <reference path="__ENV_TYPES_PATH__" />

// ============================================================================
// AUTO-GENERATED SEANIME TORRENT EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: __PLUGIN_ID__
// Original Class: __ORIGINAL_CLASS__
// Strategy Used: __CONVERSION_STRATEGY__
// ============================================================================

__COMPAT_SHIM__

__ANILIST_RESOLVER__

class Provider {
    private mainUrl: string = __MAIN_URL__;
    private defaultHeaders: Record<string, string> = __DEFAULT_HEADERS__;

    getSettings(): TorrentProviderSettings {
        return {
            canSmartSearch: true,
            smartSearchFilters: ["query", "episodeNumber", "resolution", "batch"],
            supportsAdult: false,
            type: "main",
        };
    }

    async search(opts: TorrentSearchOptions): Promise<AnimeTorrent[]> {
__TORRENT_SEARCH_BODY__
    }

    async smartSearch(opts: TorrentSmartSearchOptions): Promise<AnimeTorrent[]> {
__TORRENT_SMART_SEARCH_BODY__
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
