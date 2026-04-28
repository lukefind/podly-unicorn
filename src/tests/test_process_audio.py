import struct
import tempfile
import wave
from pathlib import Path

from podcast_processor.audio import (
    clip_segments_with_fade,
    get_audio_duration_ms,
    split_audio,
)

TEST_FILE_DURATION = 66_048
TEST_FILE_PATH = "src/tests/data/count_0_99.mp3"
TEST_WAV_SAMPLE_RATE = 8_000
TEST_WAV_SAMPLE_VALUE = 10_000


def _write_constant_wave(path: Path, duration_ms: int) -> None:
    frame_count = int(TEST_WAV_SAMPLE_RATE * duration_ms / 1000)
    frame = struct.pack("<h", TEST_WAV_SAMPLE_VALUE)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TEST_WAV_SAMPLE_RATE)
        wav_file.writeframes(frame * frame_count)


def _write_sectioned_wave(path: Path, sections: list[tuple[int, int]]) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TEST_WAV_SAMPLE_RATE)

        for duration_ms, sample_value in sections:
            frame_count = int(TEST_WAV_SAMPLE_RATE * duration_ms / 1000)
            frame = struct.pack("<h", sample_value)
            wav_file.writeframes(frame * frame_count)


def _read_wave_sample(path: Path, time_ms: int) -> int:
    with wave.open(str(path), "rb") as wav_file:
        frame_index = min(
            int(TEST_WAV_SAMPLE_RATE * time_ms / 1000),
            wav_file.getnframes() - 1,
        )
        wav_file.setpos(frame_index)
        return struct.unpack("<h", wav_file.readframes(1))[0]


def test_get_duration_ms() -> None:
    assert get_audio_duration_ms(TEST_FILE_PATH) == TEST_FILE_DURATION


def test_clip_segment_with_fade() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 3_000, 21_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = TEST_FILE_DURATION - (
            ad_end_offset_ms - ad_start_offset_ms
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 120, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_beginning() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 0, 18_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = TEST_FILE_DURATION - (
            ad_end_offset_ms - ad_start_offset_ms
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 120, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_end() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = (
        TEST_FILE_DURATION - 18_000,
        TEST_FILE_DURATION,
    )

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = TEST_FILE_DURATION - (
            ad_end_offset_ms - ad_start_offset_ms
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 120, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_does_not_duplicate_short_cuts() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 3_000, 7_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = TEST_FILE_DURATION - (
            ad_end_offset_ms - ad_start_offset_ms
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 120, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_removes_ad_audio_content() -> None:
    fade_len_ms = 1_000

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "input.wav"
        output_path = Path(temp_dir) / "output.wav"

        _write_sectioned_wave(
            input_path,
            sections=[
                (3_000, 2_000),
                (4_000, 12_000),
                (3_000, 4_000),
            ],
        )

        clip_segments_with_fade(
            [(3_000, 7_000)],
            fade_len_ms,
            str(input_path),
            str(output_path),
        )

        assert get_audio_duration_ms(str(output_path)) == 6_000
        assert abs(_read_wave_sample(output_path, 1_000) - 2_000) <= 5
        assert abs(_read_wave_sample(output_path, 4_250) - 4_000) <= 5


def test_build_keep_segments_normalizes_unsorted_overlapping_ranges() -> None:
    from podcast_processor.audio import _build_keep_segments

    keep_segments = _build_keep_segments(
        [
            (9_000, 15_000),
            (-500, 500),
            (3_000, 6_000),
            (5_000, 8_000),
        ],
        audio_duration_ms=10_000,
    )

    assert keep_segments == [(500, 3_000), (8_000, 9_000)]


def test_split_audio() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        split_audio(Path(TEST_FILE_PATH), temp_dir_path, 38_000)

        expected = {
            "0.mp3": (6_384, 38_108),
            "1.mp3": (6_384, 38_252),
            "2.mp3": (6_384, 38_108),
            "3.mp3": (6_384, 38_108),
            "4.mp3": (6_384, 38_252),
            "5.mp3": (6_384, 38_252),
            "6.mp3": (6_384, 38_252),
            "7.mp3": (6_384, 38_108),
            "8.mp3": (6_384, 38_108),
            "9.mp3": (6_384, 38_252),
            "10.mp3": (2_784, 16_508),
        }

        for split in temp_dir_path.iterdir():
            assert split.name in expected
            duration_ms, filesize = expected[split.name]
            actual_duration = get_audio_duration_ms(str(split))
            assert (
                actual_duration is not None
            ), f"Failed to get audio duration for {split}"
            assert abs(actual_duration - duration_ms) <= 100, (
                f"Duration mismatch for {split}. Expected {duration_ms}ms, got {actual_duration}ms, "
                f"difference: {abs(actual_duration - duration_ms)}ms"
            )
            assert (
                abs(filesize - split.stat().st_size) <= 500
            ), f"filesize <> 500 bytes for {split}. found {split.stat().st_size}, expected {filesize}"  # pylint: disable=line-too-long
