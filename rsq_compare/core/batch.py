"""폴더 일괄 가져오기 (자동화의 출발점).

새 측정 자료 폴더(여러 세션이 섞여 있어도 됨)를 통째로 지정하면
- 세션을 모두 찾고
- 각 세션을 읽어(.dis는 세션 이름과 같은 파일, 없으면 첫 후보)
- 누적 DB에 아직 없는 것만 등록한다(같은 .dis 내용은 건너뜀).
결과는 '가져오기 보고' 표로 돌려준다. 원본 파일은 읽기만 한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from rsq_compare.core.db import register_session
from rsq_compare.core.discovery import scan_folder
from rsq_compare.core.loader import load_session

RESULT_KOR = {"added": "새로 등록", "review": "측정 관계 확인 필요", "version": "재처리본 등록", "exists": "이미 등록됨(건너뜀)", "no_dis": "등록 안 함(.dis 없음)", "error": "오류"}


def import_folder(root: Path, db_path: Path, progress: Callable[[str], None] | None = None) -> pd.DataFrame:
    say = progress or (lambda _m: None)
    say("폴더를 살펴보는 중...")
    sessions, _scan_checks = scan_folder(Path(root))
    rows = []
    for i, sf in enumerate(sessions, start=1):
        say(f"[{i}/{len(sessions)}] {sf.name} 읽는 중...")
        try:
            sd = load_session(sf)
            status, sid, msg = register_session(db_path, sd)
            others = [p.name for p in sf.dis_candidates if sd.dis_path is None or p != sd.dis_path]
            n_warn = sum(1 for c in sd.checks if c.level != "정보")
            rows.append({
                "세션": sf.name, "폴더": str(sf.folder), "사용한 .dis": sd.dis_path.name if sd.dis_path else None,
                "결과": RESULT_KOR[status], "등록ID": sid, "회차 수(상세)": len(sd.records),
                "DIS에 있는 회차 수": sum(1 for r in sd.records if r.has_summary),
                "주의·오류 점검 수": n_warn,
                "다른 .dis 후보": ", ".join(others) or None, "안내": msg,
            })
        except Exception as e:  # noqa: BLE001  (한 세션이 실패해도 나머지는 계속)
            rows.append({"세션": sf.name, "폴더": str(sf.folder), "결과": RESULT_KOR["error"], "안내": str(e)})
    if not sessions:
        rows.append({"세션": None, "폴더": str(root), "결과": "세션 없음",
                     "안내": "RSQ 내보내기 파일(.dis / _T번호.sum 등)을 찾지 못함"})
    say("가져오기 완료")
    return pd.DataFrame(rows)
