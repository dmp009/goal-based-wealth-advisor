"""Annual review engine (design §5, §6.9, §9.4).

For a client with an ``original_proposal`` the engine derives today's holdings from real prices,
measures performance and drift, re-profiles, re-simulates the goals and proposes rebalancing trades.

Documented conventions:
- Proposal date: the client's ``proposal_date`` when set, otherwise ``as_of`` - 18 months.
- Holdings are derived, not stored: each product amount of the original proposal is bought at the
  last month-end price on or before the proposal date (units = amount / price). At every month
  end after it (price dates in the warehouse, up to ``as_of``) Livret A and fonds en euros accrue
  one month of interest at their configured rates, then ``monthly_saving`` is invested in the same
  wrapper/product proportions as the original proposal. Livret A only takes deposits while its
  balance is below the ceiling; the rest of its share goes to fonds en euros in the AV. The PEA
  only takes deposits while total PEA contributions are below the regulatory ceiling
  (``pea_contribution_cap``); the rest of a PEA product's share buys the same ETF in the AV.
- Structured products are held at par (no mark-to-market) and take no monthly contributions
  (their share of the saving is spread pro rata over the other products).
- ``avg_cost`` is the weighted average cost (PRU). For Livret A / fonds en euros a "unit" is one
  euro of value and interest adds units at zero cost, so units * avg_cost = euros contributed.
- Performance: monthly chain-linked time-weighted return; contributions arrive after the month's
  valuation so they never count as return. ``gain_eur`` = value - total contributed.
- Drift: target = asset-class weights of the original proposal (fonds en euros / Livret A =
  "safe", structured = "structured"); current = derived holdings at ``as_of``. ``drift`` holds
  fractions (0.05 = 5 percentage points). Classes with |diff| > ``drift_band`` are rebalanced.
- Trades stay inside each wrapper (money never moves between wrappers; future contributions do
  that). In a wrapper, over-weight flagged classes are sold and under-weight flagged classes bought
  toward the wrapper's original mix; when one side has no flagged class, the other under/over-weight
  classes of that wrapper take the counterpart. Buys equal sells per wrapper. A class trades its
  largest holding in the wrapper (sells spill to the next holding). Structured notes and the
  Livret A are not traded. CTO sells are taxable: tax on the gain of the sold units at the
  weighted average cost; PEA / AV sells are not taxable events.
- Goals: ``goals_before`` re-runs ``build_proposal`` at the proposal date (prices limited to that
  date) with ``liquid_assets`` set to the amount actually invested in the original proposal, so
  before and now describe the same money. ``goals_now`` re-simulates the same buckets (risk, safe
  share, chosen weights, safe rate, monthly contribution, nominal target, wrapper split for tax)
  from the current value: the derived portfolio minus the emergency fund (kept in Livret A) is
  split across buckets pro rata to funding_now + n_months x monthly_contribution of each bucket
  (n_months = month ends since the proposal), so buckets fed only by monthly saving get their
  share. Horizons are measured from ``as_of``. The simulation uses the re-run engine's chosen ETF
  weights, not the ETFs actually held (simplification).
- A goal can stay at 0 % before and now when the plan leaves it unfunded (e.g. c3 holiday_home,
  the deliberate underfunded example, ruling R12): the review reports it, it does not fix it.
- Month grid: warehouse price dates that are calendar month ends, in (proposal_date, as_of].
- Livret A / fonds en euros accrue at today's configured rates over the whole window.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

import pandas as pd

from wealthadvisor.clients.models import Answers, Client, Holding
from wealthadvisor.config import load_cma, load_etfs, load_rates, load_settings
from wealthadvisor.data.warehouse import monthly_returns
from wealthadvisor.goals.montecarlo import GoalResult, simulate_bucket
from wealthadvisor.portfolio.riskmodel import covariance, expected_returns
from wealthadvisor.proposal import (
    WRAPPERS,
    _eur,
    _pct,
    _product_name,
    build_proposal,
    snapshot_today,
)
from wealthadvisor.suitability.scoring import DAYS_PER_YEAR, ProfileResult, score_profile
from wealthadvisor.wrappers.tax import tax_on_gain

CASH = ("livret_a", "fonds_euros")
SAFE, STRUCTURED = "safe", "structured"
DEFAULT_LOOKBACK_MONTHS = 18
_MIN_TRADE = 0.5  # EUR: trades below this are not proposed
_NOTES = (
    (
        "Holdings are derived from the original proposal with real month-end prices and the "
        "monthly saving; structured products are valued at par (no mark-to-market)."
    ),
    "Rebalancing stays inside each wrapper; future contributions move money between wrappers.",
    "Sales in the CTO are taxable; sales inside the PEA or the assurance-vie are not taxable events.",
    (
        "Livret A and fonds en euros interest uses the current configured rates over the whole "
        "period since the proposal."
    ),
    (
        "Goal probabilities now re-simulate the plan of the proposal date with today's values; a "
        "goal left unfunded by that plan stays at 0 %."
    ),
)

_PEA_CAP_NOTE = (
    "PEA contributions reached the regulatory ceiling; the rest of the PEA share of the monthly "
    "saving bought the same ETFs in the assurance-vie."
)


@dataclass
class Trade:
    wrapper: str
    product: str
    action: Literal["buy", "sell"]
    amount_eur: float
    taxable: bool
    est_tax_eur: float


@dataclass
class Review:
    client_id: str
    as_of: date
    performance: dict[str, dict[str, float]]  # wrapper | "total" -> twr, gain_eur, ...
    drift: pd.DataFrame  # asset_class x [target, current, diff] (fractions)
    profile_before: int
    profile_now: ProfileResult
    profile_changed: bool
    goals_before: list[GoalResult]
    goals_now: list[GoalResult]
    trades: list[Trade]
    proposal_date: date | None = None
    holdings: list[Holding] = field(default_factory=list)
    client: Client | None = None
    drift_band: float = 0.05
    pea_capped: bool = False


# --------------------------------------------------------------------------- holdings


@dataclass
class _Track:
    proposal_date: date
    positions: dict[tuple[str, str], list[float]]  # (wrapper, product key) -> [units, cost]
    prices: pd.Series  # ticker -> last price on or before as_of
    contributed: dict[str, float]
    pre: list[dict[str, float]]  # month m: wrapper values before the month-end contribution
    post: list[dict[str, float]]  # month m: wrapper values after it (index 0 = proposal date)
    pea_capped: bool = False  # monthly PEA deposits hit the contribution ceiling


def proposal_date_of(client: Client, as_of: date) -> date:
    if client.proposal_date is not None:
        return client.proposal_date
    return (pd.Timestamp(as_of) - pd.DateOffset(months=DEFAULT_LOOKBACK_MONTHS)).date()


def _is_etf(product: str) -> bool:
    return product not in CASH and not product.startswith("structured:")


def _prices(con, tickers: list[str], until: date) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    df = con.execute(
        "SELECT ticker, date, adj_close FROM fact_prices WHERE date <= ? AND ticker IN "
        f"({', '.join('?' * len(tickers))}) ORDER BY date",
        [until, *tickers],
    ).df()
    px = df.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    px.index = pd.to_datetime(px.index)
    return px.reindex(columns=tickers).ffill()


def _track(client: Client, con, as_of: date) -> _Track:
    if not client.original_proposal:
        raise ValueError("Client has no existing portfolio")
    start = proposal_date_of(client, as_of)
    if start > as_of:
        raise ValueError(f"proposal date {start} is after the review date {as_of}")
    rates = load_rates()
    la_m = (1 + rates["livret_a_rate"]["value"]) ** (1 / 12)
    fe_m = (1 + rates["fonds_euros"]["value"]) ** (1 / 12)
    la_cap = rates["livret_a_cap"]["value"]
    pea_cap = rates["pea_contribution_cap"]["value"]
    pea_capped = False

    lines = [
        (w, p, float(v))
        for w, prods in client.original_proposal.items()
        for p, v in (prods or {}).items()
        if float(v) > 0
    ]
    tickers = sorted({p for _, p, _ in lines if _is_etf(p)})
    px = _prices(con, tickers, as_of)
    ts0 = pd.Timestamp(start)
    if tickers:
        before = px[px.index <= ts0]
        if before.empty or before.iloc[-1].isna().any():
            raise ValueError(f"no price on or before the proposal date {start}")
        p0 = before.iloc[-1]
    months = [
        pd.Timestamp(d)
        for (d,) in con.execute(
            "SELECT DISTINCT date FROM fact_prices WHERE date > ? AND date <= ? "
            "AND date = last_day(date) ORDER BY date",
            [start, as_of],
        ).fetchall()
    ]

    def price(product: str, ts: pd.Timestamp | None) -> float:
        if not _is_etf(product):
            return 1.0
        if ts is None:
            return float(p0[product])
        return float(px.loc[:ts, product].iloc[-1])

    pos: dict[tuple[str, str], list[float]] = {}
    contributed: dict[str, float] = {}
    for w, p, v in lines:
        u = v / price(p, None)
        cur = pos.setdefault((w, p), [0.0, 0.0])
        cur[0] += u
        cur[1] += v
        contributed[w] = contributed.get(w, 0.0) + v

    # Monthly saving split: original proportions, structured notes excluded.
    flow_base = [(w, p, v) for w, p, v in lines if not p.startswith("structured:")]
    base_total = sum(v for _, _, v in flow_base)
    split = [(w, p, v / base_total) for w, p, v in flow_base] if base_total > 0 else []

    def values(ts: pd.Timestamp | None) -> dict[str, float]:
        out: dict[str, float] = {}
        for (w, p), (u, _) in pos.items():
            out[w] = out.get(w, 0.0) + u * price(p, ts)
        return out

    pre: list[dict[str, float]] = [{}]
    post: list[dict[str, float]] = [values(None)]
    for ts in months:
        for (w, p), cur in pos.items():
            if p == "livret_a":
                cur[0] *= la_m
            elif p == "fonds_euros":
                cur[0] *= fe_m
        pre.append(values(ts))
        for w, p, share in split:
            amount = client.monthly_saving * share
            if amount <= 0:
                continue
            if p == "livret_a":
                room = max(0.0, la_cap - pos.get((w, p), [0.0])[0])
                deposit = min(amount, room)
                overflow = amount - deposit
                amount = deposit
                if overflow > 0:
                    fe = pos.setdefault(("av", "fonds_euros"), [0.0, 0.0])
                    fe[0] += overflow
                    fe[1] += overflow
                    contributed["av"] = contributed.get("av", 0.0) + overflow
                if amount <= 0:
                    continue
            elif w == "pea":
                room = max(0.0, pea_cap - contributed.get("pea", 0.0))
                deposit = min(amount, room)
                overflow = amount - deposit
                amount = deposit
                if overflow > 0:
                    pea_capped = True
                    av = pos.setdefault(("av", p), [0.0, 0.0])
                    av[0] += overflow / price(p, ts)
                    av[1] += overflow
                    contributed["av"] = contributed.get("av", 0.0) + overflow
                if amount <= 0:
                    continue
            cur = pos.setdefault((w, p), [0.0, 0.0])
            cur[0] += amount / price(p, ts)
            cur[1] += amount
            contributed[w] = contributed.get(w, 0.0) + amount
        post.append(values(ts))

    last = (
        pd.Series({t: price(t, months[-1] if months else None) for t in tickers}, dtype=float)
        if tickers
        else pd.Series(dtype=float)
    )
    return _Track(start, pos, last, contributed, pre, post, pea_capped)


def _holdings(track: _Track) -> list[Holding]:
    out = []
    for (w, p), (u, cost) in track.positions.items():
        if u <= 0:
            continue
        etf = _is_etf(p)
        out.append(
            Holding(
                wrapper=w,
                ticker=p if etf else None,
                product="etf" if etf else p,
                units=u,
                avg_cost=cost / u,
            )
        )
    order = {w: i for i, w in enumerate(WRAPPERS)}
    return sorted(out, key=lambda h: (order.get(h.wrapper, 99), h.ticker or h.product))


def derive_holdings(client: Client, con, as_of: date) -> list[Holding]:
    """Current holdings derived from the original proposal, real prices and monthly saving."""
    return _holdings(_track(client, con, as_of))


# --------------------------------------------------------------------------- analytics


def _key(h: Holding) -> str:
    return h.ticker or h.product


def _value(h: Holding, prices: pd.Series) -> float:
    return h.units * (float(prices[h.ticker]) if h.ticker else 1.0)


def _class(product: str, etf_class: dict[str, str]) -> str:
    if product in CASH:
        return SAFE
    if product.startswith("structured:"):
        return STRUCTURED
    return etf_class[product]


def _performance(track: _Track, holdings: list[Holding]) -> dict[str, dict[str, float]]:
    value: dict[str, float] = {}
    for h in holdings:
        value[h.wrapper] = value.get(h.wrapper, 0.0) + _value(h, track.prices)
    out: dict[str, dict[str, float]] = {}
    keys = [w for w in WRAPPERS if track.contributed.get(w, 0.0) > 0]
    keys += [w for w in track.contributed if w not in keys and track.contributed[w] > 0]
    for key in [*keys, "total"]:
        growth = 1.0
        for m in range(1, len(track.post)):
            if key == "total":
                start, end = sum(track.post[m - 1].values()), sum(track.pre[m].values())
            else:
                start, end = track.post[m - 1].get(key, 0.0), track.pre[m].get(key, 0.0)
            if start > 0:
                growth *= end / start
        v = sum(value.values()) if key == "total" else value.get(key, 0.0)
        c = sum(track.contributed.values()) if key == "total" else track.contributed[key]
        out[key] = {"twr": growth - 1, "gain_eur": v - c, "value_eur": v, "contributed_eur": c}
    return out


def _drift(client: Client, holdings: list[Holding], prices: pd.Series, etf_class) -> pd.DataFrame:
    target: dict[str, float] = {}
    for prods in client.original_proposal.values():
        for p, v in (prods or {}).items():
            c = _class(p, etf_class)
            target[c] = target.get(c, 0.0) + float(v)
    current: dict[str, float] = {}
    for h in holdings:
        c = _class(_key(h), etf_class)
        current[c] = current.get(c, 0.0) + _value(h, prices)
    t_tot, c_tot = sum(target.values()), sum(current.values())
    classes = sorted(set(target) | set(current), key=lambda c: (-target.get(c, 0.0), c))
    df = pd.DataFrame(
        {
            "target": [target.get(c, 0.0) / t_tot for c in classes],
            "current": [current.get(c, 0.0) / c_tot for c in classes],
        },
        index=pd.Index(classes, name="asset_class"),
    )
    df["diff"] = df["current"] - df["target"]
    return df


def _scaled(devs: dict[str, float], amount: float) -> dict[str, float]:
    total = sum(devs.values())
    return {c: d * amount / total for c, d in devs.items()} if total > 0 else {}


def _trades(
    client: Client,
    holdings: list[Holding],
    prices: pd.Series,
    drift: pd.DataFrame,
    band: float,
    etf_class: dict[str, str],
    years_held: float,
) -> list[Trade]:
    flagged = {c for c, d in drift["diff"].items() if abs(d) > band + 1e-12 and c != STRUCTURED}
    trades: list[Trade] = []
    if not flagged:
        return trades
    for w in WRAPPERS:
        orig = {
            p: float(v)
            for p, v in (client.original_proposal.get(w) or {}).items()
            if not p.startswith("structured:")
        }
        if w == "livret_a" or not orig:
            continue
        held = [h for h in holdings if h.wrapper == w and not _key(h).startswith("structured:")]
        by_class: dict[str, list[tuple[Holding, float]]] = {}
        for h in held:
            by_class.setdefault(_class(_key(h), etf_class), []).append((h, _value(h, prices)))
        tw: dict[str, float] = {}
        for p, v in orig.items():
            tw[_class(p, etf_class)] = tw.get(_class(p, etf_class), 0.0) + v
        o_tot = sum(tw.values())
        v_tot = sum(v for lst in by_class.values() for _, v in lst)
        dev = {
            c: sum(v for _, v in by_class.get(c, [])) - v_tot * tw.get(c, 0.0) / o_tot
            for c in set(tw) | set(by_class)
        }
        over = {c: d for c, d in dev.items() if c in flagged and d > 0}
        under = {c: -d for c, d in dev.items() if c in flagged and d < 0}
        if not over and not under:
            continue
        if not under:
            under = {c: -d for c, d in dev.items() if d < 0 and c in tw}
        if not over:
            over = {c: d for c, d in dev.items() if d > 0}
        amount = min(sum(over.values()), sum(under.values()))
        if amount < _MIN_TRADE:
            continue
        for c, a in _scaled(over, amount).items():
            for h, v in sorted(by_class[c], key=lambda x: -x[1]):
                take = min(a, v)
                if take <= 0:
                    break
                px = float(prices[h.ticker]) if h.ticker else 1.0
                gain = take - take / px * h.avg_cost
                taxable = w == "cto"
                tax = tax_on_gain("cto", gain, years_held, client.household) if taxable else 0.0
                trades.append(Trade(w, _key(h), "sell", take, taxable, tax))
                a -= take
        for c, a in _scaled(under, amount).items():
            lst = by_class.get(c)
            if lst:
                product = _key(max(lst, key=lambda x: x[1])[0])
            else:  # class in the wrapper's target but no longer held: buy the original product
                product = max((p for p in orig if _class(p, etf_class) == c), key=lambda p: orig[p])
            trades.append(Trade(w, product, "buy", a, False, 0.0))
    return [t for t in trades if t.amount_eur >= 0.005]


def _analyse(client: Client, con, as_of: date):
    track = _track(client, con, as_of)
    holdings = _holdings(track)
    etf_class = {e.ticker: e.asset_class for e in load_etfs()}
    band = load_settings().drift_band
    perf = _performance(track, holdings)
    drift = _drift(client, holdings, track.prices, etf_class)
    years = (as_of - track.proposal_date).days / DAYS_PER_YEAR
    trades = _trades(client, holdings, track.prices, drift, band, etf_class, years)
    return track, perf, drift, trades, holdings


def portfolio_review(
    client: Client, con, as_of: date
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, list[Trade], list[Holding]]:
    """Performance, drift, rebalancing trades and derived holdings (no goals, no profile)."""
    _, perf, drift, trades, holdings = _analyse(client, con, as_of)
    return perf, drift, trades, holdings


def reprofile(
    client: Client, proposal_date: date, as_of: date, new_answers: Answers | None = None
) -> tuple[int, ProfileResult, bool]:
    """(profile at the proposal date, profile now with the new answers if given, changed?)."""
    before = score_profile(client, proposal_date).profile
    now_client = client.model_copy(update={"answers": dict(new_answers)}) if new_answers else client
    now = score_profile(now_client, as_of)
    return before, now, now.profile != before


def _goals_now(
    client: Client, con, as_of: date, before, holdings, prices, n_months: int
) -> list[GoalResult]:
    settings = load_settings()
    etfs = load_etfs()
    tickers = [e.ticker for e in etfs]
    returns = monthly_returns(con, tickers)
    cov = covariance(returns[returns.index <= pd.Timestamp(as_of)])
    mu = expected_returns(tickers, etfs, load_cma())

    total = sum(_value(h, prices) for h in holdings)
    livret = sum(_value(h, prices) for h in holdings if h.wrapper == "livret_a")
    investable = max(0.0, total - min(before.emergency.funded, livret))
    funding = [
        bp.bucket.funding_now + n_months * bp.bucket.monthly_contribution for bp in before.buckets
    ]
    base = sum(funding)
    shares = [f / base for f in funding] if base > 0 else [1 / max(1, len(funding))] * len(funding)
    goal_dates = {g.goal_id: g.date for g in client.goals}
    out = []
    for bp, share in zip(before.buckets, shares):
        b = bp.bucket
        realised = {w: sum(p.values()) for w, p in bp.holdings_eur.items()}
        horizon = max(0.0, (goal_dates[b.goal_id] - as_of).days / DAYS_PER_YEAR)
        bucket = replace(
            b,
            horizon_years=horizon,
            funding_now=investable * share,
            wrapper_split=realised or b.monthly_split,
            rules=list(b.rules),
        )
        weights = bp.methods[bp.chosen].weights
        out.append(
            simulate_bucket(
                bucket,
                weights,
                mu,
                cov,
                bp.safe_rate,
                settings.n_paths,
                settings.seed,
                client.household,
            )
        )
    return out


def build_review(
    client: Client, con, as_of: date | None = None, new_answers: Answers | None = None
) -> Review:
    if not client.original_proposal:
        raise ValueError("Client has no existing portfolio")
    as_of = as_of or snapshot_today(con)
    start = proposal_date_of(client, as_of)
    track, perf, drift, trades, holdings = _analyse(client, con, as_of)
    before_p, now_p, changed = reprofile(client, start, as_of, new_answers)
    invested = sum(
        float(v) for prods in client.original_proposal.values() for v in (prods or {}).values()
    )
    before = build_proposal(client.model_copy(update={"liquid_assets": invested}), con, as_of=start)
    goals_before = [bp.goal for bp in before.buckets]
    goals_now = _goals_now(client, con, as_of, before, holdings, track.prices, len(track.post) - 1)
    return Review(
        client_id=client.client_id,
        as_of=as_of,
        performance=perf,
        drift=drift,
        profile_before=before_p,
        profile_now=now_p,
        profile_changed=changed,
        goals_before=goals_before,
        goals_now=goals_now,
        trades=trades,
        proposal_date=start,
        holdings=holdings,
        client=client,
        drift_band=load_settings().drift_band,
        pea_capped=track.pea_capped,
    )


# --------------------------------------------------------------------------- facts


def review_facts(r: Review) -> dict:
    """JSON-serialisable review facts, same naming / rounding rules as ``proposal_facts``."""
    settings = load_settings()
    names = {e.ticker: e.name for e in load_etfs()}
    c = r.client
    goals = {g.goal_id: g for g in c.goals} if c else {}
    goal_facts = []
    for gb, gn in zip(r.goals_before, r.goals_now):
        g = goals.get(gb.goal_id)
        f = {
            "goal_id": gb.goal_id,
            "label": g.label if g else gb.goal_id,
            "label_fr": (g.label_fr or g.label) if g else gb.goal_id,
            "priority": g.priority if g else "",
            "probability_before_pct": _pct(gb.probability),
            "probability_now_pct": _pct(gn.probability),
            "p50_before_eur": _eur(gb.p50),
            "p10_now_eur": _eur(gn.p10),
            "p50_now_eur": _eur(gn.p50),
            "p90_now_eur": _eur(gn.p90),
        }
        if g:
            f["target_today_eur"] = _eur(g.target_today_eur)
            f["goal_year"] = int(g.date.year)
        goal_facts.append(f)
    band = r.drift_band
    trades = [
        {
            "wrapper": t.wrapper,
            "product": t.product,
            "name": _product_name(t.product, names),
            "action": t.action,
            "amount_eur": _eur(t.amount_eur),
            "taxable": bool(t.taxable),
            "est_tax_eur": _eur(t.est_tax_eur),
        }
        for t in r.trades
    ]
    months = (r.as_of.year - r.proposal_date.year) * 12 + r.as_of.month - r.proposal_date.month
    return {
        "disclaimer": dict(settings.disclaimer),
        "as_of": r.as_of.isoformat(),
        "as_of_year": int(r.as_of.year),
        "proposal_date": r.proposal_date.isoformat(),
        "proposal_year": int(r.proposal_date.year),
        "review_period_months_count": int(months),
        "client": {
            "client_id": r.client_id,
            "name": c.name if c else "",
            "age": int(c.age) if c else 0,
            "household": c.household if c else "",
        },
        "profile": {
            "profile_before_count": int(r.profile_before),
            "profile_now_count": int(r.profile_now.profile),
            "profile_changed": bool(r.profile_changed),
            "rules_fired": list(r.profile_now.rules_fired),
        },
        "performance": {
            k: {
                "twr_pct": _pct(v["twr"]),
                "gain_eur": _eur(v["gain_eur"]),
                "value_eur": _eur(v["value_eur"]),
                "contributed_eur": _eur(v["contributed_eur"]),
            }
            for k, v in r.performance.items()
        },
        "drift_band_pct": _pct(band),
        "drift": [
            {
                "asset_class": cls,
                "target_pct": _pct(row["target"]),
                "current_pct": _pct(row["current"]),
                "diff_pct": _pct(row["diff"]),
                "rebalance": bool(abs(row["diff"]) > band + 1e-12 and cls != STRUCTURED),
            }
            for cls, row in r.drift.iterrows()
        ],
        "trades": trades,
        "trade_totals": {
            "sells_eur": _eur(sum(t.amount_eur for t in r.trades if t.action == "sell")),
            "buys_eur": _eur(sum(t.amount_eur for t in r.trades if t.action == "buy")),
            "est_tax_eur": _eur(sum(t.est_tax_eur for t in r.trades)),
        },
        "goals": goal_facts,
        "notes": list(_NOTES) + ([_PEA_CAP_NOTE] if r.pea_capped else []),
    }
