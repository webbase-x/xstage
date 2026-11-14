"""R14: actual Google quota and measured-byte forecast, without live credentials."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from karaoke.drive_storage import (ABOUT_QUOTA_URL, format_bytes,
    projected_storage, read_drive_quota, storage_pct)
from karaoke.library import SongLibrary
from karaoke.web_drive import sync_web_assets
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer


class StorageMathTests(unittest.TestCase):
    def test_drive_about_uses_existing_authenticated_scope_and_total_account(self):
        fake=Mock()
        fake.json.return_value={'storageQuota':{'limit':'16106127360',
            'usage':'8053063680','usageInDrive':'1073741824','usageInDriveTrash':'1024'}}
        result=read_drive_quota(fake)
        fake.json.assert_called_once_with(ABOUT_QUOTA_URL)
        self.assertEqual(result['usage'],8053063680)
        self.assertEqual(result['usageInDrive'],1073741824)
        self.assertEqual(storage_pct(result['usage'],result['limit']),50.)
        self.assertEqual(format_bytes(1073741824),'1.00 GiB')

    def test_missing_or_unlimited_quota_never_invents_percentage(self):
        fake=Mock()
        fake.json.return_value={'storageQuota':{'usage':'123456','usageInDrive':'9000'}}
        result=read_drive_quota(fake)
        self.assertIsNone(storage_pct(result['usage'],result['limit']))
        fake.json.return_value={'storageQuota':{'limit':'oops','usage':'123456'}}
        self.assertIsNone(read_drive_quota(fake)['limit'])
        fake.json.return_value={'storageQuota':{'limit':'15000'}}
        with self.assertRaises(ValueError):read_drive_quota(fake)

    def test_forecast_only_with_verified_upload_samples(self):
        quota={'usage':10_000,'limit':100_000}
        self.assertIsNone(projected_storage(quota,{'processed':10,'total':100,
            'sample_songs':10,'sample_uploads':2,'sample_bytes':1000}))
        s={'processed':20,'total':100,'sample_songs':20,
           'sample_uploads':4,'sample_bytes':2000}
        result=projected_storage(quota,s)
        self.assertEqual(result['extra_bytes'],8000)
        self.assertEqual(result['bytes'],18_000)
        self.assertEqual(storage_pct(result['bytes'],quota['limit']),18.0)
        self.assertEqual(projected_storage(quota,dict(s,processed=100))['bytes'],10_000)

    def test_forecast_does_not_double_count_reused_songs(self):
        s={'processed':60,'total':100,'sample_songs':60,
           'sample_uploads':5,'sample_bytes':600}
        self.assertEqual(projected_storage({'usage':5000,'limit':6000},s)['bytes'],5400)
        self.assertIsNone(projected_storage({'usage':5000,'limit':6000},
            dict(s,sample_uploads=0)))
        self.assertEqual(storage_pct(12_000,10_000),120.0)


class MeasuredUploadTests(unittest.TestCase):
    def test_real_rendered_file_bytes_reported_not_source_midi_size(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src=root/'Songs';src.mkdir()
            font=root/'soundfont.sf2';font.write_bytes(b'fake')
            lib=SongLibrary(root/'Data'/'songs.sqlite3')
            for i in range(13):
                (src / f'{80000+i}.mid').write_bytes(midi_fixture())
            lib.add_files(sorted(src.glob('*.mid')))
            drive=FakeWebDrive()
            events=[]
            result=sync_web_assets(drive,lib.path,[src],root/'native',{},font,
                root/'WebAssets',renderer_factory=StubRenderer,
                storage_progress=events.append,first_batch_size=2,batch_size=3,
                publish_interval=9999)
            self.assertEqual(len(events[-1:]),1)
            final=events[-1]
            self.assertEqual(final['processed'],13)
            self.assertEqual(final['total'],13)
            self.assertEqual(final['sample_songs'],13)
            self.assertGreaterEqual(final['sample_uploads'],3)
            self.assertGreater(final['uploaded_bytes'],0)
            self.assertGreater(final['sample_bytes'],0)
            # Running again uses verified remote media rather than counting
            # those files as fresh new storage consumption.
            second=[]
            sync_web_assets(drive,lib.path,[src],root/'native',{},font,
                root/'WebAssets',renderer_factory=StubRenderer,
                storage_progress=second.append,first_batch_size=2,batch_size=3,
                publish_interval=9999)
            self.assertEqual(second[-1]['uploaded_bytes'],0)
            self.assertEqual(second[-1]['sample_uploads'],0)
            self.assertIsNone(projected_storage({'usage':100000,'limit':200000},
                dict(second[-1],processed=6,total=13)))
            self.assertEqual(result['failed'],[])


if __name__=='__main__': unittest.main()
