"""Exercise the actual Windows PowerShell helpers without a database or model."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ep05_fiscal_ingest_robot/run_ep05_rehearsal.ps1"

def quote(value):
    return "'" + str(value).replace("'", "''") + "'"

@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"), "Windows PowerShell only")
class PowerShellForwarding(unittest.TestCase):
    def helper(self, name):
        text = SCRIPT.read_text(encoding="utf-8-sig")
        match = re.search(r"^function " + name + r"(?:\([^\n]*\))? \{.*?^\}", text, re.M | re.S)
        self.assertIsNotNone(match, name)
        return match.group()

    def run_ps(self, body):
        with tempfile.TemporaryDirectory(prefix="ep05-ps-", dir=ROOT) as tmp:
            path = Path(tmp) / "helper probe.ps1"
            path.write_text("$ErrorActionPreference='Stop'\n" + body, encoding="utf-8")
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip().splitlines()

    def test_inline_direct_and_splatted_python_arguments(self):
        body = "$Py=" + quote(sys.executable) + "\n" + self.helper("Py") + "\n"
        code = "import json,sys; print(json.dumps(sys.argv[1:]))"
        body += "Py @('-c', " + quote(code) + ", '--reset')\nif ($LASTEXITCODE -ne 0) { exit 1 }\n"
        body += "Py -c " + quote(code) + " --flag\nif ($LASTEXITCODE -ne 0) { exit 1 }\n"
        body += "$probeArgs = @('-c', " + quote(code) + ", '--splatted')\nPy @probeArgs\nexit $LASTEXITCODE\n"
        self.assertEqual([json.loads(line) for line in self.run_ps(body)], [["--reset"], ["--flag"], ["--splatted"]])

    def test_hash_helper_computes_file_bytes(self):
        expected = hashlib.sha256(SCRIPT.read_bytes()).hexdigest().upper()
        body = self.helper("Get-Ep05Sha256") + "\nGet-Ep05Sha256 " + quote(SCRIPT)
        self.assertEqual(self.run_ps(body), [expected])
