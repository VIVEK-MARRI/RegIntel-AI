"""Secrets management (M10.6).

A small, layered secrets manager that supports the standard precedence:

1. Explicit override (passed to :meth:`SecretsManager.get`).
2. Environment variable.
3. ``.env`` / ``secrets.json`` file under a configured root.
4. Optional Vault stub (HTTP, when ``vault_url`` is configured).

The manager never logs secret values; it returns redacted previews
in diagnostics. In production, the file layer is typically used only
for development; the env and Vault layers are the supported sources.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Errors ──────────────────────────────────────────────────────────


class SecretNotFoundError(KeyError):
    """Raised when a secret cannot be resolved from any source."""


class SecretAccessError(RuntimeError):
    """Raised when a secret source is reachable but returns an error."""


# ─── Source kind ─────────────────────────────────────────────────────


class SecretSource(str, Enum):
    """The origin of a resolved secret (in order of precedence)."""

    EXPLICIT = "explicit"
    ENV = "env"
    FILE = "file"
    VAULT = "vault"


# ─── Result type ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SecretResult:
    """A resolved secret + the source it came from + metadata."""

    name: str
    value: str
    source: SecretSource
    version: Optional[str] = None
    fetched_at: float = field(default_factory=time.time)

    def preview(self, *, visible: int = 4) -> str:
        """Return a redacted preview suitable for logs and audit reports."""
        if not self.value:
            return "<empty>"
        if len(self.value) <= visible * 2:
            return "***"
        return f"{self.value[:visible]}…{self.value[-visible:]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.value,
            "version": self.version,
            "fetched_at": self.fetched_at,
            "preview": self.preview(),
        }


# ─── Manager ─────────────────────────────────────────────────────────


class SecretsManager:
    """Thread-safe, layered secrets manager."""

    def __init__(
        self,
        *,
        env_prefix: str = "REGINTEL_",
        file_root: Optional[Path] = None,
        vault_url: Optional[str] = None,
        vault_token: Optional[str] = None,
        cache_ttl_seconds: int = 60,
    ) -> None:
        self._env_prefix = env_prefix
        self._file_root = Path(file_root) if file_root else None
        self._vault_url = vault_url
        self._vault_token = vault_token
        self._cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        # The override store is a side-channel of explicit values that take
        # precedence over everything but the per-call ``override=`` arg.
        self._overrides: Dict[str, SecretResult] = {}
        # The cache only stores results resolved from the long-lived sources
        # (env / file / vault) — never the per-call override.
        self._cache: Dict[str, SecretResult] = {}
        self._lock = threading.RLock()
        # Track which secrets have been redacted for diagnostics
        self._access_counts: Dict[str, int] = {}

    # ─── Public API ────────────────────────────────────────────────

    def get(
        self,
        name: str,
        *,
        default: Optional[str] = None,
        override: Optional[str] = None,
        use_cache: bool = True,
    ) -> SecretResult:
        """Resolve ``name`` through the precedence stack.

        Raises :class:`SecretNotFoundError` if no source has the secret
        and no default was provided.
        """
        if not name:
            raise ValueError("secret name must be a non-empty string")

        # 0. Per-call override (highest priority, never cached).
        if override is not None:
            self._bump(name)
            return SecretResult(name=name, value=override, source=SecretSource.EXPLICIT)

        # 0a. Stored override (test helper / management).
        with self._lock:
            stored_override = self._overrides.get(name)
        if stored_override is not None:
            self._bump(name)
            return stored_override

        # 1. Cache (only populated from long-lived sources).
        if use_cache:
            cached = self._cache_get(name)
            if cached is not None:
                self._bump(name)
                return cached

        # 2. Environment variable
        env_value = self._lookup_env(name)
        if env_value is not None:
            result = SecretResult(name=name, value=env_value, source=SecretSource.ENV)
            self._cache_put(result)
            self._bump(name)
            return result

        # 3. File
        if self._file_root is not None:
            file_value = self._lookup_file(name)
            if file_value is not None:
                result = SecretResult(name=name, value=file_value, source=SecretSource.FILE)
                self._cache_put(result)
                self._bump(name)
                return result

        # 4. Vault
        if self._vault_url:
            vault_value, version = self._lookup_vault(name)
            if vault_value is not None:
                result = SecretResult(
                    name=name, value=vault_value, source=SecretSource.VAULT, version=version
                )
                self._cache_put(result)
                self._bump(name)
                return result

        if default is not None:
            return SecretResult(name=name, value=default, source=SecretSource.EXPLICIT)

        raise SecretNotFoundError(f"secret {name!r} not found in any source")

    def require(self, name: str, **kwargs: Any) -> SecretResult:
        """Like :meth:`get` but never falls back to a default."""
        kwargs.pop("default", None)
        return self.get(name, **kwargs)

    def set_override(self, name: str, value: str) -> None:
        """Test helper: set a stored override. Clears the cache for that name."""
        with self._lock:
            self._overrides[name] = SecretResult(
                name=name, value=value, source=SecretSource.EXPLICIT
            )
            self._cache.pop(name, None)

    def invalidate(self, name: Optional[str] = None) -> None:
        with self._lock:
            if name is None:
                self._cache.clear()
                self._overrides.clear()
            else:
                self._cache.pop(name, None)
                self._overrides.pop(name, None)

    def diagnostics(self) -> Dict[str, Any]:
        """Return a redacted view of the manager state — never includes values."""
        with self._lock:
            return {
                "env_prefix": self._env_prefix,
                "file_root": str(self._file_root) if self._file_root else None,
                "vault_url": self._vault_url,
                "cache_size": len(self._cache),
                "override_count": len(self._overrides),
                "access_counts": dict(self._access_counts),
                "cached": {
                    n: {"source": r.source.value, "preview": r.preview(), "version": r.version}
                    for n, r in self._cache.items()
                },
            }

    def list_known(self) -> Iterable[str]:
        """List the names known to the file or env sources (no values)."""
        seen = set()
        for k in os.environ.keys():
            if k.startswith(self._env_prefix):
                seen.add(k[len(self._env_prefix):].lower())
        if self._file_root and self._file_root.exists():
            for entry in self._file_root.iterdir():
                if entry.is_file():
                    seen.add(entry.stem)
        return sorted(seen)

    # ─── Internals ────────────────────────────────────────────────

    def _lookup_env(self, name: str) -> Optional[str]:
        for variant in self._env_variants(name):
            value = os.environ.get(variant)
            if value is not None and value != "":
                return value
        return None

    def _env_variants(self, name: str) -> Iterable[str]:
        upper = name.upper().replace("-", "_")
        yield f"{self._env_prefix}{upper}"
        yield upper
        yield name

    def _lookup_file(self, name: str) -> Optional[str]:
        if self._file_root is None:
            return None
        # Try .env, secrets.json, and a direct file. Lookup is case-insensitive
        # so callers can use the canonical lowercase name regardless of how the
        # value was spelled in the file.
        for candidate in (
            self._file_root / f"{name}.txt",
            self._file_root / "secrets.json",
            self._file_root / ".env",
        ):
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                if candidate.suffix == ".json":
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, value in data.items():
                            if isinstance(k, str) and k.lower() == name.lower() and isinstance(value, str):
                                return value
                else:
                    text = candidate.read_text(encoding="utf-8")
                    for line in text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        if k.strip().lower() == name.lower():
                            return v.strip().strip('"').strip("'")
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Failed to read secret file %s: %s", candidate, exc)
        return None

    def _lookup_vault(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        if not self._vault_url:
            return None, None
        # Vault stub: this implementation performs an HTTP GET against
        # the KV v2 endpoint. If the network is unreachable we treat that
        # the same as "not found" so callers can degrade gracefully.
        try:
            import urllib.request

            url = f"{self._vault_url.rstrip('/')}/v1/secret/data/{name}"
            req = urllib.request.Request(url, method="GET")
            if self._vault_token:
                req.add_header("X-Vault-Token", self._vault_token)
            with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec - URL is configured
                payload = json.loads(resp.read().decode("utf-8"))
            data = payload.get("data", {}).get("data", {})
            value = data.get("value")
            version = str(payload.get("data", {}).get("metadata", {}).get("version", "")) or None
            return (value if isinstance(value, str) else None), version
        except Exception as exc:  # pragma: no cover - network
            logger.debug("Vault lookup for %s failed: %s", name, exc)
            return None, None

    def _cache_get(self, name: str) -> Optional[SecretResult]:
        with self._lock:
            cached = self._cache.get(name)
            if cached is None:
                return None
            if self._cache_ttl_seconds == 0:
                return cached
            if (time.time() - cached.fetched_at) > self._cache_ttl_seconds:
                self._cache.pop(name, None)
                return None
            return cached

    def _cache_put(self, result: SecretResult) -> None:
        with self._lock:
            self._cache[result.name] = result

    def _bump(self, name: str) -> None:
        with self._lock:
            self._access_counts[name] = self._access_counts.get(name, 0) + 1


# ─── Module-level singleton ──────────────────────────────────────────


_singleton: Optional[SecretsManager] = None
_singleton_lock = threading.Lock()


def get_secrets_manager() -> SecretsManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = SecretsManager()
        return _singleton


def reset_secrets_manager() -> None:
    """Test helper."""
    global _singleton
    _singleton = None


def set_secrets_manager(manager: SecretsManager) -> None:
    """Test helper: install a specific manager instance."""
    global _singleton
    _singleton = manager
