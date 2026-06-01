import uuid
import pytest
from httpx import AsyncClient
from app.schemas.structure import StructureElement
from app.services.structure.hierarchy import HierarchyBuilder
from app.services.structure.validator import HierarchyValidator
from app.schemas.hierarchy import HierarchyNode
from app.models.document import Document, SourceEnum, StatusEnum
from app.models.page import DocumentPage

def test_hierarchy_builder_and_stable_ids():
    builder = HierarchyBuilder()
    doc_id = uuid.uuid4()
    
    elements = [
        StructureElement(type="title", title="KYC Circular", page=1, level=0),
        StructureElement(type="chapter", title="Chapter I", numbering="CHAPTER I", page=1, level=1),
        StructureElement(type="section", title="Background", numbering="1", page=1, level=2),
        StructureElement(type="subsection", title="Applicability", numbering="1.1", page=2, level=3),
        StructureElement(type="clause", title="Small accounts", numbering="(a)", page=2, level=5),
        StructureElement(type="chapter", title="Chapter II", numbering="CHAPTER II", page=3, level=1),
    ]
    
    root = builder.build_hierarchy(doc_id, "KYC Circular", elements)
    
    # Assert hierarchy structure
    assert root.node_type == "document"
    assert root.title == "KYC Circular"
    assert len(root.children) == 2  # 2 Chapters
    
    ch1 = root.children[0]
    assert ch1.title == "Chapter I"
    assert len(ch1.children) == 1  # 1 Section
    
    sec1 = ch1.children[0]
    assert sec1.title == "Background"
    assert len(sec1.children) == 1  # 1 Subsection
    
    subsec1 = sec1.children[0]
    assert subsec1.title == "Applicability"
    assert len(subsec1.children) == 1  # 1 Clause
    
    clause1 = subsec1.children[0]
    assert clause1.title == "Small accounts"
    assert clause1.parent_id == subsec1.node_id
    
    ch2 = root.children[1]
    assert ch2.title == "Chapter II"
    assert ch2.parent_id == root.node_id
    
    # Verify Stable Node ID generation invariance
    # Rebuilding with same structure but slightly different page numbers should yield IDENTICAL node_ids
    elements_new_pages = [
        StructureElement(type="title", title="KYC Circular", page=1, level=0),
        StructureElement(type="chapter", title="Chapter I", numbering="CHAPTER I", page=2, level=1),  # changed page
        StructureElement(type="section", title="Background", numbering="1", page=2, level=2),
        StructureElement(type="subsection", title="Applicability", numbering="1.1", page=3, level=3),
        StructureElement(type="clause", title="Small accounts", numbering="(a)", page=4, level=5),
        StructureElement(type="chapter", title="Chapter II", numbering="CHAPTER II", page=5, level=1),
    ]
    root_new = builder.build_hierarchy(doc_id, "KYC Circular", elements_new_pages)
    
    assert root_new.node_id == root.node_id
    assert root_new.children[0].node_id == ch1.node_id
    assert root_new.children[0].children[0].node_id == sec1.node_id
    assert root_new.children[0].children[0].children[0].node_id == subsec1.node_id
    assert root_new.children[0].children[0].children[0].children[0].node_id == clause1.node_id
    
    # Rebuilding with a different doc_id must yield DIFFERENT node_ids
    doc_id_different = uuid.uuid4()
    root_diff = builder.build_hierarchy(doc_id_different, "KYC Circular", elements)
    assert root_diff.node_id != root.node_id
    assert root_diff.children[0].node_id != ch1.node_id

