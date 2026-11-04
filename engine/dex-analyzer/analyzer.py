import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Set

@dataclass
class DexAnalysisResult:
    jadx_available: bool
    decompiled_java_files: Dict[str, str]
    string_pool: List[str]
    discovered_urls: List[str]
    css_selectors: List[str]
    regex_patterns: List[str]
    class_descriptors: List[str]
    method_names: List[str]
    extracted_headers: Dict[str, str]
    uses_crypto: bool
    uses_jsoup: bool
    uses_packer: bool

class DexAnalyzer:
    """Executes JADX CLI when available AND implements a native Python Dalvik DEX binary parser fallback."""

    DEX_MAGIC = b"dex\n"

    def __init__(self, jadx_bin: str = "jadx"):
        self.jadx_bin = shutil.which(jadx_bin)

    @staticmethod
    def _read_uleb128(data: bytes, offset: int) -> tuple[int, int]:
        result = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return result, offset

    def parse_dex_binary_strings_and_types(self, dex_path: str) -> tuple[List[str], List[str], List[str]]:
        """Directly parses the Dalvik Executable (.dex) binary header, string_ids, type_ids, and method_ids."""
        with open(dex_path, "rb") as f:
            data = f.read()

        if len(data) < 112 or not data.startswith(self.DEX_MAGIC):
            # Fallback regex string scan if synthetic/minimal test DEX
            ascii_strings = re.findall(rb"[\x20-\x7E]{4,}", data)
            decoded = [s.decode("utf-8", errors="ignore") for s in ascii_strings]
            return decoded, [], []

        # Parse standard Dalvik header offsets (little-endian uint32)
        string_ids_size, string_ids_off = struct.unpack_from("<II", data, 56)
        type_ids_size, type_ids_off = struct.unpack_from("<II", data, 64)
        method_ids_size, method_ids_off = struct.unpack_from("<II", data, 88)

        strings: List[str] = []
        for i in range(min(string_ids_size, 50000)):
            str_data_off = struct.unpack_from("<I", data, string_ids_off + i * 4)[0]
            if str_data_off >= len(data):
                continue
            try:
                utf16_len, pos = self._read_uleb128(data, str_data_off)
                end_pos = data.find(b"\x00", pos)
                if end_pos == -1:
                    end_pos = min(len(data), pos + utf16_len * 3)
                s = data[pos:end_pos].decode("utf-8", errors="ignore")
                strings.append(s)
            except Exception:
                continue

        type_descriptors: List[str] = []
        for i in range(min(type_ids_size, 10000)):
            desc_idx = struct.unpack_from("<I", data, type_ids_off + i * 4)[0]
            if 0 <= desc_idx < len(strings):
                type_descriptors.append(strings[desc_idx])

        method_names: List[str] = []
        for i in range(min(method_ids_size, 20000)):
            class_idx, proto_idx, name_idx = struct.unpack_from("<HHI", data, method_ids_off + i * 8)
            if 0 <= name_idx < len(strings):
                method_names.append(strings[name_idx])

        return strings, type_descriptors, method_names

    def analyze_dex_files(self, dex_files: List[str], work_dir: str) -> DexAnalysisResult:
        java_files: Dict[str, str] = {}
        jadx_ok = False

        if self.jadx_bin and dex_files:
            jadx_out = os.path.join(work_dir, "jadx_out")
            os.makedirs(jadx_out, exist_ok=True)
            try:
                cmd = [self.jadx_bin, "-d", jadx_out, "--no-imports", "--show-bad-code"] + dex_files
                subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                for root, _, files in os.walk(jadx_out):
                    for fn in files:
                        if fn.endswith(".java") or fn.endswith(".kt"):
                            full_p = os.path.join(root, fn)
                            with open(full_p, "r", encoding="utf-8", errors="ignore") as f:
                                java_files[fn] = f.read()
                jadx_ok = bool(java_files)
            except Exception:
                jadx_ok = False

        all_strings: List[str] = []
        all_types: List[str] = []
        all_methods: List[str] = []

        for dex in dex_files:
            s_list, t_list, m_list = self.parse_dex_binary_strings_and_types(dex)
            all_strings.extend(s_list)
            all_types.extend(t_list)
            all_methods.extend(m_list)

        # Also harvest strings from JADX decompiled code if present
        for code in java_files.values():
            all_strings.extend(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', code))

        urls: List[str] = []
        selectors: List[str] = []
        regexes: List[str] = []
        headers: Dict[str, str] = {}

        css_hint = re.compile(r"^(div|ul|li|a|span|article|section|table|tr|td|\.[a-zA-Z0-9_-]+|#[a-zA-Z0-9_-]+)(\s|>|\.|#|\[|:).*")
        for s in all_strings:
            s_clean = s.strip()
            if s_clean.startswith(("https://", "http://")) and "schemas.android.com" not in s_clean:
                if s_clean not in urls:
                    urls.append(s_clean)
            elif css_hint.match(s_clean) and len(s_clean) < 120:
                if s_clean not in selectors:
                    selectors.append(s_clean)
            elif ("(" in s_clean and ")" in s_clean and any(tok in s_clean for tok in ("\d+", "[^", ".*?", "m3u8", "mp4"))):
                if len(s_clean) < 160 and s_clean not in regexes:
                    regexes.append(s_clean)
            elif s_clean.lower() in ("referer", "user-agent", "origin", "x-requested-with"):
                headers[s_clean] = "discovered"

        joined_str = " ".join(all_strings + list(java_files.values()))
        return DexAnalysisResult(
            jadx_available=jadx_ok,
            decompiled_java_files=java_files,
            string_pool=all_strings,
            discovered_urls=urls,
            css_selectors=selectors,
            regex_patterns=regexes,
            class_descriptors=all_types,
            method_names=list(dict.fromkeys(all_methods)),
            extracted_headers=headers,
            uses_crypto="Cipher" in joined_str or "AES" in joined_str or "CryptoJS" in joined_str,
            uses_jsoup="Jsoup" in joined_str or "select(" in joined_str or "document" in joined_str,
            uses_packer="eval(function(p,a,c,k,e" in joined_str or "getAndUnpack" in joined_str
        )
