import pytest
from app.services.validation.rules import (
    RejectEmptyChunkRule,
    TokenThresholdRule,
    MissingSectionRule,
    DuplicateChunkRule,
    MalformedHierarchyRule,
)
from app.services.validation.engine import ChunkQualityValidator


def test_reject_empty_chunk_rule():
    rule = RejectEmptyChunkRule()

    # Valid content
    assert rule.validate_chunk({"chunk_id": "c1", "content": "Valid content"}) is None

    # Empty content
    issue = rule.validate_chunk({"chunk_id": "c2", "content": ""})
    assert issue is not None
    assert issue.rule_name == "reject_empty_chunk"
    assert "empty" in issue.message

    # Whitespace content
    issue = rule.validate_chunk({"chunk_id": "c3", "content": "   "})
    assert issue is not None
    assert issue.chunk_id == "c3"


def test_token_threshold_rule():
    rule = TokenThresholdRule(min_tokens=10, max_tokens=20)

    # In bounds
    assert rule.validate_chunk({"chunk_id": "c1", "token_count": 15}) is None
    assert rule.validate_chunk({"chunk_id": "c2", "token_count": 10}) is None
    assert rule.validate_chunk({"chunk_id": "c3", "token_count": 20}) is None

    # Out of bounds - too small
    issue = rule.validate_chunk({"chunk_id": "c4", "token_count": 9})
    assert issue is not None
    assert "below" in issue.message

    # Out of bounds - too large
    issue = rule.validate_chunk({"chunk_id": "c5", "token_count": 21})
    assert issue is not None
    assert "above" in issue.message

    # Missing / None
    issue = rule.validate_chunk({"chunk_id": "c6"})
    assert issue is not None
    assert "Missing" in issue.message

    # Malformed token_count
    issue = rule.validate_chunk({"chunk_id": "c7", "token_count": "invalid"})
    assert issue is not None
    assert "Invalid" in issue.message


def test_missing_section_rule():
    rule = MissingSectionRule(invalid_sections={"General", "Placeholder"})

    # Valid section
    assert rule.validate_chunk({"chunk_id": "c1", "section": "Chapter I"}) is None

    # Missing section
    issue = rule.validate_chunk({"chunk_id": "c2"})
    assert issue is not None
    assert "missing" in issue.message.lower()

    # Default/placeholder section
    issue = rule.validate_chunk({"chunk_id": "c3", "section": "General"})
    assert issue is not None
    assert "default placeholder" in issue.message.lower()


def test_duplicate_chunk_rule():
    rule = DuplicateChunkRule()

    chunks = [
        {"chunk_id": "c1", "content": "Unique content one"},
        {"chunk_id": "c2", "content": "Unique content two"},
        {"chunk_id": "c3", "content": "Unique content three"},
    ]
    assert len(rule.validate_batch(chunks)) == 0

    # Duplicate ID
    dup_id_chunks = [
        {"chunk_id": "c1", "content": "Unique content one"},
        {"chunk_id": "c1", "content": "Unique content two"},
    ]
    issues = rule.validate_batch(dup_id_chunks)
    assert len(issues) == 1
    assert "Duplicate chunk ID" in issues[0].message

    # Duplicate Content (whitespace and case normalized)
    dup_content_chunks = [
        {"chunk_id": "c1", "content": "Hello World"},
        {"chunk_id": "c2", "content": "hello   world"},
    ]
    issues = rule.validate_batch(dup_content_chunks)
    assert len(issues) == 1
    assert "Duplicate chunk content" in issues[0].message


