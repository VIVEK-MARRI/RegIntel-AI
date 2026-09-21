"""Demo-corpus seeding for zero-friction portfolio deployments.

On a fresh database (zero documents) with ``SEED_DEMO_CORPUS=true``, ingests
the small public-domain regulatory excerpts shipped in ``seed_data/`` through
the REAL upload → parse → chunk → embed pipeline. Never re-seeds (guarded by
row count), never fails boot (all errors are logged), and every seeded row is
marked ``document_type="demo-corpus"`` so demo data is distinguishable.

Seed files are ~25 KB total; TF-IDF fitting on this corpus takes seconds,
safe for free-tier cold starts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.models.document import SourceEnum

logger = logging.getLogger(__name__)

# filename prefix → regulatory source
_SOURCE_PREFIXES = (
    ("rbi_", SourceEnum.RBI),
    ("sebi_", SourceEnum.SEBI),
    ("irdai_", SourceEnum.IRDAI),
)


def _seed_dir() -> Path:
    # repo-root/seed_data (copied into the Docker image for deploys)
    return Path(__file__).resolve().parent.parent.parent / "seed_data"


async def seed_demo_corpus() -> int:
    """Ingest seed_data/*.txt iff the flag is on and the DB is empty."""
    if not settings.SEED_DEMO_CORPUS:
        return 0
    seed_dir = _seed_dir()
    files = sorted(seed_dir.glob("*.txt")) if seed_dir.is_dir() else []
    if not files:
        logger.warning("SEED_DEMO_CORPUS is on but no seed files at %s", seed_dir)
        return 0

    from app.core.database import async_session_factory
    from app.schemas.document import DocumentCreate
    from app.services.document import DocumentService
    from app.services.ingestion import build_default_auto_ingestion_service
    from app.services.storage_provider import LocalStorageProvider
    from app.services.storage_service import StorageService

    async with async_session_factory() as session:
        from sqlalchemy import func, select

        from app.models.document import Document

        existing = await session.execute(select(func.count(Document.id)))
        if (existing.scalar() or 0) > 0:
            logger.info("Demo corpus already present; skipping seed")
            return 0

        document_service = DocumentService(session)
        storage_service = StorageService(
            LocalStorageProvider(settings.STORAGE_ROOT), session
        )
        ingestion_service = build_default_auto_ingestion_service()
        seeded = 0
        for path in files:
            try:
                source = SourceEnum.USER_UPLOAD
                for prefix, src in _SOURCE_PREFIXES:
                    if path.name.lower().startswith(prefix):
                        source = src
                        break
                with open(path, "rb") as f:
                    file_path, checksum = await storage_service.save_file(
                        file_data=f,
                        original_filename=path.name,
                        source=source.value,
                    )
                doc = await document_service.register_document(
                    DocumentCreate(
                        title=path.stem.replace("_", " ").title() + " [Demo]",
                        source=source,
                        file_name=path.name,
                        file_path=file_path,
                        document_type="demo-corpus",
                        checksum=checksum,
                    )
                )
                await session.commit()
                try:
                    await ingestion_service.ingest_upload(str(doc.id))
                except Exception as exc:
                    logger.warning("Demo seed ingestion deferred for %s: %s", path.name, exc)
                seeded += 1
            except Exception as exc:
                logger.warning("Demo seed skipped %s: %s", path.name, exc)
                try:
                    await session.rollback()
                except Exception:
                    pass
        logger.warning(
            "Seeded %d demo-corpus documents (public excerpts, ephemeral files)",
            seeded,
        )
        return seeded
