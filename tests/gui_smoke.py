"""Exercise the actual Tk window against saved camera data under Xvfb.

Usage: xvfb-run -a .venv/bin/python tests/gui_smoke.py data/webcam-test.sqlite3
"""
import sys
import time
import tkinter as tk

from racevideo.gui import ReviewWindow
from racevideo import storage


def main():
    connection = storage.connect(sys.argv[1])
    storage.initialize(connection)
    connection.close()
    root = tk.Tk()
    app = ReviewWindow(root, sys.argv[1])


    def pump(seconds=0.5):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)


    try:
        app.review_day.set('All dates');app.apply_browser()
        pump(1)
        assert app.mode == "live"
        assert app.shown_image is not None
        assert len(app.clips) >= 2
        app.strip.focus_force()
        app.strip.event_generate("<Home>")
        pump()
        assert app.selected == app.clips[0]["id"]
        assert app.mode == "replay"
        assert app.index and 0<=app.ordinal<len(app.index)
        opened_ordinal=app.ordinal
        app.viewer.focus_force()
        app.viewer.event_generate("<Right>")
        pump()
        assert app.ordinal == min(opened_ordinal+1,len(app.index)-1), app.ordinal
        app.viewer.event_generate("<End>")
        pump()
        assert app.ordinal == len(app.index) - 1
        app.viewer.event_generate("<space>")
        pump(0.3)
        assert app.playing
        assert 0 < app.ordinal < len(app.index) - 1
        app.toggle_play()
        app.strip.focus_force()
        app.strip.event_generate("<Right>")
        pump()
        assert app.selected == app.clips[1]["id"]
        app.viewer.event_generate("<Escape>")
        pump()
        assert app.mode == "live"
        if len(sys.argv) > 2:
            # Screenshot the app's own test display, never the user's desktop.
            from PIL import ImageGrab
            ImageGrab.grab().save(sys.argv[2])
        print(f"GUI passed: live, {len(app.clips)} thumbnails, strip keys, frame stepping, playback, return to Live")
    finally:
        app.close()


if __name__ == "__main__":
    main()
