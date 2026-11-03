"""데이터 폴더 탐색.

선택한 폴더(하위 폴더 포함)에서 RSQ 내보내기 파일을 찾아 세션별로 묶는다.
- 세션 파일 : <세션이름>.dis, <세션이름>.rsqmb
- 회차 파일 : <세션이름>_T<번호>.sum / .snr / .<좌표계>.vel (예: .ENU.vel)
- '~$'로 시작하는 임시 파일은 제외한다.
파일은 읽기만 하고 절대 수정하지 않는다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from rsq_compare.core.model import LEVEL_INFO, LEVEL_WARN, CheckItem, SessionFiles

DETAIL_RE = re.compile(
    r"^(?P<session>.+)_(?P<label>T(?P<num>\d+))\.(?P<ext>sum|snr|(?P<coord>[A-Za-z]+)\.vel)$",
    re.IGNORECASE,
)
SESSION_RE = re.compile(r"^(?P<session>.+)\.(?P<ext>dis|rsqmb)$", re.IGNORECASE)

# 여러 좌표계 .vel이 있을 때 우선순위 (ENU 우선, 나머지는 점검내역에 기록)
VEL_PRIORITY = ("ENU",)


def scan_folder(root: Path) -> tuple[list[SessionFiles], list[CheckItem]]:
    """폴더를 훑어 세션 목록과 탐색 단계 점검내역을 돌려준다."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {root}")

    sessions: dict[tuple[Path, str], SessionFiles] = {}
    checks: list[CheckItem] = []
    vel_candidates: dict[tuple[Path, str, int], dict[str, Path]] = {}

    def get(folder: Path, name: str) -> SessionFiles:
        k = (folder, name)
        if k not in sessions:
            sessions[k] = SessionFiles(name=name, folder=folder)
        return sessions[k]

    for dirpath, _dirnames, filenames in os.walk(root):
        folder = Path(dirpath)
        for fn in sorted(filenames):
            p = folder / fn
            if fn.startswith("~$"):
                checks.append(CheckItem(LEVEL_INFO, "파일 탐색", fn, "임시 파일(~$로 시작)이라 제외함"))
                continue
            m = DETAIL_RE.match(fn)
            if m:
                s = get(folder, m["session"])
                num = int(m["num"])
                s.labels.setdefault(num, m["label"].upper())
                ext = m["ext"].lower()
                if ext.endswith(".vel"):
                    coord = m["coord"].upper()
                    vel_candidates.setdefault((folder, m["session"], num), {})[coord] = p
                else:
                    s.details.setdefault(num, {})[ext] = p
                continue
            m = SESSION_RE.match(fn)
            if m:
                s = get(folder, m["session"])
                setattr(s, m["ext"].lower(), p)
                continue
            # 인식하지 못한 파일은 조용히 무시하지 않고 기록만 남김(정보 수준)
            checks.append(CheckItem(LEVEL_INFO, "파일 탐색", str(p.relative_to(root)), "인식하지 않는 파일 형식이라 읽지 않음"))

    # .vel 좌표계 선택
    for (folder, name, num), cands in vel_candidates.items():
        s = sessions[(folder, name)]
        chosen = next((c for c in VEL_PRIORITY if c in cands), sorted(cands)[0])
        s.details.setdefault(num, {})["vel"] = cands[chosen]
        if len(cands) > 1:
            others = ", ".join(sorted(set(cands) - {chosen}))
            s.notes.append(CheckItem(LEVEL_INFO, "파일 탐색", s.labels.get(num, str(num)),
                                     f".vel 파일이 여러 좌표계로 존재: {chosen} 사용, 미사용: {others}"))

    # 다른 이름으로 다시 내보낸 .dis 묶기:
    # '<세션>_<덧붙인 이름>.dis' 만 있고 상세 파일이 없는 '세션'은, 같은 폴더의 <세션>에 .dis 후보로 합친다.
    for key in list(sessions):
        s = sessions[key]
        if s.details or s.rsqmb is not None or s.dis is None:
            continue
        base = _find_base(s, sessions)
        if base is not None:
            base.dis_candidates.append(s.dis)
            base.notes.append(CheckItem(LEVEL_INFO, ".dis 후보", s.dis.name,
                                        f"이름이 '{base.name}_'로 시작하는 .dis라서 이 세션의 .dis 후보로 묶음 "
                                        "(화면 상단 'DIS 파일'에서 선택 가능)"))
            del sessions[key]
    for s in sessions.values():
        if s.dis is not None and s.dis not in s.dis_candidates:
            s.dis_candidates.insert(0, s.dis)
        elif s.dis is None and s.dis_candidates:
            s.dis = s.dis_candidates[0]  # 이름이 정확히 같은 .dis가 없으면 첫 후보를 기본값으로

    result = sorted(sessions.values(), key=lambda s: (str(s.folder), s.name))
    for s in result:
        if s.dis is None:
            s.notes.append(CheckItem(LEVEL_WARN, "파일 누락", s.name, ".dis 파일 없음 → 요약 결과(유량 등) 표시 불가"))
        if not s.details:
            s.notes.append(CheckItem(LEVEL_WARN, "파일 누락", s.name, "회차별 상세 파일(.sum/.vel/.snr) 없음"))
    return result, checks


def _find_base(s: SessionFiles, sessions: dict) -> SessionFiles | None:
    """s.name 이 '<다른 세션 이름>_...' 형태면 그 세션(같은 폴더, 가장 긴 이름)을 돌려준다."""
    best = None
    for (folder, name), other in sessions.items():
        if other is s or folder != s.folder:
            continue
        if not (other.details or other.rsqmb is not None):
            continue
        if s.name.startswith(name + "_") and (best is None or len(name) > len(best.name)):
            best = other
    return best
