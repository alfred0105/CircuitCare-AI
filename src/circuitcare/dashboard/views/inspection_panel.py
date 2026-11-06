"""PCB inspection summary and selected-component details."""

from __future__ import annotations

from typing import Any

from circuitcare.frontend.component_overlay_models import ComponentOverlayViewModel
from circuitcare.frontend.models import ProjectContext


def _component_label(value: str) -> str:
    types = {
        "capacitor": "커패시터", "resistor": "저항", "inductor": "인덕터",
        "diode": "다이오드", "transistor": "트랜지스터", "integrated_circuit": "IC",
        "ic": "IC", "connector": "커넥터", "unknown_component": "부품 후보",
    }
    return types.get(value.lower(), value)


def _status_label(value: str | None) -> str:
    labels = {
        "SUGGESTED_UNCONFIRMED": "미확인 후보", "SUGGESTED_CLASS_ONLY": "종류 후보",
        "NEW_COMPONENT": "신규 후보", "IDENTITY_MATCHED": "연속성 후보 · 미검증",
        "USER_CONFIRMED": "사용자 확인", "IDENTITY_AMBIGUOUS": "식별 모호",
        "IDENTITY_CONFLICT": "식별 충돌", "user_confirmed": "사용자 확인",
        "suggested": "미확인 후보", "unmatched": "미확인", "class_candidate": "종류 후보",
    }
    return labels.get(value or "", value or "미확인")


def render_inspection_panel(
    st: Any, project: ProjectContext, *, preview: bool = False,
    components: tuple[ComponentOverlayViewModel, ...] = (),
    selected_component: ComponentOverlayViewModel | None = None,
    detection_status: str = "UNKNOWN",
) -> None:
    with st.container(border=True):
        st.markdown('<span class="cc-inspection-marker"></span>', unsafe_allow_html=True)
        st.markdown("### 전체 진단")
        st.info("미리보기 · 진단 미실행" if preview else "진단 미실행")
        st.caption(f"사진 · {len(project.image_records)}장")
        symptom = {
            "power_failure": "전원 불량", "output_anomaly": "출력 이상",
            "overheating": "과열", "intermittent_operation": "간헐적 작동",
            "unknown": "증상 불명",
        }.get(project.symptom_category or "unknown", "증상 불명")
        st.caption(f"증상 · {symptom}")
        if project.symptom_description:
            st.caption(project.symptom_description)
        st.divider()
        if preview:
            st.markdown("**부품** · 인식 결과 없음")
        elif detection_status in {"DETECTOR_NOT_CONFIGURED", "BLOCKED_MODEL_UNAVAILABLE"}:
            st.markdown("**부품 검출** · 검출 모델 미설정")
        elif detection_status not in {"INFERENCE_COMPLETE", "PARTIAL_MAP_READY"}:
            st.markdown("**부품 검출** · 인식 결과 없음")
        elif not components:
            st.markdown("**인식된 부품** · 없음")
        else:
            st.markdown(f"**인식된 부품** · {len(components)}개")
        st.markdown("### 선택 부품")
        if selected_component is None:
            st.caption("선택 없음")
        else:
            st.markdown(f"**종류** · {_component_label(selected_component.component_type)}")
            st.caption(f"Component ID · {selected_component.component_id}")
            if selected_component.display_label:
                st.caption(f"Reference · {selected_component.display_label}")
            if selected_component.detection_confidence is not None:
                st.caption(f"검출 신뢰도 · {selected_component.detection_confidence:.0%}")
            if selected_component.ocr_marking:
                st.caption(f"OCR 표기 · {selected_component.ocr_marking}")
            if selected_component.possible_part_number:
                st.caption(f"가능 부품 번호 · {selected_component.possible_part_number}")
            st.caption(f"식별 상태 · {_status_label(selected_component.identification_status)}")
            if selected_component.identity_match_status:
                st.caption(f"이전 식별 연속성 · {_status_label(selected_component.identity_match_status)}")
            st.caption(f"관측 사진 · {len(selected_component.source_backend_photo_ids)}장")
            st.caption("정합 · 후보 · 미검증")
            if selected_component.evidence:
                with st.expander("검출 근거"):
                    st.write(" · ".join(selected_component.evidence))
        st.markdown("**고장 진단** · 미실행")
        st.markdown("**측정값** · 없음")
        st.markdown("**다음 점검** · 분석 데이터 없음")
