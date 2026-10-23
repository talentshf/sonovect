"""Conservative guard for optional free-text audible voice observations."""
import re

DISALLOWED = re.compile(
    r"\b(?:male|female|man|woman|men|women|boy|girl|child|children|teenager|"
    r"young|elderly|adult|infant|masculine|feminine|gender|aged|years?[- ]old|"
    r"personality|diagnosis|diagnosed|disorder|disease|autistic|bipolar|schizophrenic)\b"
    r"|男性|女性|男人|女人|男声|女声|男孩|女孩|性别|青年|中年|老年|年轻|年长|儿童|年龄|\d+\s*岁|人格|诊断|抑郁症|自闭症",
    re.IGNORECASE,
)


def audible_description(value):
    # Do not salvage demographic-relative pitch claims by inventing a new
    # absolute description. Omit the whole uncertain field instead.
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if len(value) <= 512 and not DISALLOWED.search(value) else ""
