import copy
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from racevideo import storage, passings, bib_review
from racevideo.crossmgr_client import Configuration, discover


def payload():
    categories=[dict(name='Wave',wave=True,start_offset='00:00:00'),dict(name='Women',wave=False,start_offset='0:00')]
    def rider(bib,times,calculated,flags=None,category='Wave'):
        return dict(bib=bib,category=category,first_name='Rider',last_name=str(bib),team='',status='Finisher',
            passings=[dict(seconds=t,provenance='Unattributed',metadata=None) for t in times],
            calculated_times=calculated,calculated_interpolation=flags or [False]*len(calculated),start_offset='0:00')
    rows=[rider(24,[2,60,120],[0,60,120]),rider(7,[3,65,130],[0,65,130]),
          # Duplicate component membership must not duplicate raw passings.
          rider(24,[2,60,120],[0,60,120],category='Women'),
          # Projected second lap is not an observed leader crossing.
          rider(4,[70],[0,70,115],[False,False,True])]
    inputs=[dict(path='/events/20261108-Test/test.cmn',sha256='abc')]
    return dict(inspect=dict(inputs=inputs,race=dict(categories=categories,finish_time='2026-11-08T10:03:00+00:00')),
        review=dict(inputs=inputs,race=dict(name='Test',start_time='2026-11-08T10:00:00+00:00',
            is_time_trial=False,rows=rows,tag_assignments={'ABCD':[dict(bib=24,field='Tag')]})))


