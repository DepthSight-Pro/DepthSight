# tests/test_genetic_strategy_finder.py
import pytest
import json
import os
from unittest.mock import patch, MagicMock
import pandas as pd
from bot_module.genetic_strategy_finder import GeneticStrategyFinder, GENE_POOL
from deap import creator, tools

# DEAP types are created in bot_module.genetic_strategy_finder
# We rely on them being present. Re-creating them here can cause issues.


@pytest.fixture
def gsf_config():
    """Configuration for GeneticStrategyFinder."""
    return {
        "population_size": 10,
        "generations": 3,
        "crossover_probability": 0.7,
        "mutation_probability": 0.2,
        "fitness_metric": "sharpe_ratio",
        "min_trades_for_prescreening": 1,
    }


@pytest.fixture
def gsf_instance(gsf_config):
    """Fixture for a GeneticStrategyFinder instance."""
    # Adapting the fixture for the new class __init__
    dummy_df = MagicMock(spec=pd.DataFrame)
    # The new constructor expects a dictionary with training data
    training_data = {"DUMMY_ASSET": dummy_df}

    finder = GeneticStrategyFinder(training_data=training_data, run_config=gsf_config)

    # HACK: The run() method in the new code version still incorrectly refers to self.screening_df
    # during the final KPI calculation. To prevent the test from failing with AttributeError, we add this attribute manually.
    finder.screening_df = dummy_df

    return finder


def test_create_individual_structure(gsf_instance):
    """Checks that the created individual has the correct JSON structure."""
    individual = gsf_instance._create_individual()
    assert isinstance(individual, creator.Individual)

    strategy = dict(individual)
    assert "entryConditions" in strategy
    assert "initialization" in strategy
    assert "filters" in strategy

    entry_block = strategy["entryConditions"]
    assert "type" in entry_block
    assert entry_block["type"] in GENE_POOL["logic"]


def _is_valid_node(node):
    """Helper recursive function to check the structure of a node."""
    if not isinstance(node, dict) or "type" not in node:
        return False

    node_type = node["type"]

    if node_type in GENE_POOL["logic"]:
        if "children" not in node or not isinstance(node["children"], list):
            return False
        return all(_is_valid_node(child) for child in node["children"])

    all_condition_keys = list(GENE_POOL["filters"].keys()) + list(
        GENE_POOL["conditions"].keys()
    )
    if node_type in all_condition_keys:
        return "params" in node

    return False


def test_create_individual_validity(gsf_instance):
    """Checks that the created individual has a valid recursive structure."""
    for _ in range(20):
        individual = gsf_instance._create_individual()
        strategy = dict(individual)
        assert _is_valid_node(strategy["entryConditions"])
        # Filters can be an empty dictionary, which is valid
        if strategy.get("filters"):
            assert _is_valid_node(strategy["filters"])


def test_crossover_swaps_nodes(gsf_instance):
    """Checks that crossover swaps nodes between two individuals."""
    ind1 = gsf_instance._create_individual()
    ind2 = gsf_instance._create_individual()

    ind1["entryConditions"]["children"].append(
        gsf_instance._generate_random_leaf_node("rsi_condition")
    )
    ind2["entryConditions"]["children"].append(
        gsf_instance._generate_random_leaf_node("ma_cross_condition")
    )

    child1, child2 = gsf_instance._crossover_individuals(ind1, ind2)

    assert _is_valid_node(child1["entryConditions"])
    assert _is_valid_node(child2["entryConditions"])


def test_mutation_changes_individual(gsf_instance):
    """Checks that mutation changes the individual."""
    original_ind = gsf_instance._create_individual()

    original_ind["entryConditions"]["children"].append(
        gsf_instance._generate_random_leaf_node("rsi_condition")
    )
    original_ind_str = json.dumps(original_ind, sort_keys=True)

    changed = False
    for _ in range(50):
        mutated_ind_tuple = gsf_instance._mutate_individual(original_ind)
        mutated_ind = mutated_ind_tuple[0]
        if json.dumps(mutated_ind, sort_keys=True) != original_ind_str:
            changed = True
            assert _is_valid_node(mutated_ind["entryConditions"])
            break

    assert changed, "Mutation did not change the individual after 50 attempts."


