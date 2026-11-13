# Business requirements

## 1. Context

A French retail or private bank employs wealth advisors (*conseillers en gestion de
patrimoine*) who meet each client at two key moments: **onboarding**, when the advisor must
assess suitability under MiFID II and build a first proposal, and the **annual review**, when
the advisor checks the portfolio and adjusts it.

Both moments involve the same mechanical work: scoring the questionnaire, sizing an emergency
fund, choosing between Livret A, PEA, assurance-vie and CTO, building a portfolio, estimating
whether each goal can be reached, deciding whether a structured product is suitable, and
writing a letter that compliance can approve. Done by hand in spreadsheets and word
processors, this work is slow, inconsistent between advisors and hard to audit.

**Objective.** Give the advisor one tool that produces a documented, goal-based proposal and
an annual review in minutes, where every number is computed by a tested engine, every rule
that shaped the result is written out, and every AI-drafted document is checked against the
engine's numbers.

**Out of scope.** Real client data, authentication, saving user edits beyond the session, a
full tax simulator, real bank products, order execution.

## 2. Stakeholders

| Stakeholder | Role | What they need from the tool | Involvement |
|---|---|---|---|
| Wealth advisor | Meets the client, builds and explains the proposal | A fast, complete proposal and review; a draft letter in the client's language; the freedom to switch the portfolio method per goal | Primary user, every client meeting |
| Compliance officer | Controls suitability and client communication | A traceable profile rationale, a reason for every excluded product, conditional-protection wording for autocalls, a disclaimer on every output, no AI figure that the engine did not compute | Reviewer, sign-off |
| Client | Receives the proposal and the letters | A clear letter in plain French or English, honest probabilities, no promise of returns | Indirect: never uses the app |
| Data / IT owner | Maintains data, configuration and code | Documented sources, data-quality report, data dictionary, tests and CI | Maintainer |

## 3. User stories and acceptance criteria

**US-1 Onboard a new client.**
As an advisor, I want to enter a client's situation, goals and questionnaire answers and get a
full proposal, so that I can prepare the first meeting quickly.

- The New client page accepts a sample client or a blank client (age, household, income,
  expenses, liquid assets, debts, monthly saving, goals with target, date and priority, all
  questionnaire answers).
- The proposal shows the emergency fund, one bucket per goal with its wrapper split, the
  portfolio of each bucket, the probability of each goal and the structured-product decision.
- The proposal is computed without network access, from the committed snapshot.

**US-2 Trace the suitability profile.**
As a compliance officer, I want to see why a client received a given risk profile, so that I
can check that the assessment follows the rules.

- The profile (1 to 7), the raw score, every cap rule that fired and every applicable cap that
  did not bind are shown as sentences.
- The same list is included in the facts JSON, the PDF and the AI documents.
- The four sample clients get exactly their expected profiles (3, 4, 6, 2); a test asserts it.

**US-3 Exclude unsuitable structured products with a reason.**
As a compliance officer, I want a structured product to be proposed only when the client meets
every condition, and otherwise a clear reason, so that no unsuitable product reaches a client.

- Inclusion requires profile ≥ 4, horizon ≥ 8 years and declared knowledge of structured
  products; the amount is at most 15 % of investable assets after the emergency fund.
