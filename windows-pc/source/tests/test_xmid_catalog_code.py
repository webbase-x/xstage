"""Regression: XMID embedded song codes must be indexed for catalog search."""
import ast
from pathlib import Path
import unittest


class XmidCatalogCodeTests(unittest.TestCase):
    def test_embedded_code_and_song_id_fallback(self):
        source = Path(__file__).resolve().parents[1] / 'karaoke' / 'ingest.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'metadata']
        xmids = [node for node in calls if node.args and isinstance(node.args[0], ast.Dict)
                 and any(isinstance(k, ast.Constant) and k.value == 'first_lyric'
                         for k in node.args[0].keys)
                 and any(isinstance(k, ast.Constant) and k.value == 'code'
                         for k in node.args[0].keys)]
        self.assertTrue(xmids, 'XMID metadata must populate code for search/index')
        code_expr = next(v for k, v in zip(xmids[0].args[0].keys, xmids[0].args[0].values)
                         if isinstance(k, ast.Constant) and k.value == 'code')
        self.assertIn('songId', ast.unparse(code_expr))
        self.assertIn('code', ast.unparse(code_expr))


if __name__ == '__main__':
    unittest.main()
