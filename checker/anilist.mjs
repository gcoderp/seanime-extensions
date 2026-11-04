// AniList resolution for the extension checker.
//
// Seanime is an AniList client: before it ever calls a provider it resolves the media, builds
// the `Media` struct from internal/extension/hibike/onlinestream/types.go and passes one
// AniList title per search() call. The checker reproduces that exactly, so a provider is
// tested with the same metadata the app would give it — not with a made-up query string.

const ENDPOINT = "https://graphql.anilist.co";

const MEDIA_FIELDS = `
    id
    idMal
    status
    format
    episodes
    duration
    isAdult
    synonyms
    season
    seasonYear
    title { romaji english native }
    startDate { year month day }
`;

const BY_ID = `query ($id: Int) { Media(id: $id, type: ANIME) { ${MEDIA_FIELDS} } }`;
const BY_QUERY = `query ($page: Int, $perPage: Int, $sort: [MediaSort], $season: MediaSeason, $seasonYear: Int) {
    Page(page: $page, perPage: $perPage) {
        media(type: ANIME, sort: $sort, season: $season, seasonYear: $seasonYear, isAdult: false) { ${MEDIA_FIELDS} }
    }
}`;

const SEASON_SYNONYM = /season|part|cour|\b[2-9](st|nd|rd|th)\b|\b(ii|iii|iv|v)\b/i;

async function gql(query, variables, { timeoutMs = 20000, retries = 3 } = {}) {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(ENDPOINT, {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({ query, variables }),
                signal: controller.signal,
            });
            if (res.status === 429) {
                const wait = Number(res.headers.get("retry-after") || 60) * 1000;
                await new Promise((r) => setTimeout(r, Math.min(wait, 60000)));
                continue;
            }
            const body = await res.json();
            if (body.errors && body.errors.length > 0) {
                throw new Error(`AniList: ${body.errors.map((e) => e.message).join("; ")}`);
            }
            return body.data;
        } catch (err) {
            lastError = err;
            if (attempt < retries) await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
        } finally {
            clearTimeout(timer);
        }
    }
    throw lastError || new Error("AniList request failed");
}

/**
 * AniList media -> the exact `Media` object Seanime passes to a provider.
 * Mirrors internal/extension_playground/playground.go: synonyms are filtered to the ones that
 * contain a season marker, episodeCount is -1 when unknown, and startDate is flattened.
 */
export function toSeanimeMedia(media) {
    const title = media.title || {};
    const start = media.startDate || {};
    const synonyms = (media.synonyms || []).filter((s) => typeof s === "string" && SEASON_SYNONYM.test(s));

    return {
        id: media.id,
        idMal: media.idMal ?? undefined,
        status: media.status ?? undefined,
        format: media.format ?? "TV",
        englishTitle: title.english ?? undefined,
        romajiTitle: title.romaji ?? title.english ?? "",
        episodeCount: typeof media.episodes === "number" ? media.episodes : -1,
        absoluteSeasonOffset: 0,
        synonyms,
        isAdult: media.isAdult === true,
        startDate: start.year ? { year: start.year, month: start.month ?? undefined, day: start.day ?? undefined } : undefined,
    };
}

/** The title list Seanime iterates: romaji, english, then synonyms when there is more than one. */
export function seanimeTitles(media) {
    const titles = [];
    if (media.romajiTitle) titles.push(media.romajiTitle);
    if (media.englishTitle) titles.push(media.englishTitle);
    if (media.synonyms && media.synonyms.length > 1) titles.push(...media.synonyms);
    if (titles.length === 0) titles.push(String(media.id));
    return [...new Set(titles)];
}

function target(media, label) {
    const seanimeMedia = toSeanimeMedia(media);
    return {
        label,
        anilistId: media.id,
        idMal: media.idMal ?? null,
        title: media.title?.romaji || media.title?.english || String(media.id),
        englishTitle: media.title?.english ?? null,
        year: media.startDate?.year ?? media.seasonYear ?? null,
        format: media.format ?? null,
        episodeCount: typeof media.episodes === "number" ? media.episodes : null,
        media: seanimeMedia,
        queries: seanimeTitles(seanimeMedia),
    };
}

/** Explicit AniList IDs. Titles are always resolved from AniList, never invented. */
export async function targetsFromIds(ids) {
    const out = [];
    for (const id of ids) {
        const data = await gql(BY_ID, { id: Number(id) });
        if (!data?.Media) throw new Error(`AniList has no media with id ${id}`);
        out.push(target(data.Media, `id:${id}`));
    }
    return out;
}

/** Resolves targets from AniList queries (trending, popular, ...) so no ID is hardcoded. */
export async function targetsFromQueries(queries) {
    const out = [];
    for (const q of queries) {
        const data = await gql(BY_QUERY, {
            page: q.page ?? 1,
            perPage: q.perPage ?? 3,
            sort: q.sort ?? ["TRENDING_DESC"],
            season: q.season ?? null,
            seasonYear: q.seasonYear ?? null,
        });
        const media = data?.Page?.media ?? [];
        for (const item of media) out.push(target(item, q.name || "query"));
    }
    return out;
}

export async function resolveTargets(config, { ids = [] } = {}) {
    if (ids.length > 0) return targetsFromIds(ids);
    if (config.mode === "ids" && Array.isArray(config.ids) && config.ids.length > 0) {
        return targetsFromIds(config.ids);
    }
    return targetsFromQueries(config.queries || [{ name: "trending", sort: ["TRENDING_DESC"], perPage: 3 }]);
}
