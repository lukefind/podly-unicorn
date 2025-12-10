import logging
from typing import Any, List, Optional, Tuple

from app.extensions import db
from app.models import (
    Identification,
    ModelCall,
    Post,
    ProcessingStatistics,
    PromptPreset,
    TranscriptSegment,
)
from podcast_processor.audio import clip_segments_with_fade, get_audio_duration_ms
from shared.config import Config


class AudioProcessor:
    """Handles audio processing and ad segment removal from podcast files."""

    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        identification_query: Optional[Any] = None,
        transcript_segment_query: Optional[Any] = None,
        model_call_query: Optional[Any] = None,
        db_session: Optional[Any] = None,
    ):
        self.logger = logger or logging.getLogger("global_logger")
        self.config = config
        self.identification_query = identification_query or Identification.query
        self.transcript_segment_query = (
            transcript_segment_query or TranscriptSegment.query
        )
        self.model_call_query = model_call_query or ModelCall.query
        self.db_session = db_session or db.session

    def get_ad_segments(self, post: Post) -> List[Tuple[float, float]]:
        """
        Retrieves ad segments from the database for a given post.

        Args:
            post: The Post object to retrieve ad segments for

        Returns:
            A list of tuples containing start and end times (in seconds) of ad segments
        """
        self.logger.info(f"Retrieving ad segments from database for post {post.id}.")

        ad_identifications = (
            self.identification_query.join(
                TranscriptSegment,
                Identification.transcript_segment_id == TranscriptSegment.id,
            )
            .join(ModelCall, Identification.model_call_id == ModelCall.id)
            .filter(
                TranscriptSegment.post_id == post.id,
                Identification.label == "ad",
                Identification.confidence >= self.config.output.min_confidence,
                ModelCall.status
                == "success",  # Only consider identifications from successful LLM calls
            )
            .all()
        )

        if not ad_identifications:
            self.logger.info(
                f"No ad segments found meeting criteria for post {post.id}."
            )
            return []

        ad_segments_times: List[Tuple[float, float]] = []
        for ident in ad_identifications:
            segment = ident.transcript_segment  # Accessing via backref
            if segment:
                ad_segments_times.append((segment.start_time, segment.end_time))
            else:
                # This should ideally not happen if DB integrity is maintained
                self.logger.warning(
                    f"Identification {ident.id} for post {post.id} refers to a missing TranscriptSegment {ident.transcript_segment_id}. Skipping."
                )

        self.logger.info(
            f"Found {len(ad_segments_times)} ad segments for post {post.id} from database."
        )
        # Sort by start time, as processing might expect this order
        ad_segments_times.sort(key=lambda x: x[0])
        return ad_segments_times

    def merge_ad_segments(
        self,
        *,
        duration_ms: int,
        ad_segments: List[Tuple[float, float]],
        min_ad_segment_length_seconds: float,
        min_ad_segment_separation_seconds: float,
    ) -> List[Tuple[int, int]]:
        """
        Merges nearby ad segments and filters out segments that are too short.

        Args:
            duration_ms: Duration of the audio in milliseconds
            ad_segments: List of ad segments as (start, end) tuples in seconds
            min_ad_segment_length_seconds: Minimum length of an ad segment to retain
            min_ad_segment_separation_seconds: Minimum separation between segments before merging

        Returns:
            List of merged ad segments as (start, end) tuples in milliseconds
        """
        audio_duration_seconds = duration_ms / 1000.0

        self.logger.info(
            f"Creating new audio with ads segments removed between: {ad_segments}"
        )
        # if no segments provided, return empty list
        if not ad_segments:
            return []

        # if any two ad segments overlap by fade_ms, join them into a single segment
        ad_segments = sorted(ad_segments)
        i = 0

        # Initialize variable for storing the last segment
        last_segment = None
        has_segment_near_end = False

        # Check for segments near the end before merging
        if len(ad_segments) > 0 and (
            audio_duration_seconds - ad_segments[-1][1]
            < min_ad_segment_separation_seconds
        ):
            # Save the last segment before filtering
            last_segment = ad_segments[-1]
            has_segment_near_end = True

        # Merge overlapping segments
        while i < len(ad_segments) - 1:
            if (
                ad_segments[i][1] + min_ad_segment_separation_seconds
                >= ad_segments[i + 1][0]
            ):
                ad_segments[i] = (ad_segments[i][0], ad_segments[i + 1][1])
                ad_segments.pop(i + 1)
            else:
                i += 1

        # remove any isolated ad segments that are too short, possibly misidentified
        ad_segments = [
            segment
            for segment in ad_segments
            if segment[1] - segment[0] >= min_ad_segment_length_seconds
        ]

        # Restore the last segment if it was near the end but got filtered out
        if (
            has_segment_near_end
            and last_segment is not None
            and (not ad_segments or ad_segments[-1] != last_segment)
        ):
            ad_segments.append(last_segment)

        # Extend the last segment to the end if it's near the end
        if len(ad_segments) > 0 and (
            audio_duration_seconds - ad_segments[-1][1]
            < min_ad_segment_separation_seconds
        ):
            ad_segments[-1] = (ad_segments[-1][0], audio_duration_seconds)

        self.logger.info(f"Joined ad segments into: {ad_segments}")

        ad_segments_ms = [
            (int(start * 1000), int(end * 1000)) for start, end in ad_segments
        ]
        return ad_segments_ms

    def process_audio(self, post: Post, output_path: str) -> None:
        """
        Process the podcast audio by removing ad segments.

        Args:
            post: The Post object containing the podcast to process
            output_path: Path where the processed audio file should be saved
        """
        ad_segments = self.get_ad_segments(post)

        duration_ms = get_audio_duration_ms(post.unprocessed_audio_path)
        if duration_ms is None:
            raise ValueError(
                f"Could not determine duration for audio: {post.unprocessed_audio_path}"
            )

        # Store duration in seconds
        original_duration_seconds = duration_ms / 1000.0
        post.duration = original_duration_seconds

        merged_ad_segments = self.merge_ad_segments(
            duration_ms=duration_ms,
            ad_segments=ad_segments,
            min_ad_segment_length_seconds=float(
                self.config.output.min_ad_segment_length_seconds
            ),
            min_ad_segment_separation_seconds=float(
                self.config.output.min_ad_segement_separation_seconds
            ),
        )

        clip_segments_with_fade(
            in_path=post.unprocessed_audio_path,
            ad_segments_ms=merged_ad_segments,
            fade_ms=self.config.output.fade_ms,
            out_path=output_path,
        )

        post.processed_audio_path = output_path
        
        # Calculate and store processing statistics
        self._store_processing_statistics(
            post=post,
            original_duration_seconds=original_duration_seconds,
            merged_ad_segments_ms=merged_ad_segments,
        )
        
        self.db_session.commit()

        self.logger.info(
            f"Audio processing complete for post {post.id}, saved to {output_path}"
        )

    def _store_processing_statistics(
        self,
        post: Post,
        original_duration_seconds: float,
        merged_ad_segments_ms: List[Tuple[int, int]],
    ) -> None:
        """
        Calculate and store processing statistics for the episode.

        Args:
            post: The Post object being processed
            original_duration_seconds: Original duration before ad removal
            merged_ad_segments_ms: List of merged ad segments in milliseconds
        """
        # Calculate total duration removed
        total_duration_removed_ms = sum(
            end - start for start, end in merged_ad_segments_ms
        )
        total_duration_removed_seconds = total_duration_removed_ms / 1000.0

        # Calculate processed duration
        processed_duration_seconds = (
            original_duration_seconds - total_duration_removed_seconds
        )

        # Calculate percentage removed
        percentage_removed = (
            (total_duration_removed_seconds / original_duration_seconds * 100)
            if original_duration_seconds > 0
            else 0.0
        )

        # Get active prompt preset (if any)
        active_preset = PromptPreset.query.filter_by(is_active=True).first()
        prompt_preset_id = active_preset.id if active_preset else None

        # Check if statistics already exist for this post
        existing_stats = ProcessingStatistics.query.filter_by(post_id=post.id).first()

        if existing_stats:
            # Update existing statistics
            existing_stats.total_ad_segments_removed = len(merged_ad_segments_ms)
            existing_stats.total_duration_removed_seconds = total_duration_removed_seconds
            existing_stats.original_duration_seconds = original_duration_seconds
            existing_stats.processed_duration_seconds = processed_duration_seconds
            existing_stats.percentage_removed = percentage_removed
            existing_stats.prompt_preset_id = prompt_preset_id
            self.logger.info(
                f"Updated statistics for post {post.id}: "
                f"{len(merged_ad_segments_ms)} segments, "
                f"{total_duration_removed_seconds:.1f}s removed ({percentage_removed:.1f}%)"
            )
        else:
            # Create new statistics
            stats = ProcessingStatistics(
                post_id=post.id,
                total_ad_segments_removed=len(merged_ad_segments_ms),
                total_duration_removed_seconds=total_duration_removed_seconds,
                original_duration_seconds=original_duration_seconds,
                processed_duration_seconds=processed_duration_seconds,
                percentage_removed=percentage_removed,
                prompt_preset_id=prompt_preset_id,
            )
            self.db_session.add(stats)
            self.logger.info(
                f"Created statistics for post {post.id}: "
                f"{len(merged_ad_segments_ms)} segments, "
                f"{total_duration_removed_seconds:.1f}s removed ({percentage_removed:.1f}%)"
            )
