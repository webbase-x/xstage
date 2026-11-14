import unittest
from karaoke.remote_paging import partition_sections

class RemotePagingTests(unittest.TestCase):
    def test_whole_sections_move_to_next_page(self):
        self.assertEqual(partition_sections([60,80,130,50],180),[[0,1],[2,3]])
    def test_exact_fit_and_resize_keep_every_section_once(self):
        self.assertEqual(partition_sections([60,80],140),[[0,1]])
        for height in [60,140,320,600]:
            groups=partition_sections([60,80,130,50],height)
            self.assertEqual([i for group in groups for i in group],list(range(4)))
    def test_large_section_has_its_own_page(self):
        self.assertEqual(partition_sections([60,300,50],180),[[0],[1],[2]])
        self.assertEqual(partition_sections([],180),[[]])
