# bot_module/strategy_healer.py
"""
Self-healing module for DepthSight strategy configurations.

Automatically fixes common LLM generation artifacts and edge cases:
1. Dynamic link resolution: rewires broken block_id in `value_comparison` / dynamic links
   to actual provider blocks (e.g. `local_level`) in the tree, maps key aliases ('field' -> 'key',
   'level_price' -> 'detected_level').
2. Foundation weights harmonization: synchronizes 'w_' prefixed or mismatched keys between
   `foundation_weights` and `entryConditions.children`.
3. Volatility filter adaptation: detects unscaled absolute ATR filters (e.g. ATR > 1.5) on
   low-priced assets (LINK, SOL, DOGE, ADA, etc.) and auto-converts them to percentage `natr_filter`.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Assets where price is >= $1,000 and 1m ATR can legitimately exceed 1.0 USD
HIGH_PRICED_ASSETS = ("BTC", "ETH", "PAXG")

PROVIDER_BLOCK_TYPES = {
    "local_level",
    "significant_level",
    "order_book_zone",
    "tape_analysis",
    "level_touch_analyzer",
    "price_action_analyzer",
    "volatility_squeeze",
}


def _is_high_priced_symbol(symbol: Optional[str]) -> bool:
    if not symbol:
        return False
    clean = symbol.strip().upper()
    return any(clean.startswith(prefix) for prefix in HIGH_PRICED_ASSETS)


def _collect_nodes_and_parents(
    node: Any,
    parent: Optional[Dict[str, Any]] = None,
    nodes_map: Optional[Dict[str, Dict[str, Any]]] = None,
    parent_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Recursively collects all block nodes by ID and their immediate parent block."""
    if nodes_map is None:
        nodes_map = {}
    if parent_map is None:
        parent_map = {}

    if isinstance(node, dict):
        node_id = str(node.get("id")) if node.get("id") else None
        if node_id:
            nodes_map[node_id] = node
            if parent is not None:
                parent_map[node_id] = parent

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                _collect_nodes_and_parents(child, node, nodes_map, parent_map)

        for key, val in node.items():
            if key == "children":
                continue
            if isinstance(val, dict):
                _collect_nodes_and_parents(val, parent, nodes_map, parent_map)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _collect_nodes_and_parents(item, parent, nodes_map, parent_map)

    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                _collect_nodes_and_parents(item, parent, nodes_map, parent_map)

    return nodes_map, parent_map


