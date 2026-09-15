from synthex_platform.extraction.battery_json_normalization import parse_battery_document_json


def test_parser_strips_outer_markdown_json_fence_only():
    doc = parse_battery_document_json('''```json
{
  "source": {"title": "Example"},
  "paper_types": [],
  "materials": [],
  "shared_protocols": [],
  "battery_groups": [],
  "extraction_notes": []
}
```''')
    assert doc.source.title == "Example"


def test_parser_collapses_quantity_shape_only_for_scalar_schema_fields():
    doc = parse_battery_document_json('''{
      "source": {"title": "Example"},
      "paper_types": ["electrochemical_performance"],
      "materials": [],
      "shared_protocols": [{
        "protocol_id": "p1",
        "electrochemical_testing": {
          "long_term_cycles": {"raw_value": "100 cycles", "value": 100.0, "unit": "cycles", "qualifier": "exact"},
          "long_term_c_rate": {"raw_value": "1 C", "value": 1.0, "unit": "C", "qualifier": "exact"}
        }
      }],
      "battery_groups": [{
        "group_id": "g1",
        "performance_points": [{
          "property": "capacity_retention",
          "raw_value": "89.2%",
          "value": 89.2,
          "unit": "%",
          "qualifier": "exact",
          "cycle": {"raw_value": "100 cycles", "value": 100.0, "unit": "cycles", "qualifier": "exact"},
          "c_rate": {"raw_value": "1 C", "value": 1.0, "unit": "C", "qualifier": "exact"},
          "ownership": "focal_work",
          "evidence": []
        }]
      }],
      "extraction_notes": []
    }''')
    testing = doc.shared_protocols[0].electrochemical_testing
    point = doc.battery_groups[0].performance_points[0]
    assert testing.long_term_cycles == 100
    assert testing.long_term_c_rate == "1 C"
    assert point.cycle == 100
    assert point.c_rate == "1 C"


def test_parser_does_not_derive_fractional_cycle_count():
    payload = '''{
      "source": {"title": "Example"},
      "paper_types": [],
      "materials": [],
      "shared_protocols": [{
        "protocol_id": "p1",
        "electrochemical_testing": {
          "long_term_cycles": {"raw_value": "100.5 cycles", "value": 100.5, "unit": "cycles", "qualifier": "exact"}
        }
      }],
      "battery_groups": [],
      "extraction_notes": []
    }'''
    try:
        parse_battery_document_json(payload)
    except Exception:
        pass
    else:
        raise AssertionError("fractional cycle count was silently coerced")
