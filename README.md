# video_object_find_and_review

Second-stage reviewer for motion-triggered camera clips. Watches one or more
directories for `.mp4` + `.json` pairs (produced by an upstream motion-capture
tool), re-analyzes each clip cheaply for coherent motion (people/animals/
vehicles vs. bugs, flags, IR day/night switches), escalates ambiguous cases to
YOLO object detection, and sorts clips into good/maybe/no-detect output
directories with a thumbnail and a web UI for review.

## Install

Download the code and install its dependencies into a folder on the machine
that will run it:

```bash
git clone https://github.com/clams2121/video_object_find_and_review.git
cd video_object_find_and_review
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

Edit `config.yaml` — at minimum set `watch_directories` to the folder(s)
where your camera tool drops `*.mp4`/`*.json` pairs. See the file for all
options (output directories, scan interval, detection thresholds, YOLO
settings). Most settings are also editable from the `/config` page while the
app is running; `server.host`/`server.port` require a restart.

## Run

```bash
python -m app.main
```

This starts the web app and a background scanner (polling
`watch_directories` every `scan_interval_seconds`) in one process.

- `/` — tile view of processed clips, grouped by day and hour, with a live
  status bar ("Processing 3 of 10: camera1_...") so a long-running scan is
  never silently stuck
- `/config` — configuration page
- `/errors` — clips that failed to process, plus recent warning/error log
  events; the same errors are also written to `data/logs/app.log`
  (rotated automatically) if you'd rather tail a file

## Tests

```bash
pytest
```

`scripts/synthetic_clips.py` generates synthetic mp4/json pairs (clean
motion, a day/night flicker, a bug-sized jitter) used by the pipeline
end-to-end test, and can also be run standalone to populate a watch
directory for manual testing:

```bash
python scripts/synthetic_clips.py data/watch
```
