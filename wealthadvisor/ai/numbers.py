"""Number extraction from EN/FR text and verification against engine facts (design §9.5).

Facts naming (ruling R2): numeric leaves only under keys ending ``_pct`` (percent units),
``_eur``, ``_year``, ``_count`` or ``age``. Booleans are not numbers. Every number written inside
a text leaf of the facts (rules, reasons, constraints, ...) is also allowed.

Conventions:
- Signs are ignored when matching (a drawdown of -15.0 may be written "15 %").
- Numbers 1-10 written as words are not checked; ordinal list markers ("1.") are ignored.
- ``age`` tokens ("68 ans") that are really durations ("sur 5 ans") fall back to plain matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["percent", "eur", "year", "age", "plain"]

PCT_TOL = 0.5  # pp
TEXT_TOL = 0.05
EUR_REL_TOL = 0.01
EUR_MIN_TOL = 1.0


@dataclass(frozen=True)
class NumberToken:
    value: float
    kind: Kind
    raw: str


_SP = "   "
_BODY = (
    rf"(?:\d{{1,3}}(?:[{_SP}]\d{{3}})+(?:[.,]\d+)?"  # space-grouped (FR, also EN)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # comma-grouped (EN)
    r"|\d+(?:[.,]\d+)?)"  # plain
)
_PATTERN = re.compile(
    r"(?<![\w])"
    rf"(?P<pre>(?:€|EUR|eur)[{_SP}]?)?"
    r"(?P<sign>[-−](?=\d))?"
    rf"(?P<body>{_BODY})"
    rf"(?P<mult>[{_SP}]?(?:thousand|milliards?|millions?|mille|billion|Md|mn|M|k|K)(?![A-Za-z]))?"
    rf"(?:(?P<post>[{_SP}]?(?:%|pour[{_SP}]?cent|per[{_SP}]?cent|percent|pp|€|EUR|eur|euros?)"
    r"(?![A-Za-z]))"
    rf"|(?P<age>[{_SP}-]?(?:years?[ -]old|ans)(?![A-Za-z])))?"
    r"(?![\w])"
)
_MULT = {
    "k": 1e3,
    "thousand": 1e3,
    "mille": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "md": 1e9,
    "billion": 1e9,
    "milliard": 1e9,
    "milliards": 1e9,
}
_AMBIGUOUS_MULT = {"m", "mn", "md"}
_RANGE_BETWEEN = re.compile(r"^[ ]?[-–—][ ]?$")
_LINE_PREFIX = " \t#*>-_"


def _parse(body: str, lang: str) -> float:
    s = re.sub(rf"[{_SP}]", "", body)
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        return float(s.replace(thou, "").replace(dec, "."))
    if "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s) and (lang == "en" or s.count(",") > 1):
            return float(s.replace(",", ""))
        return float(s.replace(",", "."))
    return float(s)


def _is_list_marker(text: str, m: re.Match) -> bool:
    line_start = text.rfind("\n", 0, m.start()) + 1
    prefix = text[line_start : m.start()]
    if prefix.strip(_LINE_PREFIX):
        return False
    if m.group("pre") or m.group("sign") or m.group("mult") or m.group("post") or m.group("age"):
        return False
    rest = text[m.end() : m.end() + 2]
    return bool(re.fullmatch(r"\d+", m.group("body"))) and bool(re.match(r"[.)](\s|$)", rest))


def extract_numbers(text: str, lang: Literal["en", "fr"]) -> list[NumberToken]:
    raw_tokens: list[tuple[re.Match, float, Kind, float]] = []
    for m in _PATTERN.finditer(text):
        if _is_list_marker(text, m):
            continue
        value = _parse(m.group("body"), lang)
        mult_word = (m.group("mult") or "").strip().lower()
        has_cur = bool(m.group("pre")) or (
            m.group("post") is not None
            and m.group("post").strip().lower() in ("€", "eur", "euro", "euros")
        )
        factor = 1.0
        if mult_word and (mult_word not in _AMBIGUOUS_MULT or has_cur):
            factor = _MULT[mult_word]
        elif mult_word:
            # "5 M" with no currency: not an amount; the letter is just consumed
            factor = 1.0
        post = (m.group("post") or "").strip().lower()
        kind: Kind
        if has_cur or (factor > 1.0 and not post):
            kind = "eur"
        elif post and post not in ("€", "eur", "euro", "euros"):
            kind = "percent"
        elif m.group("age"):
            kind = "age"
        elif (
            re.fullmatch(r"\d{4}", m.group("body"))
            and not m.group("sign")
            and 1900 <= value <= 2100
        ):
            kind = "year"
        else:
            kind = "plain"
        if m.group("sign"):
            value = -value
        raw_tokens.append((m, value * factor if kind == "eur" else value, kind, factor))

    # ranges "3–5 %": the first bound inherits percent/eur from the second
    for i in range(len(raw_tokens) - 1):
        m1, v1, k1, _ = raw_tokens[i]
        m2, _, k2, f2 = raw_tokens[i + 1]
        if (
            k1 == "plain"
            and k2 in ("percent", "eur")
            and _RANGE_BETWEEN.match(text[m1.end() : m2.start()])
        ):
            raw_tokens[i] = (m1, v1 * f2 if k2 == "eur" else v1, k2, f2)
    return [NumberToken(v, k, text[m.start() : m.end()].strip()) for m, v, k, _ in raw_tokens]


# ---------------------------------------------------------------- verification


@dataclass
class _Allowed:
    pct: list[float]
    eur: list[float]
    year: set[int]
    age: list[float]
    anynum: list[float]
    text: list[float]
    text_years: set[int]


def _collect(facts: dict) -> _Allowed:
    a = _Allowed([], [], set(), [], [], [], set())

    def walk(obj, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "disclaimer":
                    continue
                walk(v, k)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, key)
        elif isinstance(obj, bool):
            return
        elif isinstance(obj, (int, float)):
            v = float(obj)
            a.anynum.append(v)
            if key and key.endswith("_pct"):
                a.pct.append(v)
            elif key and key.endswith("_eur"):
                a.eur.append(v)
            elif key and key.endswith("_year"):
                a.year.add(int(v))
            elif key == "age":
                a.age.append(v)
        elif isinstance(obj, str):
            for lang in ("en", "fr"):
                for t in extract_numbers(obj, lang):  # type: ignore[arg-type]
                    a.text.append(t.value)
                    if t.kind == "year":
                        a.text_years.add(int(t.value))

    walk(facts, None)
    return a


def _near(x: float, pool: list[float], tol: float) -> bool:
    return any(abs(abs(x) - abs(p)) <= tol + 1e-9 for p in pool)


def _matches(t: NumberToken, a: _Allowed) -> bool:
    v = t.value
    if t.kind == "percent":
        return (
            _near(v, a.pct, PCT_TOL)
            or any(abs(abs(v) - round(abs(p))) < 1e-9 for p in a.pct)
            or _near(v, a.text, TEXT_TOL)
        )
    if t.kind == "eur":
        pool = a.eur + a.text
        return any(abs(abs(v) - abs(p)) <= max(EUR_MIN_TOL, EUR_REL_TOL * abs(p)) for p in pool)
    if t.kind == "year":
        return int(v) in a.year or int(v) in a.text_years
    if t.kind == "age" and re.search(r"ans$", t.raw):
        return _near(v, a.age, 1e-9) or _near(v, a.anynum, 1e-9) or _near(v, a.text, TEXT_TOL)
    if t.kind == "age":
        return _near(v, a.age, 1e-9)
    return _near(v, a.anynum, 1e-6) or _near(v, a.text, TEXT_TOL)


def verify(
    text: str,
    lang: Literal["en", "fr"],
    facts: dict,
    disclaimers: list[str] | None = None,
) -> list[str]:
    """Mismatch messages for numbers in ``text`` that the facts do not support (empty = OK)."""
    if disclaimers is None:
        disclaimers = [d for d in (facts.get("disclaimer") or {}).values() if isinstance(d, str)]
    for d in sorted(disclaimers, key=len, reverse=True):
        if d:
            text = text.replace(d, " ")
    allowed = _collect(facts)
    errors = []
    for t in extract_numbers(text, lang):
        if not _matches(t, allowed):
            errors.append(
                f"'{t.raw}' ({t.kind} {t.value:g}) does not match any number in the facts"
            )
    return errors