def test_hierarchy_validator():
    validator = HierarchyValidator()
    
    # 1. Valid Tree
    valid_root = HierarchyNode(
        node_id="root",
        node_type="document",
        title="Valid Document",
        page=1,
        level=0,
        children=[
            HierarchyNode(
                node_id="ch1",
                node_type="chapter",
                title="Chapter 1",
                parent_id="root",
                page=1,
                level=1,
                children=[
                    HierarchyNode(
                        node_id="sec1",
                        node_type="section",
                        title="Section 1",
                        parent_id="ch1",
                        page=2,
                        level=2,
                        children=[]
                    )
                ]
            )
        ]
    )
    assert len(validator.validate(valid_root)) == 0
    
    # 2. Invalid Tree (Level violation: parent has level 2, child has level 1)
    invalid_level = HierarchyNode(
        node_id="root",
        node_type="document",
        title="Invalid Level",
        page=1,
        level=0,
        children=[
            HierarchyNode(
                node_id="sec1",
                node_type="section",
                title="Section 1",
                parent_id="root",
                page=1,
                level=2,
                children=[
                    HierarchyNode(
                        node_id="ch1",
                        node_type="chapter",
                        title="Chapter 1",
                        parent_id="sec1",
                        page=1,
                        level=1,  # level 1 under level 2 -> ERROR!
                        children=[]
                    )
                ]
            )
        ]
    )
    errors = validator.validate(invalid_level)
    assert len(errors) > 0
    assert any("Level violation" in e for e in errors)

    # 3. Invalid Tree (Page regression: child page < parent page)
    invalid_page = HierarchyNode(
        node_id="root",
        node_type="document",
        title="Invalid Page",
        page=5,
        level=0,
        children=[
            HierarchyNode(
                node_id="ch1",
                node_type="chapter",
                title="Chapter 1",
                parent_id="root",
                page=4,  # page 4 under page 5 -> ERROR!
                level=1,
                children=[]
            )
        ]
    )
    errors = validator.validate(invalid_page)
    assert len(errors) > 0
    assert any("Page progression violation" in e for e in errors)

    # 4. Invalid Tree (Empty title)
    invalid_title = HierarchyNode(
        node_id="root",
        node_type="document",
        title="  ",  # whitespace only -> ERROR!
        page=1,
        level=0,
        children=[]
    )
    errors = validator.validate(invalid_title)
    assert len(errors) > 0
    assert any("empty or whitespace-only title" in e for e in errors)

@pytest.mark.asyncio
async def test_get_document_hierarchy_api(client: AsyncClient, db_session):
    # 1. Register document
    doc = Document(
        title="RBI Guidelines on Cybersecurity Hierarchy",
        source=SourceEnum.RBI,
        file_name="cyber_hierarchy.pdf",
        file_path="RBI/cyber_hierarchy.pdf",
        checksum="7" * 64,
        status=StatusEnum.UPLOADED
    )
    db_session.add(doc)
    await db_session.commit()
    
    # 2. Add some pages
    page1 = DocumentPage(
        document_id=doc.id,
        page_number=1,
        content=(
            "Reserve Bank of India\n"
            "Master Circular - Cybersecurity Outline\n"
            "CHAPTER I\n"
            "Introduction\n"
            "1. Applicability\n"
        )
    )
    db_session.add(page1)
    await db_session.commit()
    
    # 3. Request hierarchy API
    response = await client.get(f"/api/v1/documents/{doc.id}/hierarchy")
    assert response.status_code == 200
    res_data = response.json()
    
    assert res_data["document_id"] == str(doc.id)
    root = res_data["root"]
    assert root["node_type"] == "document"
    assert root["title"] == "Master Circular - Cybersecurity Outline"
    
    # Chapter I
    assert len(root["children"]) == 1
    ch1 = root["children"][0]
    assert ch1["node_type"] == "chapter"
    assert ch1["title"] == "Introduction"
    assert ch1["numbering"] == "CHAPTER I"
    
    # Section 1
    assert len(ch1["children"]) == 1
    sec1 = ch1["children"][0]
    assert sec1["node_type"] == "section"
    assert sec1["title"] == "Applicability"
    assert sec1["numbering"] == "1"

@pytest.mark.asyncio
async def test_get_document_hierarchy_api_not_found(client: AsyncClient):
    # Query non-existent document UUID
    non_existent_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/documents/{non_existent_id}/hierarchy")
    assert response.status_code == 404
    assert response.json()["error_code"] == "DOCUMENT_NOT_FOUND"
