import os
import shutil
import subprocess
from typing import List, Tuple


class TypeScriptCompiler:
    """Compiles Seanime extension TypeScript to Goja-compatible ES2020 JavaScript.

    This replaces the previous regex-based "transpiler", which could not parse the
    TypeScript it was fed and silently emitted unloadable JavaScript (see FIXES.md).
    Compilation is delegated to the real TypeScript compiler via Node.
    """

    def __init__(self, repo_root: str = ".", node_bin: str = "node"):
        self.repo_root = os.path.abspath(repo_root)
        self.node_bin = shutil.which(node_bin)
        self.driver = os.path.join(self.repo_root, "engine", "ts-compiler", "compile.mjs")
        self.node_modules = os.path.join(self.repo_root, "node_modules")

    def is_available(self) -> Tuple[bool, str]:
        if not self.node_bin:
            return False, "Node.js was not found on PATH."
        if not os.path.exists(self.driver):
            return False, f"Compiler driver missing: {self.driver}"
        if not os.path.isdir(os.path.join(self.node_modules, "typescript")):
            return False, "The 'typescript' package is not installed. Run: npm ci (or npm install)."
        return True, ""

    def compile_files(self, ts_paths: List[str]) -> List[str]:
        """Compiles each .ts file in place to a sibling .js file. Raises on any failure."""
        ok, reason = self.is_available()
        if not ok:
            raise RuntimeError(f"Cannot compile TypeScript to JavaScript: {reason}")

        env = dict(os.environ)
        env["NODE_PATH"] = self.node_modules

        proc = subprocess.run(
            [self.node_bin, self.driver] + ts_paths,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            if "TYPESCRIPT_NOT_INSTALLED" in detail:
                raise RuntimeError("Cannot compile TypeScript to JavaScript: the 'typescript' package is not installed.")
            raise RuntimeError(f"TypeScript compilation failed:\n{detail[:2000]}")

        return [p[:-3] + ".js" if p.endswith(".ts") else p + ".js" for p in ts_paths]

    def check_js_syntax(self, js_paths: List[str]) -> List[str]:
        """Runs `node --check` on each emitted file. Returns the list of failures."""
        if not self.node_bin:
            return ["node is unavailable; JavaScript syntax could not be verified."]
        failures: List[str] = []
        for path in js_paths:
            proc = subprocess.run(
                [self.node_bin, "--check", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )
            if proc.returncode != 0:
                first = (proc.stderr or proc.stdout or "").strip().splitlines()
                failures.append(f"{os.path.basename(path)}: {first[0] if first else 'syntax error'}")
        return failures
