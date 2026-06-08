# api/analytics_parsers.py

from typing import List, Dict, Any


class StrategyConfigParser:
    """Parser to extract data from strategy JSON configuration."""

    def __init__(self, config_data: Dict[str, Any]):
        self.config = config_data if isinstance(config_data, dict) else {}

    def get_used_filters(self) -> List[str]:
        """Extracts types of all used filters."""
        filters_node = self.config.get("filters", {})
        children = filters_node.get("children", [])
        return [f.get("type") for f in children if f.get("type")]

    def get_used_management_blocks(self) -> List[str]:
        """Extracts types of all position management blocks."""
        management_blocks = self.config.get("positionManagement", [])
        return [block.get("type") for block in management_blocks if block.get("type")]

    def get_all_foundations(self) -> List[str]:
        """
        Extracts ALL entry conditions from the strategy configuration.
        Includes weighted groups (w_*), indicators, and all other conditions.
        """
        conditions = []
        entry_conditions = self.config.get("entryConditions", {})

        def _traverse(node: Dict[str, Any]):
            if not node:
                return

            node_id = node.get("id")
            node_type = node.get("type")

            # Skip logical operators
            if node_type in ["AND", "OR"]:
                if "children" in node and isinstance(node["children"], list):
                    for child in node["children"]:
                        _traverse(child)
                return

            # Use ID for weighted groups
            if node_id and node_id.startswith("w_"):
                conditions.append(node_id)
                return  # Do not descend inside the weighted group

            # Use type for others
            if node_type:
                conditions.append(node_type)

            if "children" in node and isinstance(node["children"], list):
                for child in node["children"]:
                    _traverse(child)

        _traverse(entry_conditions)
        return list(set(conditions))

    # Deprecated - kept for backward compatibility
    def get_used_indicators(self) -> List[str]:
        """Deprecated: Indicators are now included in get_all_foundations()"""
        return []


class DecisionTraceParser:
    """
    Parser to extract data from the JSON decision tree (decision_trace).
    Extracts ALL triggered entry conditions without artificial division into "foundations" and "indicators".
    """

    def __init__(self, trace_data: Dict[str, Any]):
        self.trace = trace_data if isinstance(trace_data, dict) else {}

    def get_used_filters(self) -> List[str]:
        """Extracts types of all triggered (true) filters from filters_trace."""
        filters_trace = self.trace.get("filters_trace")
        if not filters_trace:
            return []

        used_filters = set()

        def _traverse(node: Dict[str, Any]):
            if not isinstance(node, dict):
                return

            node_type = node.get("type")
            node_result = node.get("result")

            # If this is a leaf node (not AND/OR) and it triggered
            if node_type and node_type not in ["AND", "OR"] and node_result is True:
                used_filters.add(node_type)

            if "children" in node and isinstance(node.get("children"), list):
                for child in node["children"]:
                    _traverse(child)

        _traverse(filters_trace)
        return list(used_filters)

    def get_used_foundations(self) -> List[str]:
        """
        Extracts ALL triggered entry conditions (without division into foundations/indicators).
        Returns the ID or type of nodes that triggered (result=True).
        """
        used_conditions = set()

        def _traverse(node: Dict[str, Any]):
            if not isinstance(node, dict):
                return

            node_id = node.get("id")
            node_type = node.get("type")
            node_result = node.get("result")

            # Skip logical operators
            if node_type in ["AND", "OR"]:
                if "children" in node and isinstance(node.get("children"), list):
                    for child in node["children"]:
                        _traverse(child)
                return

            # If the node triggered - add it
            if node_result is True:
                # Use ID for weighted groups (w_*), type for others
                if node_id and node_id.startswith("w_"):
                    used_conditions.add(node_id)
                    return  # Do not descend inside the weighted group
                elif node_type:
                    used_conditions.add(node_type)

            # Continue recursive traversal
            if "children" in node and isinstance(node.get("children"), list):
                for child in node["children"]:
                    _traverse(child)

        _traverse(self.trace)
        return list(used_conditions)

    def get_used_management_blocks(self) -> List[str]:
        """Extracts types of position management blocks (if present in the trace)."""
        # Management blocks are usually not in decision_trace,
        # but the method is kept for compatibility
        return []

    # Keep for backward compatibility, but simply return an empty list
    def get_used_indicators(self) -> List[str]:
        """Deprecated: Indicators are now included in get_used_foundations()"""
        return []
