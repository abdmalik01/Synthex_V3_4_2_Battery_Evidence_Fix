from synthex_platform.extraction.battery_models import BatteryDocument, BatteryQuantity, BatteryEvidence


def test_quantity_string_coercion():
    q = BatteryQuantity.model_validate('1.5A')
    assert q.value == 1.5
    assert q.unit == 'A'
    assert q.qualifier == 'exact'


def test_invalid_semantic_qualifier_is_normalized():
    q = BatteryQuantity.model_validate({
        'raw_value': '24°C', 'value': 24.0, 'unit': '°C', 'qualifier': 'ambient'
    })
    assert q.value == 24.0
    assert q.qualifier == 'unknown'


def test_evidence_string_coercion():
    ev = BatteryEvidence.model_validate('Temperature: Ambient 24°C')
    assert ev.text_snippet == 'Temperature: Ambient 24°C'
    assert ev.source_type == 'text'


def test_evidence_confidence_label_coercion():
    assert BatteryEvidence.model_validate({'confidence': 'high'}).confidence == 0.9
    assert BatteryEvidence.model_validate({'confidence': '75%'}).confidence == 0.75
    assert BatteryEvidence.model_validate({'confidence': 'not rated'}).confidence is None


def test_structured_c_rate_definition_uses_raw_value():
    doc = BatteryDocument.model_validate({
        'shared_protocols': [{
            'protocol_id': 'p1',
            'electrochemical_testing': {
                'c_rate_definition': {
                    'raw_value': '1 C = 300 mA/g',
                    'value': 300.0,
                    'unit': 'mA/g',
                    'qualifier': 'exact',
                },
                'evidence': [{'page': '2', 'confidence': 'high'}],
            },
        }],
    })
    testing = doc.shared_protocols[0].electrochemical_testing
    assert testing.c_rate_definition == '1 C = 300 mA/g'
    assert testing.evidence[0].confidence == 0.9


def test_gemini_like_battery_payload_validates():
    doc = BatteryDocument.model_validate({
        'source': {'title': 'Example'},
        'paper_types': ['battery_dataset_modelling'],
        'battery_groups': [{
            'group_id': 'g1',
            'battery_ids': ['25', '26'],
            'temperature': {'raw_value':'24°C','value':24.0,'unit':'°C','qualifier':'ambient'},
            'charge_protocol': {
                'mode':'CC-CV', 'constant_current':'1.5A', 'voltage_limit':'4.2V', 'cutoff_current':'20mA'
            },
            'discharge_protocol': {
                'mode':'CC', 'current':'4A', 'cutoff_voltages':['2.2V','2.5V','2.7V']
            },
            'impedance_protocol': {'method':'EIS','frequency_min':'0.1Hz','frequency_max':'5kHz'},
            'evidence': ['Temperature: Ambient 24°C']
        }]
    })
    g = doc.battery_groups[0]
    assert g.charge_protocol.constant_current.value == 1.5
    assert g.discharge_protocol.cutoff_voltages[2].value == 2.7
    assert g.impedance_protocol.frequency_max.unit == 'kHz'
    assert g.evidence[0].text_snippet == 'Temperature: Ambient 24°C'
