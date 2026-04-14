# FFmpeg + FFglitch Gateway

Media processing microservice for video/audio manipulation — standalone FastAPI Docker deployment.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + tool availability |
| POST | `/upload` | Upload a media file, get a fileId |
| GET | `/download/{filename}` | Download a processed output |
| POST | `/cleanup/{fileId}` | Delete uploaded/processed files |
| POST | `/probe` | ffprobe a media file (returns JSON) |
| POST | `/info` | Alias for `/probe` |
| POST | `/ffmpeg/preview` | Extract a section preview (`startTime`, `endTime`) |
| POST | `/ffmpeg/concat` | Concatenate segments from one file |
| POST | `/ffmpeg/split` | Split video at time boundaries |
| POST | `/ffmpeg/thumbnail` | Extract thumbnails at times or count |
| POST | `/ffmpeg/extract-audio` | Extract audio track (mp3/wav/aac/flac) |
| POST | `/ffmpeg/convert` | Convert video format (mp4/webm/mov/gif) |
| POST | `/ffglitch/detect` | Check FFglitch tool availability |
| POST | `/ffglitch/probe` | Probe file for FFglitch features |
| POST | `/ffglitch/glitch` | Apply motion vector glitch effect |
| POST | `/ffglitch/export-mv` | Export motion vectors as JSON |
| POST | `/ffglitch/replicate` | Re-encode with ffgac |
| GET | `/internal/metrics` | Prometheus metrics (requires Bearer token) |

## Deploy

```bash
cp .env.example .env
# Edit .env with your API_KEYS
docker compose up -d
```

## Development

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 3200
```

## Auth

Set `API_KEYS` env var with comma-separated keys. Requests must include `X-API-Key` header.
If `API_KEYS` is empty/unset, auth is disabled (all requests pass).
