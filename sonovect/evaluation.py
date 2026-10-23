"""Offline reference scoring. References are never submitted to a model."""
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import unicodedata

EVALUATOR_VERSION = "1.1.0"


def binomial_interval(successes: int, total: int) -> dict:
    """Wilson 95% interval; no imaginary zero rate when there are no trials."""
    if type(successes) is not int or type(total) is not int or not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    if not total:
        return {"count": successes, "total": total, "rate": None, "wilson_95": None}
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return {"count": successes, "total": total, "rate": p,
            "wilson_95": [max(0, center-half), min(1, center+half)]}


def multilabel_scores(references: list, predictions: list, vocabulary: list[str]) -> dict:
    """Exhaustive clip labels within a declared vocabulary, never outside it."""
    if (len(references) != len(predictions) or not vocabulary or
            len(vocabulary) != len(set(vocabulary))):
        raise ValueError("Invalid multilabel comparison")
    labels = set(vocabulary)
    refs, hyps = [set(v) for v in references], [set(v) for v in predictions]
    if any(not r <= labels for r in refs):
        raise ValueError("Reference outside declared vocabulary")
    per_class = {}
    for label in vocabulary:
        tp = sum(label in r and label in h for r,h in zip(refs,hyps))
        fp = sum(label not in r and label in h for r,h in zip(refs,hyps))
        fn = sum(label in r and label not in h for r,h in zip(refs,hyps))
        tn = len(refs)-tp-fp-fn
        per_class[label] = {"tp":tp,"fp":fp,"fn":fn,"tn":tn,
                            "precision":tp/(tp+fp) if tp+fp else None,
                            "recall":tp/(tp+fn) if tp+fn else None,
                            "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                            "false_positive_rate":binomial_interval(fp,fp+tn)}
    totals = {k:sum(v[k] for v in per_class.values()) for k in ("tp","fp","fn","tn")}
    tp,fp,fn = (totals[k] for k in ("tp","fp","fn"))
    negatives = [(r,h & labels) for r,h in zip(refs,hyps) if not r]
    valid_f1 = [v['f1'] for v in per_class.values() if v['f1'] is not None]
    return {"cases":len(refs),"vocabulary":vocabulary,"per_class":per_class,
            "micro":{**totals,"precision":tp/(tp+fp) if tp+fp else None,
                     "recall":tp/(tp+fn) if tp+fn else None,
                     "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None},
            "macro_f1":sum(valid_f1)/len(valid_f1) if valid_f1 else None,
            "negative_clip_false_positive_rate":binomial_interval(sum(bool(h) for _,h in negatives),len(negatives)),
            "exact_set_match":binomial_interval(sum(r==h & labels for r,h in zip(refs,hyps)),len(refs)),
            "unscored_prediction_counts":dict(Counter(label for h in hyps for label in h-labels)),
            "scope":"Clip-level presence within declared exhaustive vocabulary; other predicted labels are unscored"}


def emotion_scores(references: list[str], predictions: list, vocabulary: list[str]) -> dict:
    """One human majority reference; abstention/multiple outputs stay errors."""
    result = multilabel_scores([{r} for r in references], predictions, vocabulary)
    confusion = {r:dict.fromkeys([*vocabulary,"ABSTAIN","MULTIPLE","OUT_OF_VOCABULARY"],0) for r in vocabulary}
    correct = 0
    for r,values in zip(references,predictions):
        h = set(values)
        predicted = ("ABSTAIN" if not h else "MULTIPLE" if len(h)>1 else
                     next(iter(h)) if h <= set(vocabulary) else "OUT_OF_VOCABULARY")
        confusion[r][predicted] += 1
        correct += h == {r}
    result.update(strict_accuracy=binomial_interval(correct,len(references)),confusion=confusion,
                  abstentions=sum(not set(h) for h in predictions),
                  multiple_labels=sum(len(set(h))>1 for h in predictions))
    return result


def characters(text: str) -> str:
    """NFKC/casefold; remove corpus tags, punctuation, symbols and whitespace."""
    text = re.sub(r"<[^>]*>", "", unicodedata.normalize("NFKC", text).casefold())
    return "".join(character for character in text if character.isalnum())


def words(text: str) -> list[str]:
    text = re.sub(r"<[^>]*>", " ", unicodedata.normalize("NFKC", text).casefold()).replace("’", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text)


def edit_counts(reference, hypothesis) -> dict:
    from rapidfuzz.distance import Levenshtein
    operations = Counter(operation.tag for operation in Levenshtein.editops(reference, hypothesis))
    errors = sum(operations.values())
    return {"reference_units": len(reference), "hypothesis_units": len(hypothesis),
            "substitutions": operations["replace"], "deletions": operations["delete"],
            "insertions": operations["insert"], "errors": errors,
            "error_rate": errors / len(reference) if reference else None}


def _intervals(values: list[dict]) -> list[tuple[int, int, str]]:
    intervals = []
    for item in values:
        if item.get("speaker") is None:
            continue
        start, end = item["start_ms"], item["end_ms"]
        if type(start) is not int or type(end) is not int or start < 0 or end < start:
            raise ValueError("Invalid reference or hypothesis millisecond interval")
        if end > start:
            intervals.append((start, end, str(item["speaker"])))
    return intervals


def diarization(reference: list[dict], hypothesis: list[dict], duration_ms: int, collar_ms: int = 0) -> dict:
    """Overlap-inclusive DER with an exact one-to-one speaker assignment."""
    if type(duration_ms) is not int or duration_ms <= 0 or type(collar_ms) is not int or collar_ms < 0:
        raise ValueError("Invalid evaluation duration/collar")
    ref, hyp = _intervals(reference), _intervals(hypothesis)
    if any(end > duration_ms for _, end, _ in ref + hyp):
        raise ValueError("Interval outside evaluation duration")
    ref_labels = sorted({label for _, _, label in ref})
    hyp_labels = sorted({label for _, _, label in hyp})
    if len(ref_labels) > 16:
        raise ValueError("Exact speaker assignment supports at most 16 reference speakers")
    boundaries = {0, duration_ms}
    for start, end, _ in ref + hyp:
        boundaries.update((start, end))
    ref_boundaries = {value for start, end, _ in ref for value in (start, end)}
    if collar_ms:
        boundaries.update(max(0, min(duration_ms, value + shift)) for value in ref_boundaries for shift in (-collar_ms, collar_ms))
    points, frames, weights = sorted(boundaries), [], defaultdict(int)
    excluded_ms = 0
    for start, end in zip(points, points[1:]):
        midpoint = (start + end) / 2
        if collar_ms and any(abs(midpoint - boundary) < collar_ms for boundary in ref_boundaries):
            excluded_ms += end - start
            continue
        r = {label for left, right, label in ref if left < end and right > start}
        h = {label for left, right, label in hyp if left < end and right > start}
        frames.append((end - start, r, h))
        for predicted in h:
            for expected in r:
                weights[predicted, expected] += end - start

    @lru_cache(None)
    def assign(index, used):
        if index == len(hyp_labels):
            return 0, ()
        best_score, best_path = assign(index + 1, used)
        best_path = (None,) + best_path
        for j, expected in enumerate(ref_labels):
            weight = weights[hyp_labels[index], expected]
            if used & (1 << j) or not weight:
                continue
            score, path = assign(index + 1, used | (1 << j))
            if score + weight > best_score:
                best_score, best_path = score + weight, (expected,) + path
        return best_score, best_path

    _, assignment = assign(0, 0)
    mapping = {label: expected for label, expected in zip(hyp_labels, assignment) if expected is not None}
    missed = false_alarm = confusion = reference_time = overlap_time = 0
    for duration, r, h in frames:
        correct = len(r & {mapping[label] for label in h if label in mapping})
        reference_time += duration * len(r)
        missed += duration * max(0, len(r) - len(h))
        false_alarm += duration * max(0, len(h) - len(r))
        confusion += duration * (min(len(r), len(h)) - correct)
        if len(r) > 1:
            overlap_time += duration
    error = missed + false_alarm + confusion
    return {"der": error / reference_time if reference_time else None,
            "missed_speaker_ms": missed, "false_alarm_speaker_ms": false_alarm,
            "confusion_speaker_ms": confusion, "reference_speaker_ms": reference_time,
            "reference_overlap_ms": overlap_time, "excluded_collar_ms": excluded_ms,
            "reference_speakers": len(ref_labels), "hypothesis_speakers": len(hyp_labels),
            "collar_ms": collar_ms, "overlap_included": True, "speaker_mapping": mapping}


def event_detection(aliases: list[str], observations: list[dict]) -> dict:
    labels = [item["label"] for item in observations if isinstance(item.get("label"), str)]
    matched = []
    for label in labels:
        normalized = unicodedata.normalize("NFKC", label).casefold()
        for alias in aliases:
            alias = unicodedata.normalize("NFKC", alias).casefold()
            pattern = r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])" if re.fullmatch(r"[a-z -]+", alias) else re.escape(alias)
            if re.search(pattern, normalized):
                matched.append(label)
                break
    return {"target_detected": bool(matched), "matched_labels": matched, "predicted_labels": labels,
            "extra_labels_unscored": [label for label in labels if label not in matched]}


