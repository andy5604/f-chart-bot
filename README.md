# Trade Value Chart Bot

Watches peakedinhighskool.com for a new Half-PPR trade value chart and posts it to
`#weekly-recap-trade-value` automatically. Runs free on GitHub Actions. No server.

## How it works

1. Every 30 minutes on Thursdays it loads the chart page.
2. It finds the Half-PPR image and reads the date stamp out of the filename
   (`1QBHalf4pt_20251111.png` becomes `20251111`).
3. If that stamp matches the last one posted, it stops. Nothing happens.
4. If it changed, it downloads the chart, slices it into 3 readable chunks,
   and posts them to Discord with a link to the full-resolution original.
5. It saves the new stamp back to `state.json` so it never double-posts.

## Setup

### 1. Create the Discord webhook

In Discord, right-click `#weekly-recap-trade-value` → Edit Channel → Integrations
→ Webhooks → New Webhook. Name it something like "Trade Chart Bot", then
**Copy Webhook URL**. You need Manage Webhooks permission on the server.

### 2. Create the repo

Make a new GitHub repo (private is fine) and upload these four files, keeping the
folder structure exactly as it is:

```
chart_bot.py
requirements.txt
state.json
.github/workflows/chart-bot.yml
```

### 3. Add the webhook as a secret

In the repo: Settings → Secrets and variables → Actions → New repository secret.

- Name: `DISCORD_WEBHOOK_URL`
- Value: the webhook URL you copied

Never paste the webhook URL into the code itself. Anyone with that URL can post
to your channel.

### 4. Allow the bot to save its state

Settings → Actions → General → Workflow permissions → select
**Read and write permissions** → Save. This lets it commit `state.json` back
after each post.

### 5. Test it

Actions tab → "Trade Value Chart Bot" → Run workflow → tick **force** → Run.

Force makes it post the current chart even though nothing has changed, so you can
confirm it looks right in the channel. After that, leave force off and it only
fires on genuinely new charts.

## Changing things

**Different format.** Edit the three lines near the top of `chart_bot.py`:

```python
FORMAT_LABEL = "Half-PPR"
ALT_KEYWORD = "half-ppr"
HEADING_KEYWORD = "half-ppr"
```

Use `"non-ppr"` for standard or `"ppr"` for full PPR.

**Different schedule.** Edit the cron line in the workflow file. It is in UTC, so
`10-23` is roughly 6am to 8pm Eastern, and `4` means Thursday. Use `3,4` to add Wednesday.

**More or fewer slices.** Change `SLICE_COUNT` in `chart_bot.py`.

## Things to know

- GitHub Actions cron drifts under load, sometimes by 10 to 20 minutes. The
  half-hourly window absorbs that.
- Peak releases to Patreon Tuesday evening and the public page follows, usually
  Wednesday. Running Thursday only means the chart may sit a day before it posts.
  Change the cron to `3,4` if you want it the moment it goes live.
- Between seasons the job runs and does nothing, which is correct but means a
  genuine breakage looks identical to a quiet week. If you want a heartbeat,
  say so and I'll add a monthly "still alive" ping to a private channel.
- If he ever restructures the page, the bot logs `could not find the Half-PPR
  chart image` and exits without posting garbage. Check the Actions log.
- The bot sets `allowed_mentions` to none, so it can never ping the league even
  if the chart title contains something that looks like a mention.
