import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List
from app.services.metadata.extractor import MetadataExtractor

logger = logging.getLogger(__name__)

class MetadataService:
    """Orchestrator managing pluggable metadata extraction strategies."""
    
    def __init__(self, extractors: List[MetadataExtractor] = None):
        self.extractors = extractors or []
        logger.info(f"Initialized MetadataService with {len(self.extractors)} extractors")

    def register_extractor(self, extractor: MetadataExtractor) -> None:
        """Dynamically registers a new metadata extractor strategy."""
        self.extractors.append(extractor)
        logger.info(f"Registered new metadata extractor: {extractor.__class__.__name__}")

    def extract_metadata(self, file_path: Path, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Runs all registered extractors sequentially and merges results with the upload timestamp."""
        logger.info(f"Extracting metadata for file: {file_path}")
        
        # Base metadata payload
        merged_metadata = {
            "upload_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Run registered extractors
        for extractor in self.extractors:
            try:
                extracted = extractor.extract(file_path, context)
                merged_metadata.update(extracted)
            except Exception as e:
                logger.error(
                    f"Metadata extractor {extractor.__class__.__name__} failed on {file_path}: {e}",
                    exc_info=True
                )
                
        return merged_metadata
