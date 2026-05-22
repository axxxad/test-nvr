# CCTV NVR

Self-hosted lightweight NVR for Hikvision RTSP cameras.

**Stack:** FastAPI, Jinja2, SQLite, FFmpeg, Docker, DaisyUI + Tailwind.

## Quick start (Docker)

```bash
docker compose up --build
```

Open [http://localhost:8000/cameras](http://localhost:8000/cameras).

- **SQLite:** `./data/nvr.db`
- **Recordings:** `./recordings/cam{id}/YYYY/MM/DD/HH-MM-SS.mp4`
- **Exports:** `./exports/` (temporary concat outputs)

## Features

| Feature | Description |
|---------|-------------|
| Camera CRUD | Name + RTSP URL |
| Recording | Per-camera FFmpeg segment recording (30s, copy codec) |
| Indexer | Background scan → SQLite `segments` table (every 60s) |
| Retention | Per-camera days; auto-delete old files (every 5 min) |
| Browse | Date/time range → list segments |
| Export | FFmpeg concat → single MP4 download |

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install && npm run build:css
mkdir -p data recordings exports
export DATABASE_URL=sqlite:///./data/nvr.db
uvicorn app.main:app --reload
```

## Hikvision RTSP

```
rtsp://USER:PASS@192.168.1.100:554/Streaming/Channels/101
```

| Stream | Channel |
|--------|---------|
| Main   | `101`   |
| Sub    | `102`   |

## Recording command

```bash
ffmpeg -rtsp_transport tcp -i RTSP_URL \
  -map 0:v:0 [-map 0:a:0? -c:a aac if record_audio] -an -c copy \
  -f segment -segment_time 30 -reset_timestamps 1 \
  -strftime 1 -strftime_mkdir 1 \
  /recordings/cam{id}/%Y/%m/%d/%H-%M-%S.mp4
```

Today's and tomorrow's `YYYY/MM/DD` folders are created in Python before FFmpeg starts and refreshed every index cycle (60s). FFmpeg `-strftime_mkdir` is unreliable at midnight on some mounts; a dead FFmpeg process is also restarted while recording stays enabled.

## Export command

```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4
```

## Environment

| Variable | Default (local) | Docker |
|----------|-----------------|--------|
| `DATABASE_URL` | `sqlite:///./data/nvr.db` | `sqlite:////data/nvr.db` |
| `RECORDINGS_DIR` | `./recordings` | `/recordings` |
| `APP_TIMEZONE` | `UTC` | `Europe/London` |
| `TZ` | — | **same as** `APP_TIMEZONE` (FFmpeg segment folders) |

Set `TZ` and `APP_TIMEZONE` to your camera/PC timezone (IANA name). If they differ from Docker’s default UTC, segment folders and the UI were off by 1–2 hours (worse after daylight saving).

Copy `.env.example` to `.env` and adjust the zone. After changing it, redeploy and open Recordings once (segment times are refreshed from filenames).

## Roadmap

- Live preview (optional)
- Scale / worker split for 30+ cameras
