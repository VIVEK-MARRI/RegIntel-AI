import pytest
import os
import json
from app.services.query_analysis.base import QueryType
from app.services.query_analysis.service import (
    QueryAnalyzer,
    RuleBasedQueryClassifier,
    AnalyticsManager,
    CircularSearchRule,
    RegulationSearchRule,
    DefinitionQueryRule,
    ComparativeQueryRule,
    SemanticQuestionRule,
    KeywordLookupRule
)

def test_rules_individually():
    circular_rule = CircularSearchRule()
    assert circular_rule.evaluate("RBI Circular 17/2024") > 0.9
    assert circular_rule.evaluate("circular no 12") > 0.9
    assert circular_rule.evaluate("SEBI Notification") > 0.7
    assert circular_rule.evaluate("normal search") == 0.0

    reg_rule = RegulationSearchRule()
    assert reg_rule.evaluate("section 45 of RBI Act") > 0.9
    assert reg_rule.evaluate("sec. 12") > 0.9
    assert reg_rule.evaluate("chapter III") > 0.9
    assert reg_rule.evaluate("SEBI Regulations") > 0.7
    assert reg_rule.evaluate("what is that") == 0.0

    def_rule = DefinitionQueryRule()
    assert def_rule.evaluate("what is KYC diligence") > 0.8
    assert def_rule.evaluate("define mutual fund") > 0.8
    assert def_rule.evaluate("meaning of compliance") > 0.8
    assert def_rule.evaluate("stands for AML") > 0.8
    assert def_rule.evaluate("RBI Circular") == 0.0

    comp_rule = ComparativeQueryRule()
    assert comp_rule.evaluate("RBI vs SEBI") > 0.9
    assert comp_rule.evaluate("difference between KYC and diligence") > 0.9
    assert comp_rule.evaluate("mutual fund versus equity") > 0.9
    assert comp_rule.evaluate("what is KYC") == 0.0

    sem_rule = SemanticQuestionRule()
    assert sem_rule.evaluate("how do we comply with AML?") > 0.8
    assert sem_rule.evaluate("why did SEBI amend guidelines?") > 0.8
    assert sem_rule.evaluate("explain the role of board") > 0.8
    assert sem_rule.evaluate("impact of circular") > 0.6
    assert sem_rule.evaluate("Aadhaar PAN") == 0.0

    kw_rule = KeywordLookupRule()
    assert kw_rule.evaluate("KYC") > 0.7
    assert kw_rule.evaluate("KYC Aadhaar PAN") > 0.5
    assert kw_rule.evaluate("this is a very long keyword query that is not standard") == 0.3


def test_rule_based_classifier():
    classifier = RuleBasedQueryClassifier()
    
    # Test circular classification
    qtype, conf = classifier.classify("RBI Circular 17/2024")
    assert qtype == QueryType.CIRCULAR
    assert conf > 0.9

    # Test definition classification
    qtype, conf = classifier.classify("define compliance")
    assert qtype == QueryType.DEFINITION
    assert conf > 0.8

    # Test comparative classification
    qtype, conf = classifier.classify("mutual fund vs stock")
    assert qtype == QueryType.COMPARATIVE
    assert conf > 0.9


def test_query_analyzer_and_analytics(tmp_path):
    # Set up analytics directory dynamically to use pytest tmp_path
    analytics = AnalyticsManager(analytics_dir=str(tmp_path))
    analyzer = QueryAnalyzer(analytics=analytics)

    # 1. Test Keyword Strategy mapping
    res_kw = analyzer.analyze("RBI Circular 17/2024")
    assert res_kw.query_type == "circular"
    assert res_kw.optimal_strategy == "keyword"
    assert res_kw.confidence > 0.9

    # 2. Test Semantic Strategy mapping
    res_sem = analyzer.analyze("how do we complete Aadhaar verification?")
    assert res_sem.query_type == "semantic"
    assert res_sem.optimal_strategy == "semantic"

    # Verify analytics logging
    log_file = os.path.join(tmp_path, "query_analyses.jsonl")
    assert os.path.exists(log_file)

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2

    log_data_1 = json.loads(lines[0])
    assert log_data_1["query"] == "RBI Circular 17/2024"
    assert log_data_1["query_type"] == "circular"
    assert log_data_1["optimal_strategy"] == "keyword"
    assert "timestamp" in log_data_1

    log_data_2 = json.loads(lines[1])
    assert log_data_2["query"] == "how do we complete Aadhaar verification?"
    assert log_data_2["query_type"] == "semantic"
    assert log_data_2["optimal_strategy"] == "semantic"
