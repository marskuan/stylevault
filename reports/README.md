# FOMC Reports

The `FOMC Watch` GitHub Actions workflow (`.github/workflows/fomc-watch.yml`)
writes a dated `fomc-YYYY-MM-DD.md` here after each FOMC statement is released.

Each report includes:
- the policy rate decision (auto-extracted),
- the full statement text,
- a **redline diff** vs. the previous meeting's statement — the wording changes
  are the signal economists watch most closely, and
- an optional Traditional Chinese summary (only if an `ANTHROPIC_API_KEY`
  repo secret is configured).

For the 6/17/2026 meeting, the statement is released at 2:00 PM ET
(18:00 UTC = 02:00 the next day, Taipei time). The workflow runs shortly after,
so a report is committed well before 9 AM Taipei time.