- When excluded, every failing condition is listed in the app, the PDF and the AI documents.
- The autocall is described as conditional protection ("capital repaid at maturity unless the
  index has fallen more than 40 %"), never as "capital protected".

**US-4 Draft the proposal letter in English and French.**
As an advisor, I want an advisor summary and a client letter in both languages, drafted from
the engine's numbers only, so that I save writing time without risking a wrong figure.

- Four documents per proposal: advisor summary and client letter, each in EN and FR.
- Every number in a document must match a fact (percent at its written precision, euros within
  ±1 % and at least 1 €, years and ages exactly) and stay within its goal's section; otherwise
  the model gets one retry, then the document is rejected and the errors are shown.
- Only verified documents are cached and shown; every document ends with the disclaimer.
- The French letter uses the formal *vous*.

**US-5 Run the annual review.**
As an advisor, I want to load an existing client and see performance, drift, profile change and
goal probabilities, so that I can lead the review meeting.

- Available for clients with an original proposal (sample clients c2 and c3).
- Shows time-weighted return and gain per wrapper and in total, drift per asset class against
  the ±5 point band, profile before and now (with edited answers), and goal probabilities at
  the proposal date and today.
- Review documents (advisor summary and client letter, EN and FR) and a PDF export are
  available, with the same verification as US-4.

**US-6 Propose tax-aware rebalancing trades.**
As an advisor, I want concrete trades in euros that bring the portfolio back inside the band
without needless tax, so that I can act on the review.

- Only asset classes outside the band trigger trades; trades stay inside each wrapper and buys
  equal sells per wrapper.
- Structured products and the Livret A are not traded.
- CTO sales are flagged as taxable with an estimated tax; PEA and assurance-vie sales are not
  taxable events.

**US-7 Trust the data.**
As a data owner, I want automated checks and documented sources, so that I know which inputs
to challenge.

- Checks: no gap of more than one month within each price history, no non-positive price,
  no stale price (three or more identical month-end closes in a row, warning), prices for
  every ETF in the configuration, PEA holdings only in PEA-eligible products, Livret A balance
  within the ceiling. Results are written to `data_quality_report.md` with the checks run,
  row counts per table and the proxy share per ticker.
- Every ETF lists its sources and its unverified fields; unknown values are left empty, never
  guessed. The capital market assumptions carry their source and an `unverified` flag.
- Raw price responses are saved with a timestamp; back-filled prices are flagged `is_proxy`.

**US-8 Demo without keys or network.**
As a recruiter or a reviewer, I want to open the app and see the whole workflow without an API
key, so that the demo always works.

- `make app` runs on committed files only (snapshot parquet, sample clients, config).
- Without cached AI documents, the document tabs show "Not generated yet" and every other
  feature works.
- Tests make no network calls; CI runs ruff and pytest on every push.

## 4. KPI definitions

| KPI | Definition | Where |
|---|---|---|
| **Goal probability** | Share of the 10,000 simulated paths in which the bucket's value at the goal date, **after tax**, is at least the target inflated to that date (2 % a year). Shown with one decimal. A goal below 50 % is flagged *at risk* (`shortfall_flag`). | New client, Annual review (before and now), facts `probability_pct` |
| **P10 / P50 / P90 outcome** | 10th, 50th and 90th percentiles of the after-tax value at the goal date. | Facts `p10_eur`, `p50_eur`, `p90_eur` |
| **Drift** | Current weight minus target weight of each asset class, in percentage points of the total portfolio. Target = asset-class weights of the original proposal (fonds en euros and Livret A count as "safe"). A class drifts when the absolute difference exceeds the band (default 5 points). | Annual review, facts `drift[].diff_pct` |
| **Time-weighted return (TWR)** | Chain-linked monthly return, where each month's growth is the value before that month's contribution divided by the value after the previous month's contribution. Contributions therefore never count as performance. | Annual review, facts `performance.*.twr_pct` |
| **Gain** | Current value minus total contributions since the proposal date. | Facts `performance.*.gain_eur` |
| **Suitability coverage** | Share of risky product families with an explicit include or exclude decision and at least one written reason. Target 100 %: equity ETFs, bond ETFs and structured products each carry a decision and reasons in the facts, and every appropriateness warning is listed. Livret A and fonds en euros are capital-guaranteed and suitable for every profile by rule. | Facts `appropriateness`, `structured.reasons` |
| **Document verification rate** | Share of generated AI documents that pass the numeric check. Unverified documents are never cached or shown. | Pipeline log (`verified` / `UNVERIFIED`) |
