"""RegIntel AI backend application package.

This module exposes the canonical version string for the application.
The same version is mirrored in:

* ``app.main`` — returned by the ``/api/v1/system/info`` endpoint.
* ``RELEASE_NOTES.md`` — the user-visible release identifier.
* The container label ``org.opencontainers.image.version``.

See ``docs/VERSIONING.md`` for the full versioning policy.
"""

from __future__ import annotations

__version__: str = "1.0.0"
__release_name__: str = "v1.0.0"
