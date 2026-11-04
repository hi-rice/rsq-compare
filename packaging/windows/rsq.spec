# PyInstaller: Windows에서만 build.py를 통해 실행한다.
from pathlib import Path
root=Path(SPECPATH).parents[1]
a=Analysis([str(root/'run_app.py')],pathex=[str(root)],
           datas=[(str(root/'rsq_compare/assets/rsq.svg'),'rsq_compare/assets')]+[(str(root/'templates'/name),'templates') for name in ('README_양식.txt','비교유량_양식.csv','외부시계열_양식.csv','예시_가상_FEWP형식.csv')]+[
                  (str(root/'build/windows/licenses'),'licenses'),(str(root/'packaging/windows/THIRD_PARTY.md'),'.')],
           hiddenimports=['matplotlib.backends.backend_qtagg','PySide6.QtSvg'],
           excludes=['tkinter','PyQt5','PyQt6','pytest','tests'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='RSQCompare',debug=False,strip=False,upx=False,
        console=False,disable_windowed_traceback=False,icon=str(root/'build/windows/app.ico'),
        version=str(root/'build/windows/version_info.txt'),uac_admin=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='RSQCompare')
