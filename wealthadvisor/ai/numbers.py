"""Number extraction from EN/FR text and verification against engine facts (design §9.5).

Facts naming (ruling R2): numeric leaves only under keys ending ``_pct`` (percent units),
``_eur``, ``_year``, ``_count`` or ``age``. Booleans are not numbers. Every number written inside
a text leaf of the facts (rules, reasons, constraints, ...) is also allowed (percent and euro
amounts only when written as such in their source text).

Matching rules:
- Fail closed: any digit run that is not an extracted number token (e.g. "3D", "FR0011869353") is an
  error unless its enclosing word appears verbatim in a text leaf (or key) of the facts.
- Signs: a token with an explicit minus must match a negative fact; unsigned tokens match abs().
- Percent tolerance scales with the written precision (one decimal: +-0.05 pp; integer: +-0.5 pp).
- EUR: +-1 % (min 1 EUR; zero facts match only 0); thousands/millions suffixes are normalised.
- Goal scoping (R10): text is split into lines (a Markdown heading that names exactly one goal
  scopes the lines under it). A block naming exactly one goal (label or goal id) may only use that
  goal's numbers plus the non-goal numbers. Blocks naming no goal or several use all numbers.
  Remaining limitation: a goal described without its label/id, or two goals in one sentence, is
  matched globally, so a figure of another goal can still slip through there.
- Residual limits: unitless plain digits match any numeric leaf within the scope (all leaves
  outside any goal scope), and body lines are scoped only by a verbatim goal label (the goal id,
  an ordinary word such as "retirement", scopes headings only).
- Basis points are converted to percent; hundred/centaines/milliers are multipliers.
- Numbers 1-10 written as words are not checked; ordinal list markers ("1.") are ignored.
- ``age`` tokens followed by "ans" without an age context are durations ("sur 5 ans") and fall
  back to plain matching; "year-old", "age of", "aged", "âge", "vous avez" are strict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["percent", "eur", "year", "age", "duration", "plain"]

TEXT_TOL = 0.05
EUR_REL_TOL = 0.01
EUR_MIN_TOL = 1.0


@dataclass(frozen=True)
class NumberToken:
    value: float
    kind: Kind
    raw: str
    span: tuple[int, int] = field(default=(0, 0), compare=False)
    decimals: int = field(default=0, compare=False)
    strict: bool = field(default=True, compare=False)
    plus: bool = field(default=False, compare=False)


_SP = "   "
_BODY = (
    rf"(?:\d{{1,3}}(?:[{_SP}]\d{{3}})+(?:[.,]\d+)?"  # space-grouped (FR, also EN)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # comma-grouped (EN)
    r"|\d{1,3}(?:\.\d{3}){2,}"  # dot-grouped (FR), 2+ groups
    r"|\d+(?:[.,]\d+)?)"  # plain
)
_CUR = ("€", "eur", "euro", "euros")
_PATTERN = re.compile(
    r"(?<![\w])"
    rf"(?P<pre>(?:€|EUR|eur)[{_SP}]?)?"
    r"(?P<sign>[-−+](?=\d))?"
    rf"(?P<body>{_BODY})"
    rf"(?P<mult>[{_SP}]?(?:thousand|hundreds?|centaines?|milliers?|milliards?|millions?|mille|billion|mln|Mrds?|Mds?|Mio|bn|mn|M|m|k|K)"
    r"(?![A-Za-z]))?"
    rf"(?:(?P<post>[{_SP}]?(?:%|points?[{_SP}]de[{_SP}]base|basis[{_SP}]points?|bps?|pour[{_SP}]?cent|per[{_SP}]?cent|percent|pct|pp|pts?|points?"
    r"|€|EUR|eur|euros?)(?![A-Za-z]))"
    rf"|(?P<age>[{_SP}-]?(?:years?[ -]old|ans)(?![A-Za-z]))"
    rf"|(?P<dur>[{_SP}-]?(?:years?|yrs?|y|ans?|mois|months?)(?![A-Za-z]))"
    r"|(?P<unit>(?:x|×|s)(?![A-Za-z])))?"
    r"(?![\w])"
)
_ORDINAL = re.compile(
    r"(?<![\w])(?:(?:[1-9]|10)(?:st|nd|rd|th|er|ère|ème|e)(?![A-Za-z])"
    r"|(?:10|50|90)(?:th|e|ème)(?=[ \u00a0]+(?:percentile|centile)))"
)
_MULT = {
    "k": 1e3,
    "hundred": 1e2,
    "hundreds": 1e2,
    "centaine": 1e2,
    "centaines": 1e2,
    "millier": 1e3,
    "milliers": 1e3,
    "thousand": 1e3,
    "mille": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "mln": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "md": 1e9,
    "mds": 1e9,
    "mrd": 1e9,
    "mrds": 1e9,
    "mio": 1e6,
    "bn": 1e9,
    "billion": 1e9,
    "milliard": 1e9,
    "milliards": 1e9,
}
_AMBIGUOUS_MULT = {"m", "mn"}
_RANGE_BETWEEN = re.compile(r"^[ ]?[-–—][ ]?$")
_LINE_PREFIX = " \t#*>-_"
_AGE_CTX = re.compile(
    r"(?:\bage|\baged|\bâge|\bvous avez|\byou are)\s+(?:of\s+|de\s+)?$", re.IGNORECASE
)


def _parse(body: str, lang: str) -> tuple[float, int]:
    s = re.sub(rf"[{_SP}]", "", body)
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        return float(s.replace(thou, "").replace(dec, ".")), len(s) - s.rfind(dec) - 1
    if "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s) and (lang == "en" or s.count(",") > 1):
            return float(s.replace(",", "")), 0
        return float(s.replace(",", ".")), len(s) - s.rfind(",") - 1
    if re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", s):
        return float(s.replace(".", "")), 0
    if "." in s:
        return float(s), len(s) - s.rfind(".") - 1
    return float(s), 0


def _is_list_marker(text: str, m: re.Match) -> bool:
    line_start = text.rfind("\n", 0, m.start()) + 1
    prefix = text[line_start : m.start()]
    if prefix.strip(_LINE_PREFIX):
        return False
    if any(m.group(g) for g in ("pre", "sign", "mult", "post", "age", "dur", "unit")):
        return False
    rest = text[m.end() : m.end() + 2]
    return bool(re.fullmatch(r"\d+", m.group("body"))) and bool(re.match(r"[.)](\s|$)", rest))


def _scan(text: str, lang: str) -> tuple[list[NumberToken], list[tuple[int, int]]]:
    """Tokens plus the spans deliberately ignored (list markers, small ordinals)."""
    raw_tokens: list[list] = []
    ignored: list[tuple[int, int]] = [m.span() for m in _ORDINAL.finditer(text)]
    for m in _PATTERN.finditer(text):
        if _is_list_marker(text, m):
            ignored.append(m.span())
            continue
        value, decimals = _parse(m.group("body"), lang)
        mult_word = (m.group("mult") or "").strip().lower()
        post = (m.group("post") or "").strip().lower()
        has_cur = bool(m.group("pre")) or post in _CUR
        if has_cur and re.fullmatch(r"\d{1,3}\.\d{3}", m.group("body")):
            value, decimals = float(m.group("body").replace(".", "")), 0  # FR "12.600 €"
        factor = 1.0
        if mult_word and (mult_word not in _AMBIGUOUS_MULT or has_cur):
            factor = _MULT[mult_word]
        strict = True
        kind: Kind
        if has_cur or (factor > 1.0 and not post):
            kind = "eur"
        elif post:
            kind = "percent"
            if re.match(rf"bps?$|basis|points?[{_SP}]de[{_SP}]base", post):
                value, decimals = value / 100, decimals + 2  # basis points -> percent
        elif m.group("age"):
            if re.search(r"year", m.group("age")) or _age_context(text, m):
                kind = "age"
            else:
                kind = "duration"  # "sur 5 ans"
        elif m.group("dur"):
            kind = "duration"
        elif _AGE_CTX.search(text[max(0, m.start() - 20) : m.start()]) and not m.group("unit"):
            kind = "age"
        elif (
            re.fullmatch(r"\d{4}", m.group("body"))
            and not m.group("sign")
            and 1900 <= value <= 2100
            and (not m.group("unit") or m.group("unit") == "s")
        ):
            kind = "year"
        else:
            kind = "plain"
        if m.group("sign") and m.group("sign") != "+":
            value = -value
        plus = m.group("sign") == "+"
        raw_tokens.append(
            [m, value * factor if kind == "eur" else value, kind, factor, decimals, strict, plus]
        )

    # ranges "3–5 %": the first bound inherits percent/eur from the second
    for i in range(len(raw_tokens) - 1):
        m1, v1, k1 = raw_tokens[i][:3]
        m2, _, k2, f2 = raw_tokens[i + 1][:4]
        if (
            k1 == "plain"
            and k2 in ("percent", "eur", "duration")
            and _RANGE_BETWEEN.match(text[m1.end() : m2.start()])
        ):
            raw_tokens[i][1] = v1 * f2 if k2 == "eur" else v1
            raw_tokens[i][2] = k2
    tokens = [
        NumberToken(v, k, text[m.start() : m.end()].strip(), m.span(), d, st, pl)
        for m, v, k, _, d, st, pl in raw_tokens
    ]
    return tokens, ignored


def _age_context(text: str, m: re.Match) -> bool:
    before = text[max(0, m.start() - 20) : m.start()]
    after = text[m.end() : m.end() + 12]
    if re.match(r"\s*(?:d['’]|de\b|du\b|des\b)", after):
        return False  # "14 ans d'horizon"
    return bool(_AGE_CTX.search(before) or re.search(r"âge", after, re.IGNORECASE))


def extract_numbers(text: str, lang: Literal["en", "fr"]) -> list[NumberToken]:
    return _scan(text, lang)[0]


# ---------------------------------------------------------------- verification


@dataclass
class _Allowed:
    pct: list[float] = field(default_factory=list)
    eur: list[float] = field(default_factory=list)
    year: set[int] = field(default_factory=set)
    age: list[float] = field(default_factory=list)
    anynum: list[float] = field(default_factory=list)
    text: list[float] = field(default_factory=list)
    text_pct: list[float] = field(default_factory=list)
    text_eur: list[float] = field(default_factory=list)
    text_years: set[int] = field(default_factory=set)
    dur: list[float] = field(default_factory=list)
    text_dur: list[float] = field(default_factory=list)
    words: set[str] = field(default_factory=set)


_PUNCT = ".,;:!?()[]{}\"'*_“”‘’«»"


def _norm_word(w: str) -> str:
    return w.strip(_PUNCT)


def _collect(objs: list) -> _Allowed:
    a = _Allowed()

    def walk(obj, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "disclaimer":
                    continue
                a.words.add(k)
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
            elif key and key.endswith(("_years_count", "_months_count")):
                a.dur.append(v)
            elif key and key.endswith("_year"):
                a.year.add(int(v))
            elif key == "age":
                a.age.append(v)
        elif isinstance(obj, str):
            for w in obj.split():
                a.words.add(_norm_word(w))
            # engine text is English: "39,257 EUR" is thousands-grouped, never 39.257
            for t in extract_numbers(obj, "en"):
                a.text.append(t.value)
                if t.kind == "year":
                    a.text_years.add(int(t.value))
                elif t.kind == "percent":
                    a.text_pct.append(t.value)
                elif t.kind == "eur":
                    a.text_eur.append(t.value)
                elif t.kind == "duration":
                    a.text_dur.append(t.value)

    for o in objs:
        walk(o, None)
    return a


def _near(v: float, pool: list[float], tol: float, plus: bool = False) -> bool:
    if plus:  # explicit plus: must match a positive fact
        return any(p > 0 and abs(v - p) <= tol + 1e-9 for p in pool)
    if v < 0:  # explicit minus: must match a negative fact
        return any(p < 0 and abs(v - p) <= tol + 1e-9 for p in pool)
    return any(abs(v - abs(p)) <= tol + 1e-9 for p in pool)


def _near_eur(v: float, pool: list[float], plus: bool = False) -> bool:
    for p in pool:
        if (v < 0 and p >= 0) or (plus and p <= 0):
            continue
        tol = 0.0 if p == 0 else max(EUR_MIN_TOL, EUR_REL_TOL * abs(p))
        if abs(abs(v) - abs(p)) <= tol + 1e-9:
            return True
    return False


def _matches(t: NumberToken, a: _Allowed) -> bool:
    v = t.value
    if t.kind == "percent":
        tol = 0.5 if t.decimals == 0 else 0.5 * 10 ** (-t.decimals)
        return _near(v, a.pct, tol, t.plus) or _near(v, a.text_pct, TEXT_TOL, t.plus)
    if t.kind == "eur":
        return _near_eur(v, a.eur + a.text_eur, t.plus)
    if t.kind == "duration":
        return _near(v, a.dur, 1e-9) or _near(v, a.text_dur, TEXT_TOL)
    if t.kind == "year":
        return int(v) in a.year or int(v) in a.text_years
    if t.kind == "age":
        return _near(v, a.age, 1e-9)
    return _near(v, a.anynum, 1e-6, t.plus) or _near(v, a.text, TEXT_TOL, t.plus)


_PERCENTILE = re.compile(r"^[Pp](?:10|50|90)$")


def _word_ok(word: str, words: set[str]) -> bool:
    if word in words:
        return True
    pieces = [p for p in re.split(r"[–—/-]", word) if re.search(r"\d", p)]
    return bool(pieces) and all(
        _norm_word(p) in words or _PERCENTILE.match(_norm_word(p)) for p in pieces
    )


def _uncovered(block: str, tokens, ignored, words: set[str]) -> list[str]:
    spans = [t.span for t in tokens] + ignored
    bad, seen = [], set()
    for m in re.finditer(r"\d+", block):
        if any(s <= m.start() < e for s, e in spans):
            continue
        i, j = m.start(), m.end()
        while i > 0 and not block[i - 1].isspace():
            i -= 1
        while j < len(block) and not block[j].isspace():
            j += 1
        word = _norm_word(block[i:j])
        if word not in seen and not _word_ok(word, words):
            seen.add(word)
            bad.append(word)
    return bad


def _goal_names(goals: list, with_ids: bool) -> list[list[re.Pattern]]:
    out = []
    for g in goals:
        pats = []
        if isinstance(g, dict):
            for key in ("label", "label_fr"):
                if g.get(key):
                    pats.append(re.compile(re.escape(_apos(str(g[key]))), re.IGNORECASE))
            if with_ids and g.get("goal_id"):
                pats.append(
                    re.compile(rf"(?<![\w]){re.escape(str(g['goal_id']))}(?![\w])", re.IGNORECASE)
                )
        out.append(pats)
    return out


def _apos(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'")


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
    goals = facts.get("goals") if isinstance(facts.get("goals"), list) else []
    global_allowed = _collect([facts])
    non_goal = {k: v for k, v in facts.items() if k != "goals"}
    scoped = [_collect([non_goal, g]) for g in goals]
    names = _goal_names(goals, with_ids=False)
    heading_names = _goal_names(goals, with_ids=True)

    def named(line: str, heading: bool) -> list[int]:
        flat = _apos(line)
        pool = heading_names if heading else names
        return [i for i, pats in enumerate(pool) if any(p.search(flat) for p in pats)]

    errors: list[str] = []
    scope: tuple[int, int] | None = None  # (goal index, heading level)
    for line in text.splitlines():
        if not line.strip():
            continue
        stripped = line.lstrip()
        hits = named(line, stripped.startswith("#"))
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if len(hits) == 1:
                scope = (hits[0], level)
            elif not (scope and not hits and level > scope[1]):
                scope = None  # same/higher level heading, or several goals: scope ends
        goal = hits[0] if len(hits) == 1 else (scope[0] if scope and not hits else None)
        allowed = scoped[goal] if goal is not None else global_allowed
        tokens, ignored = _scan(line, lang)
        for t in tokens:
            if not _matches(t, allowed):
                where = f" for goal '{goals[goal].get('label', goal)}'" if goal is not None else ""
                errors.append(
                    f"'{t.raw}' ({t.kind} {t.value:g}) does not match any number in the facts{where}"
                )
        for w in _uncovered(line, tokens, ignored, global_allowed.words):
            errors.append(f"'{w}' contains an unverifiable number")
    return errors
