# Release Checklist

> The mandatory procedure for cutting a new release. **No release may
> ship without every box ticked.**

## 1. Pre-release

- [ ] The release branch `release/vX.Y.Z` is cut from `main`.
- [ ] All targeted issues / PRs are merged.
- [ ] The CI pipeline is green on the release branch.
- [ ] The benchmark suite has been run on the RC; results are
      attached to the release PR.
- [ ] The security audit (Trivy + pip-audit + bandit) is clean.
- [ ] The release notes (`RELEASE_NOTES.md`) are complete and reviewed.
- [ ] `docs/VERSIONING.md` reflects the new version.
- [ ] The deprecation list (`docs/VERSIONING.md#deprecation-policy`) is
      up to date.

## 2. Version bump

- [ ] `app/__init__.py` — `__version__` updated to `X.Y.Z`.
- [ ] `app/main.py` — `APP_VERSION` updated to `X.Y.Z`.
- [ ] `app/main.py` — `API_VERSION` unchanged (only bumped on a
      breaking API change).
- [ ] `frontend/package.json` — `version` updated to `X.Y.Z`.
- [ ] `requirements.txt` — no change unless a new dependency was
      added (and is reflected in the release notes).

## 3. Migration

- [ ] Any schema change has an Alembic migration in
      `alembic/versions/`.
- [ ] The migration has been tested on a copy of production data.
- [ ] The migration is **backward-compatible** (old code can read
      the new schema) unless this is a MAJOR release, in which case
      the destructive change is called out in the release notes.

## 4. Build

- [ ] `git tag -s vX.Y.Z-rcN -m "RegIntel AI vX.Y.Z-rcN"` (sign with
      the release team's GPG key).
- [ ] `git push origin vX.Y.Z-rcN`.
- [ ] The release workflow (`.github/workflows/release.yml`) builds
      multi-arch images and pushes to GHCR.
- [ ] SBOM (`*.sbom`) and provenance (`*.att`) are generated.
- [ ] Trivy image scan completes with no critical findings.
- [ ] The release is drafted in GitHub Releases with the release
      notes.

## 5. Smoke test on staging

- [ ] Pull the new image on staging:
      `docker compose -f docker-compose.production.yml pull`.
- [ ] Apply migrations:
      `docker compose -f docker-compose.production.yml run --rm backend alembic upgrade head`.
- [ ] Restart: `docker compose -f docker-compose.production.yml up -d`.
- [ ] Verify:
      - [ ] `curl -f https://staging.<host>/health/live`
      - [ ] `curl -f https://staging.<host>/health/ready`
      - [ ] `curl -f https://staging.<host>/api/v1/security/selftest`
      - [ ] `curl -f https://staging.<host>/api/v1/benchmark/health`
- [ ] Run a smoke test suite:
      - [ ] Sign in as a viewer; ask a question; confirm citations.
      - [ ] Sign in as an operator; upload a document; confirm
            ingestion.
      - [ ] Sign in as an auditor; review a governance decision.
      - [ ] Sign in as an admin; rotate an API key; confirm rotation.
- [ ] Run the benchmark suite:
      `curl -X POST https://staging.<host>/api/v1/benchmark/run -d '{"suite":"full"}' -H 'Content-Type: application/json'`.
- [ ] Compare the results against the previous release. A
      regression > 10% in p99 latency or cost blocks the release.

## 6. Promote to production

- [ ] Create a maintenance window (off-peak, ≥ 30 minutes).
- [ ] Notify stakeholders (`#regintel-ops`, status page).
- [ ] Repeat step 5 against production (without the destructive
      tests).
- [ ] Verify the post-deploy dashboard for 30 minutes.
- [ ] If the regression budget is exceeded, roll back: `kubectl
      rollout undo deploy/regintel-backend` (or
      `docker compose up -d` with the previous tag).

## 7. Post-release

- [ ] The GitHub release is published.
- [ ] The release notes are mirrored to the documentation site.
- [ ] The Slack `#announce` channel is notified.
- [ ] The status page is updated.
- [ ] The next MINOR release branch (`release/vX.(Y+1).0`) is created
      from `main`.
- [ ] Any post-release issues are filed as `priority/critical` and
      triaged within 24 hours.

## 8. Security review (for MAJOR releases only)

- [ ] A third-party security audit is performed.
- [ ] Penetration testing covers the new features.
- [ ] The audit report is attached to the release PR.
- [ ] The compliance team signs off.

## Approval

- [ ] Engineering lead
- [ ] Security lead
- [ ] Operations lead
- [ ] Product owner

## Tools

* `tools/release.py` — automated version bump + tag.
* `tools/migrate_v0_to_v1.py` — v0 → v1 data migration.
* `tools/benchmark_compare.py` — compare two benchmark reports.

## See also

* `docs/VERSIONING.md` — the versioning policy.
* `docs/DEPLOYMENT.md` — the deployment procedure.
* `docs/OPERATIONS.md` — the day-2 operations guide.
