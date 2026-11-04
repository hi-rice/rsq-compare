"""그래프 만들기 (matplotlib).

화면(GUI)과 PNG 저장에서 같은 함수를 쓴다. pyplot 대신 Figure 객체를 직접 만들어
작업 스레드에서도 안전하게 그릴 수 있게 했다.
결측(NaN)은 선을 끊어서 표시하고, 보간하거나 0으로 채우지 않는다.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from matplotlib import font_manager, rcParams
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure

from rsq_compare.core.loader import sample_col
from rsq_compare.core.model import SessionData
from rsq_compare.core.tables import STATS_TITLE, SelStats, q_unit

_FONT_CANDIDATES = ["Malgun Gothic", "맑은 고딕", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR",
                    "AppleGothic", "Noto Sans CJK JP", "Noto Sans CJK SC"]
_font_ready = False

C_SEL = "#2563a8"
C_UNSEL = "#c3ccd6"
C_DEPTH = "#2563a8"
C_SPEED = "#c2410c"


def setup_korean_font() -> str | None:
    global _font_ready
    names = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((n for n in _FONT_CANDIDATES if n in names), None)
    if chosen:
        rcParams["font.family"] = [chosen, "DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    _font_ready = True
    return chosen


def _ensure_font():
    if not _font_ready:
        setup_korean_font()


def _fmt(v: float) -> str:
    return f"{v:.4f}"


def fig_q_bar(sd: SessionData, selected_nums: list[int], st: SelStats) -> Figure:
    _ensure_font()
    fig = Figure(figsize=(9, 5.2), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    recs = [r for r in sd.records]
    if not recs:
        ax.text(0.5, 0.5, "표시할 회차가 없습니다", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    labels = [r.label for r in recs]
    x = np.arange(len(recs))
    qs = [r.total_q for r in recs]
    has = [q is not None for q in qs]
    vals = [q if q is not None else 0.0 for q in qs]  # 막대 위치 계산용, 값 없는 회차는 막대를 그리지 않음
    colors = [C_SEL if r.num in selected_nums else C_UNSEL for r in recs]
    ymax = max([abs(q) for q in qs if q is not None] or [1.0])
    for xi, q, ok, c in zip(x, vals, has, colors):
        if ok:
            ax.bar(xi, q, color=c, width=0.65, edgecolor="none")
            ax.text(xi, q + ymax * 0.015 * (1 if q >= 0 else -1), _fmt(q), ha="center",
                    va="bottom" if q >= 0 else "top", fontsize=8.5, color="#333")
        else:
            ax.text(xi, ymax * 0.04, "요약 결과\n없음", ha="center", va="bottom", fontsize=8.5,
                    color="#9a3412")
    if st.mean is not None:
        ax.axhline(st.mean, color="#111", lw=1.1, ls="--")
    ax.set_xticks(x, labels)
    ax.axhline(0, color="#666", lw=0.6)
    u = q_unit(sd)
    ax.set_xlabel("회차 (원래 파일명의 T번호)")
    ax.set_ylabel(f"RSQ 총유량 ({u})" if u else "RSQ 총유량")
    ax.set_ylim(min(0, min([q for q in qs if q is not None] or [0]) * 1.15), ymax * 1.2)
    ax.set_title("회차별 유량 · DIS 기록값", fontsize=11, pad=32)
    ax.spines[["top", "right"]].set_visible(False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=C_SEL, label="선택 회차"),
                       Patch(color=C_UNSEL, label="미선택 회차")],
              loc="lower left", bbox_to_anchor=(0,1.0), ncol=2, fontsize=9, frameon=False)
    return fig


def _find_col(df: pd.DataFrame, prefix: str) -> str | None:
    for c in df.columns:
        s = str(c).strip()
        if s == prefix or s.startswith(prefix + " ") or s.startswith(prefix + "("):
            return c
    return None


SECTION_COLORS = {"시작 Edge": "#fde9c4", "횡단 섹션": None, "마침 Edge": "#d6e6fb"}


def section_runs(x: pd.Series, sec: pd.Series | None) -> list[tuple[str, float, float]]:
    """연속된 같은 구간을 (이름, 첫 샘플, 끝 샘플)로 묶는다. sec는 index=샘플 번호."""
    if sec is None:
        return []
    runs: list[list] = []
    for xv in x:
        t = sec.get(xv)
        if t is None:
            continue
        if runs and runs[-1][0] == t:
            runs[-1][2] = xv
        else:
            runs.append([t, xv, xv])
    return [tuple(r) for r in runs]


def _shade_sections(ax, runs, label_top: bool = False):
    from matplotlib.patches import Patch
    seen = {}
    for t, a, b in runs:
        c = SECTION_COLORS.get(t, "#eeeeee")
        if c:
            ax.axvspan(a - 0.5, b + 0.5, color=c, zorder=0, lw=0)
        seen.setdefault(t, c)
    for i, (t, a, b) in enumerate(runs):
        if i > 0:
            ax.axvline(a - 0.5, color="#777", lw=0.8, ls=":", zorder=1)
        if label_top:
            ax.text((a + b) / 2, 1.0, t, transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                    fontsize=8, color="#444")
    return [Patch(facecolor=c or "white", edgecolor="#999", lw=0.5, label=t) for t, c in seen.items()]


def fig_depth_speed(df: pd.DataFrame | None, label: str, sections: pd.Series | None = None,
                    subset_name: str | None = None) -> Figure:
    """sections: index=샘플 번호, 값=구간 이름(.rsqmb 기록). None 이면 구간 표시 없이 전체 기록.
    subset_name: 구간 필터로 일부만 그릴 때 그 이름(제목에 표시)."""
    _ensure_font()
    fig = Figure(figsize=(9, 6), dpi=100, layout="constrained")
    if df is None or df.empty:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, f"{label}: .sum 자료가 없거나 읽지 못했습니다", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    xcol = sample_col(df)
    x = pd.to_numeric(df[xcol], errors="coerce")
    specs = [("수심", C_DEPTH), ("평균 속력", C_SPEED)]
    axes = fig.subplots(2, 1, sharex=True)
    runs = section_runs(x, sections)
    handles = []
    for i, ax in enumerate(axes):
        if runs:
            handles = _shade_sections(ax, runs, label_top=(i == 0))
    for ax, (prefix, color) in zip(axes, specs):
        col = _find_col(df, prefix)
        if col is None:
            ax.text(0.5, 0.5, f"'{prefix}' 열을 .sum에서 찾지 못함", ha="center", va="center", transform=ax.transAxes)
            continue
        y = pd.to_numeric(df[col], errors="coerce")
        ax.plot(x, y, color=color, lw=1.2, marker="o", ms=2.5)
        ax.set_ylabel(str(col))
        n_na = int(y.isna().sum())
        note = f"빈값 {n_na}개는 표시하지 않음(0으로 바꾸지 않음)" if n_na else "빈값 없음"
        ax.text(0.995, 0.97, note, transform=ax.transAxes, ha="right", va="top", fontsize=8, color="#555")
        ax.grid(alpha=0.3, lw=0.5)
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xlabel(f"샘플 번호 (.sum '{xcol}' 열)")
    if runs:
        what = f"'{subset_name}' 구간만" if subset_name else "전체 기록"
        fig.suptitle(f"{label}  .sum {what} — 구간 음영: .rsqmb에 기록된 샘플 타입(RSQ 기록값)", fontsize=11)
        axes[-1].legend(handles=handles, loc="upper left", fontsize=8, frameon=True, ncol=len(handles))
    else:
        fig.suptitle(f"{label}  .sum 전체 기록 — 구간(시작 Edge/횡단/마침 Edge) 정보 없음", fontsize=11)
    return fig


_CELL_RE = re.compile(r"^셀(\d+) 위치")


def vel_cells(df: pd.DataFrame):
    """.vel의 셀 번호 목록과 (위치열, 속도열)."""
    out = []
    for c in df.columns:
        m = _CELL_RE.match(str(c))
        if m:
            k = int(m.group(1))
            spd = _find_col(df, f"셀{k} 속도")
            if spd is not None:
                out.append((k, c, spd))
    return out


def fig_vel_profile(df: pd.DataFrame | None, label: str,
                    sections: pd.Series | None = None) -> tuple[Figure, str]:
    """샘플 번호 × 셀 위치의 '셀 속도' 값 분포. 빈 셀은 그리지 않음(보간 없음)."""
    _ensure_font()
    fig = Figure(figsize=(10, 5.2), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    if df is None or df.empty:
        ax.text(0.5, 0.5, f"{label}: .vel 자료가 없거나 읽지 못했습니다", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        return fig, "자료 없음"
    cells = vel_cells(df)
    size_col = _find_col(df, "셀 크기")
    start_col = _find_col(df, "셀 시작")
    if not cells or size_col is None:
        ax.text(0.5, 0.5, "셀 위치/속도/크기 열을 찾지 못함", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig, "열 없음"
    xs = pd.to_numeric(df[sample_col(df)], errors="coerce").to_numpy()
    size = pd.to_numeric(df[size_col], errors="coerce").to_numpy()
    start = pd.to_numeric(df[start_col], errors="coerce").to_numpy() if start_col else None

    # 위치 = 셀 시작 + (k−0.5)×크기 관계가 성립하면 '셀 중심'으로 보고 크기만큼 사각형으로 그림
    centered = start is not None
    tol = 0.0015
    polys, vals = [], []
    for k, pcol, scol in cells:
        pos = pd.to_numeric(df[pcol], errors="coerce").to_numpy()
        spd = pd.to_numeric(df[scol], errors="coerce").to_numpy()
        if start is not None:
            ok = np.isnan(pos) | (np.abs(pos - (start + (k - 0.5) * size)) <= tol)
            if not ok.all():
                centered = False
        for i in range(len(xs)):
            if np.isnan(pos[i]) or np.isnan(spd[i]) or np.isnan(size[i]) or np.isnan(xs[i]):
                continue
            polys.append(((xs[i], pos[i]), spd[i], size[i]))
    if not polys:
        ax.text(0.5, 0.5, "그릴 수 있는 셀 값이 없습니다", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig, "값 없음"
    verts = []
    for (x, p), v, s in polys:
        if centered:
            y0, y1 = p - s / 2, p + s / 2
        else:
            y0, y1 = p - s * 0.1, p + s * 0.1  # 기준 불명 → 얇은 표시만
        verts.append([(x - 0.5, y0), (x + 0.5, y0), (x + 0.5, y1), (x - 0.5, y1)])
        vals.append(v)
    pc = PolyCollection(verts, array=np.asarray(vals), cmap="viridis", edgecolors="none")
    ax.add_collection(pc)
    ax.autoscale_view()
    # 가로축은 파일의 전체 샘플 범위(값이 없는 샘플도 빈칸으로 보이게)
    ax.set_xlim(np.nanmin(xs) - 0.5, np.nanmax(xs) + 0.5)
    ax.invert_yaxis()
    runs = section_runs(pd.Series(xs), sections)
    for i, (t, a, b) in enumerate(runs):
        if i > 0:
            ax.axvline(a - 0.5, color="#c2410c", lw=1.2, ls="--")
        ax.text((a + b) / 2, 1.0, t, transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                fontsize=8, color="#c2410c")
    cb = fig.colorbar(pc, ax=ax, pad=0.01)
    cb.set_label("셀 속도 (m/s) — .vel '셀k 속도' 열 원문 값")
    ax.set_xlabel(f"샘플 번호 (.vel '{sample_col(df)}' 열)")
    ax.set_ylabel("셀 위치 (m)\n원문 값 · 기준면 미확인")
    mode = ("셀 위치 = 셀 시작 + (k−0.5)×셀 크기 관계가 모든 행에서 확인되어, 위치를 셀 중심으로 보고 셀 크기만큼 그림"
            if centered else "셀 위치와 크기 관계를 확인하지 못해 위치에 얇은 띠로만 표시함")
    ax.set_title(f"{label}  .vel 셀 속도 분포 — 전체 기록 (빈 셀은 비워 둠 · 보간 없음)", fontsize=11, pad=16)
    if runs:
        mode += "  ·  주황 점선 = 구간 경계(.rsqmb 샘플 타입)"
    ax.text(0.0, -0.16, mode, transform=ax.transAxes, fontsize=8, color="#555", va="top")
    ax.set_facecolor("#f4f4f4")
    return fig, mode
