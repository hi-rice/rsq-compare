"""Windows x64 배포 준비/빌드. --prepare-only는 실행파일을 만들지 않는다."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from rsq_compare import APP_NAME,APP_VERSION


def prepare(target):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    from PIL import Image
    target.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    image=QImage(256,256,QImage.Format_ARGB32);image.fill(Qt.transparent)
    painter=QPainter(image);QSvgRenderer(str(ROOT/'rsq_compare/assets/rsq.svg')).render(painter);painter.end()
    assert image.save(str(target/'icon.png'))
    Image.open(target/'icon.png').save(target/'app.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    version=tuple(int(v) for v in APP_VERSION.split('.'))+(0,)
    text=f'''VSVersionInfo(ffi=FixedFileInfo(filevers={version!r},prodvers={version!r},mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription',{APP_NAME!r}),StringStruct('ProductName',{APP_NAME!r}),StringStruct('FileVersion',{APP_VERSION!r}),StringStruct('ProductVersion',{APP_VERSION!r})])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])'''
    (target/'version_info.txt').write_text(text,encoding='utf-8')
    (target/'version.iss').write_text(f'#define AppVersion "{APP_VERSION}"\n#define AppName "{APP_NAME}"\n',encoding='utf-8-sig')
    (target/'manifest.json').write_text(json.dumps(dict(name=APP_NAME,version=APP_VERSION,python=sys.version,platform=sys.platform,prepared_only=True),ensure_ascii=False,indent=2),encoding='utf-8')
    licenses=target/'licenses';licenses.mkdir(exist_ok=True)
    for dist in importlib.metadata.distributions():
        for f in dist.files or []:
            if any(s in str(f).lower() for s in ('license','copying','notice')) and dist.locate_file(f).is_file():
                dest=licenses/(dist.metadata['Name']+'_'+str(f).replace('/','_').replace('\\','_'))
                dest.write_bytes(dist.locate_file(f).read_bytes())
    return target


def audit_dist(path):
    blocked={'.db','.sqlite','.sqlite3','.dis','.sum','.snr','.vel','.rsqmb','.xlsx','.bak'}
    bad=[p.name for p in path.rglob('*') if p.is_file() and p.suffix.lower() in blocked]
    if bad:raise RuntimeError(f'배포 폴더에 연구자료 형식이 있습니다: {bad}')
    executable=path/'RSQCompare.exe'
    if not executable.exists():raise RuntimeError('Windows 실행파일이 없습니다.')
    with executable.open('rb') as stream:
        if stream.read(2)!=b'MZ':raise RuntimeError('Windows PE 실행파일 형식이 아닙니다.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if sys.platform!='win32' and not args.prepare_only:parser.error('Windows 빌드는 Windows에서만 실행하세요.')
    if args.out and not args.prepare_only:parser.error('--out은 준비 검증에만 사용할 수 있습니다.')
    target=prepare(args.out or ROOT/'build/windows')
    if args.prepare_only:
        print(f'PREPARED ONLY: {APP_VERSION}, Windows 실행파일 미생성');return
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm',str(ROOT/'packaging/windows/rsq.spec')],cwd=ROOT,check=True)
    audit_dist(ROOT/'dist/RSQCompare')
    iscc=Path(os.environ.get('ISCC_EXE',r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'))
    subprocess.run([str(iscc),str(ROOT/'packaging/windows/installer.iss')],cwd=ROOT,check=True)
    installers=list((ROOT/'dist/installer').glob('*.exe'))
    if not installers:raise RuntimeError('설치파일이 생성되지 않았습니다.')
    import hashlib
    manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    manifest.update(prepared_only=False,windows_build_succeeded=True,installer=installers[0].name,
                    sha256=hashlib.sha256(installers[0].read_bytes()).hexdigest())
    (ROOT/'dist/installer/build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Windows installer:',installers[0].name)

if __name__=='__main__':main()
