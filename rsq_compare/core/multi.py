"""여러 세션 비교 / 비교 유량 비교 (표와 그래프).

- 세션별 통계는 '그 세션에 등록된 .dis 회차표의 Total Q'만으로 계산한다(DIS에 들어간 회차 = RSQ에서 체크된 회차).
- DIS 전체 Total Q(원문)도 함께 보여준다. 두 값은 test 자료에서 같았지만 항상 같다고 가정하지 않는다.
- 비교 유량 비교는 차이와 차이율만 보여준다. 합격/불합격·허용오차 판정은 하지 않는다.
"""
from __future__ import annotations

import statistics

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from rsq_compare.core.plots import _ensure_font

NOTE_MULTI = ("세션별 통계는 각 세션에 등록된 .dis의 회차별 Total Q(=RSQ에서 체크돼 .dis에 들어간 회차)로 계산한 "
              "단순 비교값입니다. 공식 최종유량·판정이 아닙니다.")


def session_label(row) -> str:
    return f"#{row['id']} {row['session_name']}\n({row['dis_file']})"


def session_summary(sess: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, s in sess.iterrows():
        q = tr[(tr["session_id"] == s["id"]) & (tr["has_summary"] == 1)]["total_q"].dropna().tolist()
        n = len(q)
        mean = statistics.fmean(q) if n else None
        sd = statistics.stdev(q) if n >= 2 else None
        psd = statistics.pstdev(q) if n else None
        cov = (psd / mean) if (psd is not None and mean not in (None, 0)) else None
        ref = s.get("ref_q")
        ref = None if ref is None or pd.isna(ref) else float(ref)
        diff = (mean - ref) if (mean is not None and ref is not None) else None
        pct = (diff / ref * 100) if (diff is not None and ref != 0) else None
        u = s.get("q_unit") or ""
        rows.append({
            "등록ID": s["id"], "세션": s["session_name"],
            "소하천코드": s.get("site_code"), "소하천코드 출처": s.get("site_code_source"),
            "소하천명[목록]": s.get("river_name"), "시군구[목록]": f"{s.get('sido') or ''} {s.get('sigungu') or ''}".strip() or None,
            "가까운 AWS[목록]": (f"{s.get('aws_name')} ({s.get('aws_id')}, {s.get('aws_dist_km')} km)"
                               if s.get("aws_name") else None),
            "측정자": s.get("operator"), "RSQ Site Name": s.get("site_name"),
            "측정일": s.get("date_measured"), "첫 회차 시작(DIS 원문)": s.get("first_start_time"),
            "시간 기준": s.get("time_basis"), "사용한 .dis": s.get("dis_file"),
            "DIS 회차 수": n, f"DIS 전체 Total Q 원문 ({u})": s.get("dis_total_q_raw"),
            f"회차 Total Q 산술평균 ({u})": mean, f"표본표준편차 ({u}, n−1)": sd,
            f"[RSQ 방식] 모표준편차 ({u}, n)": psd, "[RSQ 방식] COV": cov,
            f"최소 ({u})": min(q) if q else None, f"최대 ({u})": max(q) if q else None,
            f"비교 유량 ({u})": ref, "비교 유량 출처": s.get("ref_source"),
            f"평균 − 비교 유량 ({u})": diff, "(평균 − 비교 유량) / 비교 유량 (%)": pct, "메모": s.get("memo"),
        })
    return pd.DataFrame(rows)


def reference_by_transect(sess: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    ref = {r["id"]: r["ref_q"] for _, r in sess.iterrows() if r.get("ref_q") is not None and not pd.isna(r.get("ref_q"))}
    rows = []
    for _, t in tr[tr["has_summary"] == 1].iterrows():
        rq = ref.get(t["session_id"])
        if rq is None:
            continue
        q = t["total_q"]
        d = None if q is None or pd.isna(q) else q - rq
        rows.append({"등록ID": t["session_id"], "세션": t["session_name"], "회차": t["label"],
                     "회차 Total Q [DIS]": q, "비교 유량": rq, "회차 − 비교 유량": d,
                     "(회차 − 비교 유량) / 비교 유량 (%)": (d / rq * 100) if (d is not None and rq != 0) else None})
    return pd.DataFrame(rows)


def fig_sessions(sess: pd.DataFrame, tr: pd.DataFrame) -> Figure:
    _ensure_font()
    fig = Figure(figsize=(10, 5.4), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    if sess.empty:
        ax.text(0.5, 0.5, "비교할 세션을 선택하세요", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    labels = [session_label(r) for _, r in sess.iterrows()]
    x = np.arange(len(sess))
    u = next((v for v in sess["q_unit"] if v), "")
    has_ref = False
    for xi, (_, s) in zip(x, sess.iterrows()):
        q = tr[(tr["session_id"] == s["id"]) & (tr["has_summary"] == 1)]["total_q"].dropna()
        if len(q):
            offs = np.linspace(-0.18, 0.18, len(q)) if len(q) > 1 else [0.0]
            ax.scatter(xi + np.asarray(offs), q, s=22, color="#2563a8", alpha=0.8, zorder=3,
                       label="회차 Total Q [DIS]" if xi == 0 else None)
            m = q.mean()
            ax.hlines(m, xi - 0.28, xi + 0.28, color="#111", lw=2, zorder=4,
                      label="회차 산술평균" if xi == 0 else None)
            ax.text(xi + 0.3, m, f"{m:.4f}", va="center", fontsize=8)
        else:
            ax.text(xi, 0, "DIS 회차 없음", ha="center", fontsize=8, color="#9a3412")
        rq = s.get("ref_q")
        if rq is not None and not pd.isna(rq):
            ax.scatter([xi], [rq], marker="D", s=50, color="#c2410c", zorder=5,
                       label="비교 유량" if not has_ref else None)
            has_ref = True
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel(f"RSQ 총유량 ({u})" if u else "RSQ 총유량")
    ax.set_xlabel("등록된 세션 (첫 회차 시작 시각 순)")
    ax.set_title("세션별 회차 총유량 비교 — DIS에 기록된 RSQ 결과", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8, loc="best")
    return fig


def fig_reference(summ: pd.DataFrame) -> Figure:
    _ensure_font()
    fig = Figure(figsize=(6.5, 5.4), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    mcol = next((c for c in summ.columns if c.startswith("회차 Total Q 산술평균")), None)
    rcol = next((c for c in summ.columns if c.startswith("비교 유량 (")), None)
    d = summ[[mcol, rcol, "등록ID"]].dropna() if (mcol and rcol and not summ.empty) else pd.DataFrame()
    if d.empty:
        ax.text(0.5, 0.5, "비교 유량이 입력된 세션이 없습니다.\n'비교 유량' 칸에 직접 입력하거나 양식 파일을 불러오세요.",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    ax.scatter(d[rcol], d[mcol], s=40, color="#2563a8", zorder=3)
    for _, r in d.iterrows():
        ax.annotate(f"#{int(r['등록ID'])}", (r[rcol], r[mcol]), textcoords="offset points", xytext=(5, 4), fontsize=8)
    lo = float(min(d[rcol].min(), d[mcol].min()))
    hi = float(max(d[rcol].max(), d[mcol].max()))
    pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1.0
    ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color="#888", ls="--", lw=1, label="1:1 선(같으면 이 선 위)")
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlabel(rcol)
    ax.set_ylabel(mcol + " [DIS]")
    ax.set_title("비교 유량 대비 세션 평균 (판정 없음)", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return fig


def fig_external(values: pd.DataFrame, matched: pd.DataFrame, name: str, unit: str, shift_note: str,
                 shift_hours: float) -> Figure:
    """외부 시계열 + 회차 시간창(음영). 시각축은 DIS 기준."""
    _ensure_font()
    fig = Figure(figsize=(10, 4.8), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    ok = matched[matched.get("시간창 시작(DIS 기준)").notna()] if "시간창 시작(DIS 기준)" in matched else pd.DataFrame()
    if values.empty or ok.empty:
        ax.text(0.5, 0.5, "그릴 자료가 없습니다(연결된 회차 없음)", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    t = pd.to_datetime(values["t"]) + pd.to_timedelta(shift_hours, unit="h")
    w0 = pd.to_datetime(ok["시간창 시작(DIS 기준)"]).min() - pd.Timedelta(minutes=30)
    w1 = pd.to_datetime(ok["시간창 끝(DIS 기준)"]).max() + pd.Timedelta(minutes=30)
    sel = (t >= w0) & (t <= w1)
    ax.plot(t[sel], values["value"][sel], color="#2563a8", lw=1.2, marker="o", ms=3, label=name)
    # 같은 시간창(같은 세션을 다른 .dis로 등록한 경우 등)은 한 번만 그리고 등록ID를 모아 표시
    grp = ok.groupby(["시간창 시작(DIS 기준)", "시간창 끝(DIS 기준)", "회차"], sort=True)["등록ID"].apply(
        lambda x: ",".join(f"#{int(v)}" for v in sorted(set(x))))
    for i, ((a, b, lab), ids) in enumerate(grp.items()):
        a, b = pd.to_datetime(a), pd.to_datetime(b)
        ax.axvspan(a, b, color="#fde9c4", alpha=0.8, zorder=0, label="회차 시간창" if i == 0 else None)
        ax.text(a + (b - a) / 2, 1.0, f"{ids} {lab}", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set_xlim(w0, w1)
    ax.set_ylabel(f"{name} ({unit})" if unit else name)
    ax.set_xlabel("시각 (DIS 시간 기준)")
    ax.set_title(f"외부 시계열과 회차 시간창 — {shift_note}", fontsize=10, pad=40)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3)
    from matplotlib.dates import DateFormatter
    ax.xaxis.set_major_formatter(DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    return fig
