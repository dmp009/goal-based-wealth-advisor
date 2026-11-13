"""Proposal PDF (reportlab, built-in Helvetica: WinAnsi covers €, é, à, ç).

The client letter is included only when a *verified* document exists for the language; an
unverified body is never printed.
"""

from __future__ import annotations

import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from wealthadvisor.ai.documents import Document
from wealthadvisor.config import load_etfs, load_settings
from wealthadvisor.i18n import asset_class_label, render
from wealthadvisor.proposal import _product_name, _structured_name

NAVY = colors.HexColor("#1f3a5f")
_METHOD = {"markowitz": "Markowitz", "black_litterman": "Black-Litterman", "hrp": "HRP"}
_WRAPPER = {
    "livret_a": "Livret A",
    "pea": "PEA",
    "av": {"en": "Life insurance (AV)", "fr": "Assurance-vie (AV)"},
    "cto": {"en": "Securities account (CTO)", "fr": "Compte-titres (CTO)"},
    "fonds_euros": {"en": "of which fonds en euros", "fr": "dont fonds en euros"},
}
_T = {
    "en": {
        "title": "Investment proposal",
        "client": "Client",
        "date": "Data as of",
        "profile": "Risk profile",
        "of7": "of 7",
        "rules": "Rules applied",
        "none": "None",
        "wrappers": "Wrapper plan",
        "wrapper": "Wrapper",
        "amount": "Amount",
        "total": "Total",
        "goals": "Goals",
        "goal": "Goal",
        "target": "Target",
        "prob": "Probability",
        "method": "Method",
        "ret": "Exp. return",
        "vol": "Volatility",
        "structured": "Structured product",
        "excluded": "No structured product is proposed.",
        "included": "Product",
        "loss": "Probability of capital loss",
        "letter": "Client letter",
        "noletter": "No verified client letter is available for this proposal.",
        "page": "Page",
        "r_title": "Annual review",
        "r_proposal": "Proposal date",
        "r_perf": "Performance",
        "r_scope": "Scope",
        "r_twr": "TWR",
        "r_gain": "Gain",
        "r_value": "Value",
        "r_all": "Total",
        "r_drift": "Drift versus target",
        "r_class": "Asset class",
        "r_cur": "Current",
        "r_diff": "Difference",
        "r_reb": "Rebalance",
        "r_yes": "yes",
        "r_no": "no",
        "r_profile": "Risk profile",
        "r_before": "at proposal",
        "r_now": "now",
        "r_changed": "The risk profile has changed.",
        "r_same": "The risk profile is unchanged.",
        "r_goals": "Goals: before and now",
        "r_pb": "Prob. before",
        "r_pn": "Prob. now",
        "r_trades": "Rebalancing trades",
        "r_wr": "Wrapper",
        "r_prod": "Product",
        "r_act": "Action",
        "r_buy": "buy",
        "r_sell": "sell",
        "r_tax": "Taxable",
        "r_esttax": "Est. tax",
        "r_notrades": "No rebalancing needed: all asset classes are within ±{band} pp of target.",
        "r_letter": "Client letter",
        "r_noletter": "No verified client letter is available for this review.",
    },
    "fr": {
        "title": "Proposition d'investissement",
        "client": "Client",
        "date": "Données au",
        "profile": "Profil de risque",
        "of7": "sur 7",
        "rules": "Règles appliquées",
        "none": "Aucune",
        "wrappers": "Répartition par enveloppe",
        "wrapper": "Enveloppe",
        "amount": "Montant",
        "total": "Total",
        "goals": "Objectifs",
        "goal": "Objectif",
        "target": "Cible",
        "prob": "Probabilité",
        "method": "Méthode",
        "ret": "Rend. espéré",
        "vol": "Volatilité",
        "structured": "Produit structuré",
        "excluded": "Aucun produit structuré n'est proposé.",
        "included": "Produit",
        "loss": "Probabilité de perte en capital",
        "letter": "Lettre au client",
        "noletter": "Aucune lettre client vérifiée n'est disponible pour cette proposition.",
        "page": "Page",
        "r_title": "Revue annuelle",
        "r_proposal": "Date de la proposition",
        "r_perf": "Performance",
        "r_scope": "Périmètre",
        "r_twr": "TWR",
        "r_gain": "Gain",
        "r_value": "Valeur",
        "r_all": "Total",
        "r_drift": "Dérive par rapport à la cible",
        "r_class": "Classe d'actifs",
        "r_cur": "Actuel",
        "r_diff": "Écart",
        "r_reb": "Rééquilibrer",
        "r_yes": "oui",
        "r_no": "non",
        "r_profile": "Profil de risque",
        "r_before": "à la proposition",
        "r_now": "aujourd'hui",
        "r_changed": "Le profil de risque a changé.",
        "r_same": "Le profil de risque est inchangé.",
        "r_goals": "Objectifs : avant et maintenant",
        "r_pb": "Prob. avant",
        "r_pn": "Prob. maintenant",
        "r_trades": "Arbitrages de rééquilibrage",
        "r_wr": "Enveloppe",
        "r_prod": "Produit",
        "r_act": "Action",
        "r_buy": "achat",
        "r_sell": "vente",
        "r_tax": "Imposable",
        "r_esttax": "Impôt est.",
        "r_notrades": "Aucun rééquilibrage nécessaire : toutes les classes d'actifs sont à ±{band} pp de la cible.",
        "r_letter": "Lettre au client",
        "r_noletter": "Aucune lettre client vérifiée n'est disponible pour cette revue.",
    },
}


