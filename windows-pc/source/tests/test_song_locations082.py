import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from karaoke.lister import locations,migrate_locations,register_catalog_location
from karaoke.ui import KaraokeApp

class SongLocationTests(unittest.TestCase):
    def test_remembered_catalog_becomes_a_scan_root_once(self):
        settings={'song_folders':[],'legacy_root':'legacy'}
        self.assertTrue(migrate_locations(settings));self.assertEqual(locations(settings),locations({'song_folders':[{'path':'legacy','type':'ทุกประเภท'}]}))
        self.assertFalse(migrate_locations(settings))
    def test_explicit_roots_preserved_during_migration(self):
        settings={'song_folders':[{'path':'chosen','type':'EMK'}],'legacy_root':'legacy'}
        before=locations(settings);migrate_locations(settings);self.assertEqual(locations(settings),before)
    def test_removed_folder_is_not_added_back(self):
        settings={'song_folders':[],'legacy_root':'legacy'};migrate_locations(settings);settings['song_folders']=[]
        migrate_locations(settings);self.assertEqual(locations(settings),[])
    def test_register_catalog_preserves_other_roots_and_deduplicates(self):
        settings={'song_folders':[{'path':'chosen','type':'EMK'}]}
        register_catalog_location(settings,'legacy');register_catalog_location(settings,'legacy')
        self.assertEqual(len(locations(settings)),2);self.assertEqual(settings['legacy_root'],'legacy')
    def test_empty_or_invalid_legacy_does_not_invent_a_root(self):
        for value in ('',None,{},42):
            settings={'legacy_root':value};migrate_locations(settings);self.assertEqual(locations(settings),[])
    def test_database_only_yes_calls_supported_rebuild_arguments(self):
        app=NS(settings={},start_index_job=Mock(),library=NS(rebuild=Mock(return_value=(0,0,[]))),messages=Mock(),cancel_scan=object(),job_event=Mock(),index_protected_ids=Mock(return_value={123}))
        with patch('karaoke.ui.messagebox.askyesno',return_value=True):KaraokeApp.rebuild_library(app,force=True)
        operation=app.start_index_job.call_args.args[0];self.assertEqual(operation(),(0,0,[]))
        kwargs=app.library.rebuild.call_args.kwargs
        self.assertNotIn('import_options',kwargs);self.assertEqual(kwargs['protected'],{123});self.assertTrue(kwargs['force'])
    def test_database_only_no_does_not_start_a_job(self):
        app=NS(settings={},start_index_job=Mock())
        with patch('karaoke.ui.messagebox.askyesno',return_value=False):KaraokeApp.rebuild_library(app)
        app.start_index_job.assert_not_called()
