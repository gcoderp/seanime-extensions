import re
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class SmaliControlFlowIR:
    method_signatures: List[str] = field(default_factory=list)
    invoked_apis: List[str] = field(default_factory=list)
    const_strings: List[str] = field(default_factory=list)
    http_endpoints: List[str] = field(default_factory=list)
    jsoup_queries: List[str] = field(default_factory=list)

class SmaliAnalyzer:
    """Analyzes Smali disassembly or synthesizes Dalvik instruction IR when JADX fails on Kotlin coroutines."""

    CONST_STRING_RE = re.compile(r'const-string(?:/jumbo)?\s+v\d+,\s+"([^"]+)"')
    INVOKE_RE = re.compile(r'invoke-(?:virtual|direct|static|interface)\s+\{[^}]*\},\s+([L][^;]+;->[^\s(]+\([^)]*\)\S+)')

    def analyze_smali_text(self, smali_content: str) -> SmaliControlFlowIR:
        ir = SmaliControlFlowIR()
        for m in self.CONST_STRING_RE.finditer(smali_content):
            val = m.group(1)
            ir.const_strings.append(val)
            if val.startswith(("http://", "https://", "/")):
                ir.http_endpoints.append(val)
        for m in self.INVOKE_RE.finditer(smali_content):
            sig = m.group(1)
            ir.invoked_apis.append(sig)
        return ir

    def reconstruct_from_dex_strings(self, string_pool: List[str], method_names: List[str]) -> SmaliControlFlowIR:
        ir = SmaliControlFlowIR(method_signatures=method_names)
        for idx, s in enumerate(string_pool):
            ir.const_strings.append(s)
            if s.startswith(("https://", "http://")) or "/search" in s or "/ajax/" in s or "/episode" in s:
                ir.http_endpoints.append(s)
            if any(tag in s for tag in ("div.", "ul.", "li.", "a[href", ".film_list", ".episodes", ".items", "article")):
                ir.jsoup_queries.append(s)
        return ir
