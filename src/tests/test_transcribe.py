import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest
from openai.types.audio.transcription_segment import TranscriptionSegment
from openai.types.audio.transcription_verbose import TranscriptionVerbose


def test_remote_transcribe_uses_openai_sdk_contract(tmp_path: Path) -> None:
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        OpenAIWhisperTranscriber,
        Segment,
    )
    from shared.config import (  # pylint: disable=import-outside-toplevel
        RemoteWhisperConfig,
    )

    logger = logging.getLogger("global_logger")
    config = RemoteWhisperConfig(
        base_url="https://transcription.example/v1",
        api_key="resolved-openai-key",
        model="whisper-1",
        language="en",
        timeout_sec=45,
    )
    chunk_path = tmp_path / "chunk.mp3"
    chunk_path.write_bytes(b"test audio")
    sdk_response = TranscriptionVerbose(
        duration=2.0,
        language="en",
        text="First segment. Second segment.",
        segments=[
            TranscriptionSegment(
                id=0,
                avg_logprob=-0.1,
                seek=0,
                temperature=0.0,
                text="First segment.",
                tokens=[1],
                compression_ratio=1.0,
                no_speech_prob=0.01,
                start=0.0,
                end=1.0,
            ),
            TranscriptionSegment(
                id=1,
                avg_logprob=-0.2,
                seek=100,
                temperature=0.0,
                text="Second segment.",
                tokens=[2],
                compression_ratio=1.1,
                no_speech_prob=0.02,
                start=1.0,
                end=2.0,
            ),
        ],
    )

    with patch("podcast_processor.transcribe.OpenAI") as openai_constructor:
        openai_constructor.return_value.audio.transcriptions.create.return_value = (
            sdk_response
        )
        transcriber = OpenAIWhisperTranscriber(logger, config)
        segments = transcriber.get_segments_for_chunk(str(chunk_path))

    openai_constructor.assert_called_once_with(
        base_url="https://transcription.example/v1",
        api_key="resolved-openai-key",
        timeout=45,
    )
    openai_constructor.return_value.audio.transcriptions.create.assert_called_once_with(
        model="whisper-1",
        file=ANY,
        timestamp_granularities=["segment"],
        language="en",
        response_format="verbose_json",
    )
    assert OpenAIWhisperTranscriber.convert_segments(segments) == [
        Segment(start=0.0, end=1.0, text="First segment."),
        Segment(start=1.0, end=2.0, text="Second segment."),
    ]


@pytest.mark.skip
def test_local_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        LocalWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    transcriber = LocalWhisperTranscriber(logger, "base.en")
    transcription = transcriber.transcribe("src/tests/file.mp3")
    assert transcription == []


def test_groq_transcribe_uses_groq_sdk_contract(tmp_path: Path) -> None:
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        GroqWhisperTranscriber,
        Segment,
    )
    from shared.config import (  # pylint: disable=import-outside-toplevel
        GroqWhisperConfig,
    )

    chunk_path = tmp_path / "chunk.mp3"
    chunk_path.write_bytes(b"test audio")
    sdk_response = SimpleNamespace(
        text="This is a test segment. This is another test segment.",
        segments=[
            {"start": 0.0, "end": 1.0, "text": "This is a test segment."},
            {"start": 1.0, "end": 2.0, "text": "This is another test segment."},
        ],
    )

    logger = logging.getLogger("global_logger")
    config = GroqWhisperConfig(
        api_key="test_key", model="whisper-large-v3-turbo", language="en"
    )

    with patch("podcast_processor.transcribe.Groq") as groq_constructor:
        groq_constructor.return_value.audio.transcriptions.create.return_value = (
            sdk_response
        )
        transcriber = GroqWhisperTranscriber(logger, config)
        segments = transcriber.get_segments_for_chunk(str(chunk_path))

    groq_constructor.assert_called_once_with(api_key="test_key", max_retries=3)
    groq_constructor.return_value.audio.transcriptions.create.assert_called_once_with(
        file=chunk_path,
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
        language="en",
    )
    assert GroqWhisperTranscriber.convert_segments(segments) == [
        Segment(start=0.0, end=1.0, text="This is a test segment."),
        Segment(start=1.0, end=2.0, text="This is another test segment."),
    ]


def test_offset() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (  # pylint: disable=import-outside-toplevel
        OpenAIWhisperTranscriber,
    )

    assert OpenAIWhisperTranscriber.add_offset_to_segments(
        [
            TranscriptionSegment(
                id=1,
                avg_logprob=2,
                seek=6,
                temperature=7,
                text="hi",
                tokens=[],
                compression_ratio=3,
                no_speech_prob=4,
                start=12.345,
                end=45.678,
            )
        ],
        123,
    ) == [
        TranscriptionSegment(
            id=1,
            avg_logprob=2,
            seek=6,
            temperature=7,
            text="hi",
            tokens=[],
            compression_ratio=3,
            no_speech_prob=4,
            start=12.468,
            end=45.800999999999995,
        )
    ]
