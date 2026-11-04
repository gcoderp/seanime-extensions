import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BEGIN = "<!-- BEGIN GENERATED:EXTENSIONS -->"
END = "<!-- END GENERATED:EXTENSIONS -->"

TYPE_LABELS = {
    "onlinestream-provider": "Online streaming",
    "anime-torrent-provider": "Anime torrent",
    "manga-provider": "Manga",
    "custom-source": "Custom source",
}


class ReadmeGenerator:
    """Writes the repository README section that lists every published extension with its manifest link.

    The section lives between two HTML comment markers so hand-written documentation above and
    below it is never touched.
    """

    def __init__(self, repo_root: str, owner: str, repo: str, branch: str = "main", version: str = "2.5.0"):
        self.repo_root = repo_root
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.version = version

    def _raw_base(self) -> str:
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{self.branch}"

    def _manifest_url(self, provider_type: str, ext_id: str) -> str:
        return f"{self._raw_base()}/src/{provider_type}/{ext_id}/manifest.json"

    def collect(self) -> List[Dict[str, Any]]:
        published: List[Dict[str, Any]] = []
        for p_type in ("onlinestream-provider", "anime-torrent-provider", "manga-provider", "custom-source"):
            type_dir = os.path.join(self.repo_root, "src", p_type)
            if not os.path.isdir(type_dir):
                continue
            for ext_id in sorted(os.listdir(type_dir)):
                ext_dir = os.path.join(type_dir, ext_id)
                m_path = os.path.join(ext_dir, "manifest.json")
                r_path = os.path.join(ext_dir, "conversion-report.json")
                if not os.path.exists(m_path) or not os.path.exists(r_path):
                    continue
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    with open(r_path, "r", encoding="utf-8") as f:
                        report = json.load(f)
                except Exception:
                    continue
                published.append({
                    "id": manifest.get("id", ext_id),
                    "name": manifest.get("name", ext_id),
                    "type": p_type,
                    "version": manifest.get("version", ""),
                    "author": manifest.get("author", ""),
                    "lang": manifest.get("lang", ""),
                    "status": report.get("overall_status"),
                    "strategy": report.get("strategy") or report.get("notes") or "",
                    "license": report.get("license_spdx", ""),
                    "manifest_url": self._manifest_url(p_type, ext_id),
                    "live_test": report.get("live_test_status", "NOT_RUN"),
                    "source": self._source_label(report),
                })
        return published

    @staticmethod
    def _source_label(report: Dict[str, Any]) -> str:
        """How much evidence backs the scraper logic, strongest first."""
        strategy = str(report.get("strategy", ""))
        recovery = str(report.get("source_recovery_status", ""))
        decomp = str(report.get("decompilation_status", ""))
        if "STRATEGY_1" in strategy or recovery == "RECOVERED":
            return "Kotlin source"
        if "STRATEGY_2" in strategy or decomp == "JADX_OK":
            return "JADX (Java)"
        return "DEX strings"

    def render(self, entries: List[Dict[str, Any]], withheld: int) -> str:
        ok = [e for e in entries if e["status"] == "SUCCESS"]
        ok.sort(key=lambda e: (e["type"], e["name"].lower()))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines: List[str] = []
        lines.append(BEGIN)
        lines.append("")
        lines.append("## Install in Seanime")
        lines.append("")
        lines.append("Marketplace URL — adds every extension listed below at once:")
        lines.append("")
        lines.append("```text")
        lines.append(f"{self._raw_base()}/marketplace.json")
        lines.append("```")
        lines.append("")
        lines.append("In Seanime: **Extensions → Marketplace → Change repository**, paste the URL and save.")
        lines.append("")
        lines.append("To install a single extension instead: **Extensions → Add extensions**, paste the")
        lines.append("`manifest.json` link from the table below, then click **Find**.")
        lines.append("")
        lines.append(f"## Extensions ({len(ok)})")
        lines.append("")
        if not ok:
            lines.append("_No extension has passed validation yet._")
        else:
            lines.append("| # | Extension | Type | Recovered from | Version | Manifest link |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for idx, e in enumerate(ok, 1):
                label = TYPE_LABELS.get(e["type"], e["type"])
                lines.append(
                    f"| {idx} | **{e['name']}** <br>`{e['id']}` | {label} | {e.get('source', 'unknown')} | "
                    f"{e['version']} | [manifest.json]({e['manifest_url']}) |"
                )
        lines.append("")
        if withheld:
            lines.append(f"> {withheld} further conversion(s) are held in `reports/needs-review.json` and are "
                         f"**not** published: they parse, but their scraper could not be recovered with "
                         f"enough confidence (string-pool reconstruction, generic selectors, or no base URL).")
            lines.append("")
        lines.append(f"_Generated by cloudstream-seanime-converter {self.version} on {now}. "
                     f"Every extension above passed the static, parse and contract gates; "
                     f"`liveTestStatus` is recorded per extension in `reports/`._")
        lines.append("")
        lines.append(END)
        return "\n".join(lines)

    def write(self, readme_path: Optional[str] = None, withheld: int = 0) -> str:
        readme_path = readme_path or os.path.join(self.repo_root, "README.md")
        entries = self.collect()
        block = self.render(entries, withheld)

        existing = ""
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8") as f:
                existing = f.read()

        if BEGIN in existing and END in existing:
            head, _, rest = existing.partition(BEGIN)
            _, _, tail = rest.partition(END)
            updated = head + block + tail
        elif existing.strip():
            # Insert after the document title so the docs below stay intact.
            lines = existing.splitlines()
            insert_at = 1
            for i, line in enumerate(lines[:10]):
                if line.startswith("# "):
                    insert_at = i + 1
                    break
            updated = "\n".join(lines[:insert_at]) + "\n\n" + block + "\n" + "\n".join(lines[insert_at:])
        else:
            updated = block + "\n"

        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(updated.rstrip("\n") + "\n")
        return readme_path

    def write_url_list(self, path: Optional[str] = None) -> str:
        """Plain list of published manifest URLs, ready to append to a consumer's source list."""
        path = path or os.path.join(self.repo_root, "manifest-urls.txt")
        entries = [e for e in self.collect() if e["status"] == "SUCCESS"]
        entries.sort(key=lambda e: (e["type"], e["id"]))
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(e["manifest_url"] + "\n")
        return path
