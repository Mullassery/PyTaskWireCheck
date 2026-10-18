"""Opt-in shared cache backend.

The local cache is always authoritative. A remote cache is a best-effort
mirror: a failed download is a local miss, and a failed upload never changes a
task's result. This keeps CI usable when the shared cache is unavailable.

Wire format is intentionally simple and implementation-agnostic:

    GET  <base>/<key>.tgz   -> 200 + tar.gz of the entry directory, or 404
    PUT  <base>/<key>.tgz   -> store the body

The archive contains ``meta.json`` and ``artifacts/...`` exactly as the local
entry does. Extraction rejects absolute paths and ``..`` components before
writing anything.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class RemoteCache:
    """A minimal HTTP(S) shared-cache client."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("remote cache URL must be http(s)")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def _url(self, key: str) -> str:
        return "%s/%s.tgz" % (self.base_url, urllib.parse.quote(key, safe=""))

    def _headers(self) -> dict:
        headers = {"User-Agent": "pytaskwirecheck-remote-cache"}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers

    def fetch(self, key: str, destination: Path) -> bool:
        """Download and safely extract an entry. Returns False on any miss/error."""
        request = urllib.request.Request(self._url(key), headers=self._headers())
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                payload = response.read()
        except (urllib.error.URLError, OSError, ValueError):
            return False

        try:
            with tempfile.TemporaryDirectory(prefix="pytaskwirecheck-remote-") as tmp:
                archive_path = Path(tmp) / "entry.tgz"
                archive_path.write_bytes(payload)
                with tarfile.open(archive_path, "r:gz") as archive:
                    members = archive.getmembers()
                    for member in members:
                        name = member.name
                        if name.startswith("/") or ".." in Path(name).parts:
                            return False
                        if not (member.isfile() or member.isdir()):
                            return False
                    archive.extractall(tmp)
                extracted = Path(tmp) / "entry"
                if not (extracted / "meta.json").is_file():
                    return False
                import shutil

                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                shutil.copytree(extracted, destination)
        except (OSError, tarfile.TarError, ValueError):
            return False
        return True

    def push(self, key: str, entry: Path) -> bool:
        """Upload a local entry. Best-effort; returns False on any error."""
        if not entry.is_dir():
            return False
        buffer = io.BytesIO()
        try:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                archive.add(entry, arcname="entry", recursive=True)
        except (OSError, tarfile.TarError):
            return False
        request = urllib.request.Request(
            self._url(key),
            data=buffer.getvalue(),
            headers={**self._headers(), "Content-Type": "application/gzip"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            return False