class PassingsTests(unittest.TestCase):
    def index_bikes(self,clip,count=1):
        from racevideo import bike_index
        passages=[]
        for i in range(count):
            box=[i*30,0,i*30+28,32]
            passages.append(dict(key='detected:'+str(i+1),first_ordinal=0,last_ordinal=3,ordinal=i+1,
                box=box,points=[dict(ordinal=j,box=box) for j in range(4)],numbers=[],confirmed=False,uncertain=True))
        return bike_index.save(self.c,clip,dict(source='detector',policy='recall-v2',passages=passages))

    def test_unread_bikes_each_have_a_reviewable_entry_and_do_not_imply_dnf(self):
        clip=self.clip(80);self.index_bikes(clip,2)
        model=passings.compare_event(self.c,self.event)
        unknown=[c for c in model['cells'] if c['bib']=='?']
        self.assertEqual(len(unknown),2)
        self.assertLess(unknown[0]['at_ns'],unknown[1]['at_ns'])
        self.assertNotEqual(unknown[0]['captures'][0]['key'],unknown[1]['captures'][0]['key'])
        self.assertEqual(model['bike_coverage'],dict(indexed=1,total=1,unindexed=0))
        self.assertEqual(len([c for c in model['cells'] if c['state']=='missing']),7)
        self.assertEqual(len([c for c in passings.compare_event(self.c,self.event,category='Women')['cells'] if c['bib']=='?']),2)

    def test_ignore_one_detected_bike_is_audited_hidden_and_individually_restorable(self):
        from racevideo import passing_review
        clip=self.clip(80);self.index_bikes(clip,2)
        model=passings.compare_event(self.c,self.event)
        row=next(c for c in model['cells'] if c['bib']=='?')['captures'][0]
        passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=row['ordinal'],action='ignored',visual_key=row['key'])
        model=passings.compare_event(self.c,self.event)
        self.assertEqual(len([c for c in model['cells'] if c['bib']=='?']),1)
        self.assertEqual(len(model['ignored_cells']),1)
        passing_review.undo(self.path,model['ignored_cells'][0]['restore_history_id'])
        self.assertEqual(len([c for c in passings.compare_event(self.c,self.event)['cells'] if c['bib']=='?']),2)
        self.assertEqual(self.c.execute('SELECT count(*) FROM frames WHERE clip_id=?',(clip,)).fetchone()[0],4)

    def test_confirm_unidentified_bike_does_not_leave_duplicate_unknown(self):
        from racevideo import passing_review
        clip=self.clip(60);self.index_bikes(clip)
        row=next(c for c in passings.compare_event(self.c,self.event)['cells'] if c['bib']=='?')['captures'][0]
        passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=row['ordinal'],action='confirmed',number='24',visual_key=row['key'])
        cells=passings.compare_event(self.c,self.event)['cells']
        self.assertFalse(any(c['bib']=='?' for c in cells))
        self.assertTrue(any(c['bib']=='24' and c['confirmed'] and c['state']=='matched' for c in cells))

    def test_one_bike_with_two_in_roster_ocr_guesses_is_not_two_riders(self):
        clip=self.clip(60,'24');self.index_bikes(clip)
        original=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone());original.pop('id');original['number']='7'
        with self.c:self.c.execute('INSERT INTO ocr_observations('+','.join(original)+') VALUES('+','.join('?' for _ in original)+')',tuple(original.values()))
        cells=passings.compare_event(self.c,self.event,tolerance=10)['cells']
        self.assertEqual(len([c for c in cells if c['state']=='matched']),1)
        self.assertFalse(any(c['origin']=='Visual only' for c in cells))

    def test_expected_missing_rider_offers_individual_nearby_bike_candidates(self):
        from racevideo import passing_review
        clip=self.clip(65);self.index_bikes(clip,2)
        cells=passings.compare_event(self.c,self.event)['cells']
        expected=next(c for c in cells if c['bib']=='7' and c.get('seconds')==65)
        self.assertEqual(len(expected['captures']),2)
        row=expected['captures'][0]
        self.assertTrue(row['candidate']);self.assertIsNotNone(row['ordinal'])
        passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=row['ordinal'],action='confirmed',number='7',visual_key=row['key'])
        cells=passings.compare_event(self.c,self.event)['cells']
        self.assertTrue(next(c for c in cells if c['bib']=='7' and c.get('seconds')==65)['confirmed'])
        self.assertEqual(len([c for c in cells if c['bib']=='?']),1)

    def test_ignore_does_not_hide_other_bike_sharing_an_ocr_encounter_label(self):
        import json
        from racevideo import passing_review
        clip=self.clip(80,'999');self.index_bikes(clip,2)
        original=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone())
        with self.c:
            self.c.execute('UPDATE ocr_observations SET quad=? WHERE id=?',(json.dumps([[5,8],[15,8],[15,15],[5,15]]),original['id']))
            original.pop('id');original.update(number='888',quad=json.dumps([[35,8],[45,8],[45,15],[35,15]]))
            self.c.execute('INSERT INTO ocr_observations('+','.join(original)+') VALUES('+','.join('?' for _ in original)+')',tuple(original.values()))
        cells=passings.compare_event(self.c,self.event)['cells']
        first=next(c for c in cells if c['bib']=='999')['captures'][0]
        passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=first['ordinal'],action='ignored',visual_key=first['key'])
        cells=passings.compare_event(self.c,self.event)['cells']
        self.assertFalse(any(c['bib']=='999' for c in cells))
        self.assertTrue(any(c['bib']=='888' for c in cells))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'store.sqlite3'
        self.c=storage.connect(self.path);storage.initialize(self.c)
        self.config=Configuration(url='http://test/mcp',timezone='UTC')
        self.source=payload();self.event=self.cache(self.source)
        self.start=passings.absolute_ns('2026-11-08T10:00:00+00:00',timezone.utc)
        out=io.BytesIO();Image.new('RGB',(64,32),'white').save(out,'JPEG');self.jpeg=out.getvalue()
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def cache(self,data):return passings.cache_event(self.c,self.config,'/events/20261108-Test/test.cmn','2026-11-08',data)
    def clip(self,seconds,number=None,encounter='track:1'):
        stamp=self.start+round(seconds*1e9)
        frames=[storage.Frame(stamp+i*100_000_000,stamp+i*100_000_000,i,'1/10',self.jpeg) for i in range(4)]
        clip=storage.save_clip(self.c,frames,stamp,'test',64,32,'test')
        if number:
            run=storage.create_ocr_run(self.path,clip,{})
            with self.c:
                self.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (run,number,stamp,stamp+200_000_000,3,95,1,'[]',self.jpeg,'repeated',encounter))
                self.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
        return clip
    def test_sources_are_cached_idempotently_and_changed_inputs_preserve_history(self):
        self.cache(self.source)
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_sources').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_passings').fetchone()[0],7)
        changed=copy.deepcopy(self.source)
        changed['inspect']['inputs'][0]['sha256']='changed';self.cache(changed)
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_sources').fetchone()[0],2)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_leader_columns_exclude_start_reads_projection_and_category_duplicates(self):
        model=passings.compare_event(self.c,self.event)
        self.assertEqual([c['label'] for c in model['columns']],['Start / pre-lap','Lap 1','Lap 2'])
        self.assertEqual(model['columns'][2]['start_ns'],self.start+120*10**9)
        for col in (1,2):
            cells=[c for c in model['cells'] if c['column']==col]
            self.assertEqual(cells[0]['bib'],'24')
        self.assertEqual(len(model['cells']),7)
        filtered=passings.compare_event(self.c,self.event,category='Women')
        self.assertEqual({c['bib'] for c in filtered['cells']},{'24'})
        self.assertEqual(filtered['columns'],model['columns'])
    def test_matching_needs_bib_and_time_but_missing_rows_offer_unread_captures(self):
        self.clip(60,'24');unknown=self.clip(65)
        self.clip(100,'24');self.clip(75,'999')
        model=passings.compare_event(self.c,self.event,tolerance=1)
        match=next(c for c in model['cells'] if c['bib']=='24' and c.get('seconds')==60)
        self.assertEqual(match['state'],'matched');self.assertFalse(match['confirmed'])
        missing=next(c for c in model['cells'] if c['bib']=='7' and c.get('seconds')==65)
        self.assertEqual(missing['state'],'missing');self.assertEqual(missing['captures'][0]['clip_id'],unknown)
        self.assertTrue(any(c['bib']=='24' and c['state']=='video_only' for c in model['cells']))
        self.assertTrue(any(c['bib']=='999' and c['state']=='extra' for c in model['cells']))
    def test_manual_review_updates_cached_comparison_without_reimporting_crossmgr(self):
        clip=self.clip(60,'999')
        row=self.c.execute('SELECT id FROM ocr_observations').fetchone()
        bib_review.decide(self.path,clip,observation_id=row[0],decision='corrected',number='24')
        model=passings.compare_event(self.c,self.event)
        self.assertTrue(next(c for c in model['cells'] if c['state']=='matched')['confirmed'])
        self.assertFalse(any(c['bib']=='999' for c in model['cells']))
    def test_clock_offset_is_explicit_and_does_not_modify_source_time(self):
        self.clip(70,'24')
        before=[tuple(r) for r in self.c.execute('SELECT * FROM race_passings')]
        self.assertFalse(any(c['state']=='matched' for c in passings.compare_event(self.c,self.event,tolerance=.5)['cells']))
        model=passings.compare_event(self.c,self.event,tolerance=.5,offset=10)
        self.assertTrue(any(c['state']=='matched' and c['bib']=='24' for c in model['cells']))
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM race_passings')])
    def test_same_bib_in_another_event_has_separate_identity_and_passings(self):
        other=copy.deepcopy(self.source);other['review']['race']['name']='Another event'
        second=passings.cache_event(self.c,self.config,'/events/20261108-Test/other.cmn','2026-11-08',other)
        self.assertNotEqual(second,self.event)
        self.assertEqual(len(passings.list_events(self.c,'2026-11-08')),2)
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_participants WHERE bib="24"').fetchone()[0],2)
    def test_time_trial_and_inconsistent_snapshot_are_rejected(self):
        bad=copy.deepcopy(self.source);bad['review']['race']['is_time_trial']=True
        with self.assertRaisesRegex(ValueError,'Time-trial'):self.cache(bad)
        bad=copy.deepcopy(self.source);bad['review']['inputs']=[]
        with self.assertRaisesRegex(ValueError,'Inconsistent'):self.cache(bad)
    def test_discover_uses_date_directories_and_rejects_escaping_symlinks(self):
        root=Path(self.tmp.name)/'events';folder=root/'20261108-Test';folder.mkdir(parents=True)
        (folder/'race.cmn').write_bytes(b'not unpickled')
        (folder/'notes.txt').write_text('ignore')
        self.assertEqual(discover(root,'2026-11-08'),[str(folder/'race.cmn')])
        outside=Path(self.tmp.name)/'outside.cmn';outside.touch();(folder/'escape.cmn').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'symlink'):discover(root,'2026-11-08')
    def test_ambiguous_local_start_requires_explicit_offset(self):
        from zoneinfo import ZoneInfo
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            passings.absolute_ns('2026-11-01T01:30:00',ZoneInfo('America/New_York'))
    def test_short_bibs_are_exact_and_not_zero_padded(self):
        self.clip(60,'024')
        model=passings.compare_event(self.c,self.event)
        self.assertTrue(any(c['bib']=='024' and c['state']=='extra' for c in model['cells']))
        self.assertFalse(any(c['bib']=='24' and c['state']=='matched' for c in model['cells']))
    def test_alternative_strings_on_a_matched_track_are_not_additional_riders(self):
        clip=self.clip(60,'24')
        row=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone())
        row.pop('id');row['number']='42'
        with self.c:self.c.execute('INSERT INTO ocr_observations('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        cells=passings.compare_event(self.c,self.event)['cells']
        matched=next(c for c in cells if c['state']=='matched')
        self.assertEqual(matched['alternative_bibs'],['42']);self.assertTrue(matched['ambiguous'])
        self.assertFalse(any(c['state']=='extra' for c in cells))
    def test_unknown_alternatives_share_one_red_encounter(self):
        self.clip(80,'999')
        row=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone())
        row.pop('id');row['number']='888'
        with self.c:self.c.execute('INSERT INTO ocr_observations('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        extras=[c for c in passings.compare_event(self.c,self.event)['cells'] if c['state']=='extra']
        self.assertEqual(len(extras),1);self.assertEqual(extras[0]['alternative_bibs'],['888','999'])
    def test_workbook_tag_owner_without_any_model_read_is_still_an_event_entrant(self):
        data=copy.deepcopy(self.source)
        data['review']['race']['tag_assignments']['UNREAD']=[dict(bib=805,field='Tag')]
        data['inspect']['inputs'][0]['sha256']='new-roster';self.cache(data)
        self.clip(80,'805')
        cells=passings.compare_event(self.c,self.event)['cells']
        entrant=next(c for c in cells if c['bib']=='805')
        self.assertEqual(entrant['state'],'video_only')
        self.assertEqual(entrant['origin'],'Visual only')
        self.assertFalse(any(c['bib']=='805' and c['origin']=='CrossMgr' for c in cells))


if __name__=='__main__':unittest.main()
