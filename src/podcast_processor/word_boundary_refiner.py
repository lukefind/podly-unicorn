from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import litellm
from jinja2 import Template

from app.extensions import db
from app.models import ModelCall
from podcast_processor.boundary_refiner import (
    MAX_END_EXTENSION_SECONDS,
    MAX_START_EXTENSION_SECONDS,
    _build_completion_args,
    _extract_completion_content,
    _get_or_create_refinement_model_call,
    _update_refinement_model_call,
)
from shared.config import Config, TestWhisperConfig


@dataclass(slots=True)
class WordBoundaryRefinement:
    refined_start: float
    refined_end: float
    start_adjustment_reason: str
    end_adjustment_reason: str


class WordBoundaryRefiner:
    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        model_call_query: Any = None,
        db_session: Any = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("global_logger")
        self.model_call_query = model_call_query or ModelCall.query
        self.db_session = db_session or db.session
        self.template = self._load_template()

    def _load_template(self) -> Template:
        path = Path(__file__).resolve().parent.parent / "word_boundary_refinement_prompt.jinja"
        if path.exists():
            return Template(path.read_text())
        return Template(
            """Find start/end phrases for the ad break.
Ad: {{ad_start}}s-{{ad_end}}s
{% for seg in context_segments %}[seq={{seg.sequence_num}} start={{seg.start_time}} end={{seg.end_time}}] {{seg.text}}
{% endfor %}
Return JSON: {"refined_start_segment_seq": 0, "refined_start_phrase": "", "refined_end_segment_seq": 0, "refined_end_phrase": "", "start_adjustment_reason": "", "end_adjustment_reason": ""}"""
        )

    def refine(
        self,
        ad_start: float,
        ad_end: float,
        confidence: float,
        all_segments: List[Dict[str, Any]],
        *,
        post_id: Optional[int] = None,
        first_seq_num: Optional[int] = None,
        last_seq_num: Optional[int] = None,
    ) -> WordBoundaryRefinement:
        context = self._get_context(
            ad_start,
            ad_end,
            all_segments,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
        )
        if not context:
            return self._fallback(ad_start, ad_end)

        prompt = self.template.render(
            ad_start=ad_start,
            ad_end=ad_end,
            ad_confidence=confidence,
            context_segments=context,
        )

        model_call = _get_or_create_refinement_model_call(
            config=self.config,
            db_session=self.db_session,
            model_call_query=self.model_call_query,
            model_name_suffix="::word-boundary-refinement",
            post_id=post_id,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
            prompt=prompt,
        )

        if isinstance(self.config.whisper, TestWhisperConfig):
            fallback = self._fallback(ad_start, ad_end)
            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="success_heuristic",
                response=None,
                error_message="test_mode",
            )
            return fallback

        try:
            response = litellm.completion(
                **_build_completion_args(config=self.config, prompt=prompt, max_tokens=1536)
            )
            content = _extract_completion_content(response)
            parsed = self._parse_json(content)
            if parsed is None:
                fallback = self._fallback(ad_start, ad_end)
                _update_refinement_model_call(
                    db_session=self.db_session,
                    model_call=model_call,
                    status="success_heuristic",
                    response=content,
                    error_message="parse_failed",
                )
                return fallback

            refined_start = self._estimate_phrase_time(
                all_segments=all_segments,
                context_segments=context,
                preferred_segment_seq=parsed.get("refined_start_segment_seq"),
                phrase=parsed.get("refined_start_phrase"),
                direction="start",
            )
            refined_end = self._estimate_phrase_time(
                all_segments=all_segments,
                context_segments=context,
                preferred_segment_seq=parsed.get("refined_end_segment_seq"),
                phrase=parsed.get("refined_end_phrase"),
                direction="end",
            )

            result = WordBoundaryRefinement(
                refined_start=self._constrain_start(
                    float(refined_start if refined_start is not None else ad_start),
                    ad_start,
                ),
                refined_end=self._constrain_end(
                    float(refined_end if refined_end is not None else ad_end),
                    ad_end,
                ),
                start_adjustment_reason=str(
                    parsed.get("start_adjustment_reason") or "phrase_refinement"
                ),
                end_adjustment_reason=str(
                    parsed.get("end_adjustment_reason") or "phrase_refinement"
                ),
            )
            if result.refined_end <= result.refined_start:
                result = self._fallback(ad_start, ad_end)
                _update_refinement_model_call(
                    db_session=self.db_session,
                    model_call=model_call,
                    status="success_heuristic",
                    response=content,
                    error_message="invalid_refined_window",
                )
                return result

            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="success",
                response=content,
                error_message=None,
            )
            return result
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Word boundary refinement failed: %s", exc)
            fallback = self._fallback(ad_start, ad_end)
            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="failed_permanent",
                response=None,
                error_message=str(exc),
            )
            return fallback

    def _parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        cleaned = re.sub(r"```json|```", "", (content or "").strip())
        json_candidates = re.findall(r"\{.*?\}", cleaned, re.DOTALL)
        for candidate in json_candidates:
            try:
                loaded = json.loads(candidate)
            except Exception:
                continue
            if isinstance(loaded, dict):
                return loaded
        return None

    def _fallback(self, ad_start: float, ad_end: float) -> WordBoundaryRefinement:
        return WordBoundaryRefinement(
            refined_start=ad_start,
            refined_end=ad_end,
            start_adjustment_reason="heuristic_fallback",
            end_adjustment_reason="heuristic_fallback",
        )

    def _constrain_start(self, estimated_start: float, orig_start: float) -> float:
        return max(estimated_start, orig_start - MAX_START_EXTENSION_SECONDS)

    def _constrain_end(self, estimated_end: float, orig_end: float) -> float:
        return min(estimated_end, orig_end + MAX_END_EXTENSION_SECONDS)

    def _get_context(
        self,
        ad_start: float,
        ad_end: float,
        all_segments: List[Dict[str, Any]],
        *,
        first_seq_num: Optional[int],
        last_seq_num: Optional[int],
    ) -> List[Dict[str, Any]]:
        if first_seq_num is not None and last_seq_num is not None:
            selected = [
                segment
                for segment in all_segments
                if first_seq_num - 2 <= int(segment.get("sequence_num", -1)) <= last_seq_num + 2
            ]
            if selected:
                return selected

        overlapping = [
            segment
            for segment in all_segments
            if float(segment.get("start_time", 0.0)) <= ad_end
            and float(segment.get("end_time", 0.0)) >= ad_start
        ]
        if not overlapping:
            return []

        first_index = all_segments.index(overlapping[0])
        last_index = all_segments.index(overlapping[-1])
        start_index = max(0, first_index - 2)
        end_index = min(len(all_segments), last_index + 3)
        return all_segments[start_index:end_index]

    def _estimate_phrase_time(
        self,
        *,
        all_segments: List[Dict[str, Any]],
        context_segments: List[Dict[str, Any]],
        preferred_segment_seq: Any,
        phrase: Any,
        direction: str,
    ) -> Optional[float]:
        phrase_tokens = [token.lower() for token in self._split_words(str(phrase or ""))]
        if not phrase_tokens:
            return None

        candidates: List[Dict[str, Any]] = []
        preferred_segment = self._find_segment(all_segments, preferred_segment_seq)
        if preferred_segment is not None:
            candidates.append(preferred_segment)

        ordered_context = list(context_segments)
        try:
            ordered_context.sort(key=lambda segment: int(segment.get("sequence_num", -1)))
        except Exception:
            pass
        if direction == "end":
            ordered_context.reverse()

        for segment in ordered_context:
            if segment not in candidates:
                candidates.append(segment)

        for segment in candidates:
            words = [token.lower() for token in self._split_words(str(segment.get("text", "")))]
            if not words:
                continue
            start_time = float(segment.get("start_time", 0.0))
            end_time = float(segment.get("end_time", start_time))
            duration = max(0.0, end_time - start_time)
            if duration <= 0.0:
                continue

            match = self._find_phrase_match(
                words=words,
                phrase_tokens=phrase_tokens,
                direction=direction,
            )
            if match is None:
                continue

            match_start, match_end = match
            seconds_per_word = duration / float(len(words))
            if direction == "start":
                return min(start_time + (float(match_start) * seconds_per_word), end_time)
            return min(start_time + (float(match_end + 1) * seconds_per_word), end_time)

        return None

    def _find_phrase_match(
        self,
        *,
        words: List[str],
        phrase_tokens: List[str],
        direction: str,
    ) -> Optional[Tuple[int, int]]:
        if not words or not phrase_tokens:
            return None

        max_words = min(4, len(phrase_tokens))
        if direction == "start":
            base = phrase_tokens[:max_words]
            for size in range(len(base), 0, -1):
                match = self._find_subsequence(words, base[:size], choose="first")
                if match is not None:
                    return match
            return None

        base = phrase_tokens[-max_words:]
        for size in range(len(base), 0, -1):
            match = self._find_subsequence(words, base[-size:], choose="last")
            if match is not None:
                return match
        return None

    def _find_subsequence(
        self,
        words: List[str],
        target: List[str],
        *,
        choose: str,
    ) -> Optional[Tuple[int, int]]:
        if not target or len(target) > len(words):
            return None

        matches: List[Tuple[int, int]] = []
        target_len = len(target)
        for index in range(0, len(words) - target_len + 1):
            if words[index : index + target_len] == target:
                matches.append((index, index + target_len - 1))

        if not matches:
            return None
        return matches[-1] if choose == "last" else matches[0]

    def _find_segment(
        self, all_segments: List[Dict[str, Any]], segment_seq: Any
    ) -> Optional[Dict[str, Any]]:
        try:
            seq_int = int(segment_seq)
        except Exception:
            return None

        for segment in all_segments:
            if int(segment.get("sequence_num", -1)) == seq_int:
                return segment
        return None

    def _split_words(self, text: str) -> List[str]:
        raw_tokens = [token for token in re.split(r"\s+", (text or "").strip()) if token]
        normalized = [self._normalize_token(token) for token in raw_tokens]
        return [token for token in normalized if token]

    def _normalize_token(self, token: str) -> str:
        return re.sub(r"(^[^A-Za-z0-9']+)|([^A-Za-z0-9']+$)", "", token)
