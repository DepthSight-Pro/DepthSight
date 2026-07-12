# Rule Lifecycle Evaluation

## Analysis Context

Analyze the following strategy config which resulted in a **{outcome}** (PnL: `{pnl}%`).

### Strategy Config (snippet)

```json
{strategy_str}
```

### Active Rules in Memory

```
{rules_context}
```

## Task

Did this strategy **apply or follow** any of the active rules listed above?
Return the **exact integer IDs** of the rules that were actively applied in this strategy.
If none were applied, return an **empty list**.

## Output Format

Output strictly JSON matching this structure:

```json
{{
    "applied_rule_ids": [1, 2]
}}
```
