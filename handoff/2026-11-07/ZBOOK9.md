# zbook9 installation and first-race check

Installed and validated 2026-11-04 for the planned Sunday, November 8 trial.
This opening installation record is historical. The ELP camera has since been
tested and isolated GPU OCR environments added; see ELP_CAMERA.md, GPU_OCR.md
and SUNDAY_TRIAL.md for the current experiments and field-trial procedure.

## Installed layout

- Source/environment: `/home/sl/racevideo`, including `.venv`.
- Recordings: `/home/sl/.local/share/racevideo/racevideo.sqlite3`, schema v8.
- Launchers: `~/.local/bin/racevideo`, `~/.local/bin/racevideo-tool`.
- Application menu: **RaceVideo**; desktop shortcut: `~/Desktop/RaceVideo.desktop`.
- User service: `racevideo-mcp.service`, enabled/running on loopback
  `http://127.0.0.1:8766/mcp`. Existing user lingering is enabled.
- Private MCP/bridge configuration: `~/.config/racevideo-mcp/`; do not copy these
  credentials between machines or include their contents in logs.

Open RaceVideo from the applications menu or run `~/.local/bin/racevideo`.
The launcher opens Live/review **without opening a camera**. Click Start recorder
after configuring the intended device. Closing the GUI leaves recording running;
Stop recorder ends capture. If the desktop shell asks, right-click its shortcut
and choose Allow Launching; the application-menu entry is also available.

Recordings are outside the checkout so source updates need not touch footage.
Development recordings were not copied to the laptop; its race store starts empty.

## Verified laptop environment

Ubuntu 26.04.1 LTS, standard Python 3.14.4 (not free-threaded), i7-12850HX,
approximately 32 GB RAM and 811 GB available on the installation check. Performance
power profile was active; timezone is America/Vancouver with NTP synchronized.
Python dependencies and English Tesseract data are installed locally; no runtime
model download is required. Native desktop/OCR packages were installed through apt;
Python dependencies are isolated in `.venv`.

39 unit tests, real Tk review/date/bib/star/cleanup tests, production-store GUI and
MCP bridge, authenticated MCP integration, deterministic motion/pre-post-roll and
normal/overrun stress tests passed on this laptop. The synthetic full-HD test
measured approximately 63 ms median / 91 ms p95 preview receipt-to-submission age,
3.4 ms p95 GUI callback delay, with analysis approximately 4.8 seconds behind.
These are synthetic timings, not a real-camera, sustained race/OCR CPU-budget or
sensor-to-monitor calibration.

The forced decoder-termination test exposed a multiprocessing Event shutdown
hang. Worker cancellation/completion now uses monotonic shared flags that cannot
be stranded by a child dying while holding an Event condition lock. The failure,
clean shutdown and overwrite tests pass with the fix on zbook9.

[Environment and evidence](docs/evidence/zbook9/installation.json),
[validated package snapshot](docs/evidence/zbook9/pip-freeze.txt),
[normal stress](docs/evidence/zbook9/pipeline-stress.json),
[forced overwrite](docs/evidence/zbook9/pipeline-overrun.json).

## When the external camera arrives

1. Connect it and identify its capture-capable node and stable alias:

   ```sh
   ~/.local/bin/racevideo-tool call camera.devices
   v4l2-ctl --list-devices
   v4l2-ctl --device /dev/v4l/by-id/NEW_CAMERA_ALIAS --list-formats-ext
   ```

   The built-in HP RGB camera currently occupies `/dev/video0`; there is also an
   IR camera and metadata nodes. Do not assume the new camera becomes video0.

2. Choose an actually advertised **MJPEG** resolution/frame rate. The prototype
   requires MJPEG; YUYV-only modes are not implemented. Configure/start using MCP,
   substituting the real alias and supported dimensions/rate. Example only:

   ```sh
   ~/.local/bin/racevideo-tool call recorder.start --arguments '{"configuration":{"device":"/dev/v4l/by-id/NEW_CAMERA_ALIAS","width":3840,"height":2160,"fps":30,"buffer_mb":256}}'
   ```

   Start/stop reuse the recorded capture configuration. The desktop launcher does
   not override it with a default built-in camera. Actual frame rate, ring duration
   and freshness must be checked rather than inferred from the requested rate.

3. Open RaceVideo. Check MCP linked, live preview, actual FPS and the Performance
   window. Adjust the yellow motion rectangle at the finish line. Verify it turns
   red for motion and that a saved segment contains pre-roll and its quiet tail.

4. Use Camera settings/readback to establish fixed short exposure and focus at
   race distance, with gain/light sufficient for a recognizable operator image.
   Test moving plates, not just a stationary sharp scene. Recheck actual settings
   after unplugging/restarting: the capture mode is saved, but the camera may
   reset its own controls. Focus/zoom support depends on the actual device/lens.

5. Save/review several groups. Test scrub/zoom/pan, OCR candidates and source
   evidence, bib filtering, starring, and closing/reopening review while recording
   continues. Use a disposable store/date for any cleanup demonstration.

6. Check sustained capture plus OCR/review load and available disk, with the laptop
   in its actual race power arrangement. Check analysis lag, ring duration and gap
   counters, not just preview FPS. Compare receipt timestamps with the race system;
   they are not calibrated exposure/finish times. Use explicit Stop recorder at
   the end and confirm the final segments are saved.

The first Sunday use is standalone visual/OCR evidence. CrossMgr/RaceDB/Impinj
identity/correlation and provisional-result integration remain planned in
[INTEGRATION.md](INTEGRATION.md).

## Service and diagnostics

```sh
systemctl --user status racevideo-mcp.service
~/.local/bin/racevideo-tool call racevideo.status
~/.local/bin/racevideo-tool call camera.devices
journalctl --user -u racevideo-mcp.service -n 50
~/.local/bin/racevideo status
~/.local/bin/racevideo stop
```

Recorder/OCR logs are beside the recording store. Service restarts preserve its
independently supervised recorder. No cross-host MCP token is installed: agents
can use the authenticated client through SSH, or an explicitly configured tunnel.

## Reinstall/update

Copy source excluding `.venv`, `.git`, `data`, caches and generated package metadata.
Never overwrite the recording store or private host configuration during updates.
The reusable user installer runs after creating `.venv` and installing extras:

```sh
.venv/bin/pip install -e '.[ocr,mcp]'
.venv/bin/python tools/install_user.py --service --desktop
```

The package snapshot records this validated environment. Validate dependency or
code changes separately before using them during an event.
