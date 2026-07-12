# Strategy Classification Tagging

## Strategy & Performance Context

Analyze this trading strategy configuration and its backtest performance:

| Field | Value |
|-------|-------|
| **Symbol** | `{symbol}` |
| **Timeframe** | `{timeframe}` |
| **PnL** | `{pnl}%` |
| **Win Rate** | `{win_rate}%` |
| **Trades** | `{trades}` |
| **Config Blocks** | `{all_blocks}` |

## Tag Selection Rules

1. Generate structured classification tags for this strategy.
2. **Existing tags in the database:** `[{tags_str}]`
3. Prefer picking **1 to 4** appropriate tags from the existing pool to maintain consistency.
4. If none fit well, you may create a **new short, descriptive tag** (max 2 words, `snake_case`).

## Output Format

Your response **MUST** be a JSON object matching this exact structure:

```json
{{
  "strategy_type": "breakout" | "mean_reversion" | "trend_following" | "scalping" | "momentum",
  "tags": ["tag1", "tag2"],
  "outcome": "success" | "failure",
  "confidence": 0.0 to 1.0
}}
```
