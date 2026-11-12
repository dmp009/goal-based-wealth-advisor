"""Simplified 2026 French tax (design §9.7). No IR option, no inheritance rules.

Simplifications: the assurance-vie allowance is applied once to the gain being taxed
(not per year of withdrawals); Livret A is tax free; fonds en euros held inside an AV
follow the AV rule.
"""

from __future__ import annotations

from wealthadvisor.config import load_tax_rules


def tax_on_gain(
    wrapper: str, gain: float, years_held: float, household: str, rules: dict | None = None
) -> float:
    if gain <= 0:
        return 0.0
    r = rules or load_tax_rules()
    if wrapper == "livret_a":
        return gain * r["livret_a"]["rate"]
    if wrapper == "pea":
        p = r["pea"]
        rate = p["rate_after_5y"] if years_held >= p["threshold_years"] else p["rate_before_5y"]
        return gain * rate
    if wrapper in ("av", "fonds_euros"):
        a = r["assurance_vie"]
        if years_held >= a["threshold_years"]:
            allowance = a["allowance_couple" if household == "couple" else "allowance_single"]
            return max(0.0, gain - allowance) * a["rate_after_8y"]
        return gain * a["rate_before_8y"]
    if wrapper == "cto":
        return gain * r["cto"]["rate"]
    raise ValueError(f"unknown wrapper {wrapper!r}")


def weighted_average_cost(lots: list[tuple[float, float]]) -> float:
    """PRU: sum(units * price) / sum(units) over (units, price) lots."""
    units = sum(u for u, _ in lots)
    if units <= 0:
        raise ValueError("no units")
    return sum(u * p for u, p in lots) / units
