import hashlib
import uuid
import logging
from typing import BinaryIO
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.storage_provider import StorageProvider
from app.repositories.document import DocumentRepository
from app.core.exceptions import DuplicateDocumentError

logger = logging.getLogger(__name__)

class StorageService:
    """Orchestrates file storage, calculates checksums, and enforces DB-level duplicate validation."""
    
    def __init__(self, provider: StorageProvider, db_session: AsyncSession):
        self.provider = provider
        self.repository = DocumentRepository(db_session)
        self.db_session = db_session

    async def calculate_checksum(self, file_data: BinaryIO) -> str:
        """Calculates the SHA-256 checksum of a file-like object in chunks."""
        sha256 = hashlib.sha256()
        file_data.seek(0)
        
        # Read in 64KB chunks to optimize memory
        chunk_size = 65536
        while True:
            chunk = file_data.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
            
        file_data.seek(0)  # Reset pointer to start for subsequent reads
        checksum = sha256.hexdigest()
        logger.debug(f"Calculated checksum: {checksum}")
        return checksum

    async def save_file(self, file_data: BinaryIO, original_filename: str, source: str) -> tuple[str, str]:
        """Saves a file after checking for duplicates based on SHA-256 checksum.
        
        Args:
            file_data: Binary file stream.
            original_filename: Name of the uploaded file.
            source: Source regulatory agency ("RBI" or "SEBI").
            
        Returns:
            Tuple of (relative_storage_path, sha256_checksum)
        """
        source_upper = source.upper()
        if source_upper not in ["RBI", "SEBI", "USER_UPLOAD"]:
            raise ValueError("Invalid source regulatory body. Must be RBI, SEBI, or USER_UPLOAD.")
            
        # Calculate checksum
        checksum = await self.calculate_checksum(file_data)
        
        # Check duplication in the database registry
        existing = await self.repository.get_document_by_checksum(checksum)
        if existing:
            logger.warning(f"File upload rejected. Checksum duplicate found in registry: {checksum}")
            raise DuplicateDocumentError(checksum)
            
        # Generate UUID-based destination filename
        file_ext = Path(original_filename).suffix
        if not file_ext:
            file_ext = ".pdf"  # Fallback to pdf if not specified
            
        new_filename = f"{uuid.uuid4()}{file_ext}"
        destination_path = f"{source_upper}/{new_filename}"
        
        # Store file using provider
        await self.provider.save_file(file_data, destination_path)
        logger.info(f"Saved file {original_filename} to path: {destination_path}")
        
        return destination_path, checksum

    async def delete_file(self, file_path: str) -> None:
        """Deletes a file from storage."""
        await self.provider.delete_file(file_path)
        logger.info(f"Deleted file at path: {file_path}")

    async def file_exists(self, file_path: str) -> bool:
        """Checks if a file exists in storage."""
        return await self.provider.file_exists(file_path)
