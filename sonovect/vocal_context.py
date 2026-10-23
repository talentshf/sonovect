"""Reuse the speech pipeline's VAD output without altering upstream packages."""
from copy import deepcopy


def capture_vad(model):
    """Observe the existing public inference call; never run a second detector."""
    original = model.inference
    model.sonovect_vad_regions = None

    def inference(*args, **kwargs):
        value = original(*args, **kwargs)
        if kwargs.get("model") is model.vad_model:
            if not isinstance(value, list) or len(value) != 1:
                raise ValueError("unexpected_vad_result_count")
            model.sonovect_vad_regions = deepcopy(value[0]["value"])
        return value

    model.inference = inference
    return model


def speech_context(regions, engine=None):
    if not isinstance(regions, list):
        raise ValueError("speech_regions_unavailable")
    return {"speech_regions": regions, **({"vad": engine} if engine else {})}


def regions_from_context(context, duration_ms):
    """Invalid handoff is a failed stage, never evidence of silence."""
    if not isinstance(context, dict) or not isinstance(context.get("speech_regions"), list):
        raise ValueError("speech_context_required")
    result = []
    for span in context["speech_regions"]:
        if isinstance(span, dict):
            span = [span.get("start_ms"), span.get("end_ms")]
        if (not isinstance(span, (list, tuple)) or len(span) != 2
                or any(type(v) is not int for v in span)
                or not 0 <= span[0] < span[1] <= duration_ms):
            raise ValueError("invalid_speech_context")
        result.append(tuple(span))
    return sorted(result)
