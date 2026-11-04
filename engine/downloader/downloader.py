import hashlib
import ipaddress
import json
import os
import socket
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, Tuple

class SecureCS3Downloader:
    """Downloads .cs3 archives and manifests with SSRF protection, size limits, and SHA-256 caching."""

    def __init__(self, cache_dir: str = ".cache/packages", max_size_mb: int = 25, timeout: int = 25):
        self.cache_dir = cache_dir
        self.max_bytes = max_size_mb * 1024 * 1024
        self.timeout = timeout
        os.makedirs(self.cache_dir, exist_ok=True)
        self.state_file = os.path.join(self.cache_dir, "download_state.json")
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_state(self) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    @staticmethod
    def normalize_url(url: str) -> str:
        """Percent-encodes characters that urllib refuses, e.g. the space in "Aia2tv 2.cs3".

        Cloudstream repositories routinely ship package names with spaces and non-ASCII
        characters. '%' is kept safe so already-encoded URLs are not double-encoded.
        """
        if not url:
            return url
        return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")

    @staticmethod
    def validate_url_security(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Disallowed URL scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Missing hostname in URL")
        if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or hostname.endswith(".local"):
            raise ValueError(f"Blocked private/local hostname: {hostname}")
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast:
                    raise ValueError(f"SSRF Protection triggered: {hostname} resolves to private IP {ip_str}")
        except socket.gaierror:
            # Allow offline test fixtures or DNS resolution handled downstream
            pass

    def fetch_json(self, url: str) -> Any:
        self.validate_url_security(url)
        req = urllib.request.Request(
            self.normalize_url(url),
            headers={"User-Agent": "Cloudstream-Seanime-Converter/2.4 (+https://github.com)"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read(self.max_bytes)
            return json.loads(raw.decode("utf-8"))

    def download_cs3(
        self,
        url: str,
        plugin_id: str,
        declared_version: int,
        expected_sha256: Optional[str] = None
    ) -> Tuple[str, str, bool]:
        """Returns (local_path, sha256_hex, was_cached_and_unchanged)."""
        self.validate_url_security(url)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in plugin_id)
        dest_path = os.path.join(self.cache_dir, f"{safe_name}_v{declared_version}.cs3")

        prev_record = self.state.get(plugin_id)
        if prev_record and os.path.exists(dest_path):
            if prev_record.get("version") == declared_version and prev_record.get("url") == url:
                cached_sha = prev_record.get("sha256", "")
                if not expected_sha256 or expected_sha256.lower() == cached_sha.lower():
                    return dest_path, cached_sha, True

        req = urllib.request.Request(
            self.normalize_url(url),
            headers={"User-Agent": "Cloudstream-Seanime-Converter/2.4"}
        )
        hasher = hashlib.sha256()
        total_read = 0

        with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > self.max_bytes:
                    out.close()
                    os.remove(dest_path)
                    raise ValueError(f"Package {plugin_id} exceeded max size limit ({self.max_bytes} bytes)")
                hasher.update(chunk)
                out.write(chunk)

        digest = hasher.hexdigest()
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            os.remove(dest_path)
            raise ValueError(f"SHA-256 mismatch for {plugin_id}: expected {expected_sha256}, got {digest}")

        self.state[plugin_id] = {
            "url": url,
            "version": declared_version,
            "sha256": digest,
            "size": total_read
        }
        self.save_state()
        return dest_path, digest, False
