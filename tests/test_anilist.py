"""Behavioural tests for the AniList matching that every converted provider uses.

Seanime is an AniList client, so a converted provider must resolve the AniList media to the
right page on the site. These tests compile seanime/compatibility/anilist-resolver.ts with the
real TypeScript compiler and exercise the ranking logic in Node.
"""
import importlib.util
import json
import os
import subprocess
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = subprocess.run(["which", "node"], stdout=subprocess.PIPE, text=True).stdout.strip()


def load_mod(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compile_resolver(tmpdir: str) -> str:
    tsc_mod = load_mod("ts_compiler", "engine/ts-compiler/compiler.py")
    compiler = tsc_mod.TypeScriptCompiler(repo_root=ROOT)
    ok, reason = compiler.is_available()
    if not ok:
        pytest.skip(reason)
    target = os.path.join(tmpdir, "anilist-resolver.ts")
    with open(os.path.join(ROOT, "seanime/compatibility/anilist-resolver.ts"), encoding="utf-8") as f:
        source = f.read().replace("export class AniListResolver", "class AniListResolver")
    with open(target, "w", encoding="utf-8") as f:
        f.write(source)
    js_paths = compiler.compile_files([target])
    return js_paths[0]


@pytest.fixture(scope="module")
def resolver_js():
    if not NODE:
        pytest.skip("node is required")
    with tempfile.TemporaryDirectory() as tmp:
        path = _compile_resolver(tmp)
        with open(path, encoding="utf-8") as f:
            yield f.read()


def run_js(resolver_source: str, script: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(resolver_source + "\n" + script)
        path = f.name
    try:
        proc = subprocess.run([NODE, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()
    finally:
        os.unlink(path)


# The exact shape Seanime sends: flattened AniList titles, no `title` object.
FRIEREN = """const media = {
    id: 154587, idMal: 52991, format: "TV", status: "FINISHED",
    romajiTitle: "Sousou no Frieren",
    englishTitle: "Frieren: Beyond Journey's End",
    synonyms: ["Frieren at the Funeral", "Frieren"],
    isAdult: false,
    startDate: { year: 2023, month: 9, day: 29 }
};"""


def test_queries_follow_anilist_title_order(resolver_js):
    out = run_js(resolver_js, FRIEREN + """
console.log(JSON.stringify(AniListResolver.queries(media, "frieren", 3)));
""")
    queries = json.loads(out)
    # The caller's query wins, then Seanime's GetAllTitles order: romaji, english, synonyms.
    assert queries[0] == "frieren"
    assert queries[1] == "Sousou no Frieren"
    assert queries[2] == "Frieren: Beyond Journey's End"
    assert len(queries) == 3


def test_ranking_picks_the_anilist_match_not_the_site_order(resolver_js):
    out = run_js(resolver_js, FRIEREN + """
const siteOrder = [
  { title: "Bleach" },
  { title: "Frieren the Slayer" },
  { title: "Sousou no Frieren (Dub)" },
  { title: "Frieren: Beyond Journey's End" }
];
const ranked = AniListResolver.rank(siteOrder, (r) => r.title, media, AniListResolver.yearOf({ year: 2023, media }));
console.log(JSON.stringify(ranked.map((r) => r.title)));
""")
    ranked = json.loads(out)
    assert ranked[-1] == "Bleach", "an unrelated show must sink to the bottom"
    assert ranked[0] in ("Frieren: Beyond Journey's End", "Sousou no Frieren (Dub)")


def test_sequel_does_not_resolve_to_the_first_season(resolver_js):
    out = run_js(resolver_js, """
const media = {
    format: "TV",
    romajiTitle: "Mushoku Tensei II: Isekai Ittara Honki Dasu",
    englishTitle: "Mushoku Tensei: Jobless Reincarnation Season 2",
    synonyms: [],
    startDate: { year: 2024 }
};
const siteOrder = [
  { title: "Mushoku Tensei: Jobless Reincarnation" },
  { title: "Mushoku Tensei: Jobless Reincarnation Season 2" }
];
const ranked = AniListResolver.rank(siteOrder, (r) => r.title, media, AniListResolver.yearOf({ year: 2023, media }));
console.log(JSON.stringify(ranked.map((r) => r.title)));
""")
    ranked = json.loads(out)
    assert ranked[0] == "Mushoku Tensei: Jobless Reincarnation Season 2"


def test_duplicate_and_qualifier_titles_are_normalised(resolver_js):
    out = run_js(resolver_js, FRIEREN + """
const scored = [
  ["Frieren: Beyond Journey's End (TV)", AniListResolver.score("Frieren: Beyond Journey's End (TV)", media)],
  ["Frieren - Beyond Journeys End [1080p]", AniListResolver.score("Frieren - Beyond Journeys End [1080p]", media)],
  ["Naruto", AniListResolver.score("Naruto", media)]
];
console.log(JSON.stringify(scored));
""")
    scored = json.loads(out)
    assert scored[0][1] > 0.9
    assert scored[1][1] > 0.7, "punctuation and quality tags must not break the match"
    assert scored[2][1] == 0


def test_generated_extension_uses_the_resolver(tmp_path):
    """Every generated provider must wire search() through AniListResolver."""
    parser_mod = load_mod("parser", "engine/kotlin-parser/parser.py")
    fixtures_mod = load_mod("build_fixtures", "tests/fixtures/build_fixtures.py")
    trans_mod = load_mod("translator", "engine/kotlin-translator/translator.py")
    extr_mod = load_mod("extractor_translator", "engine/extractor-translator/extractors.py")

    ast = parser_mod.KotlinJavaASTParser().parse_source(fixtures_mod.GOGO_KOTLIN)
    translator = trans_mod.CloudstreamToSeanimeTranslator(
        compat_shim_path=os.path.join(ROOT, "seanime/compatibility/cloudstream-runtime-shim.ts"),
        templates_dir=os.path.join(ROOT, "seanime/templates"),
        anilist_resolver_path=os.path.join(ROOT, "seanime/compatibility/anilist-resolver.ts"),
    )
    ts = translator.translate_ast_to_seanime(
        "GogoAnimeProvider", ast, extr_mod.ExtractorTranslator.generate_extractor_runtime_ts(),
        "STRATEGY_1_EMBEDDED_KOTLIN_SOURCE"
    ).typescript_code

    assert "class AniListResolver" in ts
    assert "AniListResolver.queries(" in ts
    assert "AniListResolver.rank(" in ts
    assert "AniListResolver.yearOf(opts)" in ts
    assert "private async searchSite(" in ts
    # Seanime sends flattened titles, never a `title` object
    assert "media.romajiTitle" in ts
    assert "media.title.romaji" not in ts
