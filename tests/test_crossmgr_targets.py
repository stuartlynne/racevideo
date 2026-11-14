import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from racevideo.crossmgr_client import Configuration


class TargetTests(unittest.TestCase):
    def test_selection_and_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            with patch.dict(os.environ, {'RACEVIDEO_CROSSMGR_CONFIG': str(path)}, clear=True):
                path.write_text(json.dumps({'url': 'http://old/mcp'}))
                self.assertEqual(Configuration.load().url, 'http://old/mcp')
                path.write_text(json.dumps({'selected_target': 'a', 'targets': {
                    'a': {'url': 'http://a/mcp'}, 'b': {'url': 'http://b/mcp'}}}))
                self.assertEqual(Configuration.load().target, 'a')
                self.assertEqual(Configuration.select('b').url, 'http://b/mcp')
                self.assertEqual(Configuration.load().target, 'b')
                with self.assertRaises(ValueError):
                    Configuration.select('missing')
                with patch.dict(os.environ, {'CROSSMGR_MCP_URL': 'http://override/mcp'}):
                    self.assertEqual(Configuration.load().url, 'http://override/mcp')
                    with self.assertRaises(ValueError):
                        Configuration.select('a')
