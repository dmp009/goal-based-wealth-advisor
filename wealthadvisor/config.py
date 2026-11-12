"""Loaders for the YAML files in ``config/``. Paths resolve from the repo root, not the cwd."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


@dataclass
class ETF:
    ticker: str
    isin: str
    name: str
    asset_class: str
    pea_eligible: bool
    sri: int
    ter: float
    proxy: str | None = None
    unverified: bool = False


@dataclass
class ProfileRule:
    profile: int
    vol_cap: float
    max_equity: float
    min_safe_share: float


@dataclass
class Settings:
    llm_model: str
    seed: int
    n_paths: int
    inflation: float
    drift_band: float
    prompt_version: str
    disclaimer: dict[str, str] = field(default_factory=dict)


def _load(name: str, path: Path | None = None) -> dict:
    with open(path or CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_etfs(path: Path | None = None) -> list[ETF]:
    return [ETF(**e) for e in _load("etfs.yaml", path)["etfs"]]


def load_profiles(path: Path | None = None) -> dict[int, ProfileRule]:
    raw = _load("profiles.yaml", path)["profiles"]
    return {int(k): ProfileRule(profile=int(k), **v) for k, v in sorted(raw.items())}


def load_rates(path: Path | None = None) -> dict:
    return _load("rates.yaml", path)


def load_tax_rules(path: Path | None = None) -> dict:
    return _load("tax_rules.yaml", path)


def load_cma(path: Path | None = None) -> dict[str, float]:
    return dict(_load("capital_market_assumptions.yaml", path)["returns"])


def load_reference_weights(path: Path | None = None) -> dict[str, float]:
    return dict(_load("capital_market_assumptions.yaml", path)["reference_weights"])


def load_cma_meta(path: Path | None = None) -> dict:
    """Source, as_of and unverified flag of the CMA file."""
    d = _load("capital_market_assumptions.yaml", path)
    return {k: d.get(k) for k in ("source", "as_of", "unverified")}


def load_structured(path: Path | None = None) -> dict:
    return _load("structured.yaml", path)


def load_questionnaire(path: Path | None = None) -> dict:
    return _load("questionnaire.yaml", path)


def load_settings(path: Path | None = None) -> Settings:
    return Settings(**_load("settings.yaml", path))
