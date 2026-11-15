import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import date,timedelta

from PIL import Image, ImageChops, ImageDraw, ImageStat
from racevideo import storage
from racevideo.review import View,adjust_display,render,validate_display_adjustments


def jpeg():
    image=Image.new('RGB',(640,360),'#224466')
    image.putpixel((320,180),(255,0,0))
    out=io.BytesIO();image.save(out,'JPEG');return out.getvalue()


class ReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'review.sqlite3'
        self.c=storage.connect(self.path);storage.initialize(self.c)
        self.today=date.today().isoformat();self.yesterday=(date.today()-timedelta(days=1)).isoformat()
    def tearDown(self):self.c.close();self.temp.cleanup()
    def clip(self,day=None,offset=0):
        ns=storage.local_day_bounds(day or self.today)[0]+(3600+offset)*1_000_000_000
        frame=storage.Frame(ns,ns,123,'1/30',jpeg())
        return storage.save_clip(self.c,[frame],ns,'motion',640,360,'fixture')
    def ocr(self,clip,number,state='complete'):
        run=storage.create_ocr_run(self.path,clip,{})
        ns=self.c.execute('SELECT started_ns FROM clips WHERE id=?',(clip,)).fetchone()[0]
        with self.c:
            self.c.execute('UPDATE ocr_runs SET state=? WHERE id=?',(state,run))
            self.c.execute('INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (run,number,ns,ns,2,80,0,'[]',jpeg(),'repeated'))
        return run
    def test_day_boundaries_default_and_latest_completed_ocr_or_filter(self):
        old=self.clip(self.yesterday);a=self.clip();b=self.clip(offset=30);c=self.clip(offset=60)
        self.assertTrue(all(row['ocr_state'] is None for row in storage.browse_clips(self.c,self.today)))
        self.ocr(a,'333');self.ocr(a,'444');self.ocr(a,'333','running')
        self.ocr(b,'333');self.ocr(c,'042')
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,self.today,('333','042'))],[b,c])
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,self.yesterday)],[old])
        self.assertEqual(storage.recording_dates(self.c),[self.today,self.yesterday])
        self.assertEqual([r['number'] for r in storage.bib_passages(self.c,self.today,('333',))],['333'])
        self.assertEqual(storage.bib_numbers('333, 042;333'),('333','042'))
        with self.assertRaises(ValueError):storage.bib_numbers('333 OR 1=1')
    def test_cleanup_rechecks_star_and_busy_and_keeps_arrivals_after_preview(self):
        a,b,star,busy=[self.clip(offset=i) for i in range(4)]
        storage.set_star(self.path,star,True);self.ocr(busy,'333','running');self.ocr(a,'042')
        preview=storage.cleanup_preview(self.c,self.today)
        self.assertEqual(preview['ids'],[a,b]);self.assertEqual(preview['starred'],1);self.assertEqual(preview['busy'],1)
        storage.set_star(self.path,b,True);arrival=self.clip(offset=10)
        result=storage.delete_previewed(self.path,preview)
        self.assertEqual(result,dict(deleted=[a],skipped=1))
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,self.today)],[b,star,busy,arrival])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM ocr_observations WHERE number=?',('042',)).fetchone()[0],0)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_cleanup_ids_are_never_reused_and_other_days_untouched(self):
        old=self.clip(self.yesterday);latest=self.clip()
        storage.delete_previewed(self.path,storage.cleanup_preview(self.c,self.today))
        self.assertGreater(self.clip(),latest)
        self.assertEqual(storage.read_frame(self.c,old,0),jpeg())
        storage.initialize(self.c)
        self.assertEqual(self.c.execute('PRAGMA user_version').fetchone()[0],11)
    def test_cleanup_refuses_active_older_recorder(self):
        clip=self.clip();preview=storage.cleanup_preview(self.c,self.today)
        with patch('racevideo.service.recorder_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Restart'):
                storage.delete_previewed(self.path,preview)
        self.assertEqual(len(storage.browse_clips(self.c,self.today)),1)

    def add_hit(self,run,number):
        with self.c:
            self.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status)
              SELECT ?,?,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status FROM ocr_observations WHERE run_id=? LIMIT 1''',(run,number,run))

    def pairs(self):
        return [tuple(r) for r in self.c.execute('SELECT tag_id,video_set_id FROM video_tag_matches ORDER BY video_set_id,tag_id')]

    def test_many_riders_per_video_and_many_videos_per_rider_with_unique_results(self):
        a=self.clip();b=self.clip(offset=30);old=self.clip(self.yesterday)
        run=self.ocr(a,'123');self.add_hit(run,'456');self.add_hit(run,'123')
        self.ocr(b,'456');self.ocr(old,'123')
        self.assertEqual(self.pairs(),[('123',a),('456',a),('456',b),('123',old)])
        match=self.c.execute("SELECT * FROM video_tag_matches WHERE tag_id='123' AND video_set_id=?",(a,)).fetchone()
        self.assertEqual(match['encounter_count'],2)
        self.assertEqual(match['ocr_run_id'],run)
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,self.today,('123','456'))],[a,b])
        start,end=storage.local_day_bounds(self.today)
        ids=[r[0] for r in self.c.execute('''SELECT c.id FROM clips c WHERE c.started_ns>=? AND c.started_ns<?
          AND EXISTS(SELECT 1 FROM video_tag_matches m WHERE m.video_set_id=c.id AND m.tag_id IN ('123','456'))
          ORDER BY c.started_ns,c.id''',(start,end))]
        self.assertEqual(ids,[a,b])
        today_pairs=[tuple(r) for r in self.c.execute("SELECT tag_id,video_set_id FROM today_video_tag_matches ORDER BY video_set_id,tag_id")]
        self.assertEqual(today_pairs,[('123',a),('456',a),('456',b)])
        plan=' '.join(r[3] for r in self.c.execute("EXPLAIN QUERY PLAN SELECT video_set_id FROM video_tag_matches WHERE tag_id='123'"))
        self.assertIn('INDEX',plan)

    def test_completed_reruns_publish_matches_atomically_and_failed_runs_preserve_history(self):
        clip=self.clip();original=self.ocr(clip,'123');self.add_hit(original,'456')
        rerun=self.ocr(clip,'042','running')
        self.assertEqual(self.pairs(),[('123',clip),('456',clip)])
        reader=storage.connect(self.path,readonly=True)
        try:
            self.c.execute('BEGIN')
            self.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(rerun,))
            self.assertEqual(self.pairs(),[('042',clip)])
            self.assertEqual([tuple(r) for r in reader.execute('SELECT tag_id,video_set_id FROM video_tag_matches ORDER BY tag_id')],[('123',clip),('456',clip)])
            self.c.commit()
            self.assertEqual([tuple(r) for r in reader.execute('SELECT tag_id,video_set_id FROM video_tag_matches')],[('042',clip)])
        finally:reader.close()
        failed=self.ocr(clip,'999','error')
        self.assertEqual(self.pairs(),[('042',clip)])
        empty=storage.create_ocr_run(self.path,clip,{})
        with self.c:self.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(empty,))
        self.assertEqual(self.pairs(),[])
        with self.c:self.c.execute('DELETE FROM ocr_runs WHERE id=?',(empty,))
        self.assertEqual(self.pairs(),[('042',clip)])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM ocr_observations WHERE run_id=?',(original,)).fetchone()[0],2)

    def test_observation_edits_deletes_and_cleanup_keep_lookup_consistent(self):
        clip=self.clip();run=self.ocr(clip,'123');self.add_hit(run,'456')
        with self.c:self.c.execute("UPDATE ocr_observations SET number='042' WHERE run_id=? AND number='123'",(run,))
        self.assertEqual(self.pairs(),[('042',clip),('456',clip)])
        with self.c:self.c.execute("DELETE FROM ocr_observations WHERE run_id=? AND number='456'",(run,))
        self.assertEqual(self.pairs(),[('042',clip)])
        storage.delete_previewed(self.path,storage.cleanup_preview(self.c,self.today))
        self.assertEqual(self.pairs(),[])
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_v7_migration_backfills_existing_completed_evidence_without_changing_video(self):
        clip=self.clip();run=self.ocr(clip,'123');self.add_hit(run,'456')
        original=storage.read_frame(self.c,clip,0)
        names=[r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%match%'")]
        for name in names:self.c.execute(f'DROP TRIGGER {name}')
        self.c.execute('DROP TABLE video_tag_matches');self.c.execute('PRAGMA user_version=7');self.c.commit()
        storage.initialize(self.c)
        self.assertEqual(self.pairs(),[('123',clip),('456',clip)])
        self.assertEqual(storage.read_frame(self.c,clip,0),original)
        storage.initialize(self.c)
        self.assertEqual(len(self.pairs()),2)
        self.assertEqual(self.c.execute('PRAGMA user_version').fetchone()[0],11)

    def test_ocr_jobs_freeze_saved_test_area_and_orientation(self):
        clip=self.clip()
        area=[.34,.35,.60,.56]
        storage.write_setting(self.path,'ocr_area',area)
        storage.write_setting(self.path,'ocr_rotations',[0])
        first=storage.create_ocr_run(self.path,clip,{'fps':8})
        storage.write_setting(self.path,'ocr_area',[0,0,1,1])
        storage.write_setting(self.path,'ocr_rotations',[0,180])
        second=storage.create_ocr_run(self.path,clip,{'fps':8})
        a=json.loads(self.c.execute('SELECT parameters FROM ocr_runs WHERE id=?',(first,)).fetchone()[0])
        b=json.loads(self.c.execute('SELECT parameters FROM ocr_runs WHERE id=?',(second,)).fetchone()[0])
        self.assertEqual((a['roi'],a['rotations']),(area,[0]))
        self.assertEqual((b['roi'],b['rotations']),([0,0,1,1],[0,180]))
        with self.assertRaises(ValueError):storage.create_ocr_run(self.path,clip,{'rotations':[]})

    @unittest.skipUnless(hasattr(time,'tzset'),'Requires local timezone support')
    def test_calendar_dates_follow_dst(self):
        old=os.environ.get('TZ')
        try:
            os.environ['TZ']='America/Vancouver';time.tzset()
            a,b=storage.local_day_bounds('2025-03-09');self.assertEqual((b-a)/1e9,23*3600)
            a,b=storage.local_day_bounds('2025-11-02');self.assertEqual((b-a)/1e9,25*3600)
        finally:
            if old is None:os.environ.pop('TZ',None)
            else:os.environ['TZ']=old
            time.tzset()


class ViewTests(unittest.TestCase):
    def test_zoom_anchors_pointer_pan_clamps_and_render_is_canvas_sized(self):
        view=View();source=(640,360);canvas=(500,400);point=(300,220)
        left,top,w,h=view.bounds(source,canvas);before=((point[0]-left)/w,(point[1]-top)/h)
        view.zoom_at(2,point,source,canvas)
        left,top,w,h=view.bounds(source,canvas)
        self.assertAlmostEqual((point[0]-left)/w,before[0]);self.assertAlmostEqual((point[1]-top)/h,before[1])
        picture,bounds,position=render(jpeg(),canvas,vars(view))
        self.assertLessEqual(picture.width,canvas[0]);self.assertLessEqual(picture.height,canvas[1])
        view.pan(100000,-100000,source,canvas)
        left,top,w,h=view.bounds(source,canvas)
        self.assertGreaterEqual(left+w,canvas[0]);self.assertLessEqual(left,0)
        self.assertGreaterEqual(top+h,canvas[1]);self.assertLessEqual(top,0)
        view.zoom_at(.0001,point,source,canvas)
        self.assertEqual(view,View())

    def test_display_adjustments_change_bounded_preview_only(self):
        normal,_,_=render(jpeg(),(320,180),vars(View()))
        bright,_,_=render(jpeg(),(320,180),vars(View()),dict(brightness=1.8,contrast=1,sharpness=1))
        self.assertGreater(sum(ImageStat.Stat(bright).mean),sum(ImageStat.Stat(normal).mean))
        edge=Image.new('RGB',(80,40),'#777777');ImageDraw.Draw(edge).rectangle((30,0,50,40),fill='#999999')
        sharpened=adjust_display(edge,dict(brightness=1,contrast=1,sharpness=4))
        self.assertIsNotNone(ImageChops.difference(edge,sharpened).getbbox())
        with self.assertRaises(ValueError):validate_display_adjustments(dict(brightness=float('nan')))
        with self.assertRaises(ValueError):validate_display_adjustments(dict(sharpness=5))


if __name__=='__main__':unittest.main()
