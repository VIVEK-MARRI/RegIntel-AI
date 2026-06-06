# Versioning Policy

> RegIntel AI follows [Semantic Versioning 2.0.0](https://semver.org/).

## Version format

```
vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
```

* **MAJOR** — incompatible API changes.
* **MINOR** — backward-compatible new functionality.
* **PATCH** — backward-compatible bug fixes.
* **PRERELEASE** — `rc1`, `rc2`, … for release candidates; `beta1`,
  `beta2`, … for public betas; `alpha1`, `alpha2`, … for internal
  previews.
* **BUILD** — auto-generated, used internally for traceability.

Examples:

* `v1.0.0` — first stable release.
* `v1.0.1` — first patch release.
* `v1.1.0-rc1` — first release candidate for the 1.1 minor.
* `v1.1.0-beta2` — second public beta.
* `v1.0.0+20260606` — build metadata, not part of precedence.

## Compatibility

### API

* The API version is part of the path (`/api/v1/...`). The MAJOR
  component of the software version is independent of the API version
  — we may bump the MAJOR for a non-API-breaking change.
* Breaking changes to the API:
  * Bump the API version (`/api/v2/...`).
  * Maintain the old endpoint for at least 6 months.
  * Emit `Deprecation` and `Sunset` headers.
  * Document the change in the release notes.

### Database

* Database schema changes are backward-compatible within a MINOR
  release. A migration that requires a backfill is acceptable as long
  as the old code can read the new schema.
* A MAJOR release may include destructive migrations (column drops,
  data migrations). The release notes call this out explicitly.

### Configuration

* Environment variables are stable. Removing or renaming a variable
  requires a MAJOR bump.
* New variables can be added in a MINOR release.

## Release channels

| Channel | Tag pattern | Audience | Cadence |
|---------|-------------|----------|---------|
| Stable | `vX.Y.Z` | Production | Monthly |
| RC | `vX.Y.Z-rcN` | Staging, internal users | Weekly during RC phase |
| Beta | `vX.Y.Z-betaN` | Selected external users | As needed |
| Nightly | `nightly` | Developers | Daily |

## Release lifecycle

1. **Development** — features land on `main` behind feature flags.
2. **Beta** — a `beta` branch is cut; external users opt in.
3. **RC** — the branch becomes `release/vX.Y.Z`; RCs are tagged
   weekly.
4. **Stable** — the first RC that passes all gates is re-tagged as
   `vX.Y.Z`.
5. **Maintenance** — patch releases on the previous MAJOR.MINOR for
   6 months after the next MAJOR is released.

## Deprecation policy

* An API endpoint or environment variable marked deprecated continues
  to work for at least 6 months before removal.
* The deprecation is announced:
  * In the release notes.
  * In the API response headers (`Deprecation: true`,
    `Sunset: <date>`).
  * In the documentation.
  * In the admin console (a yellow banner on the affected page).

## Support matrix

| Version | Released | EOL |
|---------|----------|-----|
| v1.0.x | 2026-06-06 | 2027-06-06 |
| v0.9.x | 2025-12-01 | 2026-12-01 |

## Release checklist

See `docs/RELEASE_CHECKLIST.md` for the step-by-step procedure.

## Version constants

The current version is exposed in three places:

* `app/__init__.py` — `__version__`.
* `app/main.py` — `APP_VERSION` (returned by `/api/v1/system/info`).
* Container labels — `org.opencontainers.image.version`.

All three are kept in lockstep by the release script
(`tools/release.py`).

## Git tags

* Tags are immutable.
* Tags follow the format `vX.Y.Z[-PRERELEASE]`.
* Tags are signed with the release team's GPG key.
* Annotated tags include the release notes excerpt as the message.

## Changelog

* `RELEASE_NOTES.md` — full release notes for the current and prior
  major versions.
* GitHub releases — auto-generated from the tag, supplemented with the
  release notes.
* `CHANGELOG.md` — machine-generated from conventional commits
  (Keep a Changelog format).
