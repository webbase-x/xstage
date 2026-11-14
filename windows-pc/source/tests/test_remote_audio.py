import base64
import threading
import time
import unittest
from karaoke.remote_audio import RemoteAudio


class AudioTests(unittest.TestCase):
    def test_disabled_never_captures_and_revokes_buffer(self):
        published=threading.Event()
        def capture(stop,publish):
            publish(b'\0\0\1\0');published.set();stop.wait(2)
        audio=RemoteAudio(capture)
        with self.assertRaises(PermissionError):audio.read()
        self.assertIsNone(audio.thread)
        audio.configure(True);audio.read();self.assertTrue(published.wait(1))
        packet=audio.read()
        self.assertEqual(base64.b64decode(packet['frames'][0]['pcm']),b'\0\0\1\0')
        sequence=packet['frames'][0]['seq']
        self.assertEqual(audio.read(sequence)['frames'],[])
        generation=audio.generation
        audio.close();audio._publish(generation,b'old')
        self.assertEqual(list(audio.frames),[])
        with self.assertRaises(PermissionError):audio.read()
        audio.thread.join(1)

    def test_bounded_ring_and_stale_frames(self):
        audio=RemoteAudio();audio.configure(True);audio.last_reader=time.monotonic()
        for _ in range(40):audio._publish(audio.generation,b'pcm')
        self.assertEqual(len(audio.frames),5)
        audio.last_reader=0;audio._publish(audio.generation,b'pcm')
        self.assertEqual(len(audio.frames),0);self.assertTrue(audio.stop_event.is_set())

    def test_capture_failure_is_visible_and_not_retried_every_poll(self):
        calls=[]
        def capture(stop,publish):calls.append(1);raise OSError('device missing')
        audio=RemoteAudio(capture);audio.configure(True);audio.read();audio.thread.join(1)
        self.assertEqual(audio.read()['error'],'device missing');self.assertEqual(len(calls),1)
        audio.close()

    def test_endpoint_requires_session_and_host_permission(self):
        from test_remote_mobile import RemoteMobileTests
        case=RemoteMobileTests();case.setUp()
        try:
            self.assertEqual(case.call('/api/audio')[0],401)
            token=case.login()
            self.assertEqual(case.call('/api/audio',token=token)[0],403)
            self.assertFalse(case.remote.policy['audio'])
            case.remote.audio.capture=lambda stop,publish:stop.wait(2)
            case.remote.configure(audio=True)
            self.assertEqual(case.call('/api/audio',token=token)[0],200)
            case.remote.configure(audio=False)
            self.assertEqual(case.call('/api/audio',token=token)[0],403)
            # A guest cannot grant itself audio through a command.
            self.assertEqual(case.call('/api/command',{'action':'audio','value':True},token)[0],403)
        finally:case.tearDown()


if __name__=='__main__':unittest.main()
