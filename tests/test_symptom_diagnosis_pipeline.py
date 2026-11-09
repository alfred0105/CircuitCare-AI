from __future__ import annotations

from copy import deepcopy
import unittest

from circuitcare.frontend.measurement_models import create_measurement_record
from circuitcare.symptom_diagnosis import diagnose, load_knowledge
from circuitcare.symptom_diagnosis.diagnosis_state import build_overlay_state, current_overlay_candidates
from circuitcare.symptom_diagnosis.engine import infer_symptom_codes, validate_knowledge_base
from circuitcare.symptom_diagnosis.measurement_evaluator import evaluate_component_measurements


def _measurement(value: str, *, low: str = "10", high: str = "100",
                 uncertainty: str = "1", fault: str = "CAPACITOR_SHORT",
                 component_id: str = "C3", measurement_id: str | None = None):
    return create_measurement_record(
        project_id="p", board_id="b", component_id=component_id,
        component_identity_status="USER_CONFIRMED", measurement_type="resistance",
        value=value, unit="Ω", uncertainty=uncertainty, source="user_measurement",
        measurement_id=measurement_id, measurement_target=f"{component_id} terminals",
        fault_hypothesis=fault, reference_min=low, reference_max=high,
        reference_source="validated board service specification",
        operating_conditions="power off, capacitor discharged",
        reference_conditions="power off, capacitor discharged",
        location_verified=True, uncertainty_source="meter accuracy specification",
    )


