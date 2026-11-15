import unittest
from types import SimpleNamespace as NS
from karaoke.transition_report import record,snapshot
class TransitionReportTests(unittest.TestCase):
    def test_report_is_bounded_and_excludes_unrelated_settings(self):
        app=NS(settings={'secret':'not-for-export','medley':{'enabled':True}},engine=None,song_queue=NS(items=[]))
        for i in range(205):record(app,'started',song_id=i)
        result=snapshot(app)
        self.assertEqual(len(result['events']),200)
        self.assertEqual(result['events'][0]['song_id'],5)
        self.assertNotIn('secret',result)
        self.assertIn('not an acoustic',result['timing_note'])
