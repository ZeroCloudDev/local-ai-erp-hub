"""Prevent future edits from moving the code cited and shown in the recorded series."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VideoLineTests(unittest.TestCase):
    def test_original_video_lines_remain_at_original_positions(self):
        manifest = json.loads((ROOT / 'tests/video_line_manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            with self.subTest(file=name):
                lines = (ROOT / name).read_text(encoding='utf-8-sig').splitlines()
                if expected['allow_append']:
                    self.assertGreaterEqual(len(lines), expected['line_count'])
                else:
                    self.assertEqual(len(lines), expected['line_count'])
                for number, digest in enumerate(expected['line_hashes'], start=1):
                    if number not in expected['allowed_replacement_lines']:
                        self.assertEqual(hashlib.sha256(lines[number-1].encode()).hexdigest(), digest,
                                         f'{name}:{number} was moved or changed outside the approved repair lines')


if __name__ == '__main__':
    unittest.main()
