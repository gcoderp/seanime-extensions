/// <reference path="../../../seanime/types/seanime-env.d.ts" />

// ============================================================================
// AUTO-GENERATED SEANIME EXTENSION FROM CLOUDSTREAM (.cs3)
// Plugin ID: __PLUGIN_ID__
// Original Class: __ORIGINAL_CLASS__
// Strategy Used: __CONVERSION_STRATEGY__
// ============================================================================

__COMPAT_SHIM__

__EXTRACTOR_HELPERS__

class Provider {
    private mainUrl: string = "__MAIN_URL__";
    private mirrorDomains: string[] = __MIRROR_DOMAINS__;
    private defaultHeaders: Record<string, string> = __DEFAULT_HEADERS__;

    getSettings(): Settings {
        return {
            episodeServers: __EPISODE_SERVERS__,
            supportsDub: __SUPPORTS_DUB__,
        };
    }

    async search(opts: SearchOptions): Promise<SearchResult[]> {
__SEARCH_BODY__
    }

    async findEpisodes(id: string): Promise<EpisodeDetails[]> {
__FIND_EPISODES_BODY__
    }

    async findEpisodeServer(episode: EpisodeDetails, server: string): Promise<EpisodeServer> {
__FIND_EPISODE_SERVER_BODY__
    }
}
