"""설치 위치와 연구자료·설정·로그 위치를 분리한다."""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QStandardPaths


def user_data_dir():
    base=Path(os.environ['LOCALAPPDATA']) if sys.platform=='win32' and os.environ.get('LOCALAPPDATA') else Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))
    return base/'RSQCompare'


def default_database(settings):
    saved=settings.value('db_path')
    if saved:return Path(saved)  # 이전 사용자가 고른 위치를 조용히 바꾸지 않는다.
    legacy=Path.home()/'Documents'/'RSQ_측정기록.db'
    if legacy.exists():return legacy
    return user_data_dir()/'data'/'RSQ_측정기록.db'


def log_error(exc_type,tb):
    """원문 값/예외 메시지/전체 경로 대신 오류 종류와 코드 위치만 기록한다."""
    path=user_data_dir()/'logs'/'errors.log';path.parent.mkdir(parents=True,exist_ok=True)
    from rsq_compare import APP_VERSION
    frames=traceback.extract_tb(tb) if tb else []
    lines=[f'{Path(f.filename).name}:{f.lineno} {f.name}' for f in frames]
    with path.open('a',encoding='utf-8') as stream:
        stream.write(f'\n{datetime.now().isoformat()} v{APP_VERSION} {exc_type.__name__}\n'+'\n'.join(lines)+'\n')
    return path


def icon_path():return Path(__file__).parent/'assets'/'rsq.svg'
