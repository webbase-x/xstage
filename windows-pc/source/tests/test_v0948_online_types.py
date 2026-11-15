"""Windows v0.9.48 selection and pre-scan regression, without Google credentials."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from karaoke.library import SongLibrary
from karaoke.web_assets import local_candidates, online_song_type
from tests.test_studio import midi_fixture


class OnlineType0948Tests(unittest.TestCase):
    def test_type_names_and_filters(self):
        self.assertEqual(online_song_type({'format': 'NCN'}), 'NCN')
        self.assertEqual(online_song_type({'format': 'MIDI'}), 'MIDI')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = SongLibrary(root / 'songs.sqlite3')
            song = root / 'Songs' / '91001.mid'
            song.parent.mkdir(parents=True)
            song.write_bytes(midi_fixture())
            db.add_files([song])
            observed = []
            candidates, rejected = local_candidates(db.path, song_types={'MIDI'},
                                                     progress=observed.append)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(rejected, [])
            self.assertEqual(observed[-1], 1)
            excluded, ignored = local_candidates(db.path, song_types={'NCN'})
            self.assertEqual(excluded, [])
            self.assertEqual(ignored, [])
            with self.assertRaises(ValueError):
                local_candidates(db.path, song_types={'MP4'})

    def test_real_sync_receives_selected_type_filter(self):
        from karaoke.web_drive import sync_web_assets
        # Fail before any Drive or rendering activity: the selection is validated
        # by the same local_candidates function the real upload invokes.
        with patch('karaoke.web_drive.local_candidates', side_effect=RuntimeError('selection passed')) as plan:
            class D:
                def children(self, parent, name):
                    return [{'id': 'existing', 'mimeType': 'application/vnd.google-apps.folder'}]
                def download(self, identity):
                    return b'{"schemaVersion": 1, "songs": []}'
            # All other sync stages are separate tests; this asserts the filter
            # is not merely a checkbox in the interface.
            with patch('karaoke.web_drive._load_current', return_value=(None, None, {'songs': []})):
                with self.assertRaisesRegex(RuntimeError, 'selection passed'):
                    sync_web_assets(D(), 'unused.db', None, None, {}, 'unused.sf2',
                                    Path('cache'), song_types={'NCN'})
            self.assertEqual(plan.call_args.kwargs['song_types'], {'NCN'})

if __name__ == '__main__':
    unittest.main()
