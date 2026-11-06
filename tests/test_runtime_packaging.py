import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rsq_compare import APP_NAME, APP_VERSION
from rsq_compare import runtime

class Settings:
    def __init__(self,value):self.saved=value
    def value(self,key):return self.saved

class RuntimeTests(unittest.TestCase):
    def test_chosen_database_is_never_redirected_even_when_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'한글 경로'/'연구 DB.db'
            self.assertEqual(runtime.default_database(Settings(str(target))),target)
            self.assertFalse(target.exists())
    def test_legacy_database_without_saved_setting_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);p=home/'Documents'/'RSQ_측정기록.db';p.parent.mkdir();p.write_bytes(b'private')
            with patch.object(Path,'home',return_value=home):self.assertEqual(runtime.default_database(Settings(None)),p)
    def test_log_excludes_exception_payload_and_full_path(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(runtime,'user_data_dir',return_value=Path(folder)):
            try:raise ValueError('SECRET_RAW_MEASUREMENT_AND_TOKEN')
            except ValueError as exc:path=runtime.log_error(type(exc),exc.__traceback__)
            text=path.read_text(encoding='utf-8');self.assertIn(APP_VERSION,text);self.assertIn('ValueError',text)
            self.assertNotIn('SECRET_RAW_MEASUREMENT_AND_TOKEN',text);self.assertNotIn(str(Path(__file__).resolve()),text)
    def test_missing_saved_db_is_not_replaced_on_window_start(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings
        from rsq_compare.gui.main_window import MainWindow
        from rsq_compare.gui.workers import JobRunner
        app=QApplication.instance() or QApplication([])
        settings=QSettings('NDMI','RSQCompare');old=settings.value('db_path')
        with tempfile.TemporaryDirectory() as folder:
            missing=Path(folder)/'이전 연구 DB.db';settings.setValue('db_path',str(missing))
            w=MainWindow(JobRunner())
            self.assertFalse(missing.exists());self.assertEqual(w.dbtab.db_path,missing)
            self.assertIn('기존 DB',w.dbtab.lbl_db.text());w.close()
        settings.setValue('db_path',old)

class PackagingTests(unittest.TestCase):
    def test_preparation_generates_versioned_icon_without_claiming_windows_build(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        p=Path(__file__).resolve().parents[1]/'packaging/windows/build.py'
        spec=importlib.util.spec_from_file_location('windows_builder',p);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            out=builder.prepare(Path(folder));self.assertTrue((out/'app.ico').exists())
            self.assertIn(APP_VERSION,(out/'version_info.txt').read_text(encoding='utf-8'))
            self.assertIn(APP_NAME,(out/'version_info.txt').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((out/'manifest.json').read_text(encoding='utf-8'))['name'],APP_NAME)
            self.assertIn('"prepared_only": true',(out/'manifest.json').read_text(encoding='utf-8'))
            (out/'RSQCompare.exe').write_bytes(b'fake-test-only')
            (out/'private.db').write_bytes(b'private')
            with self.assertRaises(RuntimeError):builder.audit_dist(out)
    def test_preparation_validation_under_cp1252_default(self):
        # Windows 서유럽 로캘을 Linux에서도 재현한다. 명시한 UTF-8은 그대로 따른다.
        original_read_text = Path.read_text
        def cp1252_read_text(path, encoding=None, errors=None):
            return original_read_text(path, encoding=encoding or 'cp1252', errors=errors)
        with patch.object(Path, 'read_text', cp1252_read_text):
            self.test_preparation_generates_versioned_icon_without_claiming_windows_build()

class InnoCompilerTests(unittest.TestCase):
    def builder(self):
        p=Path(__file__).resolve().parents[1]/'packaging/windows/build.py'
        spec=importlib.util.spec_from_file_location('iscc_test_builder',p)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_preinstalled_compiler_is_found_in_either_program_files_location(self):
        builder=self.builder()
        with tempfile.TemporaryDirectory() as folder:
            compiler=Path(folder)/'한글 경로'/'Inno Setup 6'/'ISCC.exe'
            compiler.parent.mkdir(parents=True);compiler.write_bytes(b'test fixture, not an executable')
            for key in ('ProgramFiles(x86)','ProgramFiles'):
                variables={'ISCC_EXE':'','ProgramFiles(x86)':'','ProgramFiles':''}
                variables[key]=str(compiler.parent.parent)
                with self.subTest(location=key),patch.dict(os.environ,variables),patch.object(builder.shutil,'which',return_value=None):
                    self.assertEqual(builder.resolve_iscc(),compiler)

    def test_explicit_override_is_respected_and_invalid_override_is_not_silently_replaced(self):
        builder=self.builder()
        with tempfile.TemporaryDirectory() as folder:
            compiler=Path(folder)/'별도 컴파일러.exe';compiler.write_bytes(b'test fixture')
            with patch.dict(os.environ,{'ISCC_EXE':str(compiler)}):
                self.assertEqual(builder.resolve_iscc(),compiler)
            with patch.dict(os.environ,{'ISCC_EXE':str(compiler.with_name('missing.exe'))}),patch.object(builder.shutil,'which',return_value=str(compiler)):
                with self.assertRaisesRegex(RuntimeError,'ISCC_EXE'):builder.resolve_iscc()

    def test_missing_compiler_fails_before_preparation_or_pyinstaller(self):
        builder=self.builder()
        with patch.object(builder.sys,'platform','win32'),patch.object(builder.sys,'argv',['build.py']),patch.dict(os.environ,{'ISCC_EXE':'','ProgramFiles(x86)':'','ProgramFiles':''}),patch.object(builder.shutil,'which',return_value=None),patch.object(builder,'prepare') as prepare,patch.object(builder.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'ISCC.exe'):builder.main()
            prepare.assert_not_called();run.assert_not_called()

if __name__=='__main__':unittest.main()
