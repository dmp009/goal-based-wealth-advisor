"""Client data model and loaders for the sample clients in ``data/clients/``."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from wealthadvisor.config import REPO_ROOT

Answers = dict[str, str]  # question id -> answer key (see config/questionnaire.yaml)


class Goal(BaseModel):
    goal_id: str
    label: str
    target_today_eur: float
    date: date
    priority: Literal["essential", "aspirational"]


class Holding(BaseModel):
    wrapper: Literal["livret_a", "pea", "av", "cto"]
    ticker: str | None  # None for fonds euros and Livret A
    product: str  # "etf", "fonds_euros", "livret_a" or "structured:<id>"
    units: float
    avg_cost: float


class Client(BaseModel):
    client_id: str
    name: str
    age: int
    household: Literal["single", "couple"]
    annual_income: float
    monthly_expenses: float
    liquid_assets: float
    debts: float
    monthly_saving: float
    goals: list[Goal]
    answers: Answers
    # wrapper -> product key -> amount in EUR, e.g. {"av": {"fonds_euros": 40000, "CW8.PA": 25000}}
    original_proposal: dict | None = None
    proposal_date: date | None = None


def load_client(path: Path | str) -> Client:
    with open(path, encoding="utf-8") as f:
        return Client.model_validate(json.load(f))


def list_sample_clients() -> list[Client]:
    files = sorted((REPO_ROOT / "data" / "clients").glob("*.json"))
    return [load_client(p) for p in files]
