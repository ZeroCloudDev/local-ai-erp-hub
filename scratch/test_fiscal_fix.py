"""Compatibility runner for the isolated regression suite; never uses the project database."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == '__main__':
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_fiscal.py'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