class SymptomDiagnosisPipelineTests(unittest.TestCase):
    def test_conflicting_observations_are_held_and_symptoms_are_not_double_counted(self):
        conflicted = diagnose(
            symptoms=["NO_POWER"],
            observations=[{"code": "NO_POWER", "value": False, "status": "observed", "source": "user_report"}],
        )
        self.assertEqual(conflicted["symptom_codes"], [])
        self.assertTrue(any(row["resolution"] == "UNRESOLVED_CONFLICT"
                            for row in conflicted["evidence_conflicts"]))
        measured_conflict = diagnose(observations=[
            {"code": "NO_POWER", "value": True, "status": "measured", "source": "meter_record"},
            {"code": "NO_POWER", "value": False, "status": "observed", "source": "user_report"},
        ])
        conflict = next(row for row in measured_conflict["evidence_conflicts"] if row["code"] == "NO_POWER")
        self.assertEqual({row["source"] for row in conflict["evidence"]}, {"meter_record", "user_report"})

        one = diagnose(symptoms=["NO_POWER"], symptom_text="전원이 안 켜집니다")
        repeated = diagnose(symptoms=["NO_POWER", "NO_POWER"], symptom_text="전원이 안 켜집니다")
        one_score = next(row["score"] for row in one["hypotheses"] if row["fault_id"] == "EXTERNAL_SUPPLY_FAILURE")
        repeated_score = next(row["score"] for row in repeated["hypotheses"] if row["fault_id"] == "EXTERNAL_SUPPLY_FAILURE")
        self.assertEqual(repeated_score, one_score)


    def test_negation_and_hypothetical_symptoms_are_not_asserted(self):
        self.assertEqual(infer_symptom_codes("안 켜지는 건 아님"), [])
        self.assertEqual(infer_symptom_codes("만약 전원이 꺼지면 확인해 주세요"), [])


    def test_relay_rule_has_no_buzzer_power_failure(self):
        result = diagnose(symptoms=["RELAY_NO_ACTUATION"])
        fault_ids = {row["fault_id"] for row in result["hypotheses"]}
        self.assertNotIn("BUZZER_POWER_FAILURE", fault_ids)
        self.assertIn("RELAY_COIL_FAILURE", fault_ids)


    def test_ambiguous_same_type_parts_are_withheld_until_component_evidence_exists(self):
        parts = [{"component_id": f"C{i}", "component_type": "capacitor"} for i in range(1, 21)]
        ambiguous = diagnose(symptoms=["SUPPLY_VOLTAGE_DROOP"], components=parts)
        self.assertFalse(ambiguous["component_candidates"])

        measured = _measurement("0.1", component_id="C3")
        narrowed = diagnose(symptoms=["SUPPLY_VOLTAGE_DROOP"], components=parts,
                            measurements=[measured.to_dict()])
        self.assertEqual([(row["component_id"], row["status"]) for row in narrowed["component_candidates"]],
                         [("C3", "TEST_ABNORMAL")])
        normal = _measurement("50", component_id="C3")
        normal_result = diagnose(symptoms=["SUPPLY_VOLTAGE_DROOP"], components=parts,
                                 measurements=[normal.to_dict()])
        self.assertEqual(normal_result["component_candidates"][0]["status"], "TEST_NORMAL")
        self.assertLess(normal_result["component_candidates"][0]["score"],
                        narrowed["component_candidates"][0]["score"])


    def test_measurement_ranges_uncertainty_and_conflicts_are_scoped(self):
        normal = _measurement("50")
        abnormal = _measurement("0.1")
        edge = _measurement("9.5")
        self.assertEqual(evaluate_component_measurements([normal.to_dict()])[('C3', 'CAPACITOR_SHORT')]["status"], "TEST_NORMAL")
        self.assertEqual(evaluate_component_measurements([abnormal.to_dict()])[('C3', 'CAPACITOR_SHORT')]["status"], "TEST_ABNORMAL")
        self.assertEqual(evaluate_component_measurements([edge.to_dict()])[('C3', 'CAPACITOR_SHORT')]["status"], "INCONCLUSIVE")
        no_uncertainty_source = create_measurement_record(
            project_id="p", board_id="b", component_id="C3", component_identity_status="USER_CONFIRMED",
            measurement_type="resistance", value="50", unit="Ω", uncertainty="1",
            source="user_measurement", measurement_target="C3 terminals", fault_hypothesis="CAPACITOR_SHORT",
            reference_min="10", reference_max="100", reference_source="spec",
            operating_conditions="power off", reference_conditions="power off", location_verified=True,
        )
        self.assertEqual(evaluate_component_measurements([no_uncertainty_source.to_dict()])[
            ('C3', 'CAPACITOR_SHORT')]["status"], "INCONCLUSIVE")
        conflict = evaluate_component_measurements([normal.to_dict(), abnormal.to_dict()])
        self.assertEqual(conflict[('C3', 'CAPACITOR_SHORT')]["status"], "CONFLICTED")


    def test_knowledge_validation_catches_duplicate_and_dangling_rules(self):
        knowledge = deepcopy(load_knowledge())
        knowledge["symptom_rules"]["rules"].append({
            "id": "R01", "name": "duplicate", "when": {"fact": "NO_POWER", "operator": "eq", "value": True},
            "generate": ["DOES_NOT_EXIST"],
        })
        with self.assertRaisesRegex(ValueError, "duplicate or empty symptom rule ID"):
            validate_knowledge_base(knowledge)


    def test_diagnosis_overlay_is_bound_to_board_and_component_map_version(self):
        result = {"diagnosis_id": "d1", "input_fingerprint": "f1", "component_candidates": [
            {"component_id": "C3", "visual_status": "TEST_ABNORMAL"},
        ]}
        state = build_overlay_state(project_id="p", board_id="b", component_map_version="m1", result=result)
        self.assertEqual(set(current_overlay_candidates(state, project_id="p", board_id="b",
                                                         component_map_version="m1")), {"C3"})
        self.assertEqual(current_overlay_candidates(state, project_id="p", board_id="other",
                                                    component_map_version="m1"), {})
        self.assertEqual(current_overlay_candidates(state, project_id="p", board_id="b",
                                                    component_map_version="m2"), {})


if __name__ == "__main__":
    unittest.main()
