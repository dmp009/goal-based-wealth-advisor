"""English / French templates for the engine's finite set of explanatory sentences.

Engine modules keep their English strings (they feed the AI facts and the app) and, next to each
sentence, a ``Msg`` (stable code + parameters). The PDFs re-render those messages in the client's
language with ``render``. The English template of every code reproduces the engine string
exactly (tested), so the English facts and text are unchanged.

French number formatting: decimal comma, space as thousands separator ("11 100 €", "4,4 ans").
"""

from __future__ import annotations

import string
from typing import Any, Literal

from pydantic import BaseModel

Lang = Literal["en", "fr"]


class Msg(BaseModel):
    code: str
    params: dict[str, Any] = {}

    def render(self, lang: Lang = "en") -> str:
        return render(self, lang)


_FAMILY = {
    "equity ETFs": {"en": "equity ETFs", "fr": "des ETF actions"},
    "bond ETFs": {"en": "bond ETFs", "fr": "des ETF obligataires"},
}

TEMPLATES: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ profile caps (scoring.py)
    "cap.horizon_lt_3y": {
        "en": "Longest goal horizon is {horizon:.1f} years (less than 3 years): "
        "profile capped at {cap}.",
        "fr": "L'horizon du plus long objectif est de {horizon:.1f} ans (moins de 3 ans) : "
        "profil plafonné à {cap}.",
    },
    "cap.horizon_3_to_5y": {
        "en": "Longest goal horizon is {horizon:.1f} years (3 to 5 years): profile capped at {cap}.",
        "fr": "L'horizon du plus long objectif est de {horizon:.1f} ans (de 3 à 5 ans) : "
        "profil plafonné à {cap}.",
    },
    "cap.loss_capacity_low": {
        "en": "Loss capacity is low: profile capped at {cap}.",
        "fr": "Capacité à subir des pertes faible : profil plafonné à {cap}.",
    },
    "cap.no_equity_etf_knowledge": {
        "en": "No knowledge of equity ETFs: profile capped at {cap}.",
        "fr": "Aucune connaissance des ETF actions : profil plafonné à {cap}.",
    },
    "cap.not_binding": {  # suffix appended to a cap sentence (its final period removed)
        "en": " (not binding, profile already {profile}).",
        "fr": " (non contraignant, profil déjà à {profile}).",
    },
    # ------------------------------------------------------------ product suitability (products.py)
    "suit.guaranteed": {
        "en": "Capital-guaranteed product, suitable for every profile.",
        "fr": "Produit à capital garanti, adapté à tous les profils.",
    },
    "suit.bond_allowed": {
        "en": "Bond ETFs are allowed from profile 1 (client profile {p}).",
        "fr": "Les ETF obligataires sont autorisés dès le profil 1 (profil du client : {p}).",
    },
    "suit.equity_allowed": {
        "en": "Equity ETFs are allowed from profile 2 (client profile {p}).",
        "fr": "Les ETF actions sont autorisés dès le profil 2 (profil du client : {p}).",
    },
    "suit.equity_requires": {
        "en": "Equity ETFs require profile 2 or higher (client profile {p}).",
        "fr": "Les ETF actions exigent un profil de 2 ou plus (profil du client : {p}).",
    },
    "suit.no_knowledge": {
        "en": "Client declares no knowledge of {label}: appropriateness warning, "
        "the advisor must explain the risks before investing.",
        "fr": "Le client déclare n'avoir aucune connaissance {label} : avertissement "
        "d'adéquation, le conseiller doit expliquer les risques avant tout investissement.",
    },
    "suit.structured_min_profile": {
        "en": "Structured products require profile {min_profile} or higher (client profile {p}).",
        "fr": "Les produits structurés exigent un profil de {min_profile} ou plus "
        "(profil du client : {p}).",
    },
    "suit.structured_min_horizon": {
        "en": "Structured products require a horizon of at least {min_years} years "
        "(client horizon {horizon:.1f} years).",
        "fr": "Les produits structurés exigent un horizon d'au moins {min_years} ans "
        "(horizon du client : {horizon:.1f} ans).",
    },
    "suit.structured_no_knowledge": {
        "en": "The client declares no knowledge of structured products.",
        "fr": "Le client déclare n'avoir aucune connaissance des produits structurés.",
    },
    "suit.structured_ok": {
        "en": "Profile, horizon and declared knowledge all meet the structured-product conditions.",
        "fr": "Le profil, l'horizon et les connaissances déclarées remplissent toutes les "
        "conditions d'accès aux produits structurés.",
    },
    # ------------------------------------------------------------ structured decision
    "structured.chosen": {
        "en": "Product {product_id} chosen for profile {profile}; amount capped at "
        "{share:.0f} % of investable assets after the emergency fund.",
        "fr": "Produit {product_id} retenu pour le profil {profile} ; montant plafonné à "
        "{share:.0f} % des actifs investissables après l'épargne de précaution.",
    },
    "structured.reduced": {
        "en": "Structured amount reduced from {before:,.0f} EUR to {after:,.0f} EUR: "
        "the longest-horizon bucket's risky sleeve is smaller.",
        "fr": "Montant du produit structuré ramené de {before:,.0f} € à {after:,.0f} € : "
        "la poche risquée de l'objectif le plus lointain est plus petite.",
    },
    "structured.too_small": {
        "en": "The longest-horizon bucket has no risky sleeve large enough to fund a structured "
        "product (minimum {min_ticket:,.0f} EUR).",
        "fr": "L'objectif le plus lointain n'a pas de poche risquée suffisante pour financer un "
        "produit structuré (minimum {min_ticket:,.0f} €).",
    },
    "structured.describe_autocall": {
        "en": "{years}-year autocall on the Euro Stoxx 50: if the index is at or above "
        "{autocall:.0f} % of its start on an annual observation date, the product is called "
        "early and pays {coupon:.1f} % per elapsed year. Otherwise capital is repaid at maturity "
        "unless the index has fallen more than {drop} %, in which case the investor bears the "
        "full index loss. Issuer credit risk applies.",
        "fr": "Autocall de {years} ans sur l'Euro Stoxx 50 : si, à une date de constatation "
        "annuelle, l'indice est au moins à {autocall:.0f} % de son niveau initial, le produit "
        "est remboursé par anticipation et verse {coupon:.1f} % par année écoulée. Sinon, le "
        "capital est remboursé à l'échéance sauf si l'indice a baissé de plus de {drop} % : "
        "l'investisseur subit alors l'intégralité de la baisse de l'indice. Le risque de crédit "
        "de l'émetteur s'applique.",
    },
    "structured.describe_cpn": {
        "en": "{years}-year note: 100 % of capital repaid at maturity plus {participation:.0f} % "
        "of any rise in the Euro Stoxx 50 (price index, dividends not included). "
        "Issuer credit risk applies.",
        "fr": "Titre de créance de {years} ans : 100 % du capital remboursé à l'échéance, plus "
        "{participation:.0f} % de la hausse éventuelle de l'Euro Stoxx 50 (indice de prix, hors "
        "dividendes). Le risque de crédit de l'émetteur s'applique.",
    },
}

