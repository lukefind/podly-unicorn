import math
from pathlib import Path
from typing import List, Optional, Tuple

import ffmpeg  # type: ignore[import-untyped]


def get_audio_duration_ms(file_path: str) -> Optional[int]:
    try:
        probe = ffmpeg.probe(file_path)
        format_info = probe["format"]
        duration_seconds = float(format_info["duration"])
        duration_milliseconds = duration_seconds * 1000
        return int(duration_milliseconds)
    except ffmpeg.Error as e:
        print("An error occurred while trying to probe the file:")
        print(e.stderr.decode())
        return None


def clip_segments_with_fade(
    ad_segments_ms: List[Tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
) -> None:

    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None

    # Try the complex filter approach first, fall back to simple if it fails
    try:
        _clip_segments_complex(ad_segments_ms, fade_ms, in_path, out_path, audio_duration_ms)
    except ffmpeg.Error as e:
        print(f"Complex filter failed, trying simple approach: {e.stderr.decode() if e.stderr else str(e)}")
        _clip_segments_simple(ad_segments_ms, in_path, out_path, audio_duration_ms)


def _clip_segments_complex(
    ad_segments_ms: List[Tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
) -> None:
    """Original complex approach with fades - can fail with many segments."""
    trimmed_list = []

    last_end = 0
    for start_ms, end_ms in ad_segments_ms:
        trimmed_list.extend(
            [
                ffmpeg.input(in_path).filter(
                    "atrim", start=last_end / 1000.0, end=start_ms / 1000.0
                ),
                ffmpeg.input(in_path)
                .filter(
                    "atrim", start=start_ms / 1000.0, end=(start_ms + fade_ms) / 1000.0
                )
                .filter("afade", t="out", ss=0, d=fade_ms / 1000.0),
                ffmpeg.input(in_path)
                .filter("atrim", start=(end_ms - fade_ms) / 1000.0, end=end_ms / 1000.0)
                .filter("afade", t="in", ss=0, d=fade_ms / 1000.0),
            ]
        )

        last_end = end_ms

    if last_end != audio_duration_ms:
        trimmed_list.append(
            ffmpeg.input(in_path).filter(
                "atrim", start=last_end / 1000.0, end=audio_duration_ms / 1000.0
            )
        )

    ffmpeg.concat(*trimmed_list, v=0, a=1).output(out_path).overwrite_output().run()


def _clip_segments_simple(
    ad_segments_ms: List[Tuple[int, int]],
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
) -> None:
    """Simpler approach without fades - more reliable for many segments."""
    import tempfile
    import os
    
    # Build list of segments to KEEP (inverse of ad segments)
    keep_segments = []
    last_end = 0
    
    for start_ms, end_ms in ad_segments_ms:
        if start_ms > last_end:
            keep_segments.append((last_end, start_ms))
        last_end = end_ms
    
    if last_end < audio_duration_ms:
        keep_segments.append((last_end, audio_duration_ms))
    
    if not keep_segments:
        # No content to keep - this shouldn't happen but handle it
        raise ValueError("No audio segments to keep after ad removal")
    
    # Create temp directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir:
        segment_files = []
        
        # Extract each segment to keep
        for i, (start_ms, end_ms) in enumerate(keep_segments):
            segment_path = os.path.join(temp_dir, f"segment_{i}.mp3")
            start_sec = start_ms / 1000.0
            duration_sec = (end_ms - start_ms) / 1000.0
            
            (
                ffmpeg.input(in_path)
                .output(segment_path, ss=start_sec, t=duration_sec, acodec="libmp3lame", q=2)
                .overwrite_output()
                .run(quiet=True)
            )
            segment_files.append(segment_path)
        
        # Create concat file list
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w") as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file}'\n")
        
        # Concatenate all segments
        (
            ffmpeg.input(concat_list_path, format="concat", safe=0)
            .output(out_path, acodec="libmp3lame", q=2)
            .overwrite_output()
            .run(quiet=True)
        )


def trim_file(in_path: Path, out_path: Path, start_ms: int, end_ms: int) -> None:
    duration_ms = end_ms - start_ms

    if duration_ms <= 0:
        return

    start_sec = max(start_ms, 0) / 1000.0
    duration_sec = duration_ms / 1000.0

    (
        ffmpeg.input(str(in_path))
        .output(
            str(out_path),
            ss=start_sec,
            t=duration_sec,
            acodec="copy",
            vn=None,
        )
        .overwrite_output()
        .run()
    )


def split_audio(
    audio_file_path: Path,
    audio_chunk_path: Path,
    chunk_size_bytes: int,
) -> List[Tuple[Path, int]]:

    audio_chunk_path.mkdir(parents=True, exist_ok=True)

    duration_ms = get_audio_duration_ms(str(audio_file_path))
    assert duration_ms is not None
    if chunk_size_bytes <= 0:
        raise ValueError("chunk_size_bytes must be a positive integer")

    file_size_bytes = audio_file_path.stat().st_size
    if file_size_bytes == 0:
        raise ValueError("Cannot split zero-byte audio file")

    chunk_ratio = chunk_size_bytes / file_size_bytes
    chunk_duration_ms = max(1, math.ceil(duration_ms * chunk_ratio))

    num_chunks = max(1, math.ceil(duration_ms / chunk_duration_ms))

    chunks: List[Tuple[Path, int]] = []

    for i in range(num_chunks):
        start_offset_ms = i * chunk_duration_ms
        if start_offset_ms >= duration_ms:
            break

        end_offset_ms = min(duration_ms, (i + 1) * chunk_duration_ms)

        export_path = audio_chunk_path / f"{i}.mp3"
        trim_file(audio_file_path, export_path, start_offset_ms, end_offset_ms)
        chunks.append((export_path, start_offset_ms))

    return chunks
