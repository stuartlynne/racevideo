import io
from pathlib import Path
import tempfile
import time
import unittest
from PIL import Image
from racevideo import storage
from racevideo.gui import Reader


class ReaderBrowseTests(unittest.TestCase):
    def test_selected_bib_polling_does_not_reload_unchanged_thumbnails(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'review.sqlite3';c=storage.connect(path);storage.initialize(c)
            out=io.BytesIO();Image.new('RGB',(64,48),'white').save(out,'JPEG')
            ns=time.time_ns();frames=[storage.Frame(ns,ns,0,'1/30',out.getvalue())]
            clips=[storage.save_clip(c,frames,ns,'fixture',64,48,'fixture') for _ in range(2)]
            c.close();reader=Reader(path);reader.browse=(1,'All dates',(),False)
            reader.jobs.put(('ocr_select',clips[0]));events=[];reader.start()
            try:
                deadline=time.monotonic()+1.35
                while time.monotonic()<deadline:
                    while not reader.output.empty():events.append(reader.output.get())
                    time.sleep(.01)
                self.assertTrue(reader.is_alive())
                loaded=[clip['id'] for kind,value in events if kind=='clips' for generation,rows in [value] for clip in rows]
                self.assertEqual(loaded,clips,'Unchanged thumbnails must be emitted once while bib/status polling continues')
                self.assertEqual(sum(kind=='browse_reset' for kind,value in events),1)
                self.assertGreaterEqual(sum(kind=='ocr_status' for kind,value in events),3)
            finally:reader.stop.set();reader.join(timeout=2)


if __name__=='__main__':unittest.main()