PRODUCT_NAMES: dict[str, dict[str, str]] = {
    "livret_a": {"en": "Livret A", "fr": "Livret A"},
    "fonds_euros": {"en": "Fonds en euros", "fr": "Fonds en euros"},
    "autocall": {"en": "Autocall on the Euro Stoxx 50", "fr": "Autocall sur l'Euro Stoxx 50"},
    "capital_protected_note": {
        "en": "Capital-protected note on the Euro Stoxx 50",
        "fr": "Note à capital protégé sur l'Euro Stoxx 50",
    },
}

ASSET_CLASSES: dict[str, dict[str, str]] = {
    "safe": {
        "en": "Safe assets (Livret A, fonds en euros)",
        "fr": "Actifs sécurisés (Livret A, fonds en euros)",
    },
    "structured": {"en": "Structured product", "fr": "Produit structuré"},
    "equity_world": {"en": "World equities", "fr": "Actions monde"},
    "equity_europe": {"en": "European equities", "fr": "Actions Europe"},
    "equity_us": {"en": "US equities", "fr": "Actions États-Unis"},
    "equity_em": {"en": "Emerging-market equities", "fr": "Actions marchés émergents"},
    "bond_gov_euro": {"en": "Euro government bonds", "fr": "Obligations d'État zone euro"},
    "bond_corp_euro": {"en": "Euro corporate bonds", "fr": "Obligations d'entreprises zone euro"},
    "bond_inflation_euro": {
        "en": "Euro inflation-linked bonds",
        "fr": "Obligations indexées sur l'inflation zone euro",
    },
}


class _Formatter(string.Formatter):
    def __init__(self, lang: Lang):
        self.lang = lang

    def format_field(self, value, format_spec):
        out = super().format_field(value, format_spec)
        if self.lang == "fr" and isinstance(value, int | float) and not isinstance(value, bool):
            out = out.replace(",", " ").replace(".", ",")
        return out


def render(msg: Msg | str, lang: Lang = "en", **params) -> str:
    """Render a message (or a code with ``params``) in ``lang``.

    ``params["not_binding"]`` (profile caps): the sentence is followed by the not-binding suffix.
    """
    if isinstance(msg, Msg):
        code, params = msg.code, {**msg.params, **params}
    else:
        code = msg
    if lang not in ("en", "fr"):
        raise ValueError(f"unsupported language {lang!r}")
    fmt = _Formatter(lang)
    p = dict(params)
    if "label" in p and p["label"] in _FAMILY:
        p["label"] = _FAMILY[p["label"]][lang]
    out = fmt.format(TEMPLATES[code][lang], **p)
    if p.get("not_binding") is not None:
        out = out.rstrip(".") + fmt.format(
            TEMPLATES["cap.not_binding"][lang], profile=p["not_binding"]
        )
    return out


def product_name(key: str, lang: Lang, default: str | None = None) -> str:
    """Display name of a product key ("livret_a", "fonds_euros") or structured kind."""
    names = PRODUCT_NAMES.get(key)
    return names[lang] if names else (default if default is not None else key)


def asset_class_label(cls: str, lang: Lang) -> str:
    labels = ASSET_CLASSES.get(cls)
    return labels[lang] if labels else cls.replace("_", " ")
