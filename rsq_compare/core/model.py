"""데이터 구조 정의.

프로그램 전체에서 주고받는 데이터의 '모양'을 한곳에 정리한 파일이다.
값을 계산하지 않고 담아두는 그릇 역할만 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# 점검내역 수준
LEVEL_INFO = "정보"
LEVEL_WARN = "주의"
LEVEL_ERROR = "오류"

# 상세 파일 종류 (화면/엑셀 표시 이름)
DETAIL_KINDS = ("sum", "vel", "snr")
DETAIL_LABEL = {"sum": ".sum", "vel": ".vel", "snr": ".snr"}


@dataclass
class CheckItem:
    """점검내역 1건 (읽기 실패, 누락, 불일치, 참고 관찰 등)."""

    level: str
    category: str
    target: str
    message: str


@dataclass
class SessionFiles:
    """폴더 탐색 결과: 한 세션에 속한 파일 목록."""

    name: str
    folder: Path
    dis: Path | None = None
    rsqmb: Path | None = None
    # 회차 번호 -> {"sum": Path, "vel": Path, "snr": Path}
    details: dict[int, dict[str, Path]] = field(default_factory=dict)
    # 회차 번호 -> 원래 파일명의 회차 표기(예: "T01")
    labels: dict[int, str] = field(default_factory=dict)
    notes: list[CheckItem] = field(default_factory=list)
    # 같은 세션으로 볼 수 있는 .dis 후보들 (예: RSQ에서 다른 이름으로 다시 내보낸 .dis)
    dis_candidates: list[Path] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.name}  ({self.folder})"


@dataclass
class DisTable:
    title: str
    header: list[str]
    rows: list[list[str]]
    delimiter: str


@dataclass
class DisResult:
    """.dis 파싱 결과 (원문 문자열 보존)."""

    path: Path
    sections: dict[str, dict[str, str]]
    tables: list[DisTable]
    notes: list[str]
    warnings: list[str]


@dataclass
class TransectRecord:
    """회차 1개에 대한 연결 결과."""

    num: int | None
    label: str
    dis_row_raw: dict[str, str] | None = None  # 논리이름 -> 원문 문자열
    dis_values: dict[str, float | None] = field(default_factory=dict)
    files: dict[str, Path] = field(default_factory=dict)
    n_rows: dict[str, int | None] = field(default_factory=dict)
    load_errors: dict[str, str] = field(default_factory=dict)
    first_time_raw: dict[str, str | None] = field(default_factory=dict)
    start_time_check: str = ""
    sample_check: str = ""
    status: str = ""
    section_summary: str = ""  # 구간 요약 (예: 시작 Edge 289–310 (22개) / ...)
    # RSQ에 입력된 수위(Gauge Height) — .dis 'Supplemental Data' 기록. 없으면 빈 dict
    gauge: dict = field(default_factory=dict)

    @property
    def has_summary(self) -> bool:
        return self.dis_row_raw is not None

    @property
    def total_q(self) -> float | None:
        return self.dis_values.get("total_q")


@dataclass
class SessionData:
    """세션 1개를 모두 읽은 결과."""

    files: SessionFiles
    dis: DisResult | None
    dis_colmap: dict[str, str]  # 논리이름 -> .dis 실제 열 머리글
    records: list[TransectRecord]
    sum_dfs: dict[int, pd.DataFrame]
    vel_dfs: dict[int, pd.DataFrame]
    snr_dfs: dict[int, pd.DataFrame]
    checks: list[CheckItem]
    rsqmb_summary: dict | None = None
    rsqmb_props: dict | None = None
    source_compare: pd.DataFrame | None = None
    dis_path: Path | None = None  # 실제로 사용한 .dis
    # 회차 번호 -> Series(index=샘플 번호, 값=구간 이름). 검증을 통과한 회차만 들어 있음
    sections: dict[int, pd.Series] = field(default_factory=dict)

    def record(self, num: int) -> TransectRecord | None:
        for r in self.records:
            if r.num == num:
                return r
        return None
