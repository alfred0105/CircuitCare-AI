from __future__ import annotations

from copy import deepcopy
import unittest

from circuitcare.frontend.measurement_models import create_measurement_record
from circuitcare.symptom_diagnosis import diagnose, load_knowledge
from circuitcare.symptom_diagnosis.diagnosis_state import build_overlay_state, current_overlay_candidates
from circuitcare.symptom_diagnosis.engine import infer_symptom_codes, validate_knowledge_base
from circuitcare.symptom_diagnosis.measurement_evaluator import evaluate_component_measurements


def _measurement(value: str, *, low: str = "10", high: str = "100",
                 uncertainty: str = "1", fault: str = "RESISTOR_FAILURE",
                 component_id: str = "R3", measurement_id: str | None = None):
    return create_measurement_record(
        project_id="p", board_id="b", component_id=component_id, component_map_version="m1",
        component_identity_status="USER_CONFIRMED", measurement_type="resistance",
        value=value, unit="Ω", uncertainty=uncertainty, source="user_measurement",
        measurement_id=measurement_id, measurement_target=f"{component_id} terminals",
        test_id="isolated_resistance", fault_hypothesis=fault,
        reference_min=low, reference_max=high,
        reference_source="manufacturer datasheet", reference_source_id="DS-R-001",
        reference_verification_status="DATASHEET_VERIFIED",
        operating_conditions="power off, component isolated",
        reference_conditions="power off, component isolated",
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
        self.assertNotIn("RELAY_COIL_FAILURE", fault_ids)
        present = diagnose(symptoms=["RELAY_NO_ACTUATION"],
                           components=[{"component_id": "K1", "component_type": "relay"}],
                           confirmed_component_ids=["K1"])
        self.assertIn("RELAY_COIL_FAILURE", {row["fault_id"] for row in present["hypotheses"]})

    def test_buzzer_driver_requires_both_confirmed_buzzer_and_driver_candidate(self):
        transistor_only = diagnose(
            symptoms=["BUZZER_NO_SOUND"],
            components=[{"component_id": "Q1", "component_type": "transistor"}],
            confirmed_component_ids=["Q1"],
        )
        self.assertNotIn("BUZZER_DRIVER_FAILURE", {row["fault_id"] for row in transistor_only["hypotheses"]})
        with_buzzer = diagnose(
            symptoms=["BUZZER_NO_SOUND"],
            components=[{"component_id": "BZ1", "component_type": "buzzer"},
                        {"component_id": "Q1", "component_type": "transistor"}],
            confirmed_component_ids=["BZ1", "Q1"],
        )
        self.assertIn("BUZZER_DRIVER_FAILURE", {row["fault_id"] for row in with_buzzer["hypotheses"]})


    def test_ambiguous_same_type_parts_are_withheld_until_component_evidence_exists(self):
        parts = [{"component_id": f"R{i}", "component_type": "resistor"} for i in range(1, 21)]
        ids = [part["component_id"] for part in parts]
        ambiguous = diagnose(symptoms=["PARTIAL_FUNCTION_FAILURE"], components=parts,
                             confirmed_component_ids=ids)
        self.assertFalse(ambiguous["component_candidates"])

        measured = _measurement("0.1", component_id="R3")
        narrowed = diagnose(symptoms=["PARTIAL_FUNCTION_FAILURE"], components=parts,
                            confirmed_component_ids=ids, measurements=[measured.to_dict()])
        self.assertEqual([(row["component_id"], row["measurement_verdict"])
                          for row in narrowed["component_candidates"]], [("R3", "supports")])
        normal = _measurement("50", component_id="R3")
        normal_result = diagnose(symptoms=["PARTIAL_FUNCTION_FAILURE"], components=parts,
                                 confirmed_component_ids=ids, measurements=[normal.to_dict()])
        self.assertEqual(normal_result["component_candidates"][0]["measurement_verdict"], "refutes")
        self.assertLess(normal_result["component_candidates"][0]["score"],
                        narrowed["component_candidates"][0]["score"])


    def test_measurement_ranges_uncertainty_and_conflicts_are_scoped(self):
        normal = _measurement("50")
        abnormal = _measurement("0.1")
        edge = _measurement("9.5")
        profiles = load_knowledge()["component_test_profiles"]
        component_row = {"component_type": "resistor"}
        normal_row = {**normal.to_dict(), **component_row}
        abnormal_row = {**abnormal.to_dict(), **component_row}
        edge_row = {**edge.to_dict(), **component_row}
        key = ("R3", "RESISTOR_FAILURE", "isolated_resistance", "r3 terminals",
               "power off, component isolated")
        self.assertEqual(evaluate_component_measurements([normal_row], profiles=profiles)[key]["status"], "TEST_NORMAL")
        self.assertEqual(evaluate_component_measurements([abnormal_row], profiles=profiles)[key]["status"], "TEST_ABNORMAL")
        self.assertEqual(evaluate_component_measurements([edge_row], profiles=profiles)[key]["status"], "INCONCLUSIVE")
        no_uncertainty_source = create_measurement_record(
            project_id="p", board_id="b", component_id="R3", component_map_version="m1", component_identity_status="USER_CONFIRMED",
            measurement_type="resistance", value="50", unit="Ω", uncertainty="1",
            source="user_measurement", measurement_target="R3 terminals", test_id="isolated_resistance",
            fault_hypothesis="RESISTOR_FAILURE", reference_min="10", reference_max="100",
            reference_source="spec", reference_source_id="DS-R-001",
            reference_verification_status="DATASHEET_VERIFIED",
            operating_conditions="power off, component isolated", reference_conditions="power off, component isolated",
            location_verified=True,
        )
        self.assertEqual(evaluate_component_measurements([{**no_uncertainty_source.to_dict(), **component_row}], profiles=profiles)[key]["status"], "INCONCLUSIVE")
        conflict = evaluate_component_measurements([normal_row, abnormal_row], profiles=profiles)
        self.assertEqual(conflict[key]["status"], "CONFLICTED")


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
        result["input_fingerprint"] = "f1"
        state = build_overlay_state(project_id="p", board_id="b", component_map_version="m1", result=result)
        self.assertEqual(set(current_overlay_candidates(state, project_id="p", board_id="b",
                                                         component_map_version="m1", input_fingerprint="f1")), {"C3"})
        self.assertEqual(current_overlay_candidates(state, project_id="p", board_id="other",
                                                    component_map_version="m1", input_fingerprint="f1"), {})
        self.assertEqual(current_overlay_candidates(state, project_id="p", board_id="b",
                                                    component_map_version="m2", input_fingerprint="f1"), {})
        self.assertEqual(current_overlay_candidates(state, project_id="p", board_id="b",
                                                    component_map_version="m1", input_fingerprint="f2"), {})


if __name__ == "__main__":
    unittest.main()
