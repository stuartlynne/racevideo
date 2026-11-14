import unittest
from racevideo.passings_layout import layout


def cell(key, column, stamp, visual=False, **values):
    return dict(cell_key=key, column=column, at_ns=stamp, origin='Visual only' if visual else 'CrossMgr', rider_lap=None if visual else column, **values)


class LayoutTests(unittest.TestCase):
    def test_visual_entries_do_not_shift_crossmgr_positions(self):
        cells=[cell('a',1,10),cell('b',1,20),cell('c',2,10),cell('d',2,20),cell('?',1,15,True),cell('??',1,16,True),cell('other',2,15,True)]
        rows=layout(cells,[1,2])
        self.assertEqual([r['position'] for r in rows],[1,None,None,2])
        self.assertEqual(rows[3]['cells'][1]['cell_key'],'b')
        self.assertEqual(rows[3]['cells'][2]['cell_key'],'d')
        self.assertNotIn(2,rows[2]['cells'])
        self.assertEqual(len([c for r in rows for c in r['cells'].values()]),len(cells))
    def test_source_order_wins_over_video_repositioning_and_raw_reads_are_unranked(self):
        a=cell('a',1,10,sort_ns=30);b=cell('b',1,20,sort_ns=5)
        raw=cell('raw',1,15);raw['rider_lap']=None
        rows=layout([b,raw,a],[1])
        self.assertEqual([r['position'] for r in rows],[1,None,2])
        self.assertEqual([r['cells'][1]['cell_key'] for r in rows],['a','raw','b'])
    def test_only_visual_entries_and_candidates_after_shorter_column(self):
        cells=[cell('?',1,5,True),cell('a',2,10),cell('b',2,20),cell('tail',1,25,True)]
        rows=layout(cells,[1,2])
        keys=[c['cell_key'] for r in rows for c in r['cells'].values()]
        self.assertCountEqual(keys,['?','a','b','tail'])
        self.assertEqual([r['position'] for r in layout(cells[:1],[1])],[None])
