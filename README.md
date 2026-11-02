# Job_Agent

**English** · [中文](README.zh-CN.md)

A human-in-the-loop agent for job and internship searches. It collects openings from
company career boards, decides for each one whether it is worth applying to — **quoting the
sentence of the posting each decision rests on** — and tracks every application in an
audited state machine. The agent does the reading, filtering and paperwork; the person makes
every final call.

All personal data (CV facts, contact details, preferences) lives in a private _vault_
outside the repository. Without one, the agent runs on a fictional demo candidate.

## How it works

```
 company career    ┐
 boards (ATS)      ├─► ingest ─► route ──────────────► ledger (SQLite) ─► pick ─────► prepare ─────► tracker.xlsx
 queued JSON       ┘   dedupe    work permit · language  13 states,         daily       JD + answers    the person
 records from any                timing · direction      enforced           shortlist,  + CV template   decides and
 collector                       size · evidence         transitions,       veto        per country     applies
                                                         audit log          window
```

1. **Collect** (`job_agent/sources/`): polls the public job-board APIs of Greenhouse, Lever,
   Ashby, SmartRecruiters, Recruitee, Workable and Teamtailor for the companies listed in the
   vault's `companies.yml`, and ingests posting records (JSON) written by any other collector.
   `scripts/ats_probe.py` finds which ATS a company uses.
2. **Route** (`route.py`, `enrich/`, `season.py`): every posting gets a status and a reason
   backed by evidence — work authorisation per country, required languages, when the
   internship runs, career direction, company size.
3. **Ledger** (`store.py`): `discovered → awaiting_confirm / approved / manual / skipped →
   tailored → applied → oa / interview / offer / rejected / withdrawn`. Only transitions in
   the `TRANSITIONS` table are allowed, and every move is written to an `events` table.
4. **Pick & prepare** (`pick.py`, `prepare.py`): proposes a daily shortlist in the person's
   order of preference (direction, country, season), with a cap per company. Picks only take
   effect the next day, so the person can veto them. For each pick it writes the JD, answers
   to the usual application questions (`answers.py`), and the right CV template for the country.
5. **Tracker** (`tracker.py`): one spreadsheet to work in — decide, update status, take
   notes. Edits are read back into the ledger before the sheet is regenerated.

## Design decisions

- **Every decision cites its evidence.** Not just "skipped: requires Swedish" but the
  sentence *"Fluent Swedish is a requirement for this role"*. A wrong rule is visible at a
  glance, and when a rule changes, `reroute` re-applies it to every posting no human has
  touched yet.
- **Rules are data, not code.** Policy, work-authorisation rules, role definitions and
  country conventions are YAML (`demo_vault/`, `packs/`). Changing the search means editing
  configuration, not Python.
- **The person stays in the loop.** The agent filters, ranks and prepares; it does not apply
  on anyone's behalf. Its picks wait a day for a veto, and the person's own decision always
  wins over the agent's.
- **Unclear means manual.** If the JD could not be read, the language requirement is
  ambiguous or the work-permit route is unverified, the posting goes to a manual list
  instead of being guessed.
- **Personal data never enters the repo.** `scripts/leak_scan.py` checks every file against
  private denylists and generic patterns (phone numbers, e-mail addresses) in a pre-commit
  hook and in CI.
- **No LinkedIn automation, no CAPTCHA workarounds.** Postings that need them go to the
  manual list.

## Run it

```bash
pip install pyyaml openpyxl pytest
python -m job_agent scan       # poll the demo companies' job boards (demo vault unless JOB_VAULT is set)
python -m job_agent route      # decide status + reason for each posting
python -m job_agent list
python -m job_agent tracker    # writes tracker.xlsx
pytest -q
```

To use it for your own search: copy `demo_vault/` somewhere private, fill it in, set
`JOB_VAULT=/path/to/your/vault`, and write `work_authorization.yml` for **your** passport
and enrolment from official sources — the demo values are illustrative.

The tracker's column headers and choices are currently in Chinese; an English locale is on
the roadmap.

## Roadmap

- **Source plugins**: declare sources in the vault (`sources.yml`: ATS boards, GitHub
  README tables, RSS, JSON feeds) and add new source types as small Python modules.
- **Locales**: tracker UI in English and Chinese.
- **More markets**: rules and sources for campus recruiting in China (graduation year,
  degree requirements, autumn / spring / summer seasons).
- Keyword-coverage check of each prepared CV against its JD.
- Draft answers to open questions ("Why us?") from the JD and the candidate's fact base,
  for the person to edit.

## License

MIT