def _clean(text: str) -> str:
    """Map characters outside WinAnsi to safe equivalents (no missing-glyph boxes)."""
    text = text.replace(" ", " ").replace(" ", " ").replace("‑", "-")
    text = text.replace("−", "-").replace("→", "->").replace("≥", ">=")
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(_clean(str(text))), style)


def _eur(x: float, lang: str) -> str:
    s = f"{round(x):,}"
    return s.replace(",", " ") + " €" if lang == "fr" else f"€{s}"


def _pct(x: float, lang: str) -> str:
    s = f"{x:.1f}"
    return (s.replace(".", ",") if lang == "fr" else s) + " %" if lang == "fr" else s + "%"


def _trade_name(trade: dict, lang: str) -> str:
    names = {e.ticker: e.name for e in load_etfs()}
    return _product_name(trade["product"], names, lang)


def _letter_flowables(doc: Document, styles) -> list:
    out = [_p(doc.title, styles["h3"]), Spacer(1, 4)]
    for raw in doc.body.split("\n"):
        line = raw.strip()
        if not line:
            out.append(Spacer(1, 4))
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*]\s+", "- ", line)
        line = line.replace("**", "").replace("__", "")
        out.append(_p(line, styles["body"]))
    return out


def _table(rows, widths, align_right_from=1) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f5f8")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=NAVY, fontSize=20),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=NAVY, spaceBefore=10),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], textColor=NAVY),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12),
        "cell": ParagraphStyle("c", parent=base["BodyText"], fontSize=8.5, leading=10),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.5, leading=9),
    }


