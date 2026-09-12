from __future__ import annotations

import json

import pytest

from synthex_platform.extraction.domain_extractor import parse_extracted_document_json


def _document_payload() -> dict:
    return {"source": {"title": "One document"}, "materials": []}


def test_normal_object_output_validates_strictly():
    document = parse_extracted_document_json(json.dumps(_document_payload()))
    assert document.source.title == "One document"


def test_singleton_list_output_is_unwrapped_then_validated():
    document = parse_extracted_document_json(json.dumps([_document_payload()]))
    assert document.source.title == "One document"


def test_empty_list_is_rejected_explicitly():
    with pytest.raises(ValueError, match="empty JSON array"):
        parse_extracted_document_json("[]")


def test_multi_object_list_is_rejected_without_merging():
    with pytest.raises(ValueError, match="2 items.*will not merge"):
        parse_extracted_document_json(json.dumps([_document_payload(), _document_payload()]))


@pytest.mark.parametrize("payload", ["null", '"not a document"', "42", "true"])
def test_primitive_output_is_rejected(payload):
    with pytest.raises(ValueError, match="top-level JSON"):
        parse_extracted_document_json(payload)
