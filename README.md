# Copytrade with Claude

Adaptive copy-trading on Hyperliquid: every day we re-evaluate the public leaderboard, pick the
top 5 most consistent/profitable traders by volume-normalized edge, and paper-trade in parallel
whenever one of them opens or closes a position.

- **No real money** for the first 2 weeks — pure paper trading ($10,000 starting cash).
- Fully autonomous via GitHub Actions + an external scheduler (cron-job.org), driving three
  workflows: daily shortlist refresh, 5-minute position polling, and a 30-minute Slack report.
- State (`active_wallets.json`, `signals.json`, `portfolio.json`, `paper_trades.json`, `state/`,
  `NOTES.md`) is committed back to the repo by `github-actions[bot]` so runs share continuity.

See [CLAUDE.md](CLAUDE.md) for full architecture, scoring logic, and implementation details.
