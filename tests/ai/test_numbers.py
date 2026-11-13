import pytest

from wealthadvisor.ai.numbers import extract_numbers, verify

FACTS = {
    "disclaimer": {"en": "Educational project — not investment advice (2026)", "fr": "Projet"},
    "as_of": "2026-10-31",
    "client": {"name": "Claire", "age": 45},
    "goals": [
        {
            "label": "House",
            "probability_pct": 72.3,
            "max_drawdown_pct": -15.0,
            "target_nominal_eur": 38500,
            "goal_year": 2031,
            "horizon_years_count": 5,
            "shortfall_flag": True,
            "rules": ["Horizon is 4.7 years", "Contribution 22,950 EUR a year", "cap of 40 %"],
        }
    ],
}


def vk(text, lang="en"):
    return [(t.value, t.kind) for t in extract_numbers(text, lang)]


def test_en_grouping_and_decimals():
    assert vk("1,234.5") == [(1234.5, "plain")]
    assert vk("1,234") == [(1234.0, "plain")]
    assert vk("about 4.7 years") == [(4.7, "plain")]


@pytest.mark.parametrize("sp", [" ", " ", " "])
def test_fr_grouping_spaces(sp):
    assert vk(f"1{sp}234,5", "fr") == [(1234.5, "plain")]
    assert vk(f"1{sp}234,5{sp}€", "fr") == [(1234.5, "eur")]


def test_percent_forms():
    assert vk("12,5 %", "fr") == [(12.5, "percent")]
    assert vk("12,5 %", "fr") == [(12.5, "percent")]
    assert vk("12.5%") == [(12.5, "percent")]
    assert vk("-15.0 %") == [(-15.0, "percent")]
    assert vk("−15,0 %", "fr") == [(-15.0, "percent")]


def test_eur_forms():
    for text, lang in [
        ("€1,200", "en"),
        ("EUR 1,200", "en"),
        ("1,200 EUR", "en"),
        ("1 200 €", "fr"),
        ("1 200 €", "fr"),
        ("1 200 euros", "fr"),
    ]:
        assert vk(text, lang) == [(1200.0, "eur")], text


def test_multipliers():
    assert vk("38.5k") == [(38500.0, "eur")]
    assert vk("€38.5k") == [(38500.0, "eur")]
    assert vk("1.2 million") == [(1_200_000.0, "eur")]
    assert vk("1,2 M€", "fr") == [(1_200_000.0, "eur")]
    assert vk("10 months") == [(10.0, "plain")]


def test_years_and_ages():
    assert vk("in 2030") == [(2030.0, "year")]
    assert vk("2026-10-31") == [(2026.0, "year"), (10.0, "plain"), (31.0, "plain")]
    assert vk("a 68-year-old client") == [(68.0, "age")]
    assert vk("a 68 years old client") == [(68.0, "age")]
    assert vk("cliente de 68 ans", "fr") == [(68.0, "age")]
    assert vk("3000") == [(3000.0, "plain")]


def test_ranges_and_markers():
    assert vk("3–5 years") == [(3.0, "plain"), (5.0, "plain")]
    assert vk("3-5") == [(3.0, "plain"), (5.0, "plain")]
    assert vk("3–5 %") == [(3.0, "percent"), (5.0, "percent")]
    assert vk("1. Intro\n2. Plan with 5 %\n  3) end") == [(5.0, "percent")]


def test_identifiers_ignored():
    assert vk("ISIN FR0011869353 and P10 and p50_eur") == []


def test_verify_matching_letter_passes():
    text = (
        "Dear Claire, your 45 years, the house goal in 2031 has a 72.3 % chance "
        "(about 72 %), target 38 500 EUR (38.5k), drawdown -15.0 %, horizon 5 years "
        "or 4.7 years, 22,950 EUR a year, cap of 40 %.\n\n"
        "1. First point\nEducational project — not investment advice (2026)"
    )
    assert verify(text, "en", FACTS) == []


def test_verify_flags_wrong_percent():
    errs = verify("The chance is 65 %.", "en", FACTS)
    assert len(errs) == 1 and "65" in errs[0]


def test_verify_percent_tolerance():
    assert verify("about 72,3 %", "fr", FACTS) == []
    assert verify("about 72 %", "fr", FACTS) == []
    assert verify("about 72,6 %", "fr", FACTS) != []
    assert verify("about 73.0 %", "en", FACTS) != []


def test_verify_year_must_match():
    assert verify("by 2032", "en", FACTS) != []
    assert verify("by 2031", "en", FACTS) == []


def test_verify_eur_tolerance_and_scale():
    assert verify("38 700 €", "fr", FACTS) == []  # within 1 %
    assert verify("39 500 €", "fr", FACTS) != []
    assert verify("€38.5k", "en", FACTS) == []
    assert verify("€385k", "en", FACTS) != []


def test_verify_age_exact_and_ans_fallback():
    assert verify("a 45-year-old", "en", FACTS) == []
    assert verify("a 50-year-old", "en", FACTS) != []
    assert verify("sur 5 ans", "fr", FACTS) == []
    assert verify("sur 7 ans", "fr", FACTS) != []


def test_verify_plain_and_text_numbers():
    assert verify("horizon of 4.7 years", "en", FACTS) == []
    assert verify("horizon of 4.9 years", "en", FACTS) != []
    assert verify("one, two, three and ten", "en", FACTS) == []


def test_verify_bool_not_a_number():
    facts = {"flag": True, "x_count": 3}
    assert verify("1", "en", facts) != []
    assert verify("3", "en", facts) == []


def test_verify_disclaimer_exempt():
    facts = {"x_count": 3}
    assert (
        verify(
            "ok 3\n\nProjet 2026 pédagogique 99",
            "fr",
            facts,
            disclaimers=["Projet 2026 pédagogique 99"],
        )
        == []
    )
