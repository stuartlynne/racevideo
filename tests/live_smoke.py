"""Optional physical-camera integration test; run under xvfb-run.

Uses its own temporary store. Requires /dev/video0 to be available.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk

from PIL import Image
import io

from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    with tempfile.TemporaryDirectory() as temp:
        motion = "--motion" in sys.argv
        path = Path(temp) / "live.sqlite3"
        connection = storage.connect(path)
        storage.initialize(connection)
        connection.close()
        recorder = subprocess.Popen([sys.executable, "-m", "racevideo", "record",
                                     "--db", str(path), "--trigger", "motion" if motion else "timer",
                                     "--interval", "3", "--run-seconds", "30"])
        root = tk.Tk()
        app = ReviewWindow(root, path)

        def pump(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                root.update()
                time.sleep(0.01)

        try:
            pump(3 if motion else 7)
            if motion:
                assert app.last_status["trigger"] == "motion"
                x0, y0, x1, y1 = app.roi_points()
                x, y = round((x0 + x1) / 2), round((y0 + y1) / 2)
                app.viewer.event_generate("<ButtonPress-1>", x=x, y=y)
                app.viewer.event_generate("<B1-Motion>", x=x + 30, y=y)
                app.viewer.event_generate("<ButtonRelease-1>", x=x + 30, y=y)
                pump(0.8)
                assert tuple(app.last_status["roi"]) == app.roi
                for _ in range(2):
                    app.send("capture")
                    pump(0.6)
            deadline=time.monotonic()+3
            while len(app.clips)<2 and time.monotonic()<deadline:pump(.1)
            assert len(app.clips) >= 2, len(app.clips)
            assert app.last_status["state"] == "recording"
            frames_before = app.last_status["frames"]
            app.select(app.clips[0]["id"])
            pump(0.3)
            selected = app.selected
            count_before = len(app.clips)
            if motion:
                app.send("capture")
            pump(3.4)
            deadline=time.monotonic()+2
            while len(app.clips)<=count_before and time.monotonic()<deadline:pump(.1)
            assert app.mode == "replay" and app.selected == selected
            assert len(app.clips) > count_before
            assert app.last_status["frames"] > frames_before
            # Save recent buffer on demand, in addition to the timer.
            app.send("capture")
            pump(0.7)
            deadline=time.monotonic()+2
            while app.clips[-1]['reason']!='manual' and time.monotonic()<deadline:pump(.1)
            assert app.clips[-1]["reason"] == "manual"
            # Add enough thumbnails to verify horizontal dragging and page keys.
            for _ in range(5):
                app.send("capture")
                pump(0.4)
            assert len(app.clips) >= 8
            app.strip.xview_moveto(1)
            before_drag = app.strip.xview()[0]
            app.strip.event_generate("<ButtonPress-1>", x=100, y=50)
            app.strip.event_generate("<B1-Motion>", x=450, y=50)
            app.strip.event_generate("<ButtonRelease-1>", x=450, y=50)
            assert app.strip.xview()[0] < before_drag - 0.1, app.strip.xview()
            app.strip.focus_force()
            pump(.05)  # Let the window server apply focus before synthetic keys.
            newest_at_keypress = app.clips[-1]['id']
            app.strip.event_generate("<End>")
            pump(0.3)
            # A concurrently saved clip may arrive after End selected its target.
            assert app.selected == newest_at_keypress, (app.selected,newest_at_keypress)
            app.strip.event_generate("<Prior>")
            pump(0.3)
            assert app.selected != newest_at_keypress
            # A second recorder is refused before touching the camera.
            duplicate = subprocess.run([sys.executable, "-m", "racevideo", "record", "--db", str(path)])
            assert duplicate.returncode == 2
            # Closing the window must leave capture alive.
            app.close()
            assert recorder.poll() is None
            storage.command(path, "stop")
            assert recorder.wait(timeout=5) == 0
            read = storage.connect(path, readonly=True)
            assert storage.read_runtime(read)["state"] == "stopped"
            assert read.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            for row in read.execute("SELECT jpeg FROM frames"):
                with Image.open(io.BytesIO(row[0])) as image:
                    image.verify()
            print(f"Physical webcam passed ({'motion' if motion else 'timer'}): {len(app.clips)} clips, concurrent review, manual capture, "
                  "drag/page navigation, duplicate protection, GUI close independence, clean stop, all JPEGs valid")
            read.close()
        finally:
            if not app.closing:
                app.close()
            if recorder.poll() is None:
                recorder.terminate()
                recorder.wait(timeout=5)


if __name__ == "__main__":
    main()
