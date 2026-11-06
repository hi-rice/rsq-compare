"""Windows x64 배포 준비/빌드. --prepare-only는 실행파일을 만들지 않는다."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import re
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
    try:
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8',stderr=subprocess.DEVNULL).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8'))
    except (OSError,subprocess.CalledProcessError):revision,dirty=None,None
    (target/'manifest.json').write_text(json.dumps(dict(name=APP_NAME,version=APP_VERSION,git_revision=revision,source_dirty=dirty,python=sys.version,platform=sys.platform,prepared_only=True),ensure_ascii=False,indent=2),encoding='utf-8')
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


def resolve_iscc():
    explicit=os.environ.get('ISCC_EXE')
    if explicit:
        path=Path(explicit)
        if not path.is_file():raise RuntimeError('ISCC_EXE에 지정한 컴파일러가 없습니다.')
        return path
    for name in ('ProgramFiles(x86)','ProgramFiles'):
        if os.environ.get(name):
            candidate=Path(os.environ[name])/'Inno Setup 6'/'ISCC.exe'
            if candidate.is_file():return candidate
    found=shutil.which('ISCC.exe')
    if found:return Path(found)
    raise RuntimeError('ISCC.exe를 찾지 못했습니다. ensure-iscc.ps1을 먼저 실행하거나 ISCC_EXE를 지정하세요.')


def probe_compiler(compiler):
    """ISCC 파일 리소스 대신 실제 컴파일 엔진을 출력 없이 검증한다."""
    compiler=Path(compiler).resolve()
    with tempfile.TemporaryDirectory(prefix='rsq-iscc-probe-') as folder:
        root=Path(folder)
        (root/'probe.txt').write_text('compiler probe',encoding='utf-8')
        script=root/'probe.iss'
        script.write_text('[Setup]\nAppName=RSQ Compiler Probe\nAppVersion=1.0\n'
                          'DefaultDirName={autopf}\\RSQCompilerProbe\nUninstallable=no\nOutput=no\n'
                          '[Files]\nSource: "probe.txt"; DestDir: "{app}"\n',encoding='utf-8-sig')
        result=subprocess.run([str(compiler),'/O-',str(script)],cwd=root,capture_output=True,timeout=60)
        output=result.stdout+b'\n'+result.stderr
        if result.returncode:
            raise RuntimeError(f'ISCC probe failed (exit {result.returncode}): '+output.decode('utf-8',errors='replace')[-4000:])
        match=re.search(rb'(?im)^Compiler engine version:[ \t]*Inno Setup[ \t]+(\d+)\.(\d+)\.(\d+)(?:[. \t\r].*)?$',output)
        if not match:raise RuntimeError('ISCC 엔진 전체 버전을 확인하지 못했습니다: '+output.decode('utf-8',errors='replace')[-4000:])
        version=tuple(int(x) for x in match.groups())
        if version[0]!=6 or version<(6,3,0):
            raise RuntimeError(f'지원하지 않는 Inno Setup 엔진 버전 {version}. 6.x의 6.3 이상이 필요합니다.')
        if list(root.glob('*.exe')) or list(root.glob('Output/*.exe')):
            raise RuntimeError('출력 없는 ISCC 사전 점검에서 예상하지 않은 설치파일이 생성됐습니다.')
    import hashlib
    return dict(path=str(compiler),version='.'.join(str(v) for v in version),sha256=hashlib.sha256(compiler.read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--out',type=Path);parser.add_argument('--probe-iscc',type=Path)
    args=parser.parse_args()
    if args.probe_iscc:
        try:result=probe_compiler(args.probe_iscc)
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:parser.exit(1,str(exc)+'\n')
        print(json.dumps(result,ensure_ascii=True));return
    if sys.platform!='win32' and not args.prepare_only:parser.error('Windows 빌드는 Windows에서만 실행하세요.')
    if args.out and not args.prepare_only:parser.error('--out은 준비 검증에만 사용할 수 있습니다.')
    iscc=None if args.prepare_only else resolve_iscc()
    compiler_info=None if args.prepare_only else probe_compiler(iscc)
    target=prepare(args.out or ROOT/'build/windows')
    if args.prepare_only:
        print(f'PREPARED ONLY: {APP_VERSION}, Windows 실행파일 미생성');return
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm',str(ROOT/'packaging/windows/rsq.spec')],cwd=ROOT,check=True)
    audit_dist(ROOT/'dist/RSQCompare')
    subprocess.run([str(iscc),str(ROOT/'packaging/windows/installer.iss')],cwd=ROOT,check=True)
    installers=list((ROOT/'dist/installer').glob('*.exe'))
    if not installers:raise RuntimeError('설치파일이 생성되지 않았습니다.')
    import hashlib
    manifest=json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    manifest.update(prepared_only=False,windows_build_succeeded=True,installer=installers[0].name,
                    inno_setup_version=compiler_info['version'],iscc_sha256=compiler_info['sha256'],
                    sha256=hashlib.sha256(installers[0].read_bytes()).hexdigest())
    (ROOT/'dist/installer/build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Windows installer:',installers[0].name)

if __name__=='__main__':main()
