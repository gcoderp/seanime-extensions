// Vendored from seanime-api-netlify (src/extensions/compat-scanner-utils.js), the Seanime-compatible
// runtime shim for Cloudflare Workers. Dependency-free; adapted only to the .mjs extension
// so the extension checker can reproduce Seanime's Goja semantics in Node.
/**
 * `$scannerUtils` — Seanime's title helpers, used by providers that need to map
 * an AniList title onto a site's naming ("Season 2", "Part 2", "2nd Season").
 *
 * Two functions are implemented, which is what the online-stream providers in
 * the wild actually call:
 *   normalizeTitle(title)            -> { season, part }   (-1 when absent)
 *   buildSmartSearchTitles(titles)   -> { titles, season, part }
 *
 * The result is pure string work, so it behaves identically on Workers.
 */

const SEASON_PATTERNS = [
  /\bseason\s*(\d+)\b/i,
  /\b(\d+)(?:st|nd|rd|th)\s*season\b/i,
  /\bseason\s*(i{1,3}|iv|v)\b/i,
];

const PART_PATTERNS = [/\bpart\s*(\d+)\b/i, /\bcour\s*(\d+)\b/i, /\b(\d+)(?:st|nd|rd|th)\s*part\b/i];

const ROMAN = { i: 1, ii: 2, iii: 3, iv: 4, v: 5 };

function firstNumber(text, patterns) {
  for (const pattern of patterns) {
    const match = String(text ?? "").match(pattern);
    if (!match) continue;
    const raw = String(match[1]).toLowerCase();
    const value = ROMAN[raw] ?? Number(raw);
    if (Number.isFinite(value) && value > 0) return value;
  }
  return -1;
}

export function normalizeTitle(title) {
  const text = String(title ?? "");
  return { season: firstNumber(text, SEASON_PATTERNS), part: firstNumber(text, PART_PATTERNS) };
}

export function buildSmartSearchTitles(input) {
  const source = Array.isArray(input) ? input : [input];
  const candidates = [];
  let season = -1;
  let part = -1;

  for (const raw of source) {
    const title = String(raw ?? "").trim();
    if (!title) continue;

    const parsed = normalizeTitle(title);
    if (parsed.season > 0 && season < 0) season = parsed.season;
    if (parsed.part > 0 && part < 0) part = parsed.part;

    candidates.push(title);

    const stripped = title
      .replace(/\b(?:season|part|cour)\s*\d+\b/gi, " ")
      .replace(/\b\d+(?:st|nd|rd|th)\s*(?:season|part|cour)\b/gi, " ")
      .replace(/\b(?:season|part|cour)\s*(?:i{1,3}|iv|v)\b/gi, " ")
      .replace(/[([{][^)\]}]*[)\]}]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    if (stripped && stripped.toLowerCase() !== title.toLowerCase()) candidates.push(stripped);
  }

  const seen = new Set();
  const titles = [];
  for (const candidate of candidates) {
    const key = candidate.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    titles.push(candidate);
  }

  return { titles, season: season > 0 ? season : 0, part: part > 0 ? part : 0 };
}

export const scannerUtils = { normalizeTitle, buildSmartSearchTitles };
