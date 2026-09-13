# bot_module/telemetry_formatter.py
"""
Telemetry and Rejection Formatter for DepthSight.

Extracts, enriches, and formats backtest event counters, rejections,
triggered foundations, and anomalies (corresponding to the 'Журнал событий'
/ Event Log tab on the UI). Automatically maps filter UUIDs to human-readable
block types and parameters, and identifies primary signal bottlenecks.
"""

from typing import Any, Dict, List, Optional


def _extract_nodes_map(strategy_config: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Recursively scans strategy configuration to map block IDs to their node dictionaries.
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    if not isinstance(strategy_config, dict):
        return nodes

    # Unpack config if wrapped in config_data or config
    root = strategy_config
    if "config_data" in root and isinstance(root["config_data"], dict):
        root = root["config_data"]
    elif "config" in root and isinstance(root["config"], dict):
        root = root["config"]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_id = str(node.get("id") or "")
            if node_id:
                nodes[node_id] = node

            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)

            for k, v in node.items():
                if k != "children" and isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    if "filters" in root:
        walk(root["filters"])
    if "entryConditions" in root:
        walk(root["entryConditions"])
    if "positionManagement" in root:
        walk(root["positionManagement"])

    return nodes


def _format_filter_node_label(node: Optional[Dict[str, Any]], filter_id: str) -> str:
    """
    Formats a human-readable label for a filter node with its key parameters.
    """
    if not node:
        return f"Filter {filter_id}"

    btype = node.get("type") or "filter"
    params = node.get("params") if isinstance(node.get("params"), dict) else {}

    parts: List[str] = []
    indicator = params.get("indicator")
    operator = params.get("operator")
    val = params.get("value", params.get("threshold"))

    if indicator and operator and val is not None:
        parts.append(f"{indicator} {operator} {val}")
    elif indicator:
        parts.append(str(indicator))
    elif operator and val is not None:
        parts.append(f"{operator} {val}")

    if "natr_threshold" in params:
        parts.append(f"NATR > {params['natr_threshold']}%")
    if "threshold" in params and not (indicator and operator and val is not None):
        parts.append(f"threshold={params['threshold']}")
    if "rel_vol_threshold" in params:
        parts.append(f"rel_vol={params['rel_vol_threshold']}")
    if "session" in params:
        parts.append(f"session={params['session']}")

    param_str = f" [{', '.join(parts)}]" if parts else ""
    return f"`{btype}`{param_str}"


