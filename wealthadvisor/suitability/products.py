"""Product-family suitability checks (design §6.4)."""

from __future__ import annotations

from pydantic import BaseModel

from wealthadvisor.clients.models import Client
from wealthadvisor.config import load_structured
from wealthadvisor.suitability.scoring import ProfileResult

FAMILIES = ("livret_a", "fonds_euros", "etf_bond", "etf_equity", "structured")


class Suitability(BaseModel):
    included: bool
    reasons: list[str]
    warnings: list[str] = []


def _knowledge_warning(client: Client, family: str, label: str) -> list[str]:
    if client.answers.get(family, "none") != "none":
        return []
    msg = (
        f"Client declares no knowledge of {label}: appropriateness warning, "
        "the advisor must explain the risks before investing."
    )
    return [msg]


def check_product(
    product_family: str, client: Client, profile: ProfileResult, horizon_years: float
) -> Suitability:
    if product_family not in FAMILIES:
        raise ValueError(f"unknown product family {product_family!r}")
    p = profile.profile
    if product_family in ("livret_a", "fonds_euros"):
        return Suitability(
            included=True, reasons=["Capital-guaranteed product, suitable for every profile."]
        )
    if product_family == "etf_bond":
        return Suitability(
            included=True,
            reasons=[f"Bond ETFs are allowed from profile 1 (client profile {p})."],
            warnings=_knowledge_warning(client, "etf_bond", "bond ETFs"),
        )
    if product_family == "etf_equity":
        if p >= 2:
            return Suitability(
                included=True,
                reasons=[f"Equity ETFs are allowed from profile 2 (client profile {p})."],
                warnings=_knowledge_warning(client, "etf_equity", "equity ETFs"),
            )
        return Suitability(
            included=False,
            reasons=[f"Equity ETFs require profile 2 or higher (client profile {p})."],
        )

    elig = load_structured()["eligibility"]
    reasons = []
    if p < elig["min_profile"]:
        reasons.append(
            f"Structured products require profile {elig['min_profile']} or higher (client profile {p})."
        )
    if horizon_years < elig["min_horizon_years"]:
        reasons.append(
            f"Structured products require a horizon of at least {elig['min_horizon_years']} years "
            f"(client horizon {horizon_years:.1f} years)."
        )
    if client.answers.get("structured", "none") == "none":
        reasons.append("The client declares no knowledge of structured products.")
    if reasons:
        return Suitability(included=False, reasons=reasons)
    return Suitability(
        included=True,
        reasons=[
            "Profile, horizon and declared knowledge all meet the structured-product conditions."
        ],
    )
