import copy,json,unittest
from unittest.mock import AsyncMock
from racevideo.crossmgr_client import Client,Configuration
from racevideo import storage,passings
import test_passings as fixtures


class LiveClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_gui_snapshot_is_read_paged_and_cached_without_writes(self):
        client=Client(Configuration());identity=dict(instance='one',race_path='/events/race.cmn',state='running')
        snap=dict(identity,path='/private/one/live.cmn',snapshot_sha256='abc')
        inputs=[dict(path=snap['path'],sha256='abc')]
        inspected=dict(inputs=inputs,race=dict(date='2026-11-13'))
        reviewed=dict(inputs=inputs,race=dict(total=501,rows=[dict(bib=i) for i in range(500)]))
        page=dict(inputs=inputs,race=dict(rows=[dict(bib=500)]))
        client.call=AsyncMock(side_effect=[identity,snap,inspected,reviewed,page,identity,dict(snap,path='/private/two/live.cmn')])
        result=await client.live_session(object())
        self.assertEqual(len(result['payload']['review']['race']['rows']),501)
        self.assertEqual(result['path'],identity['race_path'])
        self.assertEqual(result['payload']['live']['snapshot_path'],snap['path'])
        self.assertIs(await client.live_session(object()),result)
        names=[a.args[1] for a in client.call.call_args_list]
        self.assertEqual(names,['bridge.identity','bridge.snapshot','race.inspect','race.review','race.review','bridge.identity','bridge.snapshot'])
        self.assertTrue(client.call.call_args_list[2].args[2]['trusted_pickle'])
    async def test_finished_gui_is_cached_until_explicit_refresh(self):
        client=Client(Configuration());identity=dict(instance='one',race_path='/events/race.cmn',state='finished')
        snap=dict(identity,path='/private/live.cmn',snapshot_sha256='abc')
        inputs=[dict(path=snap['path'],sha256='abc')]
        inspected=dict(inputs=inputs,race=dict(date='2026-11-13'))
        reviewed=dict(inputs=inputs,race=dict(total=0,rows=[]))
        client.call=AsyncMock(side_effect=[identity,snap,inspected,reviewed,identity])
        first=await client.live_session(object());self.assertIs(await client.live_session(object()),first)
        self.assertEqual(client.call.await_count,5) # No repeated private snapshot files after finish.
        client.live_signature=None
        client.call=AsyncMock(side_effect=[identity,snap,inspected,reviewed])
        await client.live_session(object());self.assertEqual(client.call.await_count,4)
    async def test_missing_gui_is_not_replaced_by_an_archive(self):
        identity=dict(instance='x',state='none',race_path=None)
        client=Client(Configuration());client.call=AsyncMock(return_value=identity)
        with self.assertRaises(ValueError):await client.live_session(object())
        self.assertEqual(client.call.await_count,1)
    async def test_unstarted_gui_returns_roster_categories_without_fake_timing(self):
        identity=dict(instance='x',state='unstarted',race_path='/events/race.cmn')
        snapshot=dict(identity,path='/private/live.cmn',snapshot_sha256='abc')
        roster=dict(race=dict(date='2026-11-15',name='Test',total=2,categories=[dict(name='Women'),dict(name='Men')],rows=[]))
        client=Client(Configuration());client.call=AsyncMock(side_effect=[identity,snapshot,roster])
        result=await client.live_session(object())
        self.assertEqual(result['payload']['live']['state'],'unstarted')
        self.assertEqual([c['name'] for c in result['payload']['roster']['race']['categories']],['Women','Men'])
        self.assertNotIn('review',result['payload'])
        self.assertEqual([a.args[1] for a in client.call.call_args_list],['bridge.identity','bridge.snapshot','race.roster'])
    async def test_race_switch_and_input_mismatch_are_refused(self):
        identity=dict(instance='one',race_path='/events/a.cmn',state='running')
        client=Client(Configuration());client.call=AsyncMock(side_effect=[identity,dict(identity,path='/private/snapshot.cmn',race_path='/events/b.cmn',snapshot_sha256='a')])
        with self.assertRaisesRegex(ValueError,'changed race'):await client.live_session(object())
        snap=dict(identity,path='/private/snapshot.cmn',snapshot_sha256='a')
        client.call=AsyncMock(side_effect=[identity,snap,dict(inputs=['a']),dict(inputs=['b'])])
        with self.assertRaisesRegex(ValueError,'changed'):await client.live_session(object())


class LiveCacheTests(unittest.TestCase):
    def test_repeated_snapshot_paths_share_event_and_source_identity(self):
        f=fixtures.PassingsTests();f.setUp()
        try:
            for name in ['one','two']:
                data=copy.deepcopy(f.source);snapshot=f'/private/{name}/live.cmn'
                data['inspect']['inputs'][0]['path']=snapshot
                data['review']['inputs'][0]['path']=snapshot
                data['live']=dict(instance='x',race_path='/events/20261108-Test/test.cmn',snapshot_path=snapshot)
                event=f.cache(data)
                self.assertEqual(event,f.event)
            self.assertEqual(f.c.execute('SELECT count(*) FROM race_sources').fetchone()[0],1)
            self.assertEqual(f.c.execute('SELECT count(*) FROM race_events').fetchone()[0],1)
        finally:f.tearDown()
