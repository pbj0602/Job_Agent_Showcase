# Demo vault

A fictional candidate, so the engine runs end to end without anyone's real data.
Copy this folder somewhere private, replace the contents with your own, and point
`JOB_VAULT` at it. Never commit a real vault to a public repository.

| File | What it is |
|---|---|
| `profile.yml` | Who the candidate is (fictional: Alex Morgan) |
| `base.md` | Every fact a CV may use — the single source of truth for tailoring |
| `work_authorization.yml` | Per-country route: does the employer need to sponsor? (illustrative values — write your own from official sources) |
| `policy.yml` | Target roles and countries, season, how the daily shortlist is picked |
| `answers.yml` | Answers for application forms |
| `companies.yml` | Companies whose ATS feeds `job-agent scan` polls |
| `registers.yml` | Public sponsor registers to check employers against |
| `state/` | The job database (created on first run) |
