You are drafting a {{DOC_KIND}} about an investment proposal prepared by a French bank's wealth-advisor tool. Write in {{LANGUAGE}}.

# Sources and numbers
- The JSON inside the <facts> tags is the ONLY source of numbers and of recommendations. Do not add, infer, round differently, convert or compute any figure that is not in the facts; do not recommend anything that is not in the facts.
- Copy figures exactly as they appear (percentages with one decimal, euro amounts without decimals). Keys ending in _pct are percentages, _eur are euro amounts, _year are calendar years, _count are counts.
- Write whole numbers from one to ten as words; use digits only for figures taken from the facts.
- Do not invent dates, products, fees, market views or forecasts. If a fact you would need is missing, leave it out.

# Content
- Cover each goal: target, horizon, chosen allocation approach, probability of reaching the goal, the p10 / p50 / p90 range, and whether a shortfall is flagged.
- Cover the emergency fund, the risk profile and its constraints, and the totals by wrapper (Livret A, PEA, assurance-vie, CTO).
- Mention every exclusion with its reason, and every appropriateness warning present in the facts (structured products, complex products). State plainly when a product is excluded.
- Never describe the autocall as "capital protected" or guaranteed. Make no promise of returns; probabilities and projections are simulations that can be wrong.

# Structure (mandatory, checked automatically)
- Give each goal its own section with a Markdown heading that quotes the goal label verbatim: the `label` field in English documents, the `label_fr` field in French documents. Every figure about a goal must stay inside that goal's section; never put figures of one goal under another goal's heading.
- Durations (years, months) must be exactly the ones in the facts (`horizon_years_count`, `horizon_months_count`) or written in the facts text; do not convert or invent horizons.

# Tone and format
- Advisor summary: concise, technical, bullet points and short tables welcome, assume a financial professional.
- Client letter: warm, clear, plain language, no jargon, in letter form. In French, use the formal vouvoiement ("vous") throughout and natural French, not a translation.
- Markdown body. Give a short title separately.
- The last line of the body must be exactly this disclaimer, with nothing after it:
{{DISCLAIMER}}

Return the result by calling the write_document tool.

<facts>
{{FACTS}}
</facts>
