from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.compatibility import CompatibilityAdapter
from app.models.schemas import ChatResponse, ErrorResponse, OpponentPredictionReport, SimilarCaseSearchResponse


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_contract" / "legacy_contracts.json"

EXPECTED_ENDPOINTS = {
    "/api/v1/similar-cases/compare",
    "/api/v1/contract-review/stream",
    "/api/v1/chat/stream",
    "/api/v1/opponent-prediction/start",
}

SIMILAR_CASE_KEYS = {
    "session_id",
    "query",
    "comparison_query",
    "attachment_file_names",
    "case_search_profile",
    "extracted_case_points",
    "exact_match",
    "near_duplicate_matches",
    "similar_case_matches",
    "timestamp",
}

OPPONENT_PREDICTION_KEYS = {
    "report_id",
    "task_id",
    "session_id",
    "template_id",
    "case_name",
    "query",
    "case_summary",
    "predicted_arguments",
    "counter_strategies",
    "citations",
    "evidence_count",
    "inference_count",
    "uncertainties",
    "question_type",
    "focus_dimension",
    "answer_shape",
    "answer_title",
    "answer_summary",
    "retrieval_queries",
    "generated_at",
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _contracts() -> list[dict[str, Any]]:
    return _load_fixture()["contracts"]


def _contract(endpoint: str) -> dict[str, Any]:
    return next(contract for contract in _contracts() if contract["endpoint"] == endpoint)


def test_golden_contract_fixture_covers_four_core_legacy_endpoints() -> None:
    contracts = _contracts()

    assert {contract["endpoint"] for contract in contracts} == EXPECTED_ENDPOINTS
    assert all(contract["method"] == "POST" for contract in contracts)
    assert all(contract["status_code"] == 200 for contract in contracts)
    assert _contract("/api/v1/opponent-prediction/start")["legacy_domain_pattern"] == "/api/v1/prediction/*"


def test_similar_case_compare_response_matches_legacy_json_contract() -> None:
    contract = _contract("/api/v1/similar-cases/compare")
    body = contract["response"]

    assert contract["kind"] == "json"
    assert contract["response_model"] == "SimilarCaseSearchResponse"
    assert set(body) == SIMILAR_CASE_KEYS
    SimilarCaseSearchResponse.model_validate(body)
    assert set(body["case_search_profile"]) == {
        "legal_relationship",
        "dispute_focuses",
        "claim_targets",
        "party_roles",
        "key_facts",
        "timeline",
        "amount_terms",
        "retrieval_intent",
    }
    assert set(body["near_duplicate_matches"][0]) == {
        "doc_id",
        "file_name",
        "version_id",
        "final_score",
        "similarity_score",
        "match_type",
        "match_reason",
        "text_overlap_ratio",
        "file_name_aligned",
        "citations",
        "matched_points",
        "matched_profile_fields",
    }


def test_opponent_prediction_start_response_matches_legacy_json_contract() -> None:
    contract = _contract("/api/v1/opponent-prediction/start")
    body = contract["response"]

    assert contract["kind"] == "json"
    assert contract["response_model"] == "OpponentPredictionReport"
    assert set(body) == OPPONENT_PREDICTION_KEYS
    OpponentPredictionReport.model_validate(body)
    assert set(body["predicted_arguments"][0]) == {
        "title",
        "basis",
        "counter",
        "opponent_statement",
        "priority",
        "citations",
        "inference_only",
        "label",
        "category",
        "sort_reason",
    }


def test_chat_stream_matches_legacy_ndjson_event_contract() -> None:
    contract = _contract("/api/v1/chat/stream")
    events = contract["stream_events"]

    assert contract["kind"] == "stream"
    assert contract["media_type"] == "application/x-ndjson"
    assert [event["type"] for event in events] == contract["expected_event_types"]
    assert [list(event) for event in events] == contract["event_key_sequence"]

    done_event = events[-1]
    ChatResponse.model_validate({key: value for key, value in done_event.items() if key != "type"})


def test_contract_review_stream_matches_legacy_ndjson_event_contract() -> None:
    contract = _contract("/api/v1/contract-review/stream")
    events = contract["stream_events"]

    assert contract["kind"] == "stream"
    assert contract["media_type"] == "application/x-ndjson"
    assert [event["type"] for event in events] == contract["expected_event_types"]
    assert [list(event) for event in events] == contract["event_key_sequence"]
    assert events[0]["review_mode"] == "template_difference"
    assert events[-1]["review_file_count"] == events[0]["review_file_count"]


def test_public_stream_fixtures_do_not_leak_internal_agent_or_governance_events() -> None:
    fixture = _load_fixture()
    forbidden = set(fixture["metadata"]["forbidden_public_stream_event_types"])
    forbidden.update(CompatibilityAdapter.INTERNAL_EVENT_TYPES)

    for contract in fixture["contracts"]:
        if contract["kind"] != "stream":
            continue
        public_types = {event["type"] for event in contract["stream_events"]}
        assert public_types.isdisjoint(forbidden)


def test_legacy_error_contract_shape_stays_stable() -> None:
    error_contract = _load_fixture()["error_contract"]

    assert error_contract["status_code"] == 500
    assert set(error_contract["payload"]) == {"error", "detail", "citation_missing"}
    ErrorResponse.model_validate(error_contract["payload"])
