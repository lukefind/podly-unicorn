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
    # Catch both ffmpeg.Error (runtime) and ValueError/Exception (filter graph construction)
    try:
        _clip_segments_complex(ad_segments_ms, fade_ms, in_path, out_path, audio_duration_ms)
    except ffmpeg.Error as e:
        print(f"Complex filter failed (ffmpeg error), trying simple approach: {e.stderr.decode() if e.stderr else str(e)}")
        _clip_segments_simple(ad_segments_ms, in_path, out_path, audio_duration_ms)
    except Exception as e:
        # Catches filter graph construction errors like "multiple outgoing edges"
        print(f"Complex filter failed (graph error), trying simple approach: {str(e)}")
        _clip_segments_simple(ad_segments_ms, in_path, out_path, audio_duration_ms)


def _clip_segments_complex(
    ad_segments_ms: List[Tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
) -> None:
    """Apply fades to kept content edges without reintroducing removed ad audio."""
    keep_segments = _build_keep_segments(ad_segments_ms, audio_duration_ms)
    if not keep_segments:
        raise ValueError("No audio segments to keep after ad removal")

    trimmed_list = []
    last_index = len(keep_segments) - 1

    for idx, (start_ms, end_ms) in enumerate(keep_segments):
        clip_duration_ms = end_ms - start_ms
        if clip_duration_ms <= 0:
            continue

        stream = _trim_audio_segment(
            in_path,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        fade_in_ms, fade_out_ms = _get_content_fade_lengths(
            clip_duration_ms=clip_duration_ms,
            fade_ms=fade_ms,
            has_leading_cut=idx > 0,
            has_trailing_cut=idx < last_index,
        )

        if fade_in_ms > 0:
            stream = stream.filter("afade", t="in", ss=0, d=fade_in_ms / 1000.0)
        if fade_out_ms > 0:
            stream = stream.filter(
                "afade",
                t="out",
                st=max(0.0, (clip_duration_ms - fade_out_ms) / 1000.0),
                d=fade_out_ms / 1000.0,
            )

        trimmed_list.append(stream)

    if not trimmed_list:
        raise ValueError("No audio segments to keep after ad removal")

    ffmpeg.concat(*trimmed_list, v=0, a=1).output(out_path).overwrite_output().run()


def _trim_audio_segment(
    in_path: str,
    *,
    start_ms: int,
    end_ms: int,
):
    return (
        ffmpeg.input(in_path)
        .filter(
            "atrim",
            start=start_ms / 1000.0,
            end=end_ms / 1000.0,
        )
        .filter("asetpts", "PTS-STARTPTS")
    )


def _get_content_fade_lengths(
    *,
    clip_duration_ms: int,
    fade_ms: int,
    has_leading_cut: bool,
    has_trailing_cut: bool,
) -> Tuple[int, int]:
    if clip_duration_ms <= 0 or fade_ms <= 0:
        return 0, 0

    if has_leading_cut and has_trailing_cut:
        edge_fade_ms = min(fade_ms, clip_duration_ms // 2)
        return edge_fade_ms, edge_fade_ms
    if has_leading_cut:
        return min(fade_ms, clip_duration_ms), 0
    if has_trailing_cut:
        return 0, min(fade_ms, clip_duration_ms)
    return 0, 0


def _build_keep_segments(
    ad_segments_ms: List[Tuple[int, int]],
    audio_duration_ms: int,
) -> List[Tuple[int, int]]:
    normalized_ad_segments = _normalize_ad_segments(ad_segments_ms, audio_duration_ms)
    keep_segments: list[tuple[int, int]] = []
    last_end = 0

    for start_ms, end_ms in normalized_ad_segments:
        if start_ms > last_end:
            keep_segments.append((last_end, start_ms))
        last_end = end_ms

    if last_end < audio_duration_ms:
        keep_segments.append((last_end, audio_duration_ms))

    return keep_segments


def _normalize_ad_segments(
    ad_segments_ms: List[Tuple[int, int]],
    audio_duration_ms: int,
) -> List[Tuple[int, int]]:
    normalized_segments: list[tuple[int, int]] = []

    for raw_start_ms, raw_end_ms in sorted(ad_segments_ms):
        start_ms = max(0, min(raw_start_ms, audio_duration_ms))
        end_ms = max(0, min(raw_end_ms, audio_duration_ms))
        if end_ms <= start_ms:
            continue

        if normalized_segments and start_ms <= normalized_segments[-1][1]:
            last_start_ms, last_end_ms = normalized_segments[-1]
            normalized_segments[-1] = (last_start_ms, max(last_end_ms, end_ms))
            continue

        normalized_segments.append((start_ms, end_ms))

    return normalized_segments


def _clip_segments_simple(
    ad_segments_ms: List[Tuple[int, int]],
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
) -> None:
    """Simpler approach without fades - more reliable for many segments."""
    import tempfile
    import os

    keep_segments = _build_keep_segments(ad_segments_ms, audio_duration_ms)

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

    chunks: list[tuple[Path, int]] = []

    for i in range(num_chunks):
        start_offset_ms = i * chunk_duration_ms
        if start_offset_ms >= duration_ms:
            break

        end_offset_ms = min(duration_ms, (i + 1) * chunk_duration_ms)

        export_path = audio_chunk_path / f"{i}.mp3"
        trim_file(audio_file_path, export_path, start_offset_ms, end_offset_ms)
        chunks.append((export_path, start_offset_ms))

    return chunks
