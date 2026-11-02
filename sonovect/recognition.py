"""One recognition, native transcript view and preserved word evidence."""
from dataclasses import dataclass


@dataclass
class Recognition:
    transcript: dict
    analysis: dict
    evidence: dict

    def __iter__(self):
        # Keep existing in-process callers that unpack the two native layers.
        return iter((self.transcript, self.analysis))


def speech_evidence(value, transcript):
    sentences = []
    segments = value.get("segments")
    for index, sentence in enumerate(transcript.get("sentence_info") or []):
        row = {"sentence_id": index, "text": sentence["text"],
               "begin_time": sentence["start"], "end_time": sentence["end"]}
        if "spk" in sentence:
            row["speaker_id"] = sentence["spk"]
        # Never derive word text by splitting or interpolating transcript text.
        segment = next((s for s in segments or [] if isinstance(s, dict)
                        and s.get("start_ms") == sentence["start"] and s.get("end_ms") == sentence["end"]
                        and s.get("text") == sentence["text"]), {})
        words = []
        for word in segment.get("words", []):
            if (isinstance(word, dict) and isinstance(word.get("text"), str)
                    and type(word.get("start_ms")) is int and type(word.get("end_ms")) is int
                    and sentence["start"] <= word["start_ms"] <= word["end_ms"] <= sentence["end"]):
                words.append({"text": word["text"], "begin_time": word["start_ms"], "end_time": word["end_ms"]})
        if words:
            row["words"] = words
        sentences.append(row)
    if not sentences and transcript["text"].strip():
        sentences = [{"sentence_id": 0, "text": transcript["text"]}]
    return {"transcripts": [{"channel_id": 0, "text": transcript["text"], "sentences": sentences}]}
