import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from karaoke.google_drive_sync import Drive, FOLDER_MIME, ROOT_NAME, load_client, sync_library
from karaoke.library import SongLibrary, write_json


class FakeDrive(Drive):
    def __init__(self):
        super().__init__('test')
        self.items = {'root': {'id': 'root', 'name': 'root', 'mimeType': FOLDER_MIME, 'parent': None}}
        self.uploaded = []
        self.next_id = 0

    def _id(self):
        self.next_id += 1
        return str(self.next_id)

    def children(self, parent, name=None):
        return [{key: value for key, value in item.items() if key != 'parent'}
                for item in self.items.values() if item['parent'] == parent
                and (name is None or item['name'] == name)]

    def folder(self, parent, name):
        matching = self.children(parent, name)
        if matching:
            return matching[0]
        item = {'id': self._id(), 'name': name, 'mimeType': FOLDER_MIME, 'parent': parent}
        self.items[item['id']] = item
        return item

    def _upload(self, path, parent, existing=None):
        digest = hashlib.md5(Path(path).read_bytes()).hexdigest()
        item = {'id': existing['id'] if existing else self._id(), 'name': Path(path).name,
                'mimeType': 'application/octet-stream', 'parent': parent, 'md5Checksum': digest}
        self.items[item['id']] = item
        self.uploaded.append(Path(path).name)
        return item


class GoogleDriveSyncTests(unittest.TestCase):
    def test_desktop_oauth_config_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                load_client(root, root)
            (root / 'google-oauth-client.json').write_text(json.dumps({'installed': {
                'client_id': 'desktop.apps.googleusercontent.com', 'client_secret': 'example'}}))
            self.assertEqual(load_client(root, root)[0], 'desktop.apps.googleusercontent.com')

    def test_create_then_update_same_snapshot_and_publish_manifest_last(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'Data'
            data.mkdir()
            SongLibrary(data / 'songs.sqlite3')
            write_json(data / 'settings.json', {})
            write_json(data / 'queue.json', [])
            songs = root / 'Songs'
            songs.mkdir()
            (songs / 'one.mp3').write_bytes(b'one')
            drive = FakeDrive()
            first = sync_library(drive, data, 'user@example.com', [songs], None, 'new')
            self.assertEqual(drive.items[first['root_id']]['name'], ROOT_NAME)
            self.assertEqual(drive.uploaded[-1], 'web-manifest.json')
            info = drive.inspect('user@example.com')
            self.assertEqual(info['latest']['missing'], [])
            drive.uploaded.clear()
            second = sync_library(drive, data, 'user@example.com', [songs], None,
                                  'update', info['latest'])
            self.assertEqual(first['snapshot_id'], second['snapshot_id'])
            self.assertNotIn('one.mp3', drive.uploaded)
            self.assertEqual(drive.uploaded[-1], 'web-manifest.json')

    def test_incomplete_database_is_reported(self):
        drive = FakeDrive()
        root = drive.folder('root', ROOT_NAME)
        users = drive.folder(root['id'], 'users')
        account = drive.folder(users['id'], 'user@example.com')
        snapshot = drive.folder(account['id'], '20261107T000000Z')
        drive.folder(snapshot['id'], 'database')
        missing = drive.inspect('user@example.com')['latest']['missing']
        self.assertIn('database/songs.sqlite3', missing)
        self.assertIn('Songs', missing)


if __name__ == '__main__':
    unittest.main()
