import asyncio
import os
import re
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe")
FFEDIT_PATH = os.getenv("FFEDIT_PATH", "ffedit")
FFGAC_PATH = os.getenv("FFGAC_PATH", "ffgac")

WORK_DIR = Path(
    os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "ffmpeg-gateway-work"))
)
UPLOAD_DIR = WORK_DIR / "uploads"
OUTPUT_DIR = WORK_DIR / "outputs"
SCRIPTS_DIR = WORK_DIR / "scripts"


def ensure_dirs():
    for d in [UPLOAD_DIR, OUTPUT_DIR, SCRIPTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


async def run(cmd: list[str], timeout: int = 300) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=504, detail=f"Command timed out after {timeout}s"
        )
    return (
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
        proc.returncode,
    )


def sanitize_filename(value: str) -> str:
    return (
        re.sub(r"[^a-z0-9._-]+", "-", value, flags=re.IGNORECASE).strip("-") or "output"
    )


async def detect_ffmpeg() -> dict:
    stdout, _, rc = await run([FFMPEG_PATH, "-version"])
    if rc != 0:
        return {"available": False, "version": None}
    match = re.search(r"ffmpeg version (\S+)", stdout)
    return {"available": True, "version": match.group(1) if match else None}


async def detect_ffprobe() -> dict:
    stdout, _, rc = await run([FFPROBE_PATH, "-version"])
    if rc != 0:
        return {"available": False, "version": None}
    match = re.search(r"ffprobe version (\S+)", stdout)
    return {"available": True, "version": match.group(1) if match else None}


async def detect_ffglitch() -> dict:
    ffedit_ok = False
    ffgac_ok = False
    try:
        _, _, rc = await run([FFEDIT_PATH, "-version"])
        ffedit_ok = rc == 0
    except Exception:
        pass
    try:
        _, _, rc = await run([FFGAC_PATH, "-version"])
        ffgac_ok = rc == 0
    except Exception:
        pass
    return {
        "ffeditPath": FFEDIT_PATH if ffedit_ok else None,
        "ffgacPath": FFGAC_PATH if ffgac_ok else None,
        "available": ffedit_ok or ffgac_ok,
    }


async def probe_media(input_path: str) -> dict:
    stdout, stderr, rc = await run(
        [
            FFPROBE_PATH,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            input_path,
        ]
    )
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"ffprobe failed: {stderr[:500]}")
    import json

    return json.loads(stdout)


async def probe_ffglitch_features(input_path: str) -> list[str]:
    stdout, _, rc = await run([FFEDIT_PATH, "-i", input_path])
    features: list[str] = []
    if rc == 0:
        for match in re.finditer(r"\[(\w+)\s*\]", stdout):
            feat = match.group(1)
            if feat not in features:
                features.append(feat)
    return features


async def generate_glitch_script(params: dict) -> str:
    mode = params.get("mode", "shuffle")
    intensity = params.get("intensity", 1.0)
    beat_times = params.get("beatTimes", params.get("beat_times", []))

    script_content = f"""// FFglitch auto-generated script — mode: {mode}
let frame_num = 0;
const intensity = {intensity};
const beatTimes = {beat_times};
const mode = "{mode}";

export function setup(args) {{
  args.features.push("mv");
}}

export function glitch_frame(frame, stream) {{
  const mvs = frame.mv?.forward;
  if (!mvs) {{ frame_num++; return; }}

  if (mode === "zero") {{
    mvs.fill([0, 0]);
  }} else if (mode === "amplify") {{
    for (let i = 0; i < mvs.length; i++) {{
      const row = mvs[i];
      if (!row) continue;
      for (let j = 0; j < row.length; j++) {{
        const mv = row[j];
        if (!mv || mv[0] === null) continue;
        mv[0] = Math.round(mv[0] * intensity);
        mv[1] = Math.round(mv[1] * intensity);
      }}
    }}
  }} else if (mode === "reverse") {{
    for (let i = 0; i < mvs.length; i++) {{
      const row = mvs[i];
      if (!row) continue;
      for (let j = 0; j < row.length; j++) {{
        const mv = row[j];
        if (!mv || mv[0] === null) continue;
        mv[0] = -mv[0];
        mv[1] = -mv[1];
      }}
    }}
  }} else if (mode === "shuffle") {{
    const allMvs = [];
    for (let i = 0; i < mvs.length; i++) {{
      const row = mvs[i];
      if (!row) continue;
      for (let j = 0; j < row.length; j++) {{
        if (row[j] && row[j][0] !== null) allMvs.push(row[j]);
      }}
    }}
    for (let k = allMvs.length - 1; k > 0; k--) {{
      const r = Math.floor(pseudoRandom(frame_num + k) * (k + 1));
      const tmp = allMvs[k];
      allMvs[k] = allMvs[r];
      allMvs[r] = tmp;
    }}
    let idx = 0;
    for (let i = 0; i < mvs.length; i++) {{
      const row = mvs[i];
      if (!row) continue;
      for (let j = 0; j < row.length; j++) {{
        if (row[j] && row[j][0] !== null && idx < allMvs.length) {{
          const src = allMvs[idx++];
          row[j][0] = src[0];
          row[j][1] = src[1];
        }}
      }}
    }}
  }} else if (mode === "beat-sync") {{
    const beatIdx = frame_num % Math.max(1, beatTimes.length);
    const boost = beatIdx === 0 ? intensity : 1.0;
    for (let i = 0; i < mvs.length; i++) {{
      const row = mvs[i];
      if (!row) continue;
      for (let j = 0; j < row.length; j++) {{
        const mv = row[j];
        if (!mv || mv[0] === null) continue;
        mv[0] = Math.round(mv[0] * boost);
        mv[1] = Math.round(mv[1] * boost);
      }}
    }}
  }}

  frame_num++;
}}

function pseudoRandom(seed) {{
  let x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}}
"""
    script_path = SCRIPTS_DIR / f"glitch-{params.get('_job_id', 'unknown')}.js"
    script_path.write_text(script_content)
    return str(script_path)


