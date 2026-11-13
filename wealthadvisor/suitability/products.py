"""Product-family suitability checks (design §6.4)."""

from __future__ import annotations

from pydantic import BaseModel

from wealthadvisor.clients.models import Client
from wealthadvisor.config import load_structured
from wealthadvisor.i18n import Msg
from wealthadvisor.suitability.scoring import ProfileResult

FAMILIES = ("livret_a", "fonds_euros", "etf_bond", "etf_equity", "structured")


class Suitability(BaseModel):
    included: bool
    reasons: list[str]
    warnings: list[str] = []
    reason_msgs: list[Msg] = []  # same sentences as code + params (PDF translation)
    warning_msgs: list[Msg] = []


def _suit(included: bool, reasons: list[Msg], warnings: list[Msg] | None = None) -> Suitability:
    warnings = warnings or []
    return Suitability(
        included=included,
        reasons=[m.render("en") for m in reasons],
        warnings=[m.render("en") for m in warnings],
        reason_msgs=reasons,
        warning_msgs=warnings,
    )


def _knowledge_warning(client: Client, family: str, label: str) -> list[Msg]:
    if client.answers.get(family, "none") != "none":
        return []
    return [Msg(code="suit.no_knowledge", params={"label": label})]


def check_product(
    product_family: str, client: Client, profile: ProfileResult, horizon_years: float
) -> Suitability:
    if product_family not in FAMILIES:
        raise ValueError(f"unknown product family {product_family!r}")
    p = profile.profile
    if product_family in ("livret_a", "fonds_euros"):
        return _suit(True, [Msg(code="suit.guaranteed")])
    if product_family == "etf_bond":
        return _suit(
            True,
            [Msg(code="suit.bond_allowed", params={"p": p})],
            _knowledge_warning(client, "etf_bond", "bond ETFs"),
        )
    if product_family == "etf_equity":
        if p >= 2:
            return _suit(
                True,
                [Msg(code="suit.equity_allowed", params={"p": p})],
                _knowledge_warning(client, "etf_equity", "equity ETFs"),
            )
        return _suit(False, [Msg(code="suit.equity_requires", params={"p": p})])

    elig = load_structured()["eligibility"]
    reasons: list[Msg] = []
    if p < elig["min_profile"]:
        reasons.append(
            Msg(
                code="suit.structured_min_profile",
                params={"min_profile": elig["min_profile"], "p": p},
            )
        )
    if horizon_years < elig["min_horizon_years"]:
        reasons.append(
            Msg(
                code="suit.structured_min_horizon",
                params={"min_years": elig["min_horizon_years"], "horizon": horizon_years},
            )
        )
    if client.answers.get("structured", "none") == "none":
        reasons.append(Msg(code="suit.structured_no_knowledge"))
    if reasons:
        return _suit(False, reasons)
    return _suit(True, [Msg(code="suit.structured_ok")])
