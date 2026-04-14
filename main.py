"""
FFmpeg + FFglitch Gateway API
Media processing microservice for video/audio manipulation.

Run with: uvicorn main:app --reload --port 3200
"""

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Security,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pathlib import Path
from typing import Optional
import os
import tempfile
import time
import uuid
import uvicorn

from api.auth import verify_api_key
from services.ffmpeg_service import (
    ensure_dirs,
    UPLOAD_DIR,
    OUTPUT_DIR,
    SCRIPTS_DIR,
    sanitize_filename,
    detect_ffmpeg,
    detect_ffprobe,
    detect_ffglitch,
    probe_media,
    probe_ffglitch_features,
    generate_glitch_script,
    apply_glitch,
    export_motion_vectors,
    replicate_with_ffgac,
    generate_section_preview,
    generate_concat_preview,
    split_video,
    extract_thumbnails,
    extract_audio,
    get_media_info,
)

API_VERSION = "1.0.0"
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "3200"))
METRICS_TOKEN = os.getenv("METRICS_TOKEN", "").strip()
CORS_ORIGINS_STR = os.getenv("CORS_ORIGINS") or os.getenv("CORS_ORIGIN") or "*"
CORS_ORIGINS = [
    origin.strip() for origin in CORS_ORIGINS_STR.split(",") if origin.strip()
]
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024

