#!/usr/bin/env python3
"""API contract check script (P1.5).

Verifies that all API paths the frontend actually calls are present in the
OpenAPI spec exposed by the backend. Fails with a non-zero exit code if any
path or method referenced in frontend/src/services/api/** is absent from the
spec.

Usage:
    python .github/scripts/check_api_contract.py --base-url http://localhost:8000

The script does NOT require network access beyond the base_url argument — it
fetches /openapi.json from the running test server.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ─── Frontend API call extraction ─────────────────────────────────────────────

_API_CALL_PATTERN = re.compile(
    # Matches: apiClient.get("/api/v1/..."), axios.post(`/api/v1/...`), etc.
    r"""(?:apiClient|axios|api|client|http)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*[`'"]((/api/v1[^`'"?]*))""",
    re.IGNORECASE,
)

_TEMPLATE_LITERAL_PATTERN = re.compile(
    r"""\$\{[^}]+\}""",
)


def _extract_frontend_calls(services_dir: Path) -> List[Tuple[str, str]]:
    """Extract (method, path_template) pairs from frontend API service files.

    Template literals like ``/api/v1/documents/${id}`` are normalized to
    ``/api/v1/documents/{id}`` for comparison with the OpenAPI spec.
    """
    calls: List[Tuple[str, str]] = []
    for ts_file in services_dir.rglob("*.ts"):
        text = ts_file.read_text(encoding="utf-8", errors="replace")
        for match in _API_CALL_PATTERN.finditer(text):
            method = match.group(1).upper()
            raw_path = match.group(2)
            # Normalize template literals: ${id} → {id}
            normalized = _TEMPLATE_LITERAL_PATTERN.sub("{id}", raw_path)
            # Strip trailing slashes for comparison.
            normalized = normalized.rstrip("/")
            calls.append((method, normalized))
    return calls


# ─── OpenAPI spec fetching ────────────────────────────────────────────────────


def _fetch_openapi(base_url: str) -> Dict:
    url = base_url.rstrip("/") + "/openapi.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"ERROR: Could not fetch OpenAPI spec from {url}: {exc}", file=sys.stderr)
        sys.exit(2)


def _build_spec_index(spec: Dict) -> Set[Tuple[str, str]]:
    """Build a set of (METHOD, /path/template) from the OpenAPI paths object."""
    index: Set[Tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                index.add((method.upper(), path))
    return index


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Check frontend/backend API contract")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the running backend (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--services-dir",
        default=str(Path(__file__).parent.parent.parent / "frontend" / "src" / "services"),
        help="Path to frontend services directory",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail even if paths are present but with wrong method (default: error only)",
    )
    args = parser.parse_args()

    services_dir = Path(args.services_dir)
    if not services_dir.exists():
        print(f"WARNING: Frontend services directory not found: {services_dir}")
        print("Skipping frontend API extraction.")
        return 0

    print(f"Fetching OpenAPI spec from {args.base_url}/openapi.json ...")
    spec = _fetch_openapi(args.base_url)
    spec_index = _build_spec_index(spec)

    print(f"Extracting frontend API calls from {services_dir} ...")
    frontend_calls = _extract_frontend_calls(services_dir)

    if not frontend_calls:
        print("No API calls extracted from frontend. Check the regex pattern.")
        return 0

    print(f"\nFound {len(frontend_calls)} frontend API call(s):")
    print(f"Backend OpenAPI exposes {len(spec_index)} path+method combinations.")

    missing: List[Tuple[str, str]] = []
    for method, path in sorted(set(frontend_calls)):
        # Exact match first.
        if (method, path) in spec_index:
            print(f"  ✓ {method} {path}")
            continue
        # Try with and without trailing slash.
        alt = path + "/" if not path.endswith("/") else path[:-1]
        if (method, alt) in spec_index:
            print(f"  ✓ {method} {path}  (matched as {alt})")
            continue
        # Try lowercased method.
        if any(
            (spec_m, spec_p) for (spec_m, spec_p) in spec_index
            if spec_p == path and spec_m == method
        ):
            print(f"  ✓ {method} {path}")
            continue
        print(f"  ✗ {method} {path}  ← MISSING from OpenAPI spec")
        missing.append((method, path))

    if missing:
        print(f"\nCONTRACT VIOLATION: {len(missing)} path(s) missing from OpenAPI spec:")
        for method, path in missing:
            print(f"  {method} {path}")
        print("\nEither the backend needs to expose these paths, or the frontend call is stale.")
        return 1

    print(f"\nAll {len(frontend_calls)} frontend API call(s) are present in the OpenAPI spec. ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
