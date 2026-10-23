import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_actual_powershell_smoke_code_and_raw_connection_api(self):
        import core.database as database
        script = (ROOT / 'setup.ps1').read_text(encoding='utf-8-sig')
        code = re.search(r'\$smokeCode = @"\r?\n(.*?)\r?\n"@', script, re.S).group(1)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'smoke.db'
            database.init_db(db_path)
            connect = database.get_connection
            with patch.object(database, 'get_connection', side_effect=lambda: connect(db_path)):
                exec(compile(code, 'setup.ps1 smoke test', 'exec'), {})

    def test_actual_bash_smoke_imports(self):
        script = (ROOT / 'setup.sh').read_text(encoding='utf-8')
        code = re.search(r'\$VENV_PY -c "(from core.schemas.*?)"', script).group(1)
        exec(compile(code, 'setup.sh smoke test', 'exec'), {})

    @unittest.skipUnless(shutil.which('powershell') or shutil.which('pwsh'), 'PowerShell not installed')
    def test_exact_model_tag_condition_with_similar_tags(self):
        script = (ROOT / 'setup.ps1').read_text(encoding='utf-8-sig')
        condition = re.search(r'if \((\$m\.name.*?)\) \{', script).group(1)
        command = f'''$ErrorActionPreference = 'Stop'; $values = @('qwen2.5:3b','qwen2.5:latest','qwen2.5:3b-instruct','qwen2.5:3b-extra'); foreach ($value in $values) {{ $m = [pscustomobject]@{{name=$value;model=$value}}; if ({condition}) {{ $value }} }}'''
        shell = shutil.which('powershell') or shutil.which('pwsh')
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', command], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip().splitlines(), ['qwen2.5:3b'])


if __name__ == '__main__':
    unittest.main()
