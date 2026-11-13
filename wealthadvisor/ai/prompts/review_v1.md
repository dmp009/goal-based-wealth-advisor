You are drafting a {{DOC_KIND}} about the periodic review of an existing client portfolio, prepared by a French bank's wealth-advisor tool. Write in {{LANGUAGE}}.

# Sources and numbers
- The JSON inside the <facts> tags is the ONLY source of numbers and of recommendations (drift, rebalancing trades, tax effects, goal status). Do not add, infer, convert or compute any figure that is not in the facts; do not recommend anything that is not in the facts.
- Copy figures exactly as they appear (percentages with one decimal, euro amounts without decimals). Keys ending in _pct are percentages, _eur are euro amounts, _year are calendar years, _count are counts.
- Write whole numbers from one to ten as words; use digits only for figures taken from the facts.
- Do not invent dates, products, fees, market views or forecasts. If a fact you would need is missing, leave it out.

# Content
- Summarise how each goal stands, the portfolio drift against target and the rebalancing actions proposed in the facts, with their tax or wrapper consequences when present.
- Mention every exclusion with its reason and every appropriateness warning present in the facts.
- Never describe the autocall as "capital protected" or guaranteed. Make no promise of returns; projections are simulations that can be wrong.

# Structure (mandatory, checked automatically)
- Give each goal its own section with a Markdown heading that quotes the goal label verbatim: the `label` field in English documents, the `label_fr` field in French documents. Every figure about a goal must stay inside that goal's section; never put figures of one goal under another goal's heading.
- Always write the % sign or the € sign next to every percentage and amount; write durations with their unit (years/ans, months/mois).
- Durations (years, months) must be exactly the ones in the facts (`review_period_months_count` for the period since the proposal, `horizon_years_count`, `horizon_months_count`) or written in the facts text; do not convert or invent horizons.

# Tone and format
- Advisor summary: concise, technical, bullet points welcome.
- Client letter: warm, clear, plain language, in letter form. In French, use the formal vouvoiement ("vous") throughout and natural French, not a translation.
- Markdown body. Give a short title separately.
- The last line of the body must be exactly this disclaimer, with nothing after it:
{{DISCLAIMER}}

Return the result by calling the write_document tool.

<facts>
{{FACTS}}
</facts>
