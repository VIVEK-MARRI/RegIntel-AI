import tempfile
import pytest
from pathlib import Path
import fitz
from app.services.metadata.extractor import (
    MetadataExtractor,
    FileMetadataExtractor,
    PDFStructureExtractor,
    RegulatorMetadataExtractor,
)
from app.services.metadata.service import MetadataService


@pytest.fixture
def create_pdf_with_text():
    def _create(dest_path: Path, text: str, page_count: int = 1):
        doc = fitz.open()
        for i in range(page_count):
            page = doc.new_page()
            if i == 0 and text:
                page.insert_text((50, 50), text)
        doc.save(dest_path)
        doc.close()

    return _create


def test_file_metadata_extractor():
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "test.txt"
        file_path.write_bytes(b"RegIntel Metadata Test Content")

        extractor = FileMetadataExtractor()
        metadata = extractor.extract(file_path)

        assert metadata["file_size"] == len(b"RegIntel Metadata Test Content")
        import hashlib

        assert (
            metadata["checksum"]
            == hashlib.sha256(b"RegIntel Metadata Test Content").hexdigest()
        )


def test_pdf_structure_extractor(create_pdf_with_text):
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = Path(temp_dir) / "test.pdf"
        create_pdf_with_text(pdf_path, "Simple text", page_count=5)

        extractor = PDFStructureExtractor()
        metadata = extractor.extract(pdf_path)

        assert metadata["page_count"] == 5


def test_regulator_metadata_extractor_rbi(create_pdf_with_text):
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = Path(temp_dir) / "rbi_doc.pdf"
        rbi_text = (
            "RESERVE BANK OF INDIA\n"
            "Reference Number: RBI/2026-27/12\n"
            "Notification No. RBI-FMRD-15\n"
            "Sub: Cybersecurity directions for Banks."
        )
        create_pdf_with_text(pdf_path, rbi_text)

        extractor = RegulatorMetadataExtractor()
        metadata = extractor.extract(pdf_path)

        assert metadata["issuing_authority"] == "Reserve Bank of India"
        assert metadata["circular_number"] == "RBI/2026-27/12"
        assert metadata["regulation_number"] == "Notification No. RBI-FMRD-15"


def test_regulator_metadata_extractor_sebi(create_pdf_with_text):
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = Path(temp_dir) / "sebi_doc.pdf"
        sebi_text = (
            "SECURITIES AND EXCHANGE BOARD OF INDIA\n"
            "Circular: SEBI/LAD-NRO/GN/2026/89\n"
            "No. SEBI-LAD-NRO-90\n"
            "Sub: Portfolio managers guidelines."
        )
        create_pdf_with_text(pdf_path, sebi_text)

        extractor = RegulatorMetadataExtractor()
        metadata = extractor.extract(pdf_path)

        assert metadata["issuing_authority"] == "Securities and Exchange Board of India"
        assert metadata["circular_number"] == "SEBI/LAD-NRO/GN/2026/89"
        assert metadata["regulation_number"] == "No. SEBI-LAD-NRO-90"


def test_metadata_service_orchestration_and_pluggability(create_pdf_with_text):
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = Path(temp_dir) / "doc.pdf"
        rbi_text = "RESERVE BANK OF INDIA\n" "RBI/2026-27/12"
        create_pdf_with_text(pdf_path, rbi_text, page_count=2)

        # Instantiate service with default extractors
        service = MetadataService(
            [
                FileMetadataExtractor(),
                PDFStructureExtractor(),
                RegulatorMetadataExtractor(),
            ]
        )

        # 1. Run extraction
        metadata = service.extract_metadata(pdf_path)

        # Assert merged metadata
        assert metadata["issuing_authority"] == "Reserve Bank of India"
        assert metadata["circular_number"] == "RBI/2026-27/12"
        assert metadata["page_count"] == 2
        assert "file_size" in metadata
        assert "checksum" in metadata
        assert "upload_timestamp" in metadata

        # 2. Strategy Pattern Pluggability: register custom extractor on the fly
        class CustomClassificationExtractor(MetadataExtractor):
            def extract(self, file_path, context=None):
                return {"classification_score": 0.95, "topic": "Cybersecurity"}

        service.register_extractor(CustomClassificationExtractor())

        # Extract again
        enriched_metadata = service.extract_metadata(pdf_path)

        # Assert custom keys are now successfully merged without modifying core logic!
        assert enriched_metadata["classification_score"] == 0.95
        assert enriched_metadata["topic"] == "Cybersecurity"
        # Core keys are still there
        assert enriched_metadata["page_count"] == 2
        assert enriched_metadata["issuing_authority"] == "Reserve Bank of India"
