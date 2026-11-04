import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ExtractedCS3Package:
    plugin_id: str
    cs3_path: str
    sha256: str
    manifest: Dict[str, Any]
    plugin_class_name: str
    package_name: str
    dex_files: List[str]
    embedded_kotlin_sources: List[str]
    asset_files: List[str]
    extract_dir: str
    version_code: int

class CS3Extractor:
    """Validates and extracts .cs3 packages with ZIP bomb and path-traversal defenses."""

    ZIP_MAGIC = b"PK\x03\x04"

    def __init__(
        self,
        work_dir: str = ".cache/extracted",
        max_entries: int = 2500,
        max_uncompressed_bytes: int = 52_428_800,
        max_ratio: float = 80.0
    ):
        self.work_dir = work_dir
        self.max_entries = max_entries
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_ratio = max_ratio
        os.makedirs(self.work_dir, exist_ok=True)

    def extract_package(self, cs3_path: str, plugin_id: str) -> ExtractedCS3Package:
        if not os.path.exists(cs3_path):
            raise FileNotFoundError(f".cs3 archive not found: {cs3_path}")

        with open(cs3_path, "rb") as f:
            magic = f.read(4)
            if magic != self.ZIP_MAGIC:
                raise ValueError(f"Invalid .cs3 signature in {cs3_path}: not a valid PKZIP archive")
            f.seek(0)
            sha256_hex = hashlib.sha256(f.read()).hexdigest()

        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in plugin_id)
        target_dir = os.path.join(self.work_dir, f"{safe_id}_{sha256_hex[:10]}")
        os.makedirs(target_dir, exist_ok=True)

        dex_files: List[str] = []
        kotlin_sources: List[str] = []
        asset_files: List[str] = []
        manifest_data: Dict[str, Any] = {}

        with zipfile.ZipFile(cs3_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > self.max_entries:
                raise ValueError(f"Archive bomb detected: {len(infos)} entries exceed max {self.max_entries}")

            total_uncompressed = 0
            for info in infos:
                # Prevent ZIP Slip path traversal
                norm_name = os.path.normpath(info.filename)
                if norm_name.startswith("..") or norm_name.startswith("/") or ":" in norm_name:
                    raise ValueError(f"Malicious ZIP path traversal blocked: {info.filename}")

                total_uncompressed += info.file_size
                if total_uncompressed > self.max_uncompressed_bytes:
                    raise ValueError(f"Uncompressed size exceeds safety threshold ({self.max_uncompressed_bytes} bytes)")

                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > self.max_ratio and info.file_size > 1024 * 1024:
                        raise ValueError(f"Suspicious compression ratio ({ratio:.1f}x) in {info.filename}")

                dest_file = os.path.join(target_dir, norm_name)
                if info.is_dir():
                    os.makedirs(dest_file, exist_ok=True)
                    continue

                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                with zf.open(info, "r") as src, open(dest_file, "wb") as dst:
                    dst.write(src.read())

                lower_name = norm_name.lower()
                if lower_name == "manifest.json":
                    with open(dest_file, "r", encoding="utf-8") as mf:
                        manifest_data = json.load(mf)
                elif lower_name.endswith(".dex"):
                    dex_files.append(dest_file)
                elif lower_name.endswith(".kt") or lower_name.endswith(".java"):
                    kotlin_sources.append(dest_file)
                else:
                    asset_files.append(dest_file)

        if not dex_files and not kotlin_sources:
            raise ValueError(f"Package {plugin_id} contains neither classes.dex nor embedded source files")

        plugin_class = str(
            manifest_data.get("pluginClassName")
            or manifest_data.get("className")
            or manifest_data.get("entryPoint")
            or f"com.lagradost.{safe_id}Plugin"
        )
        package_name = ".".join(plugin_class.split(".")[:-1]) if "." in plugin_class else "com.lagradost"
        version_code = int(manifest_data.get("version", 1))

        return ExtractedCS3Package(
            plugin_id=plugin_id,
            cs3_path=cs3_path,
            sha256=sha256_hex,
            manifest=manifest_data,
            plugin_class_name=plugin_class,
            package_name=package_name,
            dex_files=sorted(dex_files),
            embedded_kotlin_sources=sorted(kotlin_sources),
            asset_files=sorted(asset_files),
            extract_dir=target_dir,
            version_code=version_code
        )
