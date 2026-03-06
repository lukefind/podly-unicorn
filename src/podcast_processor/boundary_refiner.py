from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import litellm
from jinja2 import Template
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ModelCall
from shared.config import Config, TestWhisperConfig
from shared.llm_utils import model_uses_max_completion_tokens

MAX_START_EXTENSION_SECONDS = 30.0
MAX_END_EXTENSION_SECONDS = 15.0


def _extract_completion_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    choice = choices[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content:
        return str(content)

    text = getattr(choice, "text", None)
    return str(text or "")


def _build_completion_args(
    *, config: Config, prompt: str, max_tokens: int
) -> Dict[str, Any]:
    messages = [{"role": "user", "content": prompt}]
    completion_args: Dict[str, Any] = {
        "model": config.llm_model,
        "messages": messages,
        "timeout": config.openai_timeout,
        "temperature": 0.1,
    }

    if config.llm_api_key:
        completion_args["api_key"] = config.llm_api_key
    if config.openai_base_url:
        completion_args["api_base"] = config.openai_base_url

    if model_uses_max_completion_tokens(config.llm_model):
        completion_args["max_completion_tokens"] = max_tokens
    else:
        completion_args["max_tokens"] = max_tokens

    return completion_args


def _get_or_create_refinement_model_call(
    *,
    config: Config,
    db_session: Any,
    model_call_query: Any,
    model_name_suffix: str,
    post_id: Optional[int],
    first_seq_num: Optional[int],
    last_seq_num: Optional[int],
    prompt: str,
) -> Optional[ModelCall]:
    if post_id is None or first_seq_num is None or last_seq_num is None:
        return None

    model_name = f"{config.llm_model}{model_name_suffix}"
    model_call: Optional[ModelCall] = (
        model_call_query.filter_by(
            post_id=post_id,
            model_name=model_name,
            first_segment_sequence_num=first_seq_num,
            last_segment_sequence_num=last_seq_num,
        )
        .order_by(ModelCall.timestamp.desc())
        .first()
    )

    if model_call is None:
        model_call = ModelCall(
            post_id=post_id,
            first_segment_sequence_num=first_seq_num,
            last_segment_sequence_num=last_seq_num,
            model_name=model_name,
            prompt=prompt,
            status="pending",
            timestamp=datetime.utcnow(),
        )
        try:
            db_session.add(model_call)
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            model_call = (
                model_call_query.filter_by(
                    post_id=post_id,
                    model_name=model_name,
                    first_segment_sequence_num=first_seq_num,
                    last_segment_sequence_num=last_seq_num,
                )
                .order_by(ModelCall.timestamp.desc())
                .first()
            )
            if model_call is None:
                raise

    model_call.prompt = prompt
    model_call.response = None
    model_call.error_message = None
    model_call.retry_attempts = 0
    model_call.status = "pending"
    model_call.timestamp = datetime.utcnow()
    db_session.add(model_call)
    db_session.commit()
    return model_call


def _update_refinement_model_call(
    *,
    db_session: Any,
    model_call: Optional[ModelCall],
    status: str,
    response: Optional[str],
    error_message: Optional[str],
) -> None:
    if model_call is None:
        return

    model_call.status = status
    model_call.response = response
    model_call.error_message = error_message
    model_call.retry_attempts = max(int(model_call.retry_attempts or 0), 1)
    db_session.add(model_call)
    db_session.commit()


@dataclass(slots=True)
class BoundaryRefinement:
    refined_start: float
    refined_end: float
    start_adjustment_reason: str
    end_adjustment_reason: str
    confidence_adjustment: float = 0.0


class BoundaryRefiner:
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
        path = (
            Path(__file__).resolve().parent.parent / "boundary_refinement_prompt.jinja"
        )
        if path.exists():
            return Template(path.read_text())
        return Template(
            """Refine ad boundaries.
Ad: {{ad_start}}s-{{ad_end}}s
{% for seg in context_segments %}[{{seg.start_time}}] {{seg.text}}
{% endfor %}
Return JSON: {"refined_start": {{ad_start}}, "refined_end": {{ad_end}}, "start_adjustment_reason": "", "end_adjustment_reason": ""}"""
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
    ) -> BoundaryRefinement:
        context = self._get_context(
            ad_start,
            ad_end,
            all_segments,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
        )
        if not context:
            return BoundaryRefinement(
                refined_start=ad_start,
                refined_end=ad_end,
                start_adjustment_reason="no_context",
                end_adjustment_reason="no_context",
            )

        prompt = self.template.render(
            ad_start=ad_start,
            ad_end=ad_end,
            ad_confidence=confidence,
            context_segments=context,
            max_start_extension=MAX_START_EXTENSION_SECONDS,
            max_end_extension=MAX_END_EXTENSION_SECONDS,
        )

        model_call = _get_or_create_refinement_model_call(
            config=self.config,
            db_session=self.db_session,
            model_call_query=self.model_call_query,
            model_name_suffix="::boundary-refinement",
            post_id=post_id,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
            prompt=prompt,
        )

        if isinstance(self.config.whisper, TestWhisperConfig):
            heuristic = self._heuristic_refine(ad_start, ad_end, context)
            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="success_heuristic",
                response=None,
                error_message="test_mode",
            )
            return heuristic

        try:
            response = litellm.completion(
                **_build_completion_args(
                    config=self.config, prompt=prompt, max_tokens=2048
                )
            )
            content = _extract_completion_content(response)
            parsed = self._parse_json(content)
            if parsed is None:
                heuristic = self._heuristic_refine(ad_start, ad_end, context)
                _update_refinement_model_call(
                    db_session=self.db_session,
                    model_call=model_call,
                    status="success_heuristic",
                    response=content,
                    error_message="parse_failed",
                )
                return heuristic

            refined = BoundaryRefinement(
                refined_start=float(parsed.get("refined_start", ad_start)),
                refined_end=float(parsed.get("refined_end", ad_end)),
                start_adjustment_reason=str(
                    parsed.get("start_adjustment_reason")
                    or parsed.get("start_reason")
                    or "llm_refinement"
                ),
                end_adjustment_reason=str(
                    parsed.get("end_adjustment_reason")
                    or parsed.get("end_reason")
                    or "llm_refinement"
                ),
                confidence_adjustment=float(parsed.get("confidence_adjustment", 0.0)),
            )
            refined = self._validate(ad_start, ad_end, refined)
            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="success",
                response=content,
                error_message=None,
            )
            return refined
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Boundary refinement failed: %s", exc)
            heuristic = self._heuristic_refine(ad_start, ad_end, context)
            _update_refinement_model_call(
                db_session=self.db_session,
                model_call=model_call,
                status="failed_permanent",
                response=None,
                error_message=str(exc),
            )
            return heuristic

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
                if first_seq_num - 2
                <= int(segment.get("sequence_num", -1))
                <= last_seq_num + 2
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
        start_index = max(0, first_index - 8)
        end_index = min(len(all_segments), last_index + 9)
        return all_segments[start_index:end_index]

    def _heuristic_refine(
        self, ad_start: float, ad_end: float, context: List[Dict[str, Any]]
    ) -> BoundaryRefinement:
        intro_patterns = [
            "brought to you",
            "word from our sponsor",
            "sponsor today",
            "let me tell you about",
            "before we continue",
        ]
        outro_patterns = [
            "use code",
            "visit",
            "thanks to",
            "back to the show",
            "and we're back",
        ]

        refined_start = ad_start
        refined_end = ad_end

        for segment in context:
            text = str(segment.get("text", "")).lower()
            segment_start = float(segment.get("start_time", ad_start))
            segment_end = float(segment.get("end_time", ad_end))
            if segment_start < ad_start and any(
                pattern in text for pattern in intro_patterns
            ):
                refined_start = min(refined_start, segment_start)
            if segment_start > ad_end and any(
                pattern in text for pattern in outro_patterns
            ):
                refined_end = max(refined_end, segment_end)

        return self._validate(
            ad_start,
            ad_end,
            BoundaryRefinement(
                refined_start=refined_start,
                refined_end=refined_end,
                start_adjustment_reason="heuristic",
                end_adjustment_reason="heuristic",
            ),
        )

    def _validate(
        self,
        orig_start: float,
        orig_end: float,
        refinement: BoundaryRefinement,
    ) -> BoundaryRefinement:
        refinement.refined_start = max(
            refinement.refined_start,
            orig_start - MAX_START_EXTENSION_SECONDS,
        )
        refinement.refined_end = min(
            refinement.refined_end,
            orig_end + MAX_END_EXTENSION_SECONDS,
        )
        if refinement.refined_end <= refinement.refined_start:
            refinement.refined_start = orig_start
            refinement.refined_end = orig_end
        return refinement
