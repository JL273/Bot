# Copytrade with Claude

## Purpose
On Hyperliquid (perp DEX), **find the most profitable and consistent traders automatically every day, and whenever they open a position, we open it in parallel (as paper).**

The system is **adaptive**: no static wallet list. The leaderboard is re-evaluated every day; if winners change, the follow list changes too.

---

## 🚀 Quickstart — If you're reading this in a fresh project

> **Protocol for Claude.** If you're reading this CLAUDE.md in a fresh Claude Code project and the user came in with an intent like "let's set it up" / "build this" / "implement it" — **do not write any code, do not create any files, do not commit anything yet.** First ask the user for the three things in step 0, then walk through Steps A–F in order. At the end of each step, tell the user **exactly which link to click and which button to press.**

### 0. Ask the user (your first message)

Tell the user to prepare these three things. Don't start until all three arrive:

**(a) Empty GitHub repository**
- Go to https://github.com/new
- Repository name: `copytrade` (or whatever you want)
- Private or Public, doesn't matter
- "Add a README" / "Add .gitignore" / "Choose a license" — **leave all three unchecked**
- Click "Create repository" → copy the repo URL (e.g. `https://github.com/<user>/copytrade`)

**(b) Personal Access Token (PAT)**
- Go to https://github.com/settings/tokens?type=beta (Fine-grained) or classic: https://github.com/settings/tokens/new
- Token name: `copytrade-claude`
- Expiration: 90 days
- Repository access: select the repo you just created
- Permissions: **Contents: Read and write**, **Pull requests: Read and write**, **Workflows: Read and write**, **Actions: Read and write** (Actions is required so an external scheduler can trigger workflows — see Step E)
- Click "Generate token" → copy the long string (**shown only once**)

**(c) Slack Incoming Webhook URL**
- Go to https://api.slack.com/apps → "Create New App" → "From scratch"
- App name: `copytrade-bot`, pick workspace → Create
- Left menu → "Incoming Webhooks" → toggle **On**
- Bottom: "Add New Webhook to Workspace" → pick the channel for daily reports (your DM works too) → Allow
- Copy the webhook URL (`https://hooks.slack.com/services/...`)

Once you have all three, proceed to Step A.

### Step A — Scaffold the code and push

