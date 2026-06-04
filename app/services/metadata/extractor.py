import os
import hashlib
import re
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

logger = logging.getLogger(__name__)

class MetadataExtractor(ABC):
    """Abstract Base Class for pluggable metadata extractors."""
    
    @abstractmethod
    def extract(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extracts metadata from the given file.
        
        Args:
            file_path: Absolute Path to the file.
            context: Optional dictionary containing additional session/metadata context.
            
        Returns:
            Dictionary containing extracted keys and values.
        """
        pass

class FileMetadataExtractor(MetadataExtractor):
    """Extractor for basic OS-level and file-level metadata (size, checksum)."""
    
    def extract(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.debug(f"FileMetadataExtractor running on {file_path}")
        if not file_path.exists():
            return {}
            
        # File size
        file_size = os.path.getsize(file_path)
        
        # Checksum calculation
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        checksum = sha256.hexdigest()
        
        return {
            "file_size": file_size,
            "checksum": checksum
        }

class PDFStructureExtractor(MetadataExtractor):
    """Extractor for PDF structural elements (page counts)."""
    
    def extract(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.debug(f"PDFStructureExtractor running on {file_path}")
        if not file_path.exists():
            return {}
        if fitz is None:
            # Keep module import-time safe; return empty metadata when PDF parsing isn't available.
            return {}
            
        try:
            with fitz.open(file_path) as doc:
                page_count = doc.page_count
            return {"page_count": page_count}
        except Exception as e:
            logger.warning(f"PDFStructureExtractor failed to open PDF {file_path}: {e}")
            return {}

class RegulatorMetadataExtractor(MetadataExtractor):
    """Heuristic extractor parsing PDF content for regulatory metadata (circulars, authorities)."""
    
    def extract(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.debug(f"RegulatorMetadataExtractor running on {file_path}")
        if not file_path.exists():
            return {}
            
        if fitz is None:
            # Import-time safe optional dependency: return no-regex metadata when PDF parsing isn't available.
            return {}
            
        try:
            with fitz.open(file_path) as doc:
                if doc.page_count == 0:
                    return {}
                    
                # Read first page text for heuristics
                first_page_text = doc[0].get_text()
            
            # 1. Issuing Authority Heuristics
            issuing_authority = None
            if "reserve bank of india" in first_page_text.lower():
                issuing_authority = "Reserve Bank of India"
            elif "securities and exchange board of india" in first_page_text.lower() or "sebi" in first_page_text.lower():
                issuing_authority = "Securities and Exchange Board of India"
                
            # 2. Circular / Reference Number Heuristics
            circular_number = None
            # RBI pattern e.g., RBI/2026-27/12 or RBI/FMRD/2026-27/89
            rbi_circ_match = re.search(r"(RBI/\d{4}-\d{2}/\d+|RBI/[A-Z0-9/-]+/\d{4}-\d{2}/\d+)", first_page_text)
            # SEBI pattern e.g., SEBI/HO/CFD/CMD1/CIR/P/2026/123 or SEBI/LAD-NRO/GN/2026/89
            sebi_circ_match = re.search(r"(SEBI/[A-Z0-9/-]+/CIR/[A-Z0-9/-]+/\d{4}/\d+|SEBI/LAD-NRO/[A-Z0-9/-]+/\d{4}/\d+)", first_page_text)
            
            if rbi_circ_match:
                circular_number = rbi_circ_match.group(1)
            elif sebi_circ_match:
                circular_number = sebi_circ_match.group(1)
                
            # 3. Regulation Number Heuristics
            regulation_number = None
            reg_match = re.search(r"(Notification\s+No\.\s+[A-Za-z0-9-/]+|No\.\s*[A-Za-z0-9-/]+)", first_page_text, re.IGNORECASE)
            if reg_match:
                regulation_number = reg_match.group(1).strip()
                
            return {
                "circular_number": circular_number,
                "regulation_number": regulation_number,
                "issuing_authority": issuing_authority
            }
        except Exception as e:
            logger.warning(f"RegulatorMetadataExtractor failed to parse {file_path}: {e}")
            return {}