async def apply_glitch(input_path: str, script_path: str, output_path: str) -> dict:
    _, stderr, rc = await run(
        [
            FFEDIT_PATH,
            "-i",
            input_path,
            "-f",
            "mv",
            "-s",
            script_path,
            "-o",
            output_path,
        ],
        timeout=600,
    )
    if rc != 0:
        raise HTTPException(
            status_code=500, detail=f"ffedit glitch failed: {stderr[:500]}"
        )
    return {"outputPath": output_path}


async def export_motion_vectors(input_path: str, output_path: str) -> dict:
    _, stderr, rc = await run(
        [
            FFEDIT_PATH,
            "-i",
            input_path,
            "-f",
            "mv",
            "-e",
            output_path,
        ],
        timeout=300,
    )
    if rc != 0:
        raise HTTPException(
            status_code=500, detail=f"ffedit MV export failed: {stderr[:500]}"
        )
    return {"outputPath": output_path}


async def replicate_with_ffgac(
    input_path: str, output_path: str, extra_args: Optional[list[str]] = None
) -> dict:
    cmd = [FFGAC_PATH, "-i", input_path] + (extra_args or []) + ["-y", output_path]
    _, stderr, rc = await run(cmd, timeout=600)
    if rc != 0:
        raise HTTPException(
            status_code=500, detail=f"ffgac replication failed: {stderr[:500]}"
        )
    return {"outputPath": output_path}


async def generate_section_preview(
    input_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
) -> dict:
    if end_time <= start_time or start_time < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid time window. Require 0 <= startTime < endTime.",
        )

    _, stderr, rc = await run(
        [
            FFMPEG_PATH,
            "-y",
            "-ss",
            str(start_time),
            "-to",
            str(end_time),
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            output_path,
        ],
        timeout=300,
    )
    if rc != 0:
        raise HTTPException(
            status_code=500, detail=f"ffmpeg preview generation failed: {stderr[:500]}"
        )
    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    return {
        "outputPath": output_path,
        "size": size,
        "startTime": start_time,
        "endTime": end_time,
    }


