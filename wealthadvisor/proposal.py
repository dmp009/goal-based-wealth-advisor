"""New-client proposal: suitability -> buckets/wrappers -> optimisers -> Monte Carlo -> structured.

``build_proposal`` wires the engine modules together; ``proposal_facts`` turns the result into the
JSON "facts" object the AI documents may cite (design §6.10, §9.5).

Documented conventions:
- "Today" is the snapshot's last price date (max date in ``fact_prices``).
- One shared risk model: Ledoit-Wolf covariance over the whole ETF universe, CMA expected returns.
- Optimisation runs once per bucket per method on the risky sleeve. If the bucket uses the PEA
  (initial or monthly split), the equity universe is the PEA-eligible ETFs only
  (``pea_eligible is True``; unknown = not eligible); bond ETFs are always all available.
  Equity ETFs are dropped when the client's profile does not allow them.
- Sleeve equity cap: min(1, max_equity / (1 - safe_share)) of the bucket's risk level.
- Holdings: safe sleeve -> Livret A / fonds en euros (in AV) per the wrapper split; equity -> PEA up
  to the split's PEA amount (pro rata across equity ETFs), overflow to AV (horizon >= 3 y) else
  CTO; bonds -> AV (>= 3 y) else CTO.
- A structured product, when included, is carved from the longest-horizon bucket's risky sleeve
  before the ETF amounts are computed. Simplification: that bucket's Monte Carlo still models the
  whole risky sleeve with the chosen ETF weights.
- Goal Monte Carlo uses the chosen method's weights; safe rate = fonds en euros rate, or the
  Livret A rate when the bucket's safe sleeve is entirely in Livret A. Its tax allocation uses the
  realised wrapper amounts from ``holdings_eur`` (monthly split if the bucket has no funding).
- ``shortfall_flag`` (facts): goal 'at risk', i.e. displayed ``probability_pct`` < 50, so it
  agrees with the probability the advisor sees. ``projected_value_eur`` (deterministic,
  pre-tax, at the bucket's expected return) is information only. The Monte Carlo
  ``underfunded`` flag (no money at all) stays internal.

Facts naming (binding for the AI numeric check): numeric leaves only under keys ending ``_pct``
(percent units, 1 dp), ``_eur`` (0 dp), ``_year`` (4-digit), ``_count`` (integers) or ``age``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime

import pandas as pd

from wealthadvisor.clients.models import Client
from wealthadvisor.config import (
    load_cma,
    load_etfs,
    load_profiles,
    load_rates,
    load_settings,
    load_structured,
)
from wealthadvisor.data.warehouse import monthly_returns, upsert
from wealthadvisor.goals.montecarlo import GoalResult, simulate_bucket
from wealthadvisor.portfolio.optimise import OptResult, optimise
from wealthadvisor.portfolio.riskmodel import covariance, expected_returns, portfolio_stats
from wealthadvisor.structured.payoff import StructuredDecision, structured_allocation
from wealthadvisor.suitability.products import Suitability, check_product
from wealthadvisor.suitability.scoring import ProfileResult, client_horizon_years, score_profile
from wealthadvisor.wrappers.allocate import Bucket, EmergencyFund, plan_buckets

METHODS = ("markowitz", "black_litterman", "hrp")
WRAPPERS = ("livret_a", "pea", "av", "cto")
TOP_HOLDINGS = 5
_EPS = 0.005  # amounts below half a cent are dropped from holdings
_PRODUCT_NAMES = {"livret_a": "Livret A", "fonds_euros": "Fonds en euros"}
_STRUCTURED_NAMES = {
    "autocall": "Autocall on the Euro Stoxx 50",
    "capital_protected_note": "Capital-protected note on the Euro Stoxx 50",
}


@dataclass
class BucketProposal:
    bucket: Bucket
    methods: dict[str, OptResult]
    chosen: str
    goal: GoalResult
    holdings_eur: dict[str, dict[str, float]]
    safe_rate: float = 0.0
    expected_return: float = 0.0  # bucket level (safe + risky sleeve), CMA mu
    volatility: float = 0.0  # bucket level
    shortfall_flag: bool = False  # goal 'at risk': displayed probability < 50 %
    projected_value: float = 0.0  # deterministic pre-tax value at expected_return (info)


@dataclass
class Proposal:
    client_id: str
    as_of: date
    profile: ProfileResult
    emergency: EmergencyFund
    buckets: list[BucketProposal]
    structured: StructuredDecision
    totals: dict[str, dict[str, float]]  # wrapper -> product -> EUR (incl. emergency fund)
    client: Client | None = None
    suitability: dict[str, Suitability] = field(default_factory=dict)
    structured_warnings: list[str] = field(default_factory=list)


def projected_value(bucket: Bucket, annual_return: float) -> float:
    """Deterministic pre-tax value at the goal date: funding and month-end contributions
    compounded at ``annual_return`` over the same month count as the Monte Carlo."""
    months = max(1, round(bucket.horizon_years * 12))
    rm = (1 + annual_return) ** (1 / 12) - 1
    fv = bucket.funding_now * (1 + rm) ** months
    c = bucket.monthly_contribution
    fv += c * (((1 + rm) ** months - 1) / rm if abs(rm) > 1e-12 else months)
    return float(fv)


def snapshot_today(con) -> date:
    """Last price date in the warehouse: the 'today' of the sample clients."""
    d = con.execute("SELECT max(date) FROM fact_prices").fetchone()[0]
    if d is None:
        raise ValueError("fact_prices is empty: cannot derive today's date")
    return d if isinstance(d, date) else pd.Timestamp(d).date()


def _add(h: dict[str, dict[str, float]], wrapper: str, product: str, amount: float) -> None:
    if amount > _EPS:
        prods = h.setdefault(wrapper, {})
        prods[product] = prods.get(product, 0.0) + float(amount)


def _universe(bucket: Bucket, etfs, equity_allowed: bool) -> list[str]:
    uses_pea = bucket.wrapper_split.get("pea", 0) > 0 or bucket.monthly_split.get("pea", 0) > 0
    out = []
    for e in etfs:
        if e.asset_class.startswith("equity_"):
            if equity_allowed and (not uses_pea or e.pea_eligible is True):
                out.append(e.ticker)
        else:
            out.append(e.ticker)
    return out


def _holdings(
    bucket: Bucket, weights: pd.Series, risky_eur: float, etf_class: dict[str, str]
) -> dict[str, dict[str, float]]:
    h: dict[str, dict[str, float]] = {}
    split = bucket.wrapper_split
    safe = bucket.funding_now * bucket.safe_share
    livret = min(split.get("livret_a", 0.0), safe)
    _add(h, "livret_a", "livret_a", livret)
    _add(h, "av", "fonds_euros", safe - livret)
    if risky_eur <= _EPS:
        return h
    if weights.empty or weights.sum() <= 0:  # no sleeve: keep the money in the safe asset
        _add(h, "av", "fonds_euros", risky_eur)
        return h
    long = bucket.horizon_years >= 3
    rest = "av" if long else "cto"
    eq = {t: w * risky_eur for t, w in weights.items() if etf_class[t].startswith("equity_")}
    eq_total = sum(eq.values())
    pea_amt = min(split.get("pea", 0.0), eq_total)
    for t, v in eq.items():
        in_pea = v * pea_amt / eq_total if eq_total > 0 else 0.0
        _add(h, "pea", t, in_pea)
        _add(h, rest, t, v - in_pea)
    for t, w in weights.items():
        if not etf_class[t].startswith("equity_"):
            _add(h, rest, t, w * risky_eur)
    return h


def _safe_rate(bucket: Bucket, holdings: dict, rates: dict) -> float:
    all_livret = (
        "fonds_euros" not in holdings.get("av", {})
        and bucket.monthly_split.get("av", 0) <= 0
        and bucket.horizon_years < 3
        and (holdings.get("livret_a") or bucket.monthly_split.get("livret_a", 0) > 0)
    )
    return rates["livret_a_rate"]["value"] if all_livret else rates["fonds_euros"]["value"]


def build_proposal(
    client: Client,
    con,
    method_override: dict[str, str] | None = None,
    views: dict | None = None,
) -> Proposal:
    method_override = method_override or {}
    for gid, m in method_override.items():
        if m not in METHODS:
            raise ValueError(f"unknown method {m!r} for goal {gid!r}; expected one of {METHODS}")

    today = snapshot_today(con)
    settings = load_settings()
    rates = load_rates()
    profiles = load_profiles()
    etfs = load_etfs()
    cma = load_cma()
    etf_class = {e.ticker: e.asset_class for e in etfs}

    prof = score_profile(client, today)
    plan = plan_buckets(client, prof.profile, today, rates, settings, profiles)
    structured = structured_allocation(client, prof, plan, today, con)
    horizon = client_horizon_years(client, today)
    suitability = {
        fam: check_product(fam, client, prof, horizon) for fam in ("etf_equity", "etf_bond")
    }

    tickers = [e.ticker for e in etfs]
    returns = monthly_returns(con, tickers)
    cov = covariance(returns)
    mu = expected_returns(tickers, etfs, cma)

    longest = max(plan.buckets, key=lambda b: b.horizon_years) if plan.buckets else None
    structured_warnings: list[str] = []
    out: list[BucketProposal] = []
    for b in plan.buckets:
        bucket = replace(b, rules=list(b.rules))
        risky = bucket.funding_now * (1 - bucket.safe_share)
        carve = 0.0
        if structured.included and b is longest:
            carve = min(structured.amount, max(0.0, risky))
            if carve < structured.amount - _EPS:
                structured_warnings.append(
                    f"Structured amount reduced from {structured.amount:,.0f} EUR to "
                    f"{carve:,.0f} EUR: the longest-horizon bucket's risky sleeve is smaller."
                )
                structured = replace(structured, amount=carve)
            bucket.rules.append(
                f"Structured product {structured.product_id} ({carve:,.0f} EUR) is taken from this "
                "longest-horizon bucket's risky sleeve before the ETF portfolio is optimised; "
                f"it is held in {structured.wrapper.upper()}."
            )
        risky_etf = risky - carve

        universe = _universe(bucket, etfs, suitability["etf_equity"].included)
        rule = profiles[bucket.risk]
        ss = bucket.safe_share
        eq_cap = 1.0 if ss >= 1 else min(1.0, rule.max_equity / (1 - ss))
        methods = {
            m: optimise(m, universe, mu, cov, returns, rule, ss, eq_cap, views=views, etfs=etfs)
            for m in METHODS
        }
        chosen = method_override.get(
            bucket.goal_id, "hrp" if bucket.risk <= 3 else "black_litterman"
        )
        weights = methods[chosen].weights
        holdings = _holdings(bucket, weights, risky_etf, etf_class)
        if carve > _EPS:
            _add(holdings, structured.wrapper, f"structured:{structured.product_id}", carve)
        safe_rate = _safe_rate(bucket, holdings, rates)
        # Tax at the goal date follows the realised wrapper amounts, not the planned split.
        realised = {w: sum(prods.values()) for w, prods in holdings.items()}
        goal = simulate_bucket(
            replace(bucket, wrapper_split=realised),
            weights,
            mu,
            cov,
            safe_rate,
            settings.n_paths,
            settings.seed,
            client.household,
        )
        if weights.empty:
            stats = {"expected_return": safe_rate, "volatility": 0.0}
        else:
            stats = portfolio_stats(weights, mu, cov, bucket.safe_share, safe_rate)
        out.append(
            BucketProposal(
                bucket,
                methods,
                chosen,
                goal,
                holdings,
                safe_rate,
                stats["expected_return"],
                stats["volatility"],
                _pct(goal.probability) < 50,
                projected_value(bucket, stats["expected_return"]),
            )
        )

    totals: dict[str, dict[str, float]] = {}
    _add(totals, "livret_a", "livret_a", plan.emergency.funded)
    for bp in out:
        for w, prods in bp.holdings_eur.items():
            for prod, v in prods.items():
                _add(totals, w, prod, v)

    return Proposal(
        client_id=client.client_id,
        as_of=today,
        profile=prof,
        emergency=plan.emergency,
        buckets=out,
        structured=structured,
        totals=totals,
        client=client,
        suitability=suitability,
        structured_warnings=structured_warnings,
    )


# --------------------------------------------------------------------------- facts


def _eur(x: float) -> int:
    return round(float(x))


def _pct(x: float) -> float:
    return round(float(x) * 100, 1)


def _product_name(product: str, names: dict[str, str]) -> str:
    if product.startswith("structured:"):
        return _structured_name(product.split(":", 1)[1])
    return _PRODUCT_NAMES.get(product) or names.get(product, product)


def _structured_name(product_id: str | None) -> str:
    tpl = load_structured()["templates"].get(product_id or "", {})
    return _STRUCTURED_NAMES.get(tpl.get("kind", ""), product_id or "")


def _wrapper_eur(holdings: dict[str, dict[str, float]]) -> dict[str, int]:
    return {f"{w}_eur": _eur(sum(holdings.get(w, {}).values())) for w in WRAPPERS}


def _goal_facts(bp: BucketProposal, client: Client | None, names: dict[str, str]) -> dict:
    b = bp.bucket
    goal = next((g for g in client.goals if g.goal_id == b.goal_id), None) if client else None
    opt = bp.methods[bp.chosen]
    items = [
        (w, prod, v)
        for w, prods in bp.holdings_eur.items()
        for prod, v in prods.items()
        if not prod.startswith("structured:")
    ]
    items.sort(key=lambda x: -x[2])
    facts = {
        "goal_id": b.goal_id,
        "label": goal.label if goal else b.goal_id,
        "label_fr": (goal.label_fr or goal.label) if goal else b.goal_id,
        "priority": goal.priority if goal else "",
        "target_nominal_eur": _eur(b.target_nominal),
        "horizon_years_count": round(float(b.horizon_years)),
        "horizon_months_count": max(1, round(float(b.horizon_years) * 12)),
        "bucket_risk_count": int(b.risk),
        "safe_share_pct": _pct(b.safe_share),
        "funding_now_eur": _eur(b.funding_now),
        "monthly_contribution_eur": _eur(b.monthly_contribution),
        "chosen_method": bp.chosen,
        "expected_return_pct": _pct(bp.expected_return),
        "volatility_pct": _pct(bp.volatility),
        "sleeve_expected_return_pct": _pct(opt.expected_return),
        "sleeve_volatility_pct": _pct(opt.volatility),
        "max_drawdown_pct": _pct(opt.max_drawdown),
        "max_drawdown_basis": "historical maximum drawdown of the risky ETF sleeve",
        "probability_pct": _pct(bp.goal.probability),
        "p10_eur": _eur(bp.goal.p10),
        "p50_eur": _eur(bp.goal.p50),
        "p90_eur": _eur(bp.goal.p90),
        "shortfall_flag": bool(bp.shortfall_flag),
        "projected_value_eur": _eur(bp.projected_value),
        "wrappers": _wrapper_eur(bp.holdings_eur),
        "top_holdings": [
            {
                "product": prod,
                "name": _product_name(prod, names),
                "wrapper": w,
                "amount_eur": _eur(v),
            }
            for w, prod, v in items[:TOP_HOLDINGS]
        ],
        "methods": {
            m: {
                "sleeve_expected_return_pct": _pct(r.expected_return),
                "sleeve_volatility_pct": _pct(r.volatility),
                "max_drawdown_pct": _pct(r.max_drawdown),
                "notes": list(r.notes),
            }
            for m, r in bp.methods.items()
        },
        "rules": list(b.rules),
    }
    if goal:
        facts["target_today_eur"] = _eur(goal.target_today_eur)
        facts["goal_year"] = int(goal.date.year)
    return facts


def _structured_facts(p: Proposal) -> dict:
    s = p.structured
    facts: dict = {
        "included": bool(s.included),
        "reasons": list(s.reasons),
        "warnings": list(p.structured_warnings),
    }
    if not s.included:
        return facts
    facts.update(
        {
            "product_id": s.product_id,
            "product_name": _structured_name(s.product_id),
            "wrapper": s.wrapper,
            "amount_eur": _eur(s.amount),
        }
    )
    if s.payoff is not None:
        facts.update(
            {
                "prob_capital_loss_pct": _pct(s.payoff.prob_capital_loss),
                "annualised_expected_return_pct": _pct(s.payoff.annualised_expected_return),
                "describe": s.payoff.describe,
            }
        )
    return facts


def proposal_facts(p: Proposal) -> dict:
    """JSON-serialisable facts for the AI documents, rounded to display precision."""
    settings = load_settings()
    names = {e.ticker: e.name for e in load_etfs()}
    c = p.client
    em = p.emergency
    totals = _wrapper_eur(p.totals)
    totals["fonds_euros_eur"] = _eur(p.totals.get("av", {}).get("fonds_euros", 0.0))
    totals["total_eur"] = _eur(sum(v for prods in p.totals.values() for v in prods.values()))
    return {
        "disclaimer": dict(settings.disclaimer),
        "as_of": p.as_of.isoformat(),
        "as_of_year": int(p.as_of.year),
        "client": {
            "client_id": p.client_id,
            "name": c.name if c else "",
            "age": int(c.age) if c else 0,
            "household": c.household if c else "",
        },
        "profile": {
            "risk_profile_count": int(p.profile.profile),
            "rules_fired": list(p.profile.rules_fired),
            "constraints": list(p.profile.constraints),
        },
        "emergency": {
            "target_eur": _eur(em.target),
            "funded_eur": _eur(em.funded),
            "shortfall_eur": _eur(em.shortfall),
            "rules": list(em.rules),
        },
        "goals": [_goal_facts(bp, c, names) for bp in p.buckets],
        "structured": _structured_facts(p),
        "totals": totals,
        "appropriateness": {
            fam: {
                "included": bool(s.included),
                "reasons": list(s.reasons),
                "warnings": list(s.warnings),
            }
            for fam, s in p.suitability.items()
        },
    }


def save_proposal(con, p: Proposal, created_at: datetime | None = None) -> None:
    """Upsert the proposal facts into ``fact_proposals``."""
    row = {
        "client_id": p.client_id,
        "created_at": pd.Timestamp(created_at or datetime.now()),
        "payload_json": json.dumps(proposal_facts(p)),
    }
    upsert(con, "fact_proposals", pd.DataFrame([row]))
