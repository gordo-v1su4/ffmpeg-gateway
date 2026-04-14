# FFmpeg + FFglitch Gateway

Media processing microservice for video/audio manipulation — standalone FastAPI Docker deployment.

## Public URL (Traefik)

Production base URL: **https://ffmpeg.v1su4.dev** (HTTPS via Traefik on the same host).

DNS: point **`ffmpeg.v1su4.dev`** at this server’s public IP (explicit **A** record overrides a `*.v1su4.dev` wildcard that targets elsewhere). Override the hostname in **`.env`** with `PUBLIC_HOST` if you use a different name; it must match the Traefik router `Host()` rule and your TLS certificate.

### Traefik must share a Docker network with this service

Traefik’s **Docker provider** only sees containers on the **same network(s)** as the Traefik container. Labels on `ffmpeg-gateway` are ignored if the service is only on the default `ffmpeg-network` bridge.

1. On the VPS, find Traefik’s network name, for example:  
   `docker inspect "$(docker ps -qf name=traefik)" --format '{{range $k, $_ := .NetworkSettings.Networks}}{{$k}} {{end}}'`
2. Set **`TRAEFIK_NETWORK`** in **`.env`** to that exact name (often `traefik`, `web`, or `stackname_default`).
3. Redeploy with the overlay file:

```bash
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d
```

Direct **`http://<server-ip>:3200/docs`** works without Traefik because port **3200** is published to the host. **`https://ffmpeg.v1su4.dev`** goes to **443** on Traefik, which must reverse-proxy to this container on the shared Docker network.

Align compose labels with your Traefik static config: **`entrypoints=websecure`** and **`tls.certresolver=letsencrypt`** must match your real entrypoint and certificate resolver names.

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
# Edit .env with your API_KEYS, PUBLIC_HOST, TRAEFIK_NETWORK (VPS + Traefik)
docker compose build
docker compose up -d
# With Traefik on the same host (see "Public URL" above):
# docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d
```

## Development

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 3200
```

## Auth

Set `API_KEYS` env var with comma-separated keys. Requests must include `X-API-Key` header.
If `API_KEYS` is empty/unset, auth is disabled (all requests pass).
