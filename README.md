# AI Quota & Burn Scale (`usage.snackdriven.com`)

Personal multi-page dashboard tracking rolling 5-hour and 7-day rate-limit windows, linear burn pace, and 7-day token/step scale across **Claude**, **ChatGPT / Codex**, and **Google Antigravity**.

## Pages

- `/` (`dist/index.html`): Cross-provider overview, 7-day weekly burn trajectory, daily volume bars, top token threads, and Antigravity model pools.
- `/claude/` (`dist/claude/index.html`): Claude Max 20x rolling 5-hour and 7-day windows, bonus pool ledger, and `plan-usage-history.json` checkpoints.
- `/chatgpt/` (`dist/chatgpt/index.html`): ChatGPT / Codex ProLite 7-day weekly burn, banked reset credits, rollout snapshots, and top personal token-consuming threads.
- `/antigravity/` (`dist/antigravity/index.html`): Google Antigravity 5-hour Gemini and Claude/GPT-OSS model pools, all 13 model quotas, and Prompt/Flow AI credits.

## Usage

Run the live local dashboard server on `http://127.0.0.1:8787`:

```powershell
python server.py
```

Print a compact terminal summary:

```powershell
python server.py --cli
```

Export fresh static pages to `dist/` for `usage.snackdriven.com`:

```powershell
python server.py --export dist
```
