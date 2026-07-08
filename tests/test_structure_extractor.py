import pytest
from httpx import AsyncClient
from app.services.structure.rule_based import RuleBasedStructureExtractor
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.page import DocumentPage


def test_rule_based_structure_extractor_direct():
    extractor = RuleBasedStructureExtractor()

    pages = [
        {
            "page_number": 1,
            "content": (
                "Reserve Bank of India\n"
                "Mumbai\n"
                "RBI/2026-27/12\n"
                "Cybersecurity Controls Guidelines\n"
                "CHAPTER I\n"
                "Introduction\n"
                "1. Background\n"
                "This guideline is issued to strengthen the cybersecurity posture.\n"
                "1.1 Applicability\n"
                "This applies to all commercial banks.\n"
                "Page 1 of 10\n"
            ),
        },
        {
            "page_number": 2,
            "content": (
                "CHAPTER II - Customer Due Diligence\n"
                "2. Customer Verification\n"
                "2.1 Guidelines\n"
                "(a) Identify the customer using reliable identity files.\n"
                "(b) Verify structural components.\n"
                "(i) Small account limits apply.\n"
                "3. This is a very long paragraph that starts with a number but should be ignored because it is actually a body text paragraph explaining the regulations in detail, with multiple sentences. Indeed, it describes the controls and governance structures. Another sentence here to test the heuristic."
            ),
        },
    ]

    elements = extractor.extract_structure(pages)

    # 1. Assert Title
    assert elements[0].type == "title"
    assert elements[0].title == "Cybersecurity Controls Guidelines"
    assert elements[0].page == 1

    # 2. Assert Chapter I
    assert elements[1].type == "chapter"
    assert elements[1].title == "Introduction"
    assert elements[1].numbering == "CHAPTER I"
    assert elements[1].page == 1

    # 3. Assert Section 1
    assert elements[2].type == "section"
    assert elements[2].title == "Background"
    assert elements[2].numbering == "1"

    # 4. Assert Subsection 1.1
    assert elements[3].type == "subsection"
    assert elements[3].title == "Applicability"
    assert elements[3].numbering == "1.1"

    # 5. Assert Chapter II
    assert elements[4].type == "chapter"
    assert elements[4].title == "Customer Due Diligence"
    assert elements[4].numbering == "CHAPTER II"
    assert elements[4].page == 2

    # 6. Assert Section 2
    assert elements[5].type == "section"
    assert elements[5].title == "Customer Verification"
    assert elements[5].numbering == "2"

    # 7. Assert Subsection 2.1
    assert elements[6].type == "subsection"
    assert elements[6].title == "Guidelines"
    assert elements[6].numbering == "2.1"

    # 8. Assert Clauses (a) and (b)
    assert elements[7].type == "clause"
    assert elements[7].title == "Identify the customer using reliable identity files."
    assert elements[7].numbering == "(a)"

    assert elements[8].type == "clause"
    assert elements[8].title == "Verify structural components."
    assert elements[8].numbering == "(b)"

    # 9. Assert Clause (i)
    assert elements[9].type == "clause"
    assert elements[9].title == "Small account limits apply."
    assert elements[9].numbering == "(i)"

    # 10. Long body paragraph starting with '3.' should be ignored
    # There shouldn't be any element with numbering "3"
    for el in elements:
        assert el.numbering != "3"


@pytest.mark.asyncio
async def test_get_document_structure_api(client: AsyncClient, db_session):
    # 1. Register a document
    doc = Document(
        title="RBI Guidelines on Cybersecurity Structure",
        source=SourceEnum.RBI,
        file_name="cyber_struct.pdf",
        file_path="RBI/cyber_struct.pdf",
        checksum="8" * 64,
        status=StatusEnum.UPLOADED,
    )
    db_session.add(doc)
    await db_session.commit()

    # 2. Add some pages
    page1 = DocumentPage(
        document_id=doc.id,
        page_number=1,
        content=(
            "Reserve Bank of India\n"
            "Master Circular - Cybersecurity\n"
            "1. Introduction\n"
            "1.1 Scope\n"
        ),
    )
    db_session.add(page1)
    await db_session.commit()

    # 3. Request structure API
    response = await client.get(f"/api/v1/documents/{doc.id}/structure")
    assert response.status_code == 200
    res_data = response.json()

    assert res_data["document_id"] == str(doc.id)
    structure = res_data["structure"]
    assert len(structure) == 3

    # Title
    assert structure[0]["type"] == "title"
    assert structure[0]["title"] == "Master Circular - Cybersecurity"

    # Section
    assert structure[1]["type"] == "section"
    assert structure[1]["title"] == "Introduction"
    assert structure[1]["numbering"] == "1"

    # Subsection
    assert structure[2]["type"] == "subsection"
    assert structure[2]["title"] == "Scope"
    assert structure[2]["numbering"] == "1.1"


@pytest.mark.asyncio
async def test_get_document_structure_api_not_found(client: AsyncClient):
    # Query non-existent document UUID
    non_existent_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/documents/{non_existent_id}/structure")
    assert response.status_code == 404
    assert response.json()["error_code"] == "DOCUMENT_NOT_FOUND"
