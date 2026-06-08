# strategy_breeder.py

"""
Strategy Breeder Service
Handles intelligent breeding (crossover) of trading strategies.
"""

from typing import Dict, Any, List, Optional
import copy
import random


class StrategyBreeder:
    """Service for breeding (combining) two strategy configurations."""

    # Breeding modes
    MODE_ENTRY_A_EXIT_B = "entry_a_exit_b"
    MODE_ENTRY_B_EXIT_A = "entry_b_exit_a"
    MODE_FILTERS_A_ENTRY_B = "filters_a_entry_b"
    MODE_FILTERS_B_ENTRY_A = "filters_b_entry_a"
    MODE_BALANCED_MERGE = "balanced_merge"
    MODE_BEST_OF_BOTH = "best_of_both"

    @staticmethod
    def breed_strategies(
        parent_a_config: Dict[str, Any],
        parent_b_config: Dict[str, Any],
        mode: str,
        mutation_rate: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Create a hybrid strategy by combining two parent strategies.
        """
        config_a = copy.deepcopy(parent_a_config)
        config_b = copy.deepcopy(parent_b_config)

        hybrid = {}

        hybrid["name"] = (
            f"Hybrid: {config_a.get('name', 'A')} × {config_b.get('name', 'B')}"
        )
        hybrid["symbol"] = config_a.get("symbol", config_b.get("symbol", "BTCUSDT"))
        hybrid["marketType"] = config_a.get("marketType", "FUTURES")

        if mode == StrategyBreeder.MODE_ENTRY_A_EXIT_B:
            hybrid = StrategyBreeder._breed_entry_a_exit_b(hybrid, config_a, config_b)
        elif mode == StrategyBreeder.MODE_ENTRY_B_EXIT_A:
            hybrid = StrategyBreeder._breed_entry_b_exit_a(hybrid, config_a, config_b)
        elif mode == StrategyBreeder.MODE_FILTERS_A_ENTRY_B:
            hybrid = StrategyBreeder._breed_filters_a_entry_b(
                hybrid, config_a, config_b
            )
        elif mode == StrategyBreeder.MODE_FILTERS_B_ENTRY_A:
            hybrid = StrategyBreeder._breed_filters_b_entry_a(
                hybrid, config_a, config_b
            )
        elif mode == StrategyBreeder.MODE_BALANCED_MERGE:
            hybrid = StrategyBreeder._breed_balanced_merge(hybrid, config_a, config_b)
        elif mode == StrategyBreeder.MODE_BEST_OF_BOTH:
            hybrid = StrategyBreeder._breed_best_of_both(hybrid, config_a, config_b)
        else:
            raise ValueError(f"Unknown breeding mode: {mode}")

        if mutation_rate > 0:
            hybrid = StrategyBreeder._apply_mutations(hybrid, mutation_rate)

        hybrid["foundation_weights"] = StrategyBreeder._merge_foundation_weights(
            config_a.get("foundation_weights", {}),
            config_b.get("foundation_weights", {}),
        )
        hybrid["min_foundation_weight_threshold"] = (
            config_a.get("min_foundation_weight_threshold", 0.0)
            + config_b.get("min_foundation_weight_threshold", 0.0)
        ) / 2

        return hybrid

    @staticmethod
    def _get_default_filters() -> Dict:
        return {"type": "AND", "children": []}

    @staticmethod
    def _get_default_entry_conditions() -> Dict:
        return {"type": "OR", "children": []}  # Entry conditions usually start with OR

    @staticmethod
    def _get_default_entry_trigger() -> Dict:
        return {"type": "on_candle_close", "timeframe": "1m"}

    @staticmethod
    def _get_default_initialization() -> Dict:
        return {"type": "open_position", "params": {}}

    @staticmethod
    def _breed_entry_a_exit_b(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        hybrid["filters"] = config_a.get(
            "filters", StrategyBreeder._get_default_filters()
        )
        hybrid["entryTrigger"] = config_a.get(
            "entryTrigger", StrategyBreeder._get_default_entry_trigger()
        )
        hybrid["entryConditions"] = config_a.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["initialization"] = config_a.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )
        hybrid["positionManagement"] = config_b.get("positionManagement", [])
        return hybrid

    @staticmethod
    def _breed_entry_b_exit_a(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        hybrid["filters"] = config_b.get(
            "filters", StrategyBreeder._get_default_filters()
        )
        hybrid["entryTrigger"] = config_b.get(
            "entryTrigger", StrategyBreeder._get_default_entry_trigger()
        )
        hybrid["entryConditions"] = config_b.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["initialization"] = config_b.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )
        hybrid["positionManagement"] = config_a.get("positionManagement", [])
        return hybrid

    @staticmethod
    def _breed_filters_a_entry_b(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        hybrid["filters"] = config_a.get(
            "filters", StrategyBreeder._get_default_filters()
        )
        hybrid["entryTrigger"] = config_b.get(
            "entryTrigger", StrategyBreeder._get_default_entry_trigger()
        )
        hybrid["entryConditions"] = config_b.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["initialization"] = config_b.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )
        hybrid["positionManagement"] = config_b.get("positionManagement", [])
        return hybrid

    @staticmethod
    def _breed_filters_b_entry_a(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        hybrid["filters"] = config_b.get(
            "filters", StrategyBreeder._get_default_filters()
        )
        hybrid["entryTrigger"] = config_a.get(
            "entryTrigger", StrategyBreeder._get_default_entry_trigger()
        )
        hybrid["entryConditions"] = config_a.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["initialization"] = config_a.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )
        hybrid["positionManagement"] = config_a.get("positionManagement", [])
        return hybrid

    @staticmethod
    def _breed_balanced_merge(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        filters_a = config_a.get("filters", StrategyBreeder._get_default_filters())
        filters_b = config_b.get("filters", StrategyBreeder._get_default_filters())
        hybrid["filters"] = StrategyBreeder._merge_condition_groups(
            filters_a, filters_b
        )

        hybrid["entryTrigger"] = config_a.get(
            "entryTrigger", StrategyBreeder._get_default_entry_trigger()
        )

        entry_a = config_a.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        entry_b = config_b.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["entryConditions"] = StrategyBreeder._merge_condition_groups(
            entry_a, entry_b
        )

        hybrid["initialization"] = config_a.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )

        mgmt_a = config_a.get("positionManagement", [])
        mgmt_b = config_b.get("positionManagement", [])
        hybrid["positionManagement"] = StrategyBreeder._merge_management_blocks(
            mgmt_a, mgmt_b
        )

        return hybrid

    @staticmethod
    def _breed_best_of_both(hybrid: Dict, config_a: Dict, config_b: Dict) -> Dict:
        filters_a = config_a.get("filters", StrategyBreeder._get_default_filters())
        filters_b = config_b.get("filters", StrategyBreeder._get_default_filters())

        count_a = StrategyBreeder._count_conditions(filters_a)
        count_b = StrategyBreeder._count_conditions(filters_b)
        hybrid["filters"] = filters_a if count_a <= count_b else filters_b

        hybrid["entryTrigger"] = StrategyBreeder._get_default_entry_trigger()

        entry_a = config_a.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        entry_b = config_b.get(
            "entryConditions", StrategyBreeder._get_default_entry_conditions()
        )
        hybrid["entryConditions"] = StrategyBreeder._merge_condition_groups(
            entry_a, entry_b, max_conditions=5
        )

        hybrid["initialization"] = config_a.get(
            "initialization", StrategyBreeder._get_default_initialization()
        )

        mgmt_a = config_a.get("positionManagement", [])
        mgmt_b = config_b.get("positionManagement", [])
        hybrid["positionManagement"] = StrategyBreeder._select_best_management(
            mgmt_a, mgmt_b
        )

        return hybrid

    @staticmethod
    def _merge_condition_groups(
        group_a: Dict, group_b: Dict, max_conditions: Optional[int] = None
    ) -> Dict:
        merged = {"type": "AND", "children": []}

        conditions_a = group_a.get("children", [])
        conditions_b = group_b.get("children", [])

        seen_types = set()
        all_conditions = conditions_a + conditions_b

        for condition in all_conditions:
            cond_type = condition.get("type")
            if cond_type and cond_type not in seen_types:
                merged["children"].append(condition)
                seen_types.add(cond_type)

        if max_conditions and len(merged["children"]) > max_conditions:
            merged["children"] = merged["children"][:max_conditions]

        return merged

    @staticmethod
    def _merge_management_blocks(
        blocks_a: List[Dict], blocks_b: List[Dict]
    ) -> List[Dict]:
        """Merge position management blocks from both parents."""
        merged = []
        seen_types = set()

        # Combine blocks, avoiding duplicates of same type
        for block in blocks_a + blocks_b:
            block_type = block.get("type")
            if block_type not in seen_types:
                merged.append(block)
                seen_types.add(block_type)

        return merged

    @staticmethod
    def _select_best_management(
        blocks_a: List[Dict], blocks_b: List[Dict]
    ) -> List[Dict]:
        """Select best management blocks based on priority."""
        # Priority: trailing_stop > profit_target > stop_loss > time_based
        priority_order = ["trailing_stop", "profit_target", "stop_loss", "time_based"]

        selected = []
        seen_types = set()

        # First pass - select by priority
        for priority_type in priority_order:
            for block in blocks_a + blocks_b:
                if (
                    block.get("type") == priority_type
                    and priority_type not in seen_types
                ):
                    selected.append(block)
                    seen_types.add(priority_type)
                    break

        # Second pass - add remaining unique types
        for block in blocks_a + blocks_b:
            block_type = block.get("type")
            if block_type not in seen_types:
                selected.append(block)
                seen_types.add(block_type)

        return selected

    @staticmethod
    def _merge_foundation_weights(
        weights_a: Dict[str, float], weights_b: Dict[str, float]
    ) -> Dict[str, float]:
        """Merge foundation weights by averaging."""
        merged = {}
        all_foundations = set(weights_a.keys()) | set(weights_b.keys())

        for foundation in all_foundations:
            weight_a = weights_a.get(foundation, 0.0)
            weight_b = weights_b.get(foundation, 0.0)

            # Average the weights
            merged[foundation] = (weight_a + weight_b) / 2

        return merged

    @staticmethod
    def _count_conditions(condition_node: Dict) -> int:
        """Count total number of conditions in a condition tree."""
        return len(condition_node.get("children", []))

    @staticmethod
    def _apply_mutations(
        config: Dict[str, Any], mutation_rate: float
    ) -> Dict[str, Any]:
        """
        Apply random mutations to strategy parameters.
        This introduces variation similar to genetic algorithms.
        """
        if random.random() > mutation_rate:
            return config

        # Mutate min_foundation_weight_threshold slightly
        if "min_foundation_weight_threshold" in config:
            current_threshold = config["min_foundation_weight_threshold"]
            mutation = (
                random.uniform(-0.1, 0.1) * current_threshold
            )  # Relative mutation
            config["min_foundation_weight_threshold"] = max(
                0.0, current_threshold + mutation
            )

        # Mutate foundation weights slightly
        if "foundation_weights" in config and config["foundation_weights"]:
            foundation_to_mutate = random.choice(
                list(config["foundation_weights"].keys())
            )
            current_weight = config["foundation_weights"][foundation_to_mutate]
            mutation = random.uniform(-0.15, 0.15) * current_weight  # Relative mutation
            config["foundation_weights"][foundation_to_mutate] = max(
                0.0, current_weight + mutation
            )

        return config
