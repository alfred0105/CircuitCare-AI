"""Editable, explicitly unverified component proposals for the PCB Workbench."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parents[3] / "apps" / "pcb-component-recognition"
MODULE_NAME = "circuitcare_pcb_component_app_server"
CLASS_OPTIONS = [
    "unknown", "resistor", "inductor", "capacitor", "connector", "jumper", "IC",
    "switch", "relay", "transistor", "potentiometer", "battery", "buzzer", "diode",
    "display", "emi_filter", "ferrite_bead", "fuse", "LED", "clock", "oscillator",
    "voltage_regulator", "MOV", "transformer", "heatsink",
]
EDITOR_COLUMNS = ["사용", "소자 종류", "신뢰도", "x1", "y1", "x2", "y2"]


@st.cache_resource(show_spinner=False)
def _app_server() -> Any:
    if not APP_DIR.is_dir():
        raise FileNotFoundError(f"PCB recognition app missing: {APP_DIR}")
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    cached = sys.modules.get(MODULE_NAME)
    if cached is not None:
        return cached
    source = APP_DIR / "app_server.py"
    spec = importlib.util.spec_from_file_location(MODULE_NAME, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load PCB recognition module: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _normalize_records(rows: list[dict], width: int, height: int) -> list[dict]:
    normalized = []
    for row in rows:
        try:
            x1, y1, x2, y2 = (int(round(float(row[key]))) for key in ("x1", "y1", "x2", "y2"))
        except (KeyError, TypeError, ValueError):
            continue
        x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
        y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        label = str(row.get("소자 종류", "unknown"))
        normalized.append({
            "사용": bool(row.get("사용", True)),
            "소자 종류": label if label in CLASS_OPTIONS else "unknown",
            "신뢰도": float(row.get("신뢰도", 0.0) or 0.0),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        })
    return normalized


def _overlay(image_bytes: bytes, rows: list[dict]):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", max(12, image.width // 90))
    except OSError:
        font = ImageFont.load_default()
    for index, row in enumerate(rows, 1):
        x1, y1, x2, y2 = (int(row[key]) for key in ("x1", "y1", "x2", "y2"))
        color = "#20d47b" if row["사용"] else "#ef5867"
        draw.rectangle((x1, y1, x2, y2), outline=color, width=max(2, image.width // 700))
        label = f"{index}: {row['소자 종류']}" if row["사용"] else f"{index}: 제외"
        bounds = draw.textbbox((x1, max(0, y1 - 20)), label, font=font)
        draw.rectangle(bounds, fill=color)
        draw.text((x1, max(0, y1 - 20)), label, fill="black", font=font)
    return image


def ensure_component_detection(
    st_api: Any, *, image_bytes: bytes, project_id: str, photo_id: str,
) -> tuple[dict | None, str | None]:
    """Automatically detect a newly selected photo once per Streamlit session."""
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    scope = f"{project_id}_{photo_id}_{image_hash[:16]}"
    result_key = f"cc_component_recognition_{scope}"
    records_key = f"cc_component_review_rows_{scope}"
    error_key = f"cc_component_recognition_error_{scope}"
    if result_key in st_api.session_state:
        return st_api.session_state[result_key], None
    if error_key in st_api.session_state:
        return None, st_api.session_state[error_key]
    try:
        with st_api.spinner("선택한 PCB 사진에서 소자를 자동 탐지하고 있습니다…"):
            engine = _app_server()
            engine.load_component_locator()
            result = engine.run_prediction(
                image_bytes, {"conf": 0.20, "tile": 1024, "overlap": 0.25},
            )
        st_api.session_state[result_key] = result
        st_api.session_state[records_key] = [
            {"사용": True, "소자 종류": row.get("class_name", "unknown"),
             "신뢰도": float(row.get("confidence", 0.0)),
             "x1": row["bbox_xyxy"][0], "y1": row["bbox_xyxy"][1],
             "x2": row["bbox_xyxy"][2], "y2": row["bbox_xyxy"][3]}
            for row in result.get("detections", [])
        ]
        return result, None
    except Exception as exc:
        st_api.session_state[error_key] = str(exc)
        return None, str(exc)


def render_component_recognition_panel(
    st_api: Any, *, image_bytes: bytes, project_id: str, photo_id: str,
    auto_result: dict | None = None, auto_error: str | None = None,
) -> None:
    """Let the user review boxes already overlaid on the PCB workbench photo."""
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    scope = f"{project_id}_{photo_id}_{image_hash[:16]}"
    result_key = f"cc_component_recognition_{scope}"
    records_key = f"cc_component_review_rows_{scope}"
    editor_key = f"cc_component_review_editor_{scope}"
    suggestion_key = f"cc_component_suggestion_{scope}"
    error_key = f"cc_component_recognition_error_{scope}"

    if result_key not in st_api.session_state:
        if auto_result is not None:
            st_api.session_state[result_key] = auto_result
            st_api.session_state[records_key] = [
                {"사용": True, "소자 종류": row.get("class_name", "unknown"),
                 "신뢰도": float(row.get("confidence", 0.0)),
                 "x1": row["bbox_xyxy"][0], "y1": row["bbox_xyxy"][1],
                 "x2": row["bbox_xyxy"][2], "y2": row["bbox_xyxy"][3]}
                for row in auto_result.get("detections", [])
            ]
        elif auto_error:
            st_api.warning(f"자동 소자 탐지 실패 · {auto_error}")
            if st_api.button("소자 탐지 다시 시도", key=f"cc_component_retry_{scope}"):
                st_api.session_state.pop(result_key, None)
                st_api.session_state.pop(records_key, None)
                st_api.session_state.pop(error_key, None)
                st_api.rerun()
            return
        else:
            st_api.info("선택한 사진에서 자동 탐지를 실행하고 있습니다.")
            return

    st_api.caption("탐지 박스는 위 PCB 사진에 겹쳐 표시됩니다. 후보를 편집해도 고장 판정이나 학습 라벨은 바뀌지 않습니다.")
    if not st_api.session_state.get(records_key):
        st_api.caption("탐지 박스가 없습니다. 사진 좌표를 지정해 박스를 추가할 수 있습니다.")

    if st_api.button("선택 사진 다시 탐지", key=f"cc_component_run_{scope}"):
        st_api.session_state.pop(result_key, None)
        st_api.session_state.pop(records_key, None)
        st_api.session_state.pop(editor_key, None)
        st_api.session_state.pop(suggestion_key, None)
        st_api.session_state.pop(error_key, None)
        st_api.rerun()

    records = st_api.session_state.get(records_key, [])
    result = st_api.session_state[result_key]
    if auto_error:
        st_api.warning(f"자동 소자 탐지 상태 · {auto_error}")
    if not records and result.get("detections"):
        st_api.session_state[records_key] = records
    if records is None:
        return

    suggestion = st_api.session_state.get(suggestion_key)
    if suggestion:
        st_api.info(f"박스 {suggestion['row'] + 1} 분류 제안: **{suggestion['class_name']}** "
                    f"(신뢰도 {suggestion['confidence']:.2f})")
        accept_col, dismiss_col = st_api.columns(2)
        if accept_col.button("제안 종류 적용", key=f"cc_component_suggest_accept_{scope}"):
            rows = st_api.session_state.get(records_key, [])
            if suggestion["row"] < len(rows):
                rows[suggestion["row"]]["소자 종류"] = suggestion["class_name"]
                rows[suggestion["row"]]["신뢰도"] = suggestion["confidence"]
                st_api.session_state[records_key] = rows
            st_api.session_state.pop(editor_key, None)
            st_api.session_state.pop(suggestion_key, None)
            st_api.rerun()
        if dismiss_col.button("제안 닫기", key=f"cc_component_suggest_dismiss_{scope}"):
            st_api.session_state.pop(suggestion_key, None)
            st_api.rerun()

    st_api.markdown("**박스 추가**")
    with st_api.form(f"cc_component_add_box_form_{scope}"):
        add_cols = st_api.columns(5)
        with add_cols[0]:
            add_x1 = st_api.number_input("왼쪽 x1", min_value=0, max_value=width, value=0, step=1, key=f"cc_add_x1_{scope}")
        with add_cols[1]:
            add_y1 = st_api.number_input("위쪽 y1", min_value=0, max_value=height, value=0, step=1, key=f"cc_add_y1_{scope}")
        with add_cols[2]:
            add_x2 = st_api.number_input("오른쪽 x2", min_value=0, max_value=width, value=min(width, 100), step=1, key=f"cc_add_x2_{scope}")
        with add_cols[3]:
            add_y2 = st_api.number_input("아래쪽 y2", min_value=0, max_value=height, value=min(height, 100), step=1, key=f"cc_add_y2_{scope}")
        with add_cols[4]:
            add_label = st_api.selectbox("초기 종류", CLASS_OPTIONS, index=0, key=f"cc_add_label_{scope}")
        add_box = st_api.form_submit_button("박스 추가", use_container_width=True)
    if add_box:
        if add_x2 - add_x1 < 4 or add_y2 - add_y1 < 4:
            st_api.error("박스는 가로·세로 각각 4px 이상이어야 합니다.")
        else:
            records.append({"사용": True, "소자 종류": add_label, "신뢰도": 0.0,
                            "x1": int(add_x1), "y1": int(add_y1), "x2": int(add_x2), "y2": int(add_y2)})
            st_api.session_state[records_key] = records
            st_api.session_state.pop(editor_key, None)
            st_api.rerun()

    table_rows = [{column: row.get(column) for column in EDITOR_COLUMNS} for row in records]

    def sync_editor_to_overlay() -> None:
        editor_state = st_api.session_state.get(editor_key, {})
        current = [dict(row) for row in st_api.session_state.get(records_key, [])]
        if not isinstance(editor_state, dict):
            return
        for row_index, changes in editor_state.get("edited_rows", {}).items():
            try:
                index = int(row_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(current) and isinstance(changes, dict):
                current[index].update(changes)
        st_api.session_state[records_key] = _normalize_records(current, width, height)

    edited = st_api.data_editor(
        pd.DataFrame(table_rows, columns=EDITOR_COLUMNS),
        key=editor_key, hide_index=True, use_container_width=True,
        on_change=sync_editor_to_overlay,
        column_config={
            "사용": st_api.column_config.CheckboxColumn("사용", default=True),
            "소자 종류": st_api.column_config.SelectboxColumn("소자 종류", options=CLASS_OPTIONS, required=True),
            "신뢰도": st_api.column_config.NumberColumn("신뢰도", min_value=0.0, max_value=1.0, format="%.2f", disabled=True),
            "x1": st_api.column_config.NumberColumn("x1", min_value=0, max_value=width, step=1),
            "y1": st_api.column_config.NumberColumn("y1", min_value=0, max_value=height, step=1),
            "x2": st_api.column_config.NumberColumn("x2", min_value=0, max_value=width, step=1),
            "y2": st_api.column_config.NumberColumn("y2", min_value=0, max_value=height, step=1),
        },
    )
    st_api.session_state[records_key] = _normalize_records(edited.to_dict("records"), width, height)
    records = st_api.session_state[records_key]

    if records:
        selected = st_api.selectbox(
            "박스 선택 후 그 영역만 재분류", range(len(records)),
            format_func=lambda index: f"박스 {index + 1} · {records[index]['소자 종류']} · "
                                     f"({records[index]['x1']},{records[index]['y1']})–"
                                     f"({records[index]['x2']},{records[index]['y2']})",
            key=f"cc_component_reclass_row_{scope}",
        )
        if st_api.button("선택 박스에서 소자 종류 다시 탐지", key=f"cc_component_reclass_{scope}"):
            try:
                with st_api.spinner("선택한 박스 안쪽을 분류하고 있습니다…"):
                    engine = _app_server()
                    box = records[selected]
                    classified = engine.classify_component_crop(
                        image_bytes, [box["x1"], box["y1"], box["x2"], box["y2"]], confidence=0.05,
                    )
                if classified.get("class_name"):
                    st_api.session_state[suggestion_key] = {
                        "row": selected, "class_name": classified["class_name"],
                        "confidence": classified["confidence"],
                    }
                    st_api.rerun()
                st_api.warning("이 영역에서 알려진 소자 종류를 찾지 못했습니다. 표에서 직접 선택해 주세요.")
            except Exception as exc:
                st_api.error(f"선택 박스 재분류 실패 · {exc}")

    result = st_api.session_state[result_key]
    diagnostics = result.get("pin_pad_diagnostics", {})
    cols = st_api.columns(4)
    cols[0].metric("전체 박스", len(records))
    cols[1].metric("사용", sum(bool(row["사용"]) for row in records))
    cols[2].metric("패드 후보", diagnostics.get("pad_candidates", 0))
    cols[3].metric("예상 핀", diagnostics.get("pin_priors", 0))
    st_api.caption(f"{result.get('model_name', 'PCB component pipeline')} · "
                   f"{result.get('seconds', 0)}초 · 탐지 결과는 검수 전 후보입니다.")
    export_rows = [{
        "project_id": project_id, "photo_id": photo_id, "active": row["사용"],
        "class_name": row["소자 종류"], "confidence": row["신뢰도"],
        "x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"],
    } for row in records]
    st_api.download_button(
        "검수 결과 CSV 저장", pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{photo_id}_component_review.csv", mime="text/csv",
        key=f"cc_component_review_download_{scope}",
    )