def _build(story: list, t: dict, disclaimer: str, title: str) -> bytes:
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, _clean(disclaimer))
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{t['page']} {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=2 * cm,
        title=title,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def review_pdf(review, facts: dict, documents: dict, lang: str) -> bytes:
    """Annual review PDF: performance, drift, profile, goals before/now, trades, verified letter."""
    if lang not in _T:
        raise ValueError(f"unsupported language {lang!r}")
    t = _T[lang]
    disclaimer = load_settings().disclaimer[lang]
    styles = _styles()
    c = facts["client"]
    pf = facts["profile"]
    story: list = [
        _p(t["r_title"], styles["title"]),
        _p(f"{t['client']}: {c['name']} ({c['client_id']})", styles["body"]),
        _p(f"{t['date']}: {facts['as_of']}", styles["body"]),
        _p(f"{t['r_proposal']}: {facts['proposal_date']}", styles["body"]),
    ]

    story.append(_p(t["r_perf"], styles["h2"]))
    rows = [[t["r_scope"], t["r_twr"], t["r_gain"], t["r_value"]]]
    perf = facts["performance"]
    for k in [k for k in perf if k != "total"] + ["total"]:
        v = perf[k]
        label = t["r_all"] if k == "total" else (_WRAPPER.get(k) or k)
        if isinstance(label, dict):
            label = label[lang]
        rows.append(
            [label, _pct(v["twr_pct"], lang), _eur(v["gain_eur"], lang), _eur(v["value_eur"], lang)]
        )
    story.append(_table(rows, [5 * cm, 3 * cm, 4 * cm, 4 * cm]))

    story.append(_p(t["r_drift"], styles["h2"]))
    rows = [[t["r_class"], t["target"], t["r_cur"], t["r_diff"], t["r_reb"]]]
    for d in facts["drift"]:
        rows.append(
            [
                asset_class_label(d["asset_class"], lang),
                _pct(d["target_pct"], lang),
                _pct(d["current_pct"], lang),
                _pct(d["diff_pct"], lang),
                t["r_yes"] if d["rebalance"] else t["r_no"],
            ]
        )
    story.append(_table(rows, [5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm]))

    story.append(_p(t["r_profile"], styles["h2"]))
    story.append(
        _p(
            f"{pf['profile_before_count']} {t['of7']} ({t['r_before']}) -> "
            f"{pf['profile_now_count']} {t['of7']} ({t['r_now']}). "
            + (t["r_changed"] if pf["profile_changed"] else t["r_same"]),
            styles["body"],
        )
    )

    story.append(_p(t["r_goals"], styles["h2"]))
    rows = [[t["goal"], t["target"], t["r_pb"], t["r_pn"]]]
    for g in facts["goals"]:
        label = g["label_fr"] if lang == "fr" else g["label"]
        rows.append(
            [
                Paragraph(escape(_clean(label)), styles["cell"]),
                _eur(g.get("target_today_eur", 0), lang),
                _pct(g["probability_before_pct"], lang),
                _pct(g["probability_now_pct"], lang),
            ]
        )
    story.append(_table(rows, [6 * cm, 3.5 * cm, 3 * cm, 3 * cm]))

    story.append(_p(t["r_trades"], styles["h2"]))
    if facts["trades"]:
        rows = [[t["r_wr"], t["r_prod"], t["r_act"], t["amount"], t["r_tax"], t["r_esttax"]]]
        for tr in facts["trades"]:
            w = _WRAPPER.get(tr["wrapper"], tr["wrapper"])
            rows.append(
                [
                    w[lang] if isinstance(w, dict) else w,
                    Paragraph(escape(_clean(_trade_name(tr, lang))), styles["cell"]),
                    t["r_buy"] if tr["action"] == "buy" else t["r_sell"],
                    _eur(tr["amount_eur"], lang),
                    t["r_yes"] if tr["taxable"] else t["r_no"],
                    _eur(tr["est_tax_eur"], lang),
                ]
            )
        story.append(_table(rows, [2.6 * cm, 5.4 * cm, 1.8 * cm, 2.6 * cm, 1.8 * cm, 2.2 * cm]))
    else:
        story.append(
            _p(t["r_notrades"].format(band=f"{review.drift_band * 100:g}"), styles["body"])
        )

    story.append(_p(t["r_letter"], styles["h2"]))
    letter = (documents or {}).get(lang)
    if letter is not None and letter.verified:
        story.extend(_letter_flowables(letter, styles))
    else:
        story.append(_p(t["r_noletter"], styles["body"]))
    story += [Spacer(1, 12), _p(disclaimer, styles["small"])]
    return _build(story, t, disclaimer, f"{t['r_title']} - {c['name']}")


def proposal_pdf(proposal, facts: dict, documents: dict, lang: str) -> bytes:
    if lang not in _T:
        raise ValueError(f"unsupported language {lang!r}")
    t = _T[lang]
    disclaimer = load_settings().disclaimer[lang]
    styles = _styles()
    c = facts["client"]
    story: list = [
        _p(t["title"], styles["title"]),
        _p(f"{t['client']}: {c['name']} ({c['client_id']})", styles["body"]),
        _p(f"{t['date']}: {facts['as_of']}", styles["body"]),
        _p(f"{t['profile']}: {facts['profile']['risk_profile_count']} {t['of7']}", styles["h2"]),
        _p(t["rules"], styles["h3"]),
    ]
    if proposal is not None:
        rules = [render(m, lang) for m in proposal.profile.rules_fired_msgs]
    else:
        rules = facts["profile"]["rules_fired"]
    for r in rules or [t["none"]]:
        story.append(_p("- " + r, styles["body"]))

    # wrapper plan
    story.append(_p(t["wrappers"], styles["h2"]))
    rows = [[t["wrapper"], t["amount"]]]
    for w in ("livret_a", "pea", "av", "cto", "fonds_euros"):
        v = facts["totals"].get(f"{w}_eur")
        if v:
            label = _WRAPPER[w] if isinstance(_WRAPPER[w], str) else _WRAPPER[w][lang]
            rows.append([label, _eur(v, lang)])
    rows.append([t["total"], _eur(facts["totals"]["total_eur"], lang)])
    story.append(_table(rows, [9 * cm, 4 * cm]))

    # goals
    story.append(_p(t["goals"], styles["h2"]))
    rows = [[t["goal"], t["target"], t["prob"], t["method"], t["ret"], t["vol"]]]
    for g in facts["goals"]:
        label = g["label_fr"] if lang == "fr" else g["label"]
        rows.append(
            [
                Paragraph(escape(_clean(label)), styles["cell"]),
                _eur(g["target_nominal_eur"], lang),
                _pct(g["probability_pct"], lang),
                _METHOD.get(g["chosen_method"], g["chosen_method"]),
                _pct(g["expected_return_pct"], lang),
                _pct(g["volatility_pct"], lang),
            ]
        )
    story.append(_table(rows, [5 * cm, 2.6 * cm, 2.2 * cm, 3 * cm, 2.2 * cm, 2.2 * cm]))

    # structured
    s = facts["structured"]
    sd = proposal.structured if proposal is not None else None
    story.append(_p(t["structured"], styles["h2"]))
    if s["included"]:
        name = _structured_name(s["product_id"], lang) if sd is not None else s["product_name"]
        story.append(_p(f"{t['included']}: {name} - {_eur(s['amount_eur'], lang)}", styles["body"]))
        if "prob_capital_loss_pct" in s:
            story.append(
                _p(f"{t['loss']}: {_pct(s['prob_capital_loss_pct'], lang)}", styles["body"])
            )
        if sd is not None and sd.payoff is not None and sd.payoff.describe_msg is not None:
            story.append(_p(render(sd.payoff.describe_msg, lang), styles["small"]))
        elif s.get("describe"):
            story.append(_p(s["describe"], styles["small"]))
        warnings = (
            [render(m, lang) for m in proposal.structured_warning_msgs]
            if proposal is not None
            else s.get("warnings", [])
        )
        for w in warnings:
            story.append(_p("- " + w, styles["small"]))
    else:
        story.append(_p(t["excluded"], styles["body"]))
        reasons = [render(m, lang) for m in sd.reason_msgs] if sd is not None else s["reasons"]
        for r in reasons:
            story.append(_p("- " + r, styles["small"]))

    # letter
    story.append(_p(t["letter"], styles["h2"]))
    letter = (documents or {}).get(lang)
    if letter is not None and letter.verified:
        story.extend(_letter_flowables(letter, styles))
    else:
        story.append(_p(t["noletter"], styles["body"]))

    story += [Spacer(1, 12), _p(disclaimer, styles["small"])]

    return _build(story, t, disclaimer, f"{t['title']} - {c['name']}")
