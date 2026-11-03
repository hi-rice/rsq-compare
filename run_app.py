"""더블클릭/명령으로 프로그램을 실행하는 파일.  python run_app.py [데이터폴더]"""
import sys
from pathlib import Path

# 이 파일이 있는 폴더를 import 경로에 넣어 'rsq_compare' 패키지를 절대 import로 찾게 함
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rsq_compare.gui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