REQUEST_COUNT = Counter(
    "ffmpeg_gateway_http_requests_total",
    "Total HTTP requests handled by the FFmpeg Gateway API.",
    ["handler", "method", "status"],
)
REQUEST_LATENCY = Histogram(
    "ffmpeg_gateway_http_request_duration_seconds",
    "Request latency for the FFmpeg Gateway API.",
    ["handler", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
REQUESTS_IN_PROGRESS = Gauge(
    "ffmpeg_gateway_http_requests_in_progress",
    "In-flight FFmpeg Gateway API requests.",
    ["handler", "method"],
)
SKIP_METRICS_PATHS = frozenset(("/internal/metrics",))

app = FastAPI(
    title="FFmpeg + FFglitch Gateway",
    version=API_VERSION,
    description="Media processing microservice: FFmpeg preview, concat, split, thumbnail, audio extract + FFglitch glitch effects.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    ensure_dirs()
    try:
        ffmpeg = await detect_ffmpeg()
        ffprobe = await detect_ffprobe()
        ffglitch = await detect_ffglitch()
    except (FileNotFoundError, OSError) as e:
        print(f"[ffmpeg-gateway] Tool probe failed (check FFMPEG_PATH / FFPROBE_PATH): {e}")
        ffmpeg = {"available": False, "version": None}
        ffprobe = {"available": False, "version": None}
        ffglitch = {
            "ffeditPath": None,
            "ffgacPath": None,
            "available": False,
        }
    print(f"[ffmpeg-gateway] Listening on :{API_PORT}")
    print(
        f"[ffmpeg-gateway] FFmpeg:  {'v' + ffmpeg['version'] if ffmpeg['available'] else 'NOT FOUND'}"
    )
    print(
        f"[ffmpeg-gateway] FFprobe: {'v' + ffprobe['version'] if ffprobe['available'] else 'NOT FOUND'}"
    )
    print(f"[ffmpeg-gateway] FFedit:  {ffglitch['ffeditPath'] or 'NOT FOUND'}")
    print(f"[ffmpeg-gateway] FFgac:   {ffglitch['ffgacPath'] or 'NOT FOUND'}")
    print(f"[ffmpeg-gateway] Work dir: {UPLOAD_DIR.parent}")


def _verify_metrics_token(request: Request) -> None:
    if not METRICS_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    import secrets

    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {METRICS_TOKEN}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.middleware("http")
async def instrument_requests(request: Request, call_next):
    handler = request.url.path or "/"
    method = request.method
    if handler in SKIP_METRICS_PATHS:
        return await call_next(request)
    start = time.perf_counter()
    status_code = "500"
    REQUESTS_IN_PROGRESS.labels(handler=handler, method=method).inc()
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    finally:
        duration = time.perf_counter() - start
        REQUEST_LATENCY.labels(handler=handler, method=method).observe(duration)
        REQUEST_COUNT.labels(handler=handler, method=method, status=status_code).inc()
        REQUESTS_IN_PROGRESS.labels(handler=handler, method=method).dec()


def job_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


async def save_upload(file: UploadFile) -> tuple[str, str]:
    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    id_ = job_id()
    dest = str(UPLOAD_DIR / f"{id_}{ext}")
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {MAX_UPLOAD_SIZE // 1024 // 1024}MB.",
        )
    Path(dest).write_bytes(content)
    return id_, dest


@app.api_route("/health", methods=["GET", "HEAD"], tags=["System"])
async def health():
    try:
        ffmpeg = await detect_ffmpeg()
        ffprobe = await detect_ffprobe()
        ffglitch = await detect_ffglitch()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )
    return {
        "status": "ok",
        "version": API_VERSION,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "ffglitch": ffglitch,
    }


@app.get("/internal/metrics", include_in_schema=False, tags=["System"])
async def internal_metrics(request: Request):
    _verify_metrics_token(request)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/upload", tags=["Files"])
async def upload_file(
    file: UploadFile = File(...),
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    return {
        "fileId": id_,
        "originalName": file.filename,
        "path": dest,
        "size": os.path.getsize(dest),
    }


@app.get("/download/{filename}", tags=["Files"])
async def download_file(filename: str):
    safe = sanitize_filename(filename)
    for base_dir in [OUTPUT_DIR, UPLOAD_DIR]:
        candidate = base_dir / safe
        resolved = candidate.resolve()
        if str(resolved).startswith(str(base_dir.resolve())) and resolved.exists():
            return FileResponse(str(resolved), filename=safe)
    raise HTTPException(status_code=404, detail="File not found.")


@app.post("/cleanup/{file_id}", tags=["Files"])
async def cleanup(file_id: str, api_key: str = Security(verify_api_key)):
    removed = 0
    safe = sanitize_filename(file_id)
    for base_dir in [UPLOAD_DIR, OUTPUT_DIR, SCRIPTS_DIR]:
        if not base_dir.exists():
            continue
        for p in base_dir.iterdir():
            if p.name.startswith(safe) or p.name.startswith(file_id):
                p.unlink(missing_ok=True)
                removed += 1
    return {"success": True, "removed": removed}


@app.post("/probe", tags=["FFprobe"])
async def probe(
    file: UploadFile = File(...),
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    try:
        result = await probe_media(dest)
        return {"success": True, "fileId": id_, "probe": result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/info", tags=["FFprobe"])
async def media_info(
    file: UploadFile = File(...),
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    try:
        result = await get_media_info(dest)
        return {"success": True, "fileId": id_, "info": result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffmpeg/preview", tags=["FFmpeg"])
async def ffmpeg_preview(
    file: UploadFile = File(...),
    startTime: float = 0.0,
    endTime: float = 10.0,
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    output_path = str(OUTPUT_DIR / f"{sanitize_filename(id_)}.mp4")
    try:
        result = await generate_section_preview(dest, startTime, endTime, output_path)
        result["fileId"] = id_
        result["downloadUrl"] = f"/download/{Path(output_path).name}"
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffmpeg/concat", tags=["FFmpeg"])
async def ffmpeg_concat(
    file: UploadFile = File(...),
    segments: str = "[]",
    api_key: str = Security(verify_api_key),
):
    import json

    id_, dest = await save_upload(file)
    try:
        seg_list = json.loads(segments)
        for seg in seg_list:
            seg["inputPath"] = dest
            seg["_job_id"] = id_
        output_path = str(OUTPUT_DIR / f"{sanitize_filename(id_)}.mp4")
        result = await generate_concat_preview(seg_list, output_path)
        result["fileId"] = id_
        result["downloadUrl"] = f"/download/{Path(output_path).name}"
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffmpeg/split", tags=["FFmpeg"])
async def ffmpeg_split(
    file: UploadFile = File(...),
    segments: str = "[]",
    api_key: str = Security(verify_api_key),
):
    import json

    id_, dest = await save_upload(file)
    try:
        seg_list = json.loads(segments)
        results = await split_video(dest, seg_list, id_)
        Path(dest).unlink(missing_ok=True)
        return {"success": True, "fileId": id_, "segments": results}
    except Exception:
        Path(dest).unlink(missing_ok=True)
        raise


@app.post("/ffmpeg/thumbnail", tags=["FFmpeg"])
async def ffmpeg_thumbnail(
    file: UploadFile = File(...),
    times: Optional[str] = None,
    count: Optional[int] = None,
    width: int = 320,
    height: int = -2,
    api_key: str = Security(verify_api_key),
):
    import json

    id_, dest = await save_upload(file)
    try:
        parsed_times = json.loads(times) if times else None
        results = await extract_thumbnails(
            dest,
            times=parsed_times,
            count=count,
            width=width,
            height=height,
            job_id=id_,
        )
        Path(dest).unlink(missing_ok=True)
        return {"success": True, "fileId": id_, "thumbnails": results}
    except Exception:
        Path(dest).unlink(missing_ok=True)
        raise


@app.post("/ffmpeg/extract-audio", tags=["FFmpeg"])
async def ffmpeg_extract_audio(
    file: UploadFile = File(...),
    format: str = "mp3",
    bitrate: str = "192k",
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    try:
        result = await extract_audio(dest, format=format, bitrate=bitrate, job_id=id_)
        result["fileId"] = id_
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffmpeg/convert", tags=["FFmpeg"])
async def ffmpeg_convert(
    file: UploadFile = File(...),
    format: str = "mp4",
    preset: str = "veryfast",
    crf: int = 20,
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    ext = format if format in ("mp4", "avi", "mkv", "webm", "mov", "gif") else "mp4"
    output_path = str(OUTPUT_DIR / f"{sanitize_filename(id_)}.{ext}")
    try:
        from services.ffmpeg_service import run

        _, stderr, rc = await run(
            [
                "ffmpeg",
                "-y",
                "-i",
                dest,
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                output_path,
            ],
            timeout=600,
        )
        if rc != 0:
            raise HTTPException(
                status_code=500, detail=f"ffmpeg convert failed: {stderr[:500]}"
            )
        size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        return {
            "success": True,
            "fileId": id_,
            "downloadUrl": f"/download/{Path(output_path).name}",
            "format": ext,
            "size": size,
        }
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffglitch/detect", tags=["FFglitch"])
async def ffglitch_detect(api_key: str = Security(verify_api_key)):
    capabilities = await detect_ffglitch()
    return {"success": True, "capabilities": capabilities}


@app.post("/ffglitch/probe", tags=["FFglitch"])
async def ffglitch_probe(
    file: UploadFile = File(...),
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    try:
        features = await probe_ffglitch_features(dest)
        return {"success": True, "fileId": id_, "features": features}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffglitch/glitch", tags=["FFglitch"])
async def ffglitch_glitch(
    file: UploadFile = File(...),
    mode: str = "shuffle",
    intensity: float = 1.0,
    beatTimes: Optional[str] = None,
    api_key: str = Security(verify_api_key),
):
    import json

    id_, dest = await save_upload(file)
    input_ext = os.path.splitext(file.filename or "video.avi")[1] or ".avi"
    output_path = str(OUTPUT_DIR / f"{sanitize_filename(id_)}-glitched{input_ext}")
    try:
        beat_list = json.loads(beatTimes) if beatTimes else []
        params = {
            "mode": mode,
            "intensity": intensity,
            "beatTimes": beat_list,
            "_job_id": id_,
        }
        script_path = await generate_glitch_script(params)
        result = await apply_glitch(dest, script_path, output_path)
        result["fileId"] = id_
        result["downloadUrl"] = f"/download/{Path(output_path).name}"
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffglitch/export-mv", tags=["FFglitch"])
async def ffglitch_export_mv(
    file: UploadFile = File(...),
    api_key: str = Security(verify_api_key),
):
    id_, dest = await save_upload(file)
    mv_path = str(OUTPUT_DIR / f"mv-{sanitize_filename(id_)}.json")
    try:
        result = await export_motion_vectors(dest, mv_path)
        result["fileId"] = id_
        result["downloadUrl"] = f"/download/{Path(mv_path).name}"
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


@app.post("/ffglitch/replicate", tags=["FFglitch"])
async def ffglitch_replicate(
    file: UploadFile = File(...),
    extraArgs: Optional[str] = None,
    api_key: str = Security(verify_api_key),
):
    import json

    id_, dest = await save_upload(file)
    input_ext = os.path.splitext(file.filename or "video.avi")[1] or ".avi"
    output_path = str(OUTPUT_DIR / f"{sanitize_filename(id_)}-replicated{input_ext}")
    try:
        extra = json.loads(extraArgs) if extraArgs else []
        result = await replicate_with_ffgac(dest, output_path, extra_args=extra)
        result["fileId"] = id_
        result["downloadUrl"] = f"/download/{Path(output_path).name}"
        return {"success": True, **result}
    finally:
        Path(dest).unlink(missing_ok=True)


if __name__ == "__main__":
    uvicorn.run(app, host=API_HOST, port=API_PORT)
