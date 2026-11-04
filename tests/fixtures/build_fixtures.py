#!/usr/bin/env python3
"""Builds the synthetic .cs3 packages used by the offline test fixtures.

These packages are *synthetic*: they are not upstream binaries. They reproduce the
structure the converter has to handle so the pipeline can be exercised without network
access:

  GogoAnimeProvider.cs3   manifest.json + classes.dex + embedded Kotlin source  -> STRATEGY_1
  NyaaTorrentProvider.cs3 manifest.json + classes.dex + embedded Kotlin source  -> STRATEGY_1 (torrent)
  HiAnimeProvider.cs3     manifest.json + classes.dex only                      -> STRATEGY_3

The HiAnime package deliberately ships no source and no recoverable site URL so the
"template only" validation gate can be regression-tested.

Run: python3 tests/fixtures/build_fixtures.py
"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

GOGO_KOTLIN = '''package com.lagradost.gogo

// Synthetic fixture: mirrors the structure of a real Cloudstream MainAPI provider.
import com.lagradost.cloudstream3.*
import com.lagradost.cloudstream3.utils.*

open class GogoAnimeProvider : MainAPI() {
    override var mainUrl = "https://anitaku.pe"
    override var name = "GogoAnime"
    override var lang = "en"
    override val hasQuickSearch = true
    override val hasMainPage = true
    override val supportedTypes = setOf(TvType.Anime, TvType.AnimeMovie, TvType.OVA)

    private val extractorHosts = listOf("VidStreaming", "GogoCDN", "StreamWish", "Mp4Upload")

    override suspend fun search(query: String): List<SearchResponse> {
        val document = app.get("$mainUrl/search.html?keyword=$query").document
        return document.select("ul.items li").mapNotNull { el ->
            val titleEl = el.select("p.name a").firstOrNull() ?: return@mapNotNull null
            val href = titleEl.attr("href")
            val title = titleEl.text()
            if (href.isBlank()) return@mapNotNull null
            newAnimeSearchResponse(title, "$mainUrl$href", TvType.Anime) {
                this.posterUrl = el.select("img").attr("src")
            }
        }
    }

    override suspend fun load(url: String): LoadResponse {
        val document = app.get(url).document
        val title = document.select("h1").text()
        val episodes = document.select("ul#episode_related li a").mapNotNull { el ->
            val href = el.attr("href")
            val number = el.select("div.name").text().filter { it.isDigit() }.toIntOrNull()
            if (href.isBlank() || number == null) return@mapNotNull null
            newEpisode("$mainUrl$href") {
                this.name = "Episode $number"
                this.episode = number
            }
        }
        return newAnimeLoadResponse(title, url, TvType.Anime) {
            this.episodes = episodes
            this.dubStatus = DubStatus.Subbed
        }
    }

    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        val document = app.get(fixUrlNull(data) ?: return false, referer = "$mainUrl/").document
        document.select("div.anime_muti_link ul li a").amap { el ->
            loadExtractor(el.attr("data-video"), "$mainUrl/", subtitleCallback, callback)
        }
        return true
    }
}
'''

NYAA_KOTLIN = '''package com.lagradost.nyaa

// Synthetic fixture: mirrors the structure of a real Cloudstream torrent provider.
import com.lagradost.cloudstream3.*
import com.lagradost.cloudstream3.utils.*

open class NyaaTorrentProvider : MainAPI() {
    override var mainUrl = "https://nyaa.si"
    override var name = "NyaaTorrents"
    override var lang = "en"
    override val supportedTypes = setOf(TvType.Torrent, TvType.Anime)

    override suspend fun search(query: String): List<SearchResponse> {
        val document = app.get("$mainUrl/?f=0&c=1_2&q=$query").document
        return document.select("table.torrent-list tbody tr").mapNotNull { row ->
            val titleEl = row.select("td:nth-child(2) a").lastOrNull() ?: return@mapNotNull null
            val magnet = row.select("a[href^=magnet]").attr("href")
            val seeders = row.select("td:nth-child(6)").text().trim()
            newTorrentSearchResponse(titleEl.text(), "$mainUrl${titleEl.attr("href")}", 1) {
                this.magnet = magnet
                this.seeders = seeders.toIntOrNull() ?: 0
                this.downloads = 0
            }
        }
    }

    override suspend fun load(url: String): LoadResponse {
        return newMovieLoadResponse("Nyaa entry", url, TvType.Torrent, url)
    }

    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean = false
}
'''

HIANIME_DEX_STRINGS = [
    "https://hianime.to",
    "/ajax/v2/search",
    "/ajax/v2/episode/list",
    "div.film_list-wrap",
    "div.flw-item",
    "h3.film-name a",
    "div.eplister ul li a",
    "div.server-item[data-embed]",
    "iframe[src]",
    "Referer",
    "User-Agent",
    "DubStatus.Dubbed",
]


def build_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            zf.writestr(name, data)


def synthetic_dex(strings):
    """A minimal, deliberately non-standard 'dex' blob.

    The DEX analyzer falls back to an ASCII string scan for inputs shorter than a real
    DEX header, which is exactly the code path we want to exercise here.
    """
    body = b"\n".join(s.encode("ascii") for s in strings)
    return b"dex\n035\x00" + b"\x00" * 8 + body + b"\x00"


def main():
    manifest = lambda cls, ver: json.dumps({"pluginClassName": cls, "version": ver, "name": cls.split(".")[-1]}, indent=2)

    build_zip(os.path.join(HERE, "GogoAnimeProvider.cs3"), {
        "manifest.json": manifest("com.lagradost.gogo.GogoAnimeProvider", 12),
        "classes.dex": synthetic_dex(["https://anitaku.pe", "/search.html", "ul.items li"]),
        "sources/GogoAnimeProvider.kt": GOGO_KOTLIN,
    })

    build_zip(os.path.join(HERE, "NyaaTorrentProvider.cs3"), {
        "manifest.json": manifest("com.lagradost.nyaa.NyaaTorrentProvider", 5),
        "classes.dex": synthetic_dex(["https://nyaa.si", "table.torrent-list"]),
        "sources/NyaaTorrentProvider.kt": NYAA_KOTLIN,
    })

    build_zip(os.path.join(HERE, "HiAnimeProvider.cs3"), {
        "manifest.json": manifest("com.lagradost.hianime.HiAnimeProvider", 9),
        "classes.dex": synthetic_dex(HIANIME_DEX_STRINGS),
    })

    plugins_path = os.path.join(HERE, "plugins.json")
    with open(plugins_path, "r", encoding="utf-8") as f:
        plugins = json.load(f)
    for entry in plugins:
        entry["license"] = "TEST_FIXTURE"
        entry["repositoryUrl"] = entry.get("repositoryUrl")
    with open(plugins_path, "w", encoding="utf-8") as f:
        json.dump(plugins, f, indent=2)
        f.write("\n")

    print("Built synthetic fixtures:", ", ".join(sorted(
        n for n in os.listdir(HERE) if n.endswith(".cs3")
    )))


if __name__ == "__main__":
    main()
