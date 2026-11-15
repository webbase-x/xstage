import sys,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
from test_restore import RestoreTests
original=Path.read_text
def windows_read(self,*args,**kwargs):
    if not args and kwargs.get('encoding') is None:kwargs['encoding']='cp874'
    return original(self,*args,**kwargs)
with patch.object(Path,'read_text',windows_read):
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RestoreTests))
sys.exit(not result.wasSuccessful())
