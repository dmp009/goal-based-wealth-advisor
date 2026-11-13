"""Deterministic MiFID-style profile scoring (design §6.4, §9.2)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from wealthadvisor.clients.models import Client
from wealthadvisor.config import load_questionnaire
from wealthadvisor.i18n import Msg

DAYS_PER_YEAR = 365.25
KNOWLEDGE_FAMILIES = ("etf_equity", "etf_bond", "structured")


class ProfileResult(BaseModel):
    profile: int
    raw_score: float
    rules_fired: list[str]
    knowledge: dict[str, bool]
    constraints: list[str] = []  # every applicable cap, binding or not
    rules_fired_msgs: list[Msg] = []  # same sentences as code + params (PDF translation)
    constraints_msgs: list[Msg] = []


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
            if qid not in answers:
                raise ValueError(f"missing answer for question {qid!r}")
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
    constraints: list[str] = []
    rule_msgs: list[Msg] = []
    constraint_msgs: list[Msg] = []

    def cap(limit: int, code: str, **params) -> None:
        nonlocal profile
        msg = Msg(code=code, params={**params, "cap": limit})
        if profile > limit:
            rules.append(msg.render("en"))
            rule_msgs.append(msg)
            profile = limit
        else:
            msg = Msg(code=code, params={**msg.params, "not_binding": profile})
        constraints.append(msg.render("en"))
        constraint_msgs.append(msg)

    if horizon < 3:
        cap(caps["horizon_lt_3y"], "cap.horizon_lt_3y", horizon=horizon)
    elif horizon <= 5:
        cap(caps["horizon_3_to_5y"], "cap.horizon_3_to_5y", horizon=horizon)
    if client.answers["loss_capacity"] == "low":
        cap(caps["loss_capacity_low"], "cap.loss_capacity_low")
    if not knowledge["etf_equity"]:
        cap(caps["no_equity_etf_knowledge"], "cap.no_equity_etf_knowledge")
    return ProfileResult(
        profile=profile,
        raw_score=round(raw, 4),
        rules_fired=rules,
        knowledge=knowledge,
        constraints=constraints,
        rules_fired_msgs=rule_msgs,
        constraints_msgs=constraint_msgs,
    )
