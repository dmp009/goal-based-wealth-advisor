"""Deterministic MiFID-style profile scoring (design §6.4, §9.2)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from wealthadvisor.clients.models import Client
from wealthadvisor.config import load_questionnaire

DAYS_PER_YEAR = 365.25
KNOWLEDGE_FAMILIES = ("etf_equity", "etf_bond", "structured")


class ProfileResult(BaseModel):
    profile: int
    raw_score: float
    rules_fired: list[str]
    knowledge: dict[str, bool]


def client_horizon_years(client: Client, today: date) -> float:
    """Longest goal horizon in years, measured from ``today``."""
    if not client.goals:
        raise ValueError(f"client {client.client_id} has no goals")
    return max((g.date - today).days for g in client.goals) / DAYS_PER_YEAR


def _raw_score(answers: dict[str, str], q: dict) -> float:
    total = 0.0
    for section in q["sections"].values():
        got = best = 0
        for qid, question in section["questions"].items():
            scores = question["answers"]
            if answers[qid] not in scores:
                raise ValueError(f"unknown answer {answers[qid]!r} for question {qid!r}")
            got += scores[answers[qid]]
            best += max(scores.values())
        total += section["weight"] * got / best
    return 1 + 6 * total


def score_profile(client: Client, today: date) -> ProfileResult:
    q = load_questionnaire()
    raw = _raw_score(client.answers, q)
    profile = 1 + sum(raw >= t for t in q["thresholds"])
    caps = q["caps"]
    horizon = client_horizon_years(client, today)
    knowledge = {f: client.answers[f] != "none" for f in KNOWLEDGE_FAMILIES}

    rules: list[str] = []

    def cap(limit: int, sentence: str) -> None:
        nonlocal profile
        if profile > limit:
            rules.append(sentence)
            profile = limit

    if horizon < 3:
        cap(
            caps["horizon_lt_3y"],
            f"Longest goal horizon is {horizon:.1f} years (less than 3 years): "
            f"profile capped at {caps['horizon_lt_3y']}.",
        )
    elif horizon <= 5:
        cap(
            caps["horizon_3_to_5y"],
            f"Longest goal horizon is {horizon:.1f} years (3 to 5 years): "
            f"profile capped at {caps['horizon_3_to_5y']}.",
        )
    if client.answers["loss_capacity"] == "low":
        cap(
            caps["loss_capacity_low"],
            f"Loss capacity is low: profile capped at {caps['loss_capacity_low']}.",
        )
    if not knowledge["etf_equity"]:
        cap(
            caps["no_equity_etf_knowledge"],
            f"No knowledge of equity ETFs: profile capped at {caps['no_equity_etf_knowledge']}.",
        )
    return ProfileResult(
        profile=profile, raw_score=round(raw, 4), rules_fired=rules, knowledge=knowledge
    )