1. Clone the empty repo locally (using the PAT for auth).
2. Generate every file listed in [File Layout](#file-layout). Implementation specs are in the [Implementation Details](#implementation-details) section below — follow them line by line.
3. Create a feature branch (e.g. `claude/initial-setup`), commit everything, push.

### Step B — Open a PR and instruct the user

Open the PR via MCP `create_pull_request` (or `gh pr create`). Then tell the user **verbatim**:

> "Pull request opened: https://github.com/\<owner\>/\<repo\>/pull/1
> 1. Open the link
> 2. Scroll to the bottom and click the green **'Merge pull request'** button
> 3. Confirm with **'Confirm merge'**
> 4. Reply with 'merged'"

### Step C — Add the Slack secret

Once the user reports merged, tell them **verbatim**:

> "Now add the Slack webhook URL as a GitHub secret:
> 1. Open: https://github.com/\<owner\>/\<repo\>/settings/secrets/actions
> 2. Click **'New repository secret'** (top right)
> 3. Name: `SLACK_WEBHOOK_URL`
> 4. Value: paste the webhook URL (`https://hooks.slack.com/services/...`)
> 5. Click **'Add secret'**
> 6. Reply with 'added'"

### Step D — Bootstrap by manually triggering the workflows

**Order matters.** `copytrade-daily` creates `active_wallets.json`; `copytrade-positions` reads it; `copytrade-report` summarizes whatever exists. If you trigger positions or report before daily has succeeded, they'll run cleanly but show "0 traders / no activity" — not an error, just empty state.

Tell the user **verbatim**:

> "Crons will run on schedule starting tomorrow morning, but let's bootstrap now — trigger the three workflows in this exact order:
>
> 1. Open: https://github.com/\<owner\>/\<repo\>/actions
> 2. Left menu → **'copytrade-daily'** → top-right **'Run workflow'** dropdown → Branch: `main` → green **'Run workflow'** button. Wait for the green tick (~30 s). Confirm in the log you see 'Shortlist updated: 5 traders'. A new commit from `github-actions[bot]` will appear on `main` with `active_wallets.json` and `NOTES.md`.
> 3. Same procedure for **'copytrade-positions'**. Confirm 'Polling 5 traders' in the log. If today's traders happen to have no position changes vs the (empty) prior snapshot, you'll see new signals appended to `signals.json` — that's the first batch.
> 4. Same procedure for **'copytrade-report'**. Check Slack — the daily report should arrive showing 'Following: 5 traders' and any positions opened in step 3.
>
> **⚠ Gotcha:** If a run fails, do **NOT** click 'Re-run jobs' on the failed run — that replays the workflow with the *commit it originally ran against*, not the current `main`, so any fix you merged won't take effect. Always start a fresh run via **'Run workflow'** instead."

### Step E — Set up reliable scheduling (cron-job.org)

> **Why this step exists.** GitHub Actions `schedule:` triggers are best-effort. In practice GitHub drops a large share of frequent scheduled runs during platform-wide contention — observed ~80 % drop for a `*/5`-style cron. The workflows keep their `schedule:` blocks as a fallback, but the **reliable** driver is an external scheduler that calls GitHub's `workflow_dispatch` API. cron-job.org is free and takes ~5 minutes to wire up.

Tell the user **verbatim**:

> "GitHub's built-in cron is unreliable for frequent jobs, so we'll drive the workflows from cron-job.org instead — free, takes 5 minutes.
>
> 1. Go to https://cron-job.org → sign up → verify email → log in
> 2. Click **'Create cronjob'**. Fill the **Common** tab:
>    - Title: `copytrade-positions`
>    - URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/copytrade-positions.yml/dispatches`
>    - Schedule: **Every 5 minutes**
> 3. Switch to the **Advanced** tab:
>    - Request method: **POST**
>    - Request body: `{\"ref\":\"main\"}`
>    - Headers — click **'+ ADD'** four times and enter:
>      - `Accept` = `application/vnd.github+json`
>      - `Authorization` = `Bearer <your PAT from step 0b>`
>      - `X-GitHub-Api-Version` = `2022-11-28`
>      - `Content-Type` = `application/json`
>    - **Save**
> 4. Click **'TEST RUN'** — you must see **204 No Content**. (401/404 = the Authorization header is wrong.)
> 5. Repeat steps 2–4 for two more cronjobs:
>    - `copytrade-report` — URL ends `copytrade-report.yml/dispatches`, schedule **every 30 minutes**
>    - `copytrade-daily` — URL ends `copytrade-daily.yml/dispatches`, schedule **once a day** (custom cron `13 9 * * *`, timezone UTC)
> 6. Reply with 'cron set' once all three return 204."

The PAT needs `repo` + `workflow` scope (classic) or **Actions: Read and write** (fine-grained) — the same token from step 0(b).

### Step F — The system is now autonomous

Nothing left for the user to do. cron-job.org fires the workflows on schedule:
- **Daily** (`13 9 * * *` UTC): leaderboard → fresh shortlist (no Slack message)
- **Positions** (every 5 min): poll trader positions + apply paper trades (no Slack message; appends to `NOTES.md` only if signals occur)
- **Report** (every 30 min): post PnL summary to Slack — **the only thing that messages Slack**

Where to look:
- **Slack channel** — report every 30 min.
- `NOTES.md` at repo root — auto-appended human-readable changelog
- GitHub Actions tab — workflow run logs (event will show `workflow_dispatch`)
- cron-job.org dashboard — execution history of the external triggers
- `main` branch commit history (`github-actions[bot]` commits) — every state change is its own commit
- `portfolio.json` commit history — equity over time

---

## Why Hyperliquid?
- Public leaderboard endpoint, no API key required
- Every trader's open positions and recent fills are public
- The busiest perp-trading DEX (BTC included)
- Traders use real leverage — real signal quality

## System Architecture

```
[Job A - once a day]         [Job B - every 5 min]             [Job C - every 30 min]
   ↓                            ↓                                ↓
fetch leaderboard            read shortlist                   read state files
   ↓                            ↓                                ↓
filter + scoring             fetch each wallet's              compute 24h PnL + activity
   ↓                            open positions                   ↓
active_wallets.json             ↓                              POST to Slack webhook
   ↓                          diff vs prior snapshot
NOTES.md (append)               ↓
                             NEW / CLOSED signals
                                ↓
                             signals.json
                                ↓
                             paper_engine.apply_new_signals()
                                ↓
                             portfolio.json + paper_trades.json
                                ↓
                             NOTES.md (append if any signals)
```

Job C (report) is read-only and never mutates state. Jobs A and B share a `concurrency.group` so they serialize against each other; Job C has no conflict with them.

## Trader Selection — Scoring Logic

**Filter criteria** (used in `analyze_wallets.py`):

| Criterion | Value | Why |
|-----------|-------|-----|
| `min_account_value` | $100,000 | micro accounts are noise |
| `min_30d_volume` | $5,000,000 | proves the trader is actually active |
| `min_30d_pnl` | $50,000 | serious earnings |
| `day_pnl > 0` | — | recency: positive today too |
| `week_pnl > 0` | — | consistency |
| `day_pnl < 0.8 * month_pnl` | — | eliminates "lucky today, flat before" types |
| `abs(day_roi) <= 5.0` | — | catches the obviously inflated ROI rows |

**Scoring formula:**
```python
month_edge_bps = (month_pnl / month_volume) * 10000
week_edge_bps  = (week_pnl  / week_volume)  * 10000
score = month_edge_bps * 2.0 + week_edge_bps * 1.0 + log10(max(month_pnl, 1))
```

Take the top 5 by score.

**Why edge_bps and not ROI?**
Hyperliquid's `roi` field returns nonsensical numbers for accounts with deposits/withdrawals (the #1 trader showed ROI of 17,197%, not real). Instead we use **volume-normalized PnL**: "how many bps earned per $1 traded." This measures **execution quality**, independent of account size.

**`week.vlm` can also be near-zero garbage.** Same data-quality class as the `roi` bug: a trader can show `week.pnl` in the millions with `week.vlm` near zero, which blows up `week_edge_bps` into the hundreds of millions and lets it dominate the score. Fix: if `week_volume < MIN_RELIABLE_WEEK_VOLUME` ($10,000), treat `week_edge_bps` as `0.0` instead of computing it — the trader still competes on `month_edge_bps` and the other filters, just without the bogus boost.

## Traps and Solutions

| Trap | Solution |
|------|----------|
| Recency bias (lucky yesterday → filtered) | Daily AND weekly AND monthly all must be positive |
| Survivorship bias | Edge-based scoring + volume filter |
| Slippage / timing | Job B polls every 5 min, paper applies +5 bps slippage |
| Position sizing mismatch | Not the trader's notional — **5 % of our portfolio** per signal |
| Leverage mismatch | Even if trader runs 20×, we cap at **3×** |
| ROI data noisy | Use edge_bps |

## Paper Trading First
**No real money for the first 2 weeks.**
- Starting cash: $10,000
- Slippage: +5 bps per fill (LONG entry fills above mid, SHORT below)
- Mark price: Hyperliquid `allMids` (live, free)
- Each `job_positions` run snapshots equity into `portfolio.equity_history`
- If results are good → wire to a real account (target: net Sharpe > 1.5)

## File Layout

```
copytrade/
├── CLAUDE.md                  # this file
├── README.md                  # brief intro (English)
├── requirements.txt           # python deps (just `requests`)
│
├── fetch_leaderboard.py       # leaderboard fetcher
├── analyze_wallets.py         # filter + scoring + shortlist writer
├── fetch_positions.py         # clearinghouseState + userFills wrappers
├── paper_engine.py            # mock execution engine
│
├── job_daily.py               # JOB A — once a day (produce shortlist)
├── job_positions.py           # JOB B — every 5 min (signals + paper)
├── daily_report.py            # JOB C — once a day (Slack report)
├── notes.py                   # NOTES.md helper (newest at top)
│
├── active_wallets.json        # current follow list (committed)
├── signals.json               # all NEW/CLOSED signals (append-only, committed)
├── portfolio.json             # paper portfolio state (committed)
├── paper_trades.json          # closed paper trades (committed)
├── NOTES.md                   # human-readable changelog (committed)
│
├── .github/workflows/
│   ├── copytrade-daily.yml      # job_daily.py     (cron-job.org: daily)
│   ├── copytrade-positions.yml  # job_positions.py (cron-job.org: every 5 min)
│   └── copytrade-report.yml     # daily_report.py  (cron-job.org: every 30 min)
│
├── data/                      # .gitignore — daily leaderboard snapshot
│   └── leaderboard_YYYY-MM-DD.json
├── state/                     # committed — trader snapshots for diff
│   └── <address>.json
└── logs/                      # .gitignore — local test logs
    ├── job_daily.log
    └── job_positions.log
```

**Why are state files committed?** GitHub Actions starts a fresh container per run. To carry state across runs, the workflow commits the changed files as `github-actions[bot]` and pushes. That's how diff (prior vs now) and portfolio continuity survive.

---

## Implementation Details

This section is precise enough that Claude can regenerate every file functionally identical to the live system. Constants, function signatures, payload shapes and edge cases are spelled out.

### `requirements.txt`
```
requests>=2.31
```

### `.gitignore`
Ignore: `data/`, `logs/`, `__pycache__/`, `*.py[cod]`, `.Python`, `venv/`, `.venv/`, `env/`, `ENV/`, `.DS_Store`, `Thumbs.db`, `.vscode/`, `.idea/`, `*.swp`, `*.swo`, `.env`, `.env.local`, `*.key`, `*.pem`.
**Do NOT ignore** `state/`, `signals.json`, `portfolio.json`, `paper_trades.json`, `active_wallets.json`, `NOTES.md` — they need to persist across cron runs.

### `fetch_leaderboard.py`
- `fetch() -> dict`: GET `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` with header `User-Agent: Mozilla/5.0`, `Accept: application/json`, 30 s timeout. Returns parsed JSON.
- `save_snapshot(payload) -> Path`: writes `data/leaderboard_<YYYY-MM-DD>.json` (UTC today), returns the path.

### `fetch_positions.py`
- API: `POST https://api.hyperliquid.xyz/info`, header `Content-Type: application/json`, 20 s timeout.
- `get_open_positions(address) -> dict`: payload `{"type":"clearinghouseState","user":address}`. Walk `assetPositions[*].position`, skip entries where `szi == 0`, return:
  ```python
  {
    "account_value": float(data["marginSummary"]["accountValue"]),
    "positions": [
      {
        "coin": p["coin"],
        "side": "LONG" if float(p["szi"]) > 0 else "SHORT",
        "size": abs(float(p["szi"])),
        "entry_price": float(p["entryPx"]),
        "position_value_usd": float(p["positionValue"]),
        "leverage": p["leverage"]["value"],
        "unrealized_pnl": float(p["unrealizedPnl"]),
        "liquidation_price": float(p["liquidationPx"] or 0),
      }
    ],
    "timestamp_ms": data["time"],
  }
  ```
- `get_recent_fills(address, limit=50) -> list[dict]`: payload `{"type":"userFills","user":address}`. Maps `B`→`BUY`, `A`→`SELL`. Optional helper, not used by the current jobs.

### `analyze_wallets.py`
- Loads the latest `data/leaderboard_<today>.json` (falls back to the newest one in `data/`).
- For each row, `score_trader(row)`:
  - Extract `day`, `week`, `month` from `row["windowPerformances"]` (list of `[name, stats]` pairs → dict).
  - Apply all filter criteria from the [Scoring Logic](#trader-selection--scoring-logic) section. Return `None` if any fail.
  - Compute `month_edge_bps`, `week_edge_bps`, and `score` as defined above.
  - Return a dict with: `address`, `account_value`, `day_pnl`, `day_roi`, `week_pnl`, `week_roi`, `month_pnl`, `month_roi`, `month_volume`, `month_edge_bps`, `week_edge_bps`, `score`.
- Sort by `score` desc, take top 5, write to `active_wallets.json`:
  ```json
  {
    "generated_at": "<isoformat>",
    "filters": {...},
    "top_traders": [{...}, ...]
  }
  ```

### `paper_engine.py`
Constants:
```python
STARTING_CASH = 10_000.0
POSITION_PCT  = 0.05    # 5% of cash per signal
SLIPPAGE_BPS  = 5
MAX_LEVERAGE  = 3
```
- `get_mark_prices() -> dict[str, float]`: POST `{"type":"allMids"}` → `{coin: float(px)}`.
- `load_portfolio()`: read `portfolio.json` or default to `{"cash": STARTING_CASH, "starting_cash": STARTING_CASH, "open_positions": {}, "equity_history": [], "last_processed_signal_index": -1}`.
- Position key: `f"{trader}:{coin}:{side}"`.
- Slippage: `LONG` fills at `mid * (1 + 5/10000)`, `SHORT` fills at `mid * (1 - 5/10000)`. Closing reverses the side.
- `open_position(portfolio, signal, mark)`:
  - `leverage = min(int(signal.get("leverage", 1)), MAX_LEVERAGE)`
  - `notional = cash * POSITION_PCT * leverage`
  - `margin = notional / leverage`
  - Skip if `margin > cash`.
  - `fill_price = apply_slippage(mark, side)`, `size = notional / fill_price`.
  - Add to `open_positions`, deduct `margin` from `cash`.
- `close_position(portfolio, signal, mark)`:
  - Find by key, pop. `exit_price = apply_slippage(mark, opposite_side)`.
  - `pnl = (exit - entry) * size` for LONG, `(entry - exit) * size` for SHORT.
  - `cash += margin + pnl`. Append to `paper_trades.json` with `exit_price`, `closed_at`, `pnl`, `pnl_pct`.
- `apply_new_signals()`:
  - Read `signals.json`. Slice from `last_processed_signal_index + 1`.
  - For each new signal, look up mark price; skip if missing.
  - `NEW` → `open_position`, `CLOSED` → `close_position`.
  - Update `last_processed_signal_index = len(signals) - 1`.
  - Append `{ts, equity, cash}` snapshot to `equity_history` (equity = cash + margin + unrealized for each open).
  - Save portfolio.
- CLI: `python paper_engine.py summary` prints current state.

### `notes.py`
NOTES.md format. Newest entry at top. Inside a day, newer entries above older ones. File header:
```
# Copytrade activity log

_Auto-generated. Newest entry at top._
```
Then per-day sections:
```
## 2026-05-18

### 09:00 UTC — Daily refresh (Job A)
- Leaderboard: 1247 traders fetched, 5 shortlisted
- Shortlist change: +2 new, -1 dropped
- #1 0xfd81b27d... acc=$2,400,000 month=$484,000 edge=450bps
...
```
- `append_entry(title: str, lines: list[str])`: prepend a new block under today's `## YYYY-MM-DD` header (create the header if missing). Each line becomes `- ...`.

### `job_daily.py`
- Log to `logs/job_daily.log` (each line `[<iso>] <msg>`).
- Read prior `active_wallets.json` (for diff). Then call `fetch_leaderboard.fetch()` → `save_snapshot()` → `analyze_wallets.main()`.
- After the shortlist is written, call `fetch_positions.get_open_positions(addr)` for each top trader to capture their current open positions for the NOTES snapshot (5 traders × 1 HTTP call ≈ 5 seconds, harmless on failure: log and continue).
- Diff prior vs new top addresses, call `notes.append_entry("Daily refresh (Job A)", [...])` with:
  - leaderboard count, shortlist size
  - `+added` / `-removed` addresses (or "First shortlist (no prior run)" on cold start)
  - one bullet per top trader (`#i addr acc month edge`)
  - a `Current positions across the shortlist:` block, one bullet per trader: either `"  <addr>... no open positions"` or `"  <addr>... <N> positions: SIDE COIN xLEV, SIDE COIN xLEV, ..."`.
- Exit 0 on success, exit 1 only on hard exception (network down, parse error, etc.).

### `job_positions.py`
- Log to `logs/job_positions.log`.
- Position key for diff: `f"{coin}:{side}"`.
- **Bootstrap behavior**: if `active_wallets.json` doesn't exist, log "active_wallets.json missing — Job A hasn't run yet, skipping" and **return 0** (NOT 1). Otherwise positions runs would alert-spam before the first daily.
- For each trader in shortlist:
  - `get_open_positions(addr)` → compare to `state/<addr>.json`'s prior `positions`.
  - `opened = curr - prev`, `closed = prev - curr` by coin:side.
  - For each opened: append `{ts, trader, type:"NEW", **p}` to `signals.json`.
  - For each closed: append `{ts, trader, type:"CLOSED", **p}` to `signals.json`.
  - Save current snapshot to `state/<addr>.json`.
- After polling: call `paper_engine.apply_new_signals()`.
- If any signals were generated, append a NOTES.md entry titled "Position poll (Job B)" with: count, one bullet per NEW/CLOSED, and current portfolio equity/PnL%.

### `daily_report.py`
Reads `portfolio.json`, `paper_trades.json`, `signals.json`, `active_wallets.json`. Computes:
- 24h PnL: `current_equity - equity_24h_ago` (find the newest snapshot ≤ now - 24h; fall back to starting cash if none).
- All-time PnL: `current_equity - starting_cash`.
- Trades closed in last 24h, realized PnL sum.
- Signals in last 24h, split by NEW vs CLOSED.
- Open positions count + a list (first 10).

Also emits a "Last activity" section showing the most recent signal and most recent closed paper trade, each with a humanised age ("23m ago", "2h 14m ago"), so the reader can tell at a glance how fresh the data is.

Posts to `os.environ["SLACK_WEBHOOK_URL"]` as `{"text": <message>}`, raising on non-2xx. If env var is missing → `exit 1` with an error log. Supports `DRY_RUN=1` env var to print and skip the POST.

Message uses Slack mrkdwn (single `*bold*`, backtick code). Example:
```
*📈 Copytrade daily report — 2026-05-18*

*Portfolio:* `$10,127.42`  (yesterday: `$10,005.10`)
*24h PnL:* `+122.32` USD  (`+1.22%`)
*All-time:* `+127.42` USD  (`+1.27%`)  — start `$10,000`

*Last 24h activity:*
• Signals: 3 NEW, 2 CLOSED
• Closed paper trades: 2  (realized PnL: `+18.40` USD)
• Open positions: 7

*Last activity:*
• Last signal: 23m ago — NEW SHORT BTC (0xfd81b27d...)
• Last paper trade closed: 2h 48m ago — SHORT ETH PnL `+3.01` USD

*Following:* 5 traders

*Open positions:*
• SHORT BTC  size=`0.0123`  entry=`$95,234.5000`  x5
...
```

### Workflow YAML — `.github/workflows/copytrade-daily.yml`
```yaml
name: copytrade-daily
on:
  schedule:
    - cron: '13 9 * * *'  # 09:13 UTC, off-peak minute
  workflow_dispatch:
permissions:
  contents: write
concurrency:
  group: copytrade-state
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python job_daily.py
      - name: Commit state changes
        if: always()  # commit whatever state was written, even if previous step failed
        run: |
          set -e
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          # Stage each path individually — `git add a b c` exits 128 and stages
          # NOTHING if any pathspec is missing, so the all-in-one form silently
          # drops every state change on cold-start runs.
          for path in active_wallets.json NOTES.md; do
            [ -e "$path" ] && git add "$path"
          done
          if git diff --cached --quiet; then echo "No changes."; exit 0; fi
          git commit -m "copytrade-daily: refresh $(date -u +%Y-%m-%dT%H:%MZ)"
          for i in 1 2 3; do
            if git push; then exit 0; fi
            echo "Retry $i…"; git pull --rebase -X theirs origin "${{ github.ref_name }}"; sleep $((2**i))
          done
          exit 1
```

### Workflow YAML — `.github/workflows/copytrade-positions.yml`
Same shape as daily, but:
- `cron: '2,7,12,17,22,27,32,37,42,47,52,57 * * * *'`  (every 5 min at off-peak slots; GitHub Actions cron min is 5 min — for tighter polling you'd need an external trigger hitting `workflow_dispatch`)
- `run: python job_positions.py`
- Stage list is `state signals.json portfolio.json paper_trades.json NOTES.md` (use the same per-path loop — `paper_trades.json` only exists once a trade has closed, so the all-in-one `git add` form would silently drop every state change).
- commit message `copytrade-positions: poll $(date ...)`

### Workflow YAML — `.github/workflows/copytrade-report.yml`
```yaml
name: copytrade-report
on:
  schedule:
    - cron: '17,47 * * * *'  # every 30 min at off-peak slots (launch period)
  workflow_dispatch:
permissions:
  contents: read
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: python daily_report.py
```

---

## Running

### Current active setup: GitHub Actions workflows + cron-job.org scheduler ⭐
The repo runs on its own; the user's machine doesn't need to be on. Three workflows live on `main`, each triggered by **cron-job.org** hitting the `workflow_dispatch` API:

| Workflow | Cadence | What it does |
|---|---|---|
| `copytrade-daily` | once a day (09:13 UTC) | Fetch leaderboard → produce shortlist → `active_wallets.json` + NOTES.md |
| `copytrade-positions` | every 5 min | Poll trader positions → diff → signals → paper portfolio → commit state |
| `copytrade-report` | every 30 min | Read portfolio → compute 24h PnL + activity → POST to Slack |

**Why cron-job.org and not GitHub's built-in `schedule:`?** GitHub Actions cron is best-effort. Observed ~80 % of `*/5`-style scheduled runs silently dropped during platform contention; runs at `:00/:15/:30/:45` are hit worst. The workflows still carry `schedule:` blocks as a fallback, but the reliable driver is cron-job.org calling `POST /actions/workflows/<file>/dispatches`. See Quickstart Step E for the exact setup.

**Required GitHub secret:**
- `SLACK_WEBHOOK_URL` — Slack Incoming Webhook (for the report). See Quickstart step 0(c) for setup.

**External scheduler:** 3 cron-job.org jobs (positions/report/daily), each POSTing to the workflow's `dispatches` endpoint with a `Bearer <PAT>` header. The PAT needs `repo` + `workflow` scope (classic) or Actions:write (fine-grained).

### Manual test (local)
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# In order
python job_daily.py                    # produce shortlist
python job_positions.py                # position diff + paper trade
python paper_engine.py summary         # portfolio summary

# Report (print only, don't send to Slack)
DRY_RUN=1 python daily_report.py

# Report (actually send to Slack)
SLACK_WEBHOOK_URL="https://hooks.slack.com/..." python daily_report.py
```

### Automation: alternative options

If the project moves to a different environment or you prefer something other than GitHub Actions, the options below are reference.

### Option 1 — macOS launchd (local machine, most reliable)

`~/Library/LaunchAgents/com.copytrade.daily.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.copytrade.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python</string>
        <string>/path/to/copytrade/job_daily.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/path/to/copytrade/logs/launchd_daily.out</string>
    <key>StandardErrorPath</key>
    <string>/path/to/copytrade/logs/launchd_daily.err</string>
</dict>
</plist>
```

Positions plist is the same but with `StartInterval` = `1800` (30 min) instead of `StartCalendarInterval`.

Load: `launchctl load ~/Library/LaunchAgents/com.copytrade.daily.plist`
Unload: `launchctl unload ~/Library/LaunchAgents/com.copytrade.daily.plist`

### Option 2 — cron (Linux or simple setup)

`crontab -e`:
```
0 9 * * *  cd /path/to/copytrade && venv/bin/python job_daily.py    >> logs/cron_daily.log 2>&1
*/30 * * * * cd /path/to/copytrade && venv/bin/python job_positions.py >> logs/cron_positions.log 2>&1
0 6 * * *  cd /path/to/copytrade && SLACK_WEBHOOK_URL="…" venv/bin/python daily_report.py >> logs/cron_report.log 2>&1
```

### Option 3 — Claude Code `/schedule` skill (when the project lives on a VPS)

If you move the project to your own server with Claude Code installed:
```
/schedule create
  name: copytrade-daily
  cron: 0 9 * * *
  command: cd <project_path> && venv/bin/python job_daily.py
```
Repeat for `job_positions.py` (cron `*/30 * * * *`) and `daily_report.py` (cron `0 6 * * *`).

### Monitoring / Troubleshooting

**GitHub Actions (current setup):**
- Run history: repo → Actions tab
- State changes: `main` branch commit history (`github-actions[bot]` commits)
- Human-readable summary: `NOTES.md` (newest at top)
- Daily report: Slack channel (06:00 UTC)
- Manual trigger: Actions → pick workflow → "Run workflow"

**Local (legacy):**
```bash
tail -f logs/job_daily.log
tail -f logs/job_positions.log
launchctl list | grep copytrade           # macOS launchd
python paper_engine.py summary            # current portfolio
DRY_RUN=1 python daily_report.py          # report preview, no Slack send
```

## Hyperliquid API Notes

**Free, no key needed:**
- `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` — leaderboard (`User-Agent` header required)
- `POST https://api.hyperliquid.xyz/info {"type":"clearinghouseState","user":"0x..."}` — open positions
- `POST https://api.hyperliquid.xyz/info {"type":"userFills","user":"0x..."}` — recent fills
- `POST https://api.hyperliquid.xyz/info {"type":"allMids"}` — live mid price for every coin

**Important detail:** A trader's leaderboard `accountValue` may differ from their `clearinghouseState` `accountValue` (they may use subaccounts/vaults). Job B still shows their open positions correctly — only the "how much of their account is at risk" ratio (notional / account_value) might be misleading. To resolve later: aggregate via the `subAccounts` endpoint.

## First Results (2026-05-17)

Today's top 5 traders (edge-weighted):
1. `0xfd81b27d...` — $2.4M account, month PnL $484K, edge 450 bps
2. `0x1e48f100...` — $11.8M account, month PnL $5.2M, edge 3120 bps ⭐ strongest
3. `0xbc3135e6...` — $531K account, month PnL $131K, edge 253 bps
4. `0xb581d667...` — $22.7M account, month PnL $6.0M, edge 419 bps
5. `0x0e0bf22e...` — $7.5M account, month PnL $3.3M, edge 1363 bps

First poll detected 12 positions:
- 10 SHORT, 2 LONG (TRX, XMR)
- Coins: BTC, ETH, SOL, OP, UNI, STRK, TRUMP, LIT, TRX, XMR
- **Net bias: bearish** — most top traders are short

Paper portfolio: $10,000 → $9,993 (-0.07 %, slippage only)

## TODOs / Next

- [ ] Subaccount aggregation (resolve the `accountValue` mismatch)
- [ ] Confluence scoring (≥2 traders, same coin, same side → strong signal)
- [ ] Tie position sizing to the trader's notional/account_value ratio
- [ ] Stop-loss automation (we set one if the trader didn't)
- [ ] Daily PnL chart / Streamlit dashboard from `equity_history`
- [ ] Collect 2 weeks of paper data, then:
  - Win rate, average R:R, max drawdown
  - Which coins the signal is reliable for, which aren't
  - If net Sharpe > 1.5 → go live with real money

## Decision Log

- **2026-05-17:** Hyperliquid picked over a Solana DEX — BTC perp focus + public leaderboard.
- **2026-05-17:** PnL-weighted scoring eliminated — pulled "lucky today" types to the top.
- **2026-05-17:** ROI-based scoring eliminated — Hyperliquid ROI is broken on accounts with withdrawals/deposits.
- **2026-05-17:** Edge-bps (volume-normalized) scoring accepted — clean, account-size independent.
- **2026-05-17:** Paper trading mandatory for 2 weeks; threshold to go live is Sharpe > 1.5.
- **2026-05-18:** Automation built on GitHub Actions — no local-machine dependency, cron runs in the cloud. State (signals/portfolio/state/) committed back to the repo so runs share continuity.
- **2026-05-18:** Added `NOTES.md` (human changelog) and `daily_report.py` (Slack daily report) — the system reports its own status at a glance.
- **2026-05-18:** Slack Incoming Webhook chosen over Gmail/email — webhook is ~3 min of setup and trivial to wire into a GitHub Actions secret.
- **2026-05-18:** Bootstrap fix — `job_positions.py` now exits 0 when `active_wallets.json` is missing (was exit 1, which alert-spammed before the first daily). Workflows bumped to `actions/checkout@v6` and `actions/setup-python@v6` for Node 24.
- **2026-05-18:** Added the Quickstart protocol + Implementation Details section in English so a fresh Claude Code session reading this file can rebuild the entire project after asking the user for a repo, a PAT and a Slack webhook URL.
- **2026-05-19:** The 22-hour silent bug — `copytrade-positions` polled fine but never committed state. Root cause: `git add a b c d e` aborts entirely (exit 128) if any one pathspec is missing, and `paper_trades.json` doesn't exist until the first trade closes. Fixed by staging each path in a loop. Also: `if: always()` on the commit step, broadened paper_engine except, and `git pull --rebase -X theirs` to auto-resolve state-file conflicts between near-simultaneous runs.
- **2026-05-19:** GitHub Actions cron confirmed unreliable — ~80 % of scheduled runs dropped. Moved the real scheduling to **cron-job.org** (free external scheduler) hitting the `workflow_dispatch` API. Workflows keep `schedule:` blocks as fallback. Positions cadence raised to every 5 min (GitHub cron minimum), report to every 30 min for the launch period.
- **2026-05-19:** `daily_report.py` gained a "Last activity" section (most recent signal + closed trade with humanised age) so the reader can tell how fresh the data is at a glance.
- **2026-06-16:** First live bootstrap run surfaced a `week_edge_bps` blow-up (621M+ bps) caused by a trader showing `week.vlm` ≈ 0 alongside a real multi-million `week.pnl` — same data-quality class as the known `roi` bug. Fixed by zeroing `week_edge_bps` when `week_volume < MIN_RELIABLE_WEEK_VOLUME` ($10,000) instead of dividing by near-zero.
