"""Navigation labels and grouping for the schematic-first workbench."""

from __future__ import annotations

WORKBENCH_VIEW = "회로도 Workbench"
WORKSPACE_VIEWS = [
    WORKBENCH_VIEW,
    "분석 개요",
    "SPICE 파형",
    "2차 손상 위험",
    "Bayesian 진단",
    "로컬 LLM 수리 지원",
    "PCB 사진 인식",
    "데이터시트 AI",
    "AI 고장 가설 분석",
    "수리 이력 및 AI 학습",
    "AI 성능 평가",
]
VIEW_GROUPS = {
    WORKBENCH_VIEW: "MAIN WORKBENCH",
    "분석 개요": "ANALYSIS DETAIL",
    "SPICE 파형": "ANALYSIS DETAIL",
    "2차 손상 위험": "ANALYSIS DETAIL",
    "Bayesian 진단": "ANALYSIS DETAIL",
    "로컬 LLM 수리 지원": "ADVANCED TOOLS",
    "PCB 사진 인식": "ADVANCED TOOLS",
    "데이터시트 AI": "ADVANCED TOOLS",
    "AI 고장 가설 분석": "ADVANCED TOOLS",
    "수리 이력 및 AI 학습": "ADVANCED TOOLS",
    "AI 성능 평가": "ADVANCED TOOLS",
}


def format_view_option(view: str) -> str:
    """Keep the existing selection values while showing their navigation group."""
    group = VIEW_GROUPS.get(view, "OTHER")
    return f"{group}  /  {view}"