def test_malformed_hierarchy_rule():
    rule = MalformedHierarchyRule()

    # Valid: section + subsection match
    assert (
        rule.validate_chunk(
            {
                "chunk_id": "c1",
                "section": "1. Introduction",
                "subsection": "1.1 Applicability",
            }
        )
        is None
    )

    # Valid: only section, no subsection
    assert (
        rule.validate_chunk(
            {
                "chunk_id": "c2",
                "section": "12. Customer Due Diligence",
                "subsection": "",
            }
        )
        is None
    )

    # Invalid: subsection defined but section is missing
    issue = rule.validate_chunk(
        {"chunk_id": "c3", "section": "", "subsection": "1.1 Applicability"}
    )
    assert issue is not None
    assert "parent section is missing" in issue.message

    # Invalid: subsection defined but section is placeholder "General"
    issue = rule.validate_chunk(
        {"chunk_id": "c4", "section": "General", "subsection": "1.1 Applicability"}
    )
    assert issue is not None

    # Invalid: Section 2 with Subsection 1.1 (numbering mismatch)
    issue = rule.validate_chunk(
        {
            "chunk_id": "c5",
            "section": "2. Definitions",
            "subsection": "1.1 Applicability",
        }
    )
    assert issue is not None
    assert "mismatch" in issue.message


def test_chunk_quality_validator_integration():
    validator = ChunkQualityValidator()

    # Mixture of valid and invalid chunks
    chunks = [
        # Valid chunk 1
        {
            "chunk_id": "valid-1",
            "section": "1. Introduction",
            "subsection": "1.1 Scope",
            "content": "This circular applies to all banking institutions operating in India.",
            "token_count": 650,
        },
        # Valid chunk 2
        {
            "chunk_id": "valid-2",
            "section": "2. Core Principles",
            "subsection": "2.1 Integrity",
            "content": "Institutions must operate with the highest standards of integrity.",
            "token_count": 550,
        },
        # Invalid chunk: Empty content
        {
            "chunk_id": "invalid-empty",
            "section": "3. Security",
            "subsection": "",
            "content": "   ",
            "token_count": 600,
        },
        # Invalid chunk: Below token threshold
        {
            "chunk_id": "invalid-too-small",
            "section": "4. Audit",
            "subsection": "",
            "content": "Audit everything.",
            "token_count": 450,
        },
        # Enriched valid format layout (using metadata dictionary)
        {
            "chunk_id": "valid-enriched",
            "content": "Enriched chunk with valid tokens and section detail.",
            "metadata": {
                "page": 5,
                "section": "5. Compliance",
                "subsection": "5.1 Reports",
                "token_count": 720,
            },
        },
    ]

    report = validator.validate_chunks(chunks)

    # Assert overall validity
    assert report.valid is False
    assert len(report.issues) == 2

    # Verify issue details
    rules_violated = [issue.rule_name for issue in report.issues]
    assert "reject_empty_chunk" in rules_violated
    assert "token_threshold" in rules_violated

    # Verify metrics
    metrics = report.metrics
    assert metrics.total_chunks == 5
    assert metrics.invalid_chunk_count == 2
    assert metrics.valid_chunk_count == 3

    # Averages should only be computed over valid chunks:
    # Valid chunks have token counts: 650, 550, 720
    # Average = (650 + 550 + 720) / 3 = 1920 / 3 = 640.0
    assert metrics.average_token_count == 640.0

    # Valid chunk char counts: 68, 67, 52
    # Average = (68 + 67 + 52) / 3 = 187 / 3 = 62.333333333333336
    assert pytest.approx(metrics.average_char_count) == 62.333333

    # Check distribution across ALL chunks with token counts
    # Token counts: 650 (500-800), 550 (500-800), 600 (500-800), 450 (300-500), 720 (500-800)
    # Distribution should count:
    # 300 - 500: 1
    # 500 - 800: 4
    dist = metrics.chunk_distribution
    assert dist["300 - 500"] == 1
    assert dist["500 - 800"] == 4
    assert dist["< 100"] == 0
    assert dist["100 - 300"] == 0
    assert dist["> 800"] == 0

    # Verify summary string
    assert "Validated 5 chunks" in report.summary
    assert "3 passed" in report.summary
    assert "2 failed" in report.summary


def test_chunk_quality_validator_all_valid():
    validator = ChunkQualityValidator()

    chunks = [
        {
            "chunk_id": "c1",
            "section": "1. Rules",
            "subsection": "1.1 Scope",
            "content": "Valid chunk content that satisfies target count.",
            "token_count": 700,
        }
    ]

    report = validator.validate_chunks(chunks)
    assert report.valid is True
    assert len(report.issues) == 0
    assert report.metrics.invalid_chunk_count == 0
    assert report.metrics.valid_chunk_count == 1
