"""ROI mouse/persistence/color checks on an isolated Tk test display."""
import io
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk

from PIL import Image, ImageDraw

from racevideo import storage
from racevideo.gui import ReviewWindow
from racevideo.motion import DEFAULT_ROI, validate_roi


def main():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "roi.sqlite3"
        connection = storage.connect(path)
        storage.initialize(connection)
        image = Image.new("RGB", (1280, 720), "#293d4d")
        draw = ImageDraw.Draw(image)
        for x in range(0, 1280, 80):
            draw.line((x, 0, x, 720), fill="#385165")
        for y in range(0, 720, 80):
            draw.line((0, y, 1280, y), fill="#385165")
        out = io.BytesIO()
        image.save(out, "JPEG")
        preview = out.getvalue()

        def publish(moving=False, roi=DEFAULT_ROI):
            storage.publish(connection, dict(state="recording", trigger="motion", moving=moving,
                                            roi=list(roi), last_frame_ns=time.time_ns()), preview)

        publish()
        root = tk.Tk()
        app = ReviewWindow(root, path)

        def pump(seconds=0.4):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                root.update()
                time.sleep(0.01)

        def drag(start, end):
            app.viewer.event_generate("<ButtonPress-1>", x=round(start[0]), y=round(start[1]))
            app.viewer.event_generate("<B1-Motion>", x=round(end[0]), y=round(end[1]))
            app.viewer.event_generate("<ButtonRelease-1>", x=round(end[0]), y=round(end[1]))
            pump()

        try:
            pump(0.7)
            x0, y0, x1, y1 = app.roi_points()
            _, _, w, h = app.image_bounds()
            assert abs((x1 - x0) / w - 0.15) < 1e-6
            assert abs((y1 - y0) / h - 0.7) < 1e-6
            assert app.viewer.itemcget(app.roi_outline, "outline") == "#ffe14a"
            publish(True)
            pump()
            assert app.viewer.itemcget(app.roi_outline, "outline") == "#ff4949"
            center = ((x0 + x1) / 2, (y0 + y1) / 2)
            drag(center, (center[0] + 60, center[1] - 25))
            assert abs(app.roi[0] - DEFAULT_ROI[0] - 60 / w) < 0.002
            assert abs(app.roi[1] - DEFAULT_ROI[1] + 25 / h) < 0.002
            assert tuple(storage.read_setting(connection, "motion_roi")) == app.roi
            # Resize each corner outward, preserving the opposite corner.
            for corner in range(4):
                before = app.roi
                x0, y0, x1, y1 = app.roi_points()
                start = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))[corner]
                dx, dy = (-12 if corner in (0, 2) else 12), (-12 if corner in (0, 1) else 12)
                drag(start, (start[0] + dx, start[1] + dy))
                validate_roi(app.roi)
                assert app.roi[2] - app.roi[0] > before[2] - before[0]
                assert app.roi[3] - app.roi[1] > before[3] - before[1]
            # Movement clamps to the image, not to the larger letterboxed canvas.
            x0, y0, x1, y1 = app.roi_points()
            center = ((x0 + x1) / 2, (y0 + y1) / 2)
            drag(center, (center[0] + 3000, center[1] - 3000))
            assert abs(app.roi[2] - 1) < 1e-9 and abs(app.roi[1]) < 1e-9
            # Persist and repaint a non-default ROI after window resize.
            publish(False, app.roi)
            root.geometry("900x700")
            pump()
            x0, y0, x1, y1 = app.roi_points()
            left, top, w, h = app.image_bounds()
            assert abs(x1 - (left + w)) < 1
            assert abs(y0 - top) < 1
            assert app.viewer.itemcget(app.roi_outline, "outline") == "#ffe14a"
            if len(sys.argv) > 1:
                from PIL import ImageGrab
                ImageGrab.grab().save(sys.argv[1])
            app.mode = "replay"
            app.draw_roi()
            assert app.viewer.itemcget(app.roi_outline, "state") == "hidden"
            print("ROI passed: initial geometry, red/yellow, move, all corners, bounds, persistence, resize, replay hiding")
        finally:
            app.close()
            connection.close()


if __name__ == "__main__":
    main()