async def generate_concat_preview(
    segments: list[dict],
    output_path: str,
) -> dict:
    segment_paths: list[str] = []
    for i, seg in enumerate(segments):
        seg_output = str(
            OUTPUT_DIR
            / f"{sanitize_filename(seg.get('_job_id', 'concat'))}-part{i}.mp4"
        )
        _, stderr, rc = await run(
            [
                FFMPEG_PATH,
                "-y",
                "-ss",
                str(seg["startTime"]),
                "-to",
                str(seg["endTime"]),
                "-i",
                seg["inputPath"],
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                seg_output,
            ],
            timeout=300,
        )
        if rc != 0:
            raise HTTPException(
                status_code=500, detail=f"ffmpeg segment {i} failed: {stderr[:500]}"
            )
        segment_paths.append(seg_output)

    if len(segment_paths) == 1:
        return {"outputPath": segment_paths[0], "segments": len(segment_paths)}

    concat_list_path = str(
        OUTPUT_DIR
        / f"{sanitize_filename(segments[0].get('_job_id', 'concat'))}-concat-list.txt"
    )
    concat_entries = "\n".join(f"file '{p}'" for p in segment_paths)
    Path(concat_list_path).write_text(concat_entries)

    try:
        _, _, rc = await run(
            [
                FFMPEG_PATH,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_path,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output_path,
            ],
            timeout=300,
        )
        if rc != 0:
            raise RuntimeError("concat copy failed")
    except Exception:
        _, stderr, rc = await run(
            [
                FFMPEG_PATH,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_path,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
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
                status_code=500, detail=f"ffmpeg concat merge failed: {stderr[:500]}"
            )

    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    return {"outputPath": output_path, "size": size, "segments": len(segment_paths)}


async def split_video(
    input_path: str,
    segments: list[dict],
    job_id: str,
) -> list[dict]:
    results = []
    for i, seg in enumerate(segments):
        output_path = str(OUTPUT_DIR / f"{sanitize_filename(job_id)}-split{i}.mp4")
        start = seg.get("startTime", seg.get("start_time", 0))
        end = seg.get("endTime", seg.get("end_time", 0))
        if end <= start:
            continue
        _, stderr, rc = await run(
            [
                FFMPEG_PATH,
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                output_path,
            ],
            timeout=300,
        )
        if rc != 0:
            raise HTTPException(
                status_code=500,
                detail=f"ffmpeg split segment {i} failed: {stderr[:500]}",
            )
        results.append(
            {
                "index": i,
                "outputPath": output_path,
                "downloadUrl": f"/download/{Path(output_path).name}",
                "startTime": start,
                "endTime": end,
            }
        )
    return results


async def extract_thumbnails(
    input_path: str,
    times: Optional[list[float]] = None,
    count: Optional[int] = None,
    width: int = 320,
    height: int = -2,
    job_id: str = "thumb",
) -> list[dict]:
    results = []
    if times:
        for i, t in enumerate(times):
            output_path = str(OUTPUT_DIR / f"{sanitize_filename(job_id)}-thumb{i}.jpg")
            _, stderr, rc = await run(
                [
                    FFMPEG_PATH,
                    "-y",
                    "-ss",
                    str(t),
                    "-i",
                    input_path,
                    "-vframes",
                    "1",
                    "-vf",
                    f"scale={width}:{height}",
                    "-q:v",
                    "2",
                    output_path,
                ],
                timeout=60,
            )
            if rc != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"ffmpeg thumbnail {i} failed: {stderr[:500]}",
                )
            results.append(
                {
                    "index": i,
                    "time": t,
                    "outputPath": output_path,
                    "downloadUrl": f"/download/{Path(output_path).name}",
                }
            )
    elif count:
        output_pattern = str(OUTPUT_DIR / f"{sanitize_filename(job_id)}-thumb%d.jpg")
        _, stderr, rc = await run(
            [
                FFMPEG_PATH,
                "-y",
                "-i",
                input_path,
                "-vf",
                f"fps={count},scale={width}:{height}",
                "-q:v",
                "2",
                output_pattern,
            ],
            timeout=120,
        )
        if rc != 0:
            raise HTTPException(
                status_code=500,
                detail=f"ffmpeg thumbnail extraction failed: {stderr[:500]}",
            )
        pattern_base = str(OUTPUT_DIR / f"{sanitize_filename(job_id)}-thumb")
        for p in sorted(
            Path(OUTPUT_DIR).glob(f"{sanitize_filename(job_id)}-thumb*.jpg")
        ):
            idx_str = p.stem.replace(f"{sanitize_filename(job_id)}-thumb", "")
            results.append(
                {
                    "index": int(idx_str) if idx_str.isdigit() else 0,
                    "outputPath": str(p),
                    "downloadUrl": f"/download/{p.name}",
                }
            )
    else:
        raise HTTPException(
            status_code=400, detail="Provide 'times' list or 'count' integer."
        )

    return results


async def extract_audio(
    input_path: str,
    format: str = "mp3",
    bitrate: str = "192k",
    job_id: str = "audio",
) -> dict:
    ext = format if format in ("mp3", "wav", "aac", "flac", "ogg", "m4a") else "mp3"
    output_path = str(OUTPUT_DIR / f"{sanitize_filename(job_id)}.{ext}")
    _, stderr, rc = await run(
        [
            FFMPEG_PATH,
            "-y",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "libmp3lame" if ext == "mp3" else "copy",
            "-b:a",
            bitrate,
            output_path,
        ],
        timeout=120,
    )
    if rc != 0:
        raise HTTPException(
            status_code=500, detail=f"ffmpeg audio extraction failed: {stderr[:500]}"
        )
    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    return {
        "outputPath": output_path,
        "downloadUrl": f"/download/{Path(output_path).name}",
        "format": ext,
        "size": size,
    }


async def get_media_info(input_path: str) -> dict:
    return await probe_media(input_path)
