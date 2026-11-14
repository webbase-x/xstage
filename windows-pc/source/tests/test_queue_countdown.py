import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from karaoke.queue_countdown import FirstQueueCountdown, tick_countdown, cancel_countdown


class QueueCountdownTests(unittest.TestCase):
    def test_five_seconds_exactly_once(self):
        timer=FirstQueueCountdown();item=object()
        self.assertEqual(timer.update(item,False,10),(5,False))
        self.assertEqual(timer.update(item,False,11),(4,False))
        self.assertEqual(timer.update(item,False,14.9),(1,False))
        self.assertEqual(timer.update(item,False,15),(0,True))
        self.assertEqual(timer.update(item,False,20),(0,False))

    def test_cancel_and_empty_reset(self):
        timer=FirstQueueCountdown();item=object()
        timer.update(item,False,0);timer.cancel(item)
        self.assertEqual(timer.update(item,False,6),(0,False))
        timer.update(None,False,7)
        self.assertEqual(timer.update(item,False,8),(5,False))

    def test_changed_first_occurrence_restarts_countdown(self):
        timer=FirstQueueCountdown();one=object();two=object()
        timer.update(one,False,0)
        self.assertEqual(timer.update(two,False,4),(5,False))
        self.assertEqual(timer.update(two,False,5),(4,False))

    def test_playing_or_paused_never_auto_starts(self):
        timer=FirstQueueCountdown();item=object()
        timer.update(item,False,0)
        self.assertEqual(timer.update(item,True,6),(0,False))
        self.assertEqual(timer.update(item,True,20),(0,False))

    def test_tick_integration_and_stop(self):
        app=SimpleNamespace(song_queue=SimpleNamespace(items=[object()]),
            engine=None,current_song=None,status_var=Mock(),next_song=Mock())
        with patch('karaoke.queue_countdown.time.monotonic',side_effect=[0,4,5,6]):
            tick_countdown(app);self.assertEqual(app._queue_countdown_seconds,5)
            tick_countdown(app);app.next_song.assert_not_called()
            tick_countdown(app);tick_countdown(app);app.next_song.assert_called_once()
        app.song_queue.items=[object()]
        with patch('karaoke.queue_countdown.time.monotonic',side_effect=[10,20]):
            tick_countdown(app);cancel_countdown(app);tick_countdown(app)
        self.assertEqual(app._queue_countdown_seconds,0)
        app.next_song.assert_called_once()


if __name__=='__main__':unittest.main()