def extract_rejection_telemetry(
    analytics_report: Optional[Dict[str, Any]],
    strategy_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Parses and enriches structured backtest analytics report into a comprehensive
    telemetry dictionary matching the 'Журнал событий' (Event Log) UI tab.
    """
    if not isinstance(analytics_report, dict):
        return {
            "signals_generated_total": 0,
            "trades_opened": 0,
            "total_rejections": 0,
            "rejections": {
                "by_global_risk_limit": 0,
                "by_cooldown": 0,
                "by_weight_threshold": 0,
                "by_position_calculation": 0,
                "by_slippage_beyond_sl": 0,
                "by_risk_manager": 0,
                "by_risk_manager_reasons": {},
                "by_filter": [],
            },
            "foundation_trigger_counts": {},
            "anomalies": [],
            "primary_bottleneck": "No backtest telemetry available.",
        }

    event_counters = analytics_report.get("event_counters") or {}
    if not isinstance(event_counters, dict):
        event_counters = {}

    raw_rejections = event_counters.get("rejections") or {}
    if not isinstance(raw_rejections, dict):
        raw_rejections = {}

    signals_total = int(event_counters.get("signals_generated_total") or 0)
    trades_opened = int(event_counters.get("trades_opened") or 0)

    # Standard scalar rejection counters
    by_global_risk = int(raw_rejections.get("by_global_risk_limit") or 0)
    by_cooldown = int(raw_rejections.get("by_cooldown") or 0)
    by_weight = int(raw_rejections.get("by_weight_threshold") or 0)
    by_calc = int(raw_rejections.get("by_position_calculation") or 0)
    by_slippage = int(raw_rejections.get("by_slippage_beyond_sl") or 0)
    by_risk_mgr = int(raw_rejections.get("by_risk_manager") or 0)

    # Sub-breakdowns
    raw_rm_reasons = raw_rejections.get("by_risk_manager_reasons") or {}
    rm_reasons: Dict[str, int] = {}
    if isinstance(raw_rm_reasons, dict):
        for rk, rv in raw_rm_reasons.items():
            try:
                cnt = int(rv)
                if cnt > 0:
                    rm_reasons[str(rk)] = cnt
            except (TypeError, ValueError):
                pass

    # Resolve filters
    nodes_map = _extract_nodes_map(strategy_config)
    raw_by_filter = raw_rejections.get("by_filter") or {}
    filter_rejections: List[Dict[str, Any]] = []
    filter_total = 0

    if isinstance(raw_by_filter, dict):
        for fid, fcount in raw_by_filter.items():
            try:
                cnt = int(fcount)
            except (TypeError, ValueError):
                continue
            if cnt <= 0:
                continue

            filter_total += cnt
            fid_str = str(fid)
            node = nodes_map.get(fid_str)
            label = _format_filter_node_label(node, fid_str)

            filter_rejections.append(
                {
                    "id": fid_str,
                    "count": cnt,
                    "label": label,
                    "type": node.get("type") if node else "unknown_filter",
                    "params": node.get("params") if node else {},
                }
            )

    # Sort filters descending by rejection count
    filter_rejections.sort(key=lambda x: x["count"], reverse=True)

    # Calculate total rejections
    total_rejections = (
        by_global_risk
        + by_cooldown
        + by_weight
        + by_calc
        + by_slippage
        + by_risk_mgr
        + filter_total
    )

    # Triggered foundations
    raw_trig = event_counters.get("foundation_trigger_counts") or {}
    foundation_triggers: Dict[str, int] = {}
    if isinstance(raw_trig, dict):
        for k, v in raw_trig.items():
            try:
                cnt = int(v)
                if cnt > 0:
                    foundation_triggers[str(k)] = cnt
            except (TypeError, ValueError):
                pass

    # Anomalies
    raw_anomalies = analytics_report.get("anomalies") or []
    anomalies: List[Dict[str, Any]] = []
    if isinstance(raw_anomalies, list):
        for item in raw_anomalies:
            if isinstance(item, dict):
                anomalies.append(item)
            elif isinstance(item, str):
                anomalies.append({"message": item})

    # Determine primary bottleneck
    primary_bottleneck: Optional[str] = None
    if signals_total == 0:
        primary_bottleneck = (
            "No signals generated: entry trigger/foundations conditions were never met."
        )
    elif total_rejections > 0:
        # Check if a specific filter is the main cause
        if filter_rejections and filter_rejections[0]["count"] >= max(
            by_cooldown, by_weight, by_risk_mgr, by_calc, by_global_risk
        ):
            top_f = filter_rejections[0]
            pct = (top_f["count"] / max(total_rejections, 1)) * 100
            primary_bottleneck = (
                f"Filter {top_f['label']} (id: {top_f['id'][:8]}...) rejected {top_f['count']} signals "
                f"({pct:.1f}% of all rejections)."
            )
        elif by_cooldown >= max(by_weight, by_risk_mgr, by_calc, by_global_risk):
            pct = (by_cooldown / max(total_rejections, 1)) * 100
            primary_bottleneck = f"Cooldown rejected {by_cooldown} signals ({pct:.1f}% of all rejections)."
        elif by_weight >= max(by_risk_mgr, by_calc, by_global_risk):
            pct = (by_weight / max(total_rejections, 1)) * 100
            primary_bottleneck = (
                f"Foundation weight threshold rejected {by_weight} signals ({pct:.1f}% of all rejections)."
            )
        elif by_risk_mgr >= max(by_calc, by_global_risk):
            rm_str = (
                ", ".join(f"{k}: {v}" for k, v in rm_reasons.items())
                if rm_reasons
                else "risk manager limits"
            )
            primary_bottleneck = f"Risk manager rejected {by_risk_mgr} signals ({rm_str})."
        elif by_calc > 0:
            primary_bottleneck = (
                f"Position calculation rejected {by_calc} signals (invalid price, stop distance, or quantity)."
            )
        elif by_global_risk > 0:
            primary_bottleneck = f"Global risk limit rejected {by_global_risk} signals."

    return {
        "signals_generated_total": signals_total,
        "trades_opened": trades_opened,
        "total_rejections": total_rejections,
        "rejections": {
            "by_global_risk_limit": by_global_risk,
            "by_cooldown": by_cooldown,
            "by_weight_threshold": by_weight,
            "by_position_calculation": by_calc,
            "by_slippage_beyond_sl": by_slippage,
            "by_risk_manager": by_risk_mgr,
            "by_risk_manager_reasons": rm_reasons,
            "by_filter": filter_rejections,
        },
        "foundation_trigger_counts": foundation_triggers,
        "anomalies": anomalies,
        "primary_bottleneck": primary_bottleneck,
    }


def format_event_log_markdown(
    telemetry: Dict[str, Any],
    language: str = "ru",
    compact: bool = False,
) -> str:
    """
    Formats telemetry into a clear, readable Markdown section matching
    the 'Журнал событий' (Event Log) UI tab.
    """
    signals = telemetry.get("signals_generated_total", 0)
    trades = telemetry.get("trades_opened", 0)
    total_rejections = telemetry.get("total_rejections", 0)
    rejections = telemetry.get("rejections", {})
    by_filter = rejections.get("by_filter", [])
    foundations = telemetry.get("foundation_trigger_counts", {})
    anomalies = telemetry.get("anomalies", [])
    bottleneck = telemetry.get("primary_bottleneck")

    if compact:
        # Compact format for prompt injection / LLM feedback
        rej_parts = []
        if rejections.get("by_cooldown"):
            rej_parts.append(f"cooldown={rejections['by_cooldown']}")
        if rejections.get("by_weight_threshold"):
            rej_parts.append(f"weight_threshold={rejections['by_weight_threshold']}")
        if rejections.get("by_position_calculation"):
            rej_parts.append(f"calc={rejections['by_position_calculation']}")
        if rejections.get("by_risk_manager"):
            rm_sub = rejections.get("by_risk_manager_reasons", {})
            sub_s = f" ({rm_sub})" if rm_sub else ""
            rej_parts.append(f"risk_manager={rejections['by_risk_manager']}{sub_s}")

        for f in by_filter:
            rej_parts.append(f"{f['label']}={f['count']}")

        rej_str = "; ".join(rej_parts) if rej_parts else "none"
        trig_str = (
            ", ".join(f"`{k}`: {v}" for k, v in foundations.items())
            if foundations
            else "none"
        )
        anom_str = f"{len(anomalies)} detected" if anomalies else "none"

        lines = [
            f"- **Event Log**: Signals={signals}, Trades={trades}, Rejections={total_rejections}",
            f"- **Rejections**: {rej_str}",
            f"- **Triggered Foundations**: {trig_str}",
        ]
        if anomalies:
            lines.append(f"- **Anomalies**: {anom_str}")
        if bottleneck:
            lines.append(f"- ⚠️ **Primary Bottleneck**: {bottleneck}")
        return "\n".join(lines)

    # Detailed format matching the UI screenshot
    if language == "ru":
        header = "### 📋 Журнал событий (Event Log)"
        lbl_signals = "Сгенерировано сигналов"
        lbl_trades = "Открыто сделок"
        lbl_total_rej = "Всего отклонений"
        lbl_risk_limit = "Отклонено: По глобальному лимиту риска"
        lbl_cooldown = "Отклонено: Из-за перезарядки"
        lbl_weight = "Отклонено: По порогу веса оснований"
        lbl_calc = "Отклонено: При расчете позиции"
        lbl_slip = "По проскальзыванию за SL"
        lbl_rm = "По риск-менеджеру"
        lbl_filter_pfx = "Отклонено: Фильтром"
        lbl_foundations = "🎯 Сработавшие основания"
        lbl_foundations_empty = "Нет сработавших оснований"
        lbl_anomalies = "⚠️ Аномалии"
        lbl_anomalies_empty = "Аномалий не обнаружено."
        lbl_diag = "💡 Диагностика блокировок"
    else:
        header = "### 📋 Event Log & Rejection Telemetry"
        lbl_signals = "Signals Generated"
        lbl_trades = "Trades Opened"
        lbl_total_rej = "Total Rejections"
        lbl_risk_limit = "Rejection: By Global Risk Limit"
        lbl_cooldown = "Rejection: By Cooldown"
        lbl_weight = "Rejection: By Weight Threshold"
        lbl_calc = "Rejection: By Position Calculation"
        lbl_slip = "Rejection: By Slippage Beyond SL"
        lbl_rm = "By Risk Manager"
        lbl_filter_pfx = "Rejection: By Filter"
        lbl_foundations = "🎯 Triggered Foundations"
        lbl_foundations_empty = "No triggered foundations"
        lbl_anomalies = "⚠️ Anomalies"
        lbl_anomalies_empty = "No anomalies detected."
        lbl_diag = "💡 Signal Bottleneck Diagnostic"

    lines = [
        header,
        f"- **{lbl_signals}**: {signals}",
        f"- **{lbl_trades}**: {trades}",
        f"- **{lbl_total_rej}**: **{total_rejections}**",
        f"  - {lbl_risk_limit}: {rejections.get('by_global_risk_limit', 0)}",
        f"  - {lbl_cooldown}: {rejections.get('by_cooldown', 0)}",
        f"  - {lbl_weight}: {rejections.get('by_weight_threshold', 0)}",
        f"  - {lbl_calc}: {rejections.get('by_position_calculation', 0)}",
        f"  - {lbl_slip}: {rejections.get('by_slippage_beyond_sl', 0)}",
    ]

    rm_cnt = rejections.get("by_risk_manager", 0)
    rm_reasons = rejections.get("by_risk_manager_reasons", {})
    if rm_reasons:
        reasons_list = ", ".join(f"{rk}: {rv}" for rk, rv in rm_reasons.items())
        lines.append(f"  - {lbl_rm}: {rm_cnt} ({reasons_list})")
    else:
        lines.append(f"  - {lbl_rm}: {rm_cnt}")

    if by_filter:
        for f in by_filter:
            lines.append(f"  - {lbl_filter_pfx} - {f['label']} (`{f['id']}`): {f['count']}")
    else:
        lines.append(f"  - {lbl_filter_pfx}: 0")

    # Foundations section
    lines.append(f"\n**{lbl_foundations}**:")
    if foundations:
        for f_name, f_cnt in foundations.items():
            clean_name = f_name.replace("w_", "")
            lines.append(f"- `{clean_name}`: {f_cnt}")
    else:
        lines.append(f"- _{lbl_foundations_empty}_")

    # Anomalies section
    lines.append(f"\n**{lbl_anomalies}**:")
    if anomalies:
        for anom in anomalies:
            atype = anom.get("type", "ANOMALY")
            msg = anom.get("message", str(anom))
            ts = f" at {anom.get('timestamp')}" if anom.get("timestamp") else ""
            lines.append(f"- [{atype}]{ts}: {msg}")
    else:
        lines.append(f"- _{lbl_anomalies_empty}_")

    # Bottleneck callout
    if bottleneck:
        lines.append(f"\n> **{lbl_diag}**: {bottleneck}")

    return "\n".join(lines)
