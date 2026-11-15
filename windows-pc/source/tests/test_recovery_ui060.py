import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from karaoke.json_recovery import prompt_recovery
from karaoke.library import JsonRecoveryError

@unittest.skipUnless(os.environ.get('DISPLAY'),'requires explicit GUI test display')
class RecoveryUiTests(unittest.TestCase):
    def test_cancel_does_not_change_target(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'settings.json';target.write_bytes(b'bad')
            with patch('tkinter.messagebox.askyesno',return_value=False):
                self.assertFalse(prompt_recovery(JsonRecoveryError(target,'test')))
            self.assertEqual(target.read_bytes(),b'bad')
    def test_invalid_selection_then_valid_restores_with_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'queue.json';target.write_bytes(b'bad')
            invalid=Path(d)/'invalid.json';invalid.write_bytes(b'[null]')
            valid=Path(d)/'valid.json';valid.write_bytes(b'[{"song_id":1}]')
            with patch('tkinter.messagebox.askyesno',return_value=True), patch('tkinter.filedialog.askopenfilename',side_effect=[str(invalid),str(valid)]), patch('tkinter.messagebox.showerror') as errors, patch('tkinter.messagebox.showinfo'):
                self.assertTrue(prompt_recovery(JsonRecoveryError(target,'test')))
                errors.assert_called_once()
            self.assertEqual(target.read_bytes(),valid.read_bytes())
            self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),b'bad')
    def test_declined_confirmation_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'settings.json';target.write_bytes(b'bad')
            source=Path(d)/'valid.json';source.write_bytes(b'{}')
            with patch('tkinter.messagebox.askyesno',side_effect=[True,False]), patch('tkinter.filedialog.askopenfilename',return_value=str(source)):
                self.assertFalse(prompt_recovery(JsonRecoveryError(target,'test')))
            self.assertEqual(target.read_bytes(),b'bad');self.assertFalse(list(Path(d).glob('*.bak')))