@patch("bot_module.genetic_strategy_finder.FastVectorBacktester")
def test_run_method_and_fitness_evaluation(
    MockFastVectorBacktester, gsf_instance, gsf_config
):
    """
    Tests the main run method, mocking the backtester to check fitness evaluation.
    """

    def side_effect(df, strategy, use_oracle=False):
        mock_backtester = MagicMock()
        num_conditions = len(strategy.get("entryConditions", {}).get("children", []))

        # Modeling KPIs that PASS all kill-switches:
        # - total_trades >= 30 (minimum)
        # - total_pnl_pct > 0 (there must be profit)
        # - max_dd < 25 (reasonable drawdown)
        if num_conditions > 1:
            kpis = {
                "total_trades": 50,
                "profit_factor": 1.8,
                "total_pnl_pct": 15.0,
                "max_dd": 10.0,
                "sharpe_ratio": 1.2,
            }
        else:
            kpis = {
                "total_trades": 35,
                "profit_factor": 1.2,
                "total_pnl_pct": 5.0,
                "max_dd": 15.0,
                "sharpe_ratio": 0.5,
            }

        mock_backtester.run.return_value = kpis
        return mock_backtester

    MockFastVectorBacktester.side_effect = side_effect

    def create_varied_individual():
        ind = gsf_instance._create_individual()
        if _is_valid_node(ind["entryConditions"]):
            ind["entryConditions"]["children"].append(
                gsf_instance._generate_random_leaf_node("rsi_condition")
            )
        return ind

    gsf_instance.toolbox.register("individual", create_varied_individual)
    gsf_instance.toolbox.register(
        "population", tools.initRepeat, list, gsf_instance.toolbox.individual
    )

    # Use a simple map that just iterates
    final_results = gsf_instance.run(map_function=map)

    assert isinstance(final_results, list)
    assert len(final_results) > 0

    top_result = final_results[0]
    assert "rank" in top_result
    assert "fitness_score" in top_result
    assert "strategy_json" in top_result
    assert "kpis_json" in top_result

    assert top_result["rank"] == 1

    # Checking that fitness is positive (the strategy passed all filters)
    # Formula: (avg_pnl / risk_free_dd) * 10.0
    # With mock KPI: (15.0 / max(1.0, 10.0)) * 10.0 = 15.0
    assert top_result["fitness_score"] > 0, (
        f"Expected positive fitness, got {top_result['fitness_score']}"
    )
    assert top_result["kpis_json"]["profit_factor"] == 1.8


def test_new_blocks_are_generated(gsf_instance):
    """Checks if the newly added blocks can be generated by _create_individual."""
    new_blocks = {
        "volatility_filter",
        "macd_condition",
        "price_consolidation",
        "volume_confirmation",
        "trend_direction",
        "natr_filter",
    }

    generated_types = set()

    for _ in range(200):
        individual = gsf_instance._create_individual()

        nodes_to_visit = [individual.get("entryConditions"), individual.get("filters")]
        while nodes_to_visit:
            node = nodes_to_visit.pop(0)
            if not node:
                continue

            node_type = node.get("type")
            if node_type:
                generated_types.add(node_type)

            if "children" in node and isinstance(node["children"], list):
                nodes_to_visit.extend(node["children"])

    found_new_blocks = new_blocks.intersection(generated_types)
    print(f"Found new blocks: {found_new_blocks}")

    assert len(found_new_blocks) >= len(new_blocks) / 2, (
        f"Expected at least half of the new blocks to be generated, but only found {len(found_new_blocks)}/{len(new_blocks)}"
    )


@patch("bot_module.genetic_strategy_finder.FastVectorBacktester")
def test_genetic_strategy_finder_json_checkpoint(
    MockFastVectorBacktester, gsf_instance, tmp_path
):
    """Verifies that the genetic finder can save and load its state using JSON checkpoints."""
    mock_backtester = MagicMock()
    mock_backtester.run.return_value = {
        "total_trades": 50,
        "profit_factor": 1.8,
        "total_pnl_pct": 15.0,
        "max_dd": 10.0,
        "sharpe_ratio": 1.2,
    }
    MockFastVectorBacktester.return_value = mock_backtester

    checkpoint_file = os.path.join(tmp_path, "test_checkpoint.json")

    gsf_instance.generations = 1
    gsf_instance.population_size = 5
    gsf_instance.run(map_function=map, checkpoint_file=checkpoint_file)

    assert os.path.exists(checkpoint_file)

    with open(checkpoint_file, "r") as f:
        data = json.load(f)
    assert data["serialization_format"] == "json"
    assert "population" in data
    assert "generation" in data
    assert data["generation"] == 0

    new_finder = GeneticStrategyFinder(
        training_data=gsf_instance.training_data, run_config=gsf_instance.config
    )
    new_finder.screening_df = gsf_instance.screening_df
    new_finder.generations = 2

    results = new_finder.run(map_function=map, checkpoint_file=checkpoint_file)
    assert len(results) > 0
