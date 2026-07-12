# Rule Synthesis from Strategy Insights

## Input Data

Analyze these **{memories_count}** strategy insights/results for the **{strategy_type}** strategy type:

{memories_content}
{rules_str}

## Task

Synthesize **ONE** high-confidence, actionable rule for the future to prevent failures or repeat successes of this strategy type.
Focus on **specific indicators, filters, or parameters**.

### Deduplication Rule (CRITICAL)

Compare your proposed rule with the **"Existing Rules in Memory Bank"** listed above.
- If a **rule with a similar concept, indicator parameter, or trade filter** already exists — **DO NOT** generate a duplicate.
- Instead, return an **empty string** for `rule_content` in the JSON payload (i.e. `"rule_content": ""`) so that no duplicate memory is created.

## Tagging Instructions

Here are the unique tags currently existing in the database: {tags_str}
Select relevant tags from this list, or create new tags if none of them are appropriate.

## Output Format

Your response **MUST** be a JSON object with this exact structure:

```json
{{
  "rule_content": "A short, clear, actionable rule (e.g. 'For breakout setups on 1m, always require volume multiplier > 2x to filter out ranges')",
  "confidence": 0.0 to 1.0,
  "tags": ["tag1", "tag2", ...]
}}
```
