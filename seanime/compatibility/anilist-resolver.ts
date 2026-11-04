// AniList-driven matching for converted Seanime providers.
//
// Seanime is an AniList client: it never hands a provider a bare search string in isolation,
// it hands it the AniList media object (id, idMal, english/romaji/native titles, synonyms,
// year, format). A converted Cloudstream provider that searches by `opts.query` alone picks
// whatever the site's own ranking returns, which is frequently the wrong season, the wrong
// adaptation, or a sequel. This resolver makes the AniList metadata the source of truth:
// query by the AniList titles, then rank the site's results against the same titles.

class AniListResolver {
    /** Lowercase, de-accent, drop bracketed qualifiers, collapse punctuation. */
    static normalize(value: string): string {
        if (!value) return "";
        let s = String(value).toLowerCase();
        if (typeof s.normalize === "function") {
            s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        }
        // (Dub), [1080p], {TV} and similar qualifiers differ per site; drop them entirely
        s = s.replace(/[([{][^)\]}]*[)\]}]/g, " ");
        s = s.replace(/[^a-z0-9]+/g, " ");
        return s.trim();
    }

    /** Removes release noise that sites add but AniList titles never contain. */
    static stripNoise(value: string): string {
        let s = AniListResolver.normalize(value);
        s = s.replace(/\b(season|s)\s*\d+\b/g, " ");
        s = s.replace(/\b(part|cour)\s*\d+\b/g, " ");
        s = s.replace(/\b(sub|subbed|dub|dubbed|eng|english|jpn|japanese|raw)\b/g, " ");
        s = s.replace(/\b(tv|series|movie|ova|ona|special)\b/g, " ");
        s = s.replace(/\s+/g, " ").trim();
        return s;
    }

    /** Which season/part a title claims. 1 when the title says nothing. */
    static seasonOf(value: string): number {
        const s = AniListResolver.normalize(value);
        const numbered = s.match(/\b(?:season|part|cour|s)\s*(\d{1,2})\b/);
        if (numbered) return parseInt(numbered[1], 10);
        const roman = s.match(/\b(ii|iii|iv|v)\b/);
        if (roman) {
            const map: Record<string, number> = { ii: 2, iii: 3, iv: 4, v: 5 };
            return map[roman[1]] || 1;
        }
        return 1;
    }

    /** Dice coefficient over word tokens, with exact/containment shortcuts. */
    static similarity(a: string, b: string): number {
        if (!a || !b) return 0;
        if (a === b) return 1;
        if (a.length >= 4 && b.length >= 4 && (a.indexOf(b) !== -1 || b.indexOf(a) !== -1)) {
            return 0.9;
        }
        const ta = a.split(" ").filter((t: string) => t.length > 0);
        const tb = b.split(" ").filter((t: string) => t.length > 0);
        if (ta.length === 0 || tb.length === 0) return 0;
        const pool = tb.slice();
        let hits = 0;
        for (const token of ta) {
            const idx = pool.indexOf(token);
            if (idx !== -1) {
                hits += 1;
                pool.splice(idx, 1);
            }
        }
        return (2 * hits) / (ta.length + tb.length);
    }

    /** Every title AniList knows for this media, most specific first, de-duplicated. */
    static titles(media: any, fallback?: string): string[] {
        const out: string[] = [];
        const push = (value?: string) => {
            if (value && String(value).trim().length > 0) out.push(String(value).trim());
        };
        if (media && media.title) {
            push(media.title.english);
            push(media.title.romaji);
            push(media.title.native);
        }
        if (media && media.synonyms && media.synonyms.length) {
            for (const synonym of media.synonyms) push(synonym);
        }
        push(fallback);

        const seen = new Set<string>();
        const unique: string[] = [];
        for (const title of out) {
            const key = title.toLowerCase();
            if (!seen.has(key)) {
                seen.add(key);
                unique.push(title);
            }
        }
        return unique;
    }

    /** 0..1 confidence that `resultTitle` is the AniList media. */
    static score(resultTitle: string, media: any, year?: number): number {
        const target = AniListResolver.stripNoise(resultTitle);
        if (!target) return 0;

        let best = 0;
        const candidates = AniListResolver.titles(media, "");
        for (const candidate of candidates) {
            const plain = AniListResolver.similarity(target, AniListResolver.normalize(candidate));
            const stripped = AniListResolver.similarity(target, AniListResolver.stripNoise(candidate));
            const value = plain > stripped ? plain : stripped;
            if (value > best) best = value;
        }

        // Season disambiguation: "Season 2" must not resolve to the season 1 page, which is
        // the single most common wrong match for AniList-driven providers.
        const primary = AniListResolver.titles(media, "")[0] || "";
        const mediaSeason = AniListResolver.seasonOf(primary);
        const resultSeason = AniListResolver.seasonOf(resultTitle);
        if (mediaSeason !== resultSeason) {
            best -= 0.2;
        } else if (mediaSeason > 1) {
            best += 0.1;
        }

        // A year printed in the result title is strong evidence when it matches AniList.
        if (year && year > 0) {
            const match = String(resultTitle).match(/\b(19|20)\d{2}\b/);
            if (match) {
                best += String(year) === match[0] ? 0.1 : -0.05;
            }
        }

        // Movie/series hints only break ties; they never rescue a bad title match.
        if (media && media.format) {
            const format = String(media.format).toUpperCase();
            const looksMovie = /\b(movie|film)\b/i.test(resultTitle);
            if (format === "MOVIE" && looksMovie) best += 0.05;
            if (format !== "MOVIE" && looksMovie && best > 0) best -= 0.05;
        }

        return best;
    }

    /** Stable sort by AniList confidence, preserving site order for equal scores. */
    static rank<T>(items: T[], titleOf: (item: T) => string, media: any, year?: number): T[] {
        const scored = items.map((item, index) => ({
            item,
            index,
            score: AniListResolver.score(titleOf(item), media, year),
        }));
        scored.sort((a, b) => (b.score - a.score) || (a.index - b.index));
        return scored.map((entry) => entry.item);
    }

    /** Query strings to try, best first. Callers should stop at the first non-empty result. */
    static queries(media: any, fallback?: string, limit: number = 3): string[] {
        return AniListResolver.titles(media, fallback).slice(0, limit);
    }
}
