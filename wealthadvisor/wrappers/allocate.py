"""Goal buckets and wrapper allocation (design §6.6, §9.2, §9.3).

Documented simplifications:
- Emergency fund is funded from ``liquid_assets`` first and is NOT topped up monthly.
- Debts are ignored: investable = liquid_assets - emergency fund funded.
- All monthly saving goes to the buckets.
- Initial funding: essential goals first, then by date; within a priority group proportional
  to inflated targets, a bucket never receiving more than the present value of its target at its
  safe rate. Surplus goes to the longest-horizon bucket (rule recorded).
- Monthly saving follows the same order, capped by the level annuity that closes each bucket's gap
  (target minus funding grown at the safe rate); leftover goes to the longest-horizon bucket.
- The PEA cap is checked against initial funding only (not cumulative monthly contributions);
  the Livret A room left after initial funding is used for monthly flows, not decremented per month.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from wealthadvisor.clients.models import Client
from wealthadvisor.config import ProfileRule, Settings, load_profiles
from wealthadvisor.suitability.scoring import DAYS_PER_YEAR


@dataclass
class EmergencyFund:
    target: float
    funded: float
    shortfall: float
    rules: list[str] = field(default_factory=list)


@dataclass
class Bucket:
    goal_id: str
    horizon_years: float
    risk: int
    funding_now: float
    monthly_contribution: float
    target_nominal: float
    wrapper_split: dict[str, float]
    safe_share: float
    rules: list[str]
    monthly_split: dict[str, float] = field(default_factory=dict)


@dataclass
class BucketPlan:
    emergency: EmergencyFund
    buckets: list[Bucket]


def bucket_risk(client_profile: int, horizon_years: float) -> int:
    """min(client profile, horizon cap): <3 y -> 2, 3-5 y -> 3, 5-8 y -> 4, else profile."""
    if horizon_years < 3:
        cap = 2
    elif horizon_years < 5:
        cap = 3
    elif horizon_years < 8:
        cap = 4
    else:
        cap = client_profile
    return min(client_profile, cap)


def inflate_target(target_today: float, years: float, inflation: float) -> float:
    return target_today * (1 + inflation) ** years


def _waterfill(total: float, weights: list[float], caps: list[float]) -> list[float]:
    """Proportional split of ``total`` by weights, no item above its cap."""
    out = [0.0] * len(weights)
    active = [i for i in range(len(weights)) if caps[i] > 0 and weights[i] > 0]
    left = total
    while active and left > 1e-9:
        wsum = sum(weights[i] for i in active)
        capped = [i for i in active if left * weights[i] / wsum >= caps[i] - out[i]]
        if not capped:
            for i in active:
                out[i] += left * weights[i] / wsum
            return out
        for i in capped:
            left -= caps[i] - out[i]
            out[i] = caps[i]
            active.remove(i)
    return out


def _split(
    amount: float, h: float, risk: int, profiles: dict[int, ProfileRule], st: dict, rules: list[str]
) -> dict[str, float]:
    """Wrapper split of ``amount``. ``st`` holds shared remaining 'livret' and 'pea' room."""
    if amount <= 1e-9:
        return {}
    prof = profiles[risk]
    safe = amount * prof.min_safe_share
    risky = amount - safe
    equity = min(risky, prof.max_equity * amount)
    bonds = risky - equity
    out: dict[str, float] = {}

    def add(k: str, v: float) -> None:
        if v > 1e-9:
            out[k] = out.get(k, 0.0) + v

    if safe > 0:
        if h < 3:
            la = min(safe, st["livret"])
            st["livret"] -= la
            add("livret_a", la)
            add("av", safe - la)
            rules.append(
                f"Safe sleeve with horizon < 3 y goes to Livret A within the remaining cap "
                f"({la:,.0f} EUR); overflow {safe - la:,.0f} EUR to fonds en euros in AV."
            )
        else:
            add("av", safe)
            rules.append("Safe sleeve with horizon >= 3 y goes to fonds en euros inside AV.")
    if equity > 0:
        if h >= 5 and st["pea"] > 0:
            pe = min(equity, st["pea"])
            st["pea"] -= pe
            add("pea", pe)
            rest_wrapper = "av" if h >= 3 else "cto"
            add(rest_wrapper, equity - pe)
            rules.append(
                f"Equity part with horizon >= 5 y goes to PEA while contributions stay below the "
                f"cap ({pe:,.0f} EUR); overflow {equity - pe:,.0f} EUR to {rest_wrapper.upper()}."
            )
        elif h >= 3:
            add("av", equity)
            rules.append("Equity part goes to AV (horizon >= 3 y, PEA not applicable or full).")
        else:
            add("cto", equity)
            rules.append("Equity part with horizon < 3 y goes to CTO.")
    if bonds > 0:
        w = "av" if h >= 3 else "cto"
        add(w, bonds)
        rules.append(
            f"Bond part of the risky sleeve goes to {w.upper()} (horizon {'>=' if h >= 3 else '<'} 3 y)."
        )
    return out


def plan_buckets(
    client: Client,
    profile: int,
    today: date,
    rates: dict,
    settings: Settings,
    profiles: dict[int, ProfileRule] | None = None,
) -> BucketPlan:
    profiles = profiles or load_profiles()
    la_cap = rates["livret_a_cap"]["value"]
    la_rate = rates["livret_a_rate"]["value"]
    fe_rate = rates["fonds_euros"]["value"]
    pea_cap = rates["pea_contribution_cap"]["value"]

    months = 6 if profile <= 3 else 3
    raw_target = months * client.monthly_expenses
    target = min(raw_target, la_cap)
    funded = min(target, max(0.0, client.liquid_assets))
    em_rules = [
        f"Emergency fund = {months} months of expenses (profile {profile}), held in Livret A."
    ]
    if raw_target > la_cap:
        em_rules.append(f"Target capped at the Livret A ceiling of {la_cap:,.0f} EUR.")
    if funded < target:
        em_rules.append(
            f"Shortfall of {target - funded:,.0f} EUR: liquid assets do not cover the target."
        )
    emergency = EmergencyFund(target, funded, target - funded, em_rules)

    investable = max(0.0, client.liquid_assets - funded)
    goals = sorted(client.goals, key=lambda g: (g.priority != "essential", g.date))
    n = len(goals)
    hs = [max(0.0, (g.date - today).days / DAYS_PER_YEAR) for g in goals]
    tgt = [inflate_target(g.target_today_eur, h, settings.inflation) for g, h in zip(goals, hs)]
    rate = [la_rate if h < 3 else fe_rate for h in hs]
    pv = [t / (1 + r) ** h for t, r, h in zip(tgt, rate, hs)]
    rules = [[] for _ in goals]

    def by_group(total: float, caps: list[float]) -> tuple[list[float], float]:
        alloc = [0.0] * n
        left = total
        for prio in ("essential", "aspirational"):
            idx = [i for i in range(n) if goals[i].priority == prio]
            if not idx or left <= 1e-9:
                continue
            got = _waterfill(left, [tgt[i] for i in idx], [caps[i] for i in idx])
            for i, v in zip(idx, got):
                alloc[i] = v
            left -= sum(got)
        return alloc, left

    init, surplus = by_group(investable, pv)
    longest = max(range(n), key=lambda i: hs[i]) if n else None
    if surplus > 1e-9 and longest is not None:
        init[longest] += surplus
        rules[longest].append(
            f"Surplus of {surplus:,.0f} EUR beyond all targets' present values goes to the "
            "longest-horizon bucket."
        )
    for i in range(n):
        rules[i].append(
            f"Initial funding {init[i]:,.0f} EUR: {goals[i].priority} goal, allocated by priority then "
            "date, proportional to inflated targets, capped at the target's present value."
        )

    # Monthly saving: capped by the level annuity closing the gap at the safe rate.
    caps_m = []
    for i in range(n):
        months_left = max(1.0, hs[i] * 12)
        rm = (1 + rate[i]) ** (1 / 12) - 1
        fv = init[i] * (1 + rate[i]) ** hs[i]
        gap = max(0.0, tgt[i] - fv)
        caps_m.append(gap * rm / ((1 + rm) ** months_left - 1) if rm > 0 else gap / months_left)
    mon, left_m = by_group(client.monthly_saving, caps_m)
    if left_m > 1e-9 and longest is not None:
        mon[longest] += left_m
        rules[longest].append(
            f"Monthly saving beyond all gaps ({left_m:,.0f} EUR) goes to the longest-horizon bucket."
        )

    st = {"livret": max(0.0, la_cap - funded), "pea": pea_cap}
    risks = [bucket_risk(profile, h) for h in hs]
    splits = [_split(init[i], hs[i], risks[i], profiles, st, rules[i]) for i in range(n)]
    msplits = []
    for i in range(n):
        mr: list[str] = []
        msplits.append(_split(mon[i], hs[i], risks[i], profiles, dict(st), mr))
        if mr:
            rules[i].append(
                "Monthly contribution follows the same wrapper rules (caps use room left after initial funding)."
            )

    buckets = [
        Bucket(
            goal_id=goals[i].goal_id,
            horizon_years=hs[i],
            risk=risks[i],
            funding_now=init[i],
            monthly_contribution=mon[i],
            target_nominal=tgt[i],
            wrapper_split=splits[i],
            safe_share=profiles[risks[i]].min_safe_share,
            rules=rules[i],
            monthly_split=msplits[i],
        )
        for i in range(n)
    ]
    return BucketPlan(emergency, buckets)
