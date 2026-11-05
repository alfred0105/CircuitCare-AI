"""Shared, scoped presentation for the schematic-first workbench."""

from __future__ import annotations

import html
from typing import Any


def apply_workbench_theme(st: Any) -> None:
    """Add small, app-owned styles without depending on Streamlit DOM classes."""
    st.markdown(
        """
        <style>
        .cc-workbench-header, .cc-context-strip {
          box-sizing: border-box; width: 100%; border: 1px solid #d6dde6;
          background: #fff; color: #17212f; font-family: sans-serif;
        }
        .cc-workbench-header {
          display: flex; align-items: center; justify-content: space-between;
          gap: 1rem; padding: .8rem 1rem; border-radius: 8px 8px 0 0;
        }
        .cc-workbench-brand { font-size: 1.05rem; font-weight: 700; letter-spacing: .01em; }
        .cc-workbench-subtitle { color: #596779; font-size: .78rem; margin-top: .15rem; }
        .cc-workbench-project { color: #354255; font-size: .82rem; text-align: right; }
        .cc-context-strip {
          display: flex; align-items: center; gap: .55rem; flex-wrap: wrap;
          padding: .55rem .8rem; border-top: 0; border-radius: 0 0 8px 8px;
          margin-bottom: .85rem; font-size: .78rem;
        }
        .cc-context-item { display: inline-flex; gap: .35rem; align-items: center;
          padding: .22rem .48rem; background: #f3f5f8; border: 1px solid #e0e5eb; border-radius: 4px; }
        .cc-context-label { color: #596779; font-weight: 700; letter-spacing: .035em; }
        .cc-context-value { color: #17212f; font-weight: 600; }
        .cc-context-state { background: #fef3c7; border-color: #f2d58a; }
        @media (max-width: 900px) {
          .cc-workbench-header { align-items: flex-start; flex-direction: column; }
          .cc-workbench-project { text-align: left; }
          .cc-context-strip { gap: .35rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_workbench_header(st: Any, *, circuit_name: str, fault_ref: str,
                            fault_type: str, fault_value: str | None,
                            simulation_status: str, verification_status: str) -> None:
    """Render the persistent project and diagnostic context above the work area."""
    def safe(value: object) -> str:
        return html.escape(str(value))
    st.markdown(
        f"""
        <section class="cc-workbench-header" aria-label="CircuitCare workbench">
          <div><div class="cc-workbench-brand">CircuitCare AI <span aria-hidden="true">/</span> 회로 진단 Workbench</div>
          <div class="cc-workbench-subtitle">로컬 회로 분석 · 근거 우선 · 명시적 실행</div></div>
          <div class="cc-workbench-project"><b>회로</b> &nbsp;{safe(circuit_name)}</div>
        </section>
        <section class="cc-context-strip" aria-label="현재 진단 문맥">
          <span class="cc-context-item"><span class="cc-context-label">FAULT SOURCE</span><span class="cc-context-value">{safe(fault_ref)}</span></span>
          <span class="cc-context-item"><span class="cc-context-label">고장 가정</span><span class="cc-context-value">{safe(fault_type)} · {safe(fault_value or '—')}</span></span>
          <span class="cc-context-item cc-context-state"><span class="cc-context-label">SIMULATION</span><span class="cc-context-value">{safe(simulation_status)}</span></span>
          <span class="cc-context-item"><span class="cc-context-label">결과 출처</span><span class="cc-context-value">{safe(verification_status)}</span></span>
        </section>
        """,
        unsafe_allow_html=True,
    )