def _find_provider_candidates(
    nodes_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Identifies all provider blocks in the strategy."""
    providers = []
    for n in nodes_map.values():
        if not isinstance(n, dict):
            continue
        b_type = n.get("type")
        params = n.get("params", {}) if isinstance(n.get("params"), dict) else {}
        if b_type in PROVIDER_BLOCK_TYPES or params.get("is_data_provider") is True:
            providers.append(n)
    return providers


def _heal_operands_in_node(
    node: Any,
    nodes_map: Dict[str, Dict[str, Any]],
    parent_map: Dict[str, Dict[str, Any]],
    providers: List[Dict[str, Any]],
):
    """Walks the node and heals operands that reference other blocks."""
    if not isinstance(node, dict):
        if isinstance(node, list):
            for item in node:
                _heal_operands_in_node(item, nodes_map, parent_map, providers)
        return

    # Check if this node itself is an operand or has operands
    for operand_key in ("leftOperand", "rightOperand", "level_source", "price_source"):
        operand = node.get(operand_key)
        if isinstance(operand, dict) and operand.get("source") == "block_result":
            _heal_block_result_operand(operand, node, parent_map, providers, nodes_map)

    # If node is an operand dict directly
    if node.get("source") == "block_result":
        _heal_block_result_operand(node, None, parent_map, providers, nodes_map)

    # Recurse
    for k, v in node.items():
        if k in ("leftOperand", "rightOperand", "level_source", "price_source"):
            continue
        if isinstance(v, (dict, list)):
            _heal_operands_in_node(v, nodes_map, parent_map, providers)


def _heal_block_result_operand(
    operand: Dict[str, Any],
    parent_node: Optional[Dict[str, Any]],
    parent_map: Dict[str, Dict[str, Any]],
    providers: List[Dict[str, Any]],
    nodes_map: Dict[str, Dict[str, Any]],
):
    """Heals a single operand referencing source: 'block_result'."""
    # 1. Normalize 'field' -> 'key'
    if "field" in operand and "key" not in operand:
        operand["key"] = operand.pop("field")

    # 2. Key aliases
    key = str(operand.get("key", "")).strip()
    if key.lower() in {"level_price", "level", "price", "levelprice"}:
        operand["key"] = "detected_level"
    elif not key:
        operand["key"] = "detected_level" if providers else "result"

    # 3. Block ID resolution
    current_block_id = operand.get("block_id")
    current_id_str = (
        str(current_block_id).strip() if current_block_id is not None else ""
    )

    if current_id_str and current_id_str in nodes_map:
        # Already points to an existing block in tree!
        return

    # Target block_id does not exist! Try to heal:
    # A. Search for a sibling provider in the same parent group
    target_provider = None
    if parent_node and parent_node.get("id"):
        parent_group = parent_map.get(str(parent_node["id"]))
        if parent_group and isinstance(parent_group.get("children"), list):
            for sibling in parent_group["children"]:
                if sibling is not parent_node and sibling in providers:
                    target_provider = sibling
                    break

    # B. If only 1 provider exists in the entire strategy, auto-link to it
    if target_provider is None and len(providers) == 1:
        target_provider = providers[0]

    # C. Match by substring or type name (e.g. "provider_1h_high" -> local_level high)
    if target_provider is None and current_id_str:
        lower_id = current_id_str.lower()
        for p in providers:
            p_id = str(p.get("id", "")).lower()
            p_type = str(p.get("type", "")).lower()
            p_params = p.get("params", {}) if isinstance(p.get("params"), dict) else {}
            p_level_type = str(p_params.get("level_type", "")).lower()

            if (
                p_id in lower_id
                or lower_id in p_id
                or (p_type in lower_id)
                or (p_level_type and p_level_type in lower_id)
            ):
                target_provider = p
                break

    # D. Fallback to the first provider if available
    if target_provider is None and providers:
        target_provider = providers[0]

    if target_provider and target_provider.get("id"):
        new_id = target_provider["id"]
        logger.info(
            f"[strategy_healer] Rewired broken block_id '{current_block_id}' -> '{new_id}' ({target_provider.get('type')})"
        )
        operand["block_id"] = new_id


def _heal_volatility_nodes(node: Any, symbol: Optional[str]):
    """
    Detects unscaled absolute ATR filters (e.g. ATR > 1.5) on assets where price < $1,000
    and converts them to normalized `natr_filter`.
    """
    if not isinstance(node, dict):
        if isinstance(node, list):
            for item in node:
                _heal_volatility_nodes(item, symbol)
        return

    if node.get("type") == "volatility_filter":
        params = node.get("params", {})
        if isinstance(params, dict):
            ind = str(params.get("indicator", "")).upper()
            op = str(params.get("operator", "")).lower()
            raw_val = params.get("value")

            try:
                val = float(raw_val) if raw_val is not None else 1.5
            except (ValueError, TypeError):
                val = 1.5

            is_high_priced = _is_high_priced_symbol(symbol)

            # If ATR > 0.8 on non-high-priced asset (e.g. LINK at $15 where ATR is 0.02, ADA at $0.50),
            # this is an unscaled absolute ATR threshold that filters out 100% of trades.
            if (
                ind == "ATR"
                and (op in {"gt", ">", "gte", ">="})
                and val >= 0.8
                and not is_high_priced
            ):
                # Determine sensible natr threshold
                natr_val = params.get("natr_threshold")
                try:
                    threshold = float(natr_val) if natr_val is not None else 0.3
                except (ValueError, TypeError):
                    threshold = 0.3

                logger.info(
                    f"[strategy_healer] Converting unscaled absolute ATR filter (value={val}) "
                    f"to natr_filter (threshold={threshold}%) for symbol '{symbol}'"
                )
                node["type"] = "natr_filter"
                node["params"] = {"natr_threshold": threshold}

    for v in node.values():
        if isinstance(v, (dict, list)):
            _heal_volatility_nodes(v, symbol)


def _heal_foundation_weights(strategy_dict: Dict[str, Any]):
    """Synchronizes `foundation_weights` keys with condition group IDs in `entryConditions`."""
    weights = strategy_dict.get("foundation_weights")
    if not isinstance(weights, dict) or not weights:
        return

    entry_cond = strategy_dict.get("entryConditions")
    if not isinstance(entry_cond, dict):
        return

    children = entry_cond.get("children")
    if not isinstance(children, list) or not children:
        return

    child_ids = [
        str(c.get("id")) for c in children if isinstance(c, dict) and c.get("id")
    ]
    if not child_ids:
        return

    # If there is exactly 1 top-level foundation group and 1 weight entry, bind them directly
    if len(child_ids) == 1 and len(weights) == 1:
        single_child_id = child_ids[0]
        single_weight_val = list(weights.values())[0]
        weights[single_child_id] = single_weight_val
        return

    # For each key in weights, ensure both 'key' and 'w_key' are accessible if one matches
    keys_to_add = {}
    for w_key, w_val in list(weights.items()):
        w_key_str = str(w_key)
        if w_key_str not in child_ids:
            # Try prepending 'w_'
            prefixed = f"w_{w_key_str}"
            if prefixed in child_ids:
                keys_to_add[prefixed] = w_val
            # Try stripping 'w_'
            elif w_key_str.startswith("w_") and w_key_str[2:] in child_ids:
                keys_to_add[w_key_str[2:]] = w_val

    if keys_to_add:
        weights.update(keys_to_add)


def heal_strategy_config(
    strategy_dict: Dict[str, Any],
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for self-healing strategy configurations.
    Modifies and returns the sanitized strategy dictionary.
    """
    if not isinstance(strategy_dict, dict):
        return strategy_dict

    target_symbol = symbol or strategy_dict.get("symbol")

    # 1. Collect all nodes and parent links
    nodes_map, parent_map = _collect_nodes_and_parents(strategy_dict)

    # 2. Identify provider candidates
    providers = _find_provider_candidates(nodes_map)

    # 3. Heal operand block references (value_comparison, etc.)
    _heal_operands_in_node(strategy_dict, nodes_map, parent_map, providers)

    # 4. Harmonize foundation_weights
    _heal_foundation_weights(strategy_dict)

    # 5. Adapt volatility filters to asset price scale
    _heal_volatility_nodes(strategy_dict, target_symbol)

    return strategy_dict