def evaluate(dataset: dict, predictions: dict) -> dict:
    cases = dataset["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate reference case ID")
    raw_predictions = predictions["cases"]
    if len({case["id"] for case in raw_predictions}) != len(raw_predictions):
        raise ValueError("Duplicate prediction case ID")
    by_id = {case["id"]: case for case in raw_predictions}
    if set(by_id) != {case["id"] for case in cases}:
        raise ValueError("Reference and prediction case IDs must match exactly")
    scores, groups = [], {}
    for case in cases:
        prediction = by_id[case["id"]]
        transcript = prediction.get("transcript") or {"text": ""}
        text = transcript.get("text", "")
        reference = case.get("text", "")
        score = {"id": case["id"], "group": case.get("group", "default"), "status": prediction["status"],
                 "cer": edit_counts(characters(reference), characters(text))}
        if case.get("language", "").startswith("en"):
            score["wer"] = edit_counts(words(reference), words(text))
        if "segments" in case:
            predicted_segments = [{"start_ms": item["start"], "end_ms": item["end"], "speaker": item.get("spk")}
                                  for item in transcript.get("sentence_info", [])]
            score["diarization"] = {str(collar): diarization(case["segments"], predicted_segments, case["duration_ms"], collar)
                                    for collar in (0, 250)}
        if "acceptable_event_labels" in case:
            score["event_detection"] = event_detection(case["acceptable_event_labels"], (prediction.get("analysis") or {}).get("events", []))
        if case.get("expect_silence"):
            score["silence"] = {"speech_hallucinated": bool(characters(text)),
                                "event_false_alarm": bool((prediction.get("analysis") or {}).get("events"))}
        scores.append(score)
    for group in sorted({score["group"] for score in scores}):
        selected = [score for score in scores if score["group"] == group]
        summary = {"cases": len(selected), "status_counts": dict(Counter(s["status"] for s in selected))}
        for name in ("cer", "wer"):
            values = [score[name] for score in selected if name in score]
            if values:
                totals = {key: sum(value[key] for value in values) for key in
                          ("reference_units", "hypothesis_units", "substitutions", "deletions", "insertions", "errors")}
                totals["error_rate"] = totals["errors"] / totals["reference_units"] if totals["reference_units"] else None
                summary[name] = totals
        events = [s["event_detection"] for s in selected if "event_detection" in s]
        if events:
            summary["event_detection"] = {"cases": len(events), "detected": sum(s["target_detected"] for s in events),
                                          "recall": sum(s["target_detected"] for s in events) / len(events),
                                          "precision": None, "precision_note": "Single-label references do not exhaustively annotate secondary sounds"}
        groups[group] = summary
    return {"schema_version": "sonovect/accuracy-report-v1", "evaluator_version": EVALUATOR_VERSION,
            "case_count": len(scores), "reference_authority": dataset.get("reference_authority"),
            "policies": {"text": "NFKC, casefold, remove corpus angle tags, punctuation/symbols; retain fillers and lexical content",
                         "meeting_order": "Reference and predicted text use segment onset order; not permutation-invariant cpCER",
                         "failure_handling": "Missing/failed predictions remain in the denominator as empty transcripts",
                         "diarization": "Exact optimal one-to-one overlap assignment, overlaps included, collars 0/250 ms",
                         "events": "Frozen bilingual label aliases; extra unannotated labels are not declared false positives"},
            "groups": groups, "cases": scores}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score saved model predictions against independent references; no network requests")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    dataset, predictions = args.dataset.read_bytes(), args.predictions.read_bytes()
    result = evaluate(json.loads(dataset), json.loads(predictions))
    result["dataset_sha256"] = hashlib.sha256(dataset).hexdigest()
    result["predictions_sha256"] = hashlib.sha256(predictions).hexdigest()
    with args.report.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"case_count": result["case_count"], "groups": result["groups"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
