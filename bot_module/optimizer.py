# bot_module/strategy_optimizer.py

import logging
import json
import random
import copy
import argparse
import sys
import os
from pathlib import Path
import multiprocessing
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from deap import creator

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from genetic_strategy_finder import (
        GeneticStrategyFinder,
        load_and_prepare_assets,
        FastVectorBacktester,
        TqdmLoggingHandler,
    )
except ImportError:
    from .genetic_strategy_finder import (
        GeneticStrategyFinder,
        load_and_prepare_assets,
        FastVectorBacktester,
        TqdmLoggingHandler,
    )

logger = logging.getLogger("bot_module.optimizer")

# OPTIMIZATION RANGES
OPTIMIZATION_POOL = {
    "time_filter": {
        "start_hour_utc": (0, 23),
        "end_hour_utc": (0, 23),
        "mode": ["include", "exclude"],
    },
    "initialization": {
        "sl_type": ["atr_multiplier"],
        "sl_value_atr": (1.0, 5.0),
        "tp_type": ["rr_multiplier"],
        "tp_value_rr": (2.0, 10.0),
        "move_sl_to_be_on_first_tp": [True, False],
        "max_partial_exits": 3,
        "partial_tp_value_rr": (0.5, 4.0),
        "partial_size_pct": (10, 50),
        # Adding retention time optimization
        "max_hold_candles": (60, 600),
    },
}


class StrategyOptimizer(GeneticStrategyFinder):
    def __init__(self, template_strategy: dict, *args, **kwargs):
        # 1. Prepare Template
        self.template_strategy = self._prepare_template(template_strategy)
        super().__init__(*args, **kwargs)

        # 2. OVERRIDE DEAP FUNCTIONS STRICTLY
        # Unregister old methods to be safe
        for method in ["individual", "mutate", "mate", "evaluate"]:
            if hasattr(self.toolbox, method):
                self.toolbox.unregister(method)

        # Register NEW Strict Methods
        self.toolbox.register("individual", self._create_seeded_individual)
        self.toolbox.register("mutate", self._mutate_strict)
        self.toolbox.register("mate", self._crossover_strict)
        self.toolbox.register("evaluate", self._evaluate_fitness_robust)

    def _prepare_template(self, strategy: dict) -> dict:
        """Injects time_filter if missing, cleans structure."""
        strat = copy.deepcopy(strategy)
        if "filters" not in strat:
            strat["filters"] = {"type": "AND", "children": []}

        root = strat["filters"]
        if root.get("type") not in ["AND", "OR"]:
            strat["filters"] = {"type": "AND", "children": [copy.deepcopy(root)]}
            root = strat["filters"]

        has_time = any(c.get("type") == "time_filter" for c in root.get("children", []))
        if not has_time:
            root.setdefault("children", []).append(
                {
                    "type": "time_filter",
                    "params": {
                        "start_hour_utc": 0,
                        "end_hour_utc": 0,
                        "mode": "include",
                    },
                }
            )
        return strat

    def _create_seeded_individual(self):
        """Creates individual based strictly on template."""
        ind_data = copy.deepcopy(self.template_strategy)
        # Apply initial random mutation to parameters to create diversity
        self._mutate_initialization(ind_data, 1.0)
        self._mutate_time_filter(ind_data, 1.0)
        return creator.Individual(ind_data)

    def _mutate_strict(self, individual: dict, ind_pb: float = 0.5) -> tuple:
        """
        Mutates ONLY:
        1. Initialization (SL, TP, Partials, MaxHold)
        2. Time Filter params
        NEVER touches Entry Conditions or Filter Logic.
        """
        self._mutate_time_filter(individual, ind_pb)
        self._mutate_initialization(individual, ind_pb)
        return (individual,)

    def _crossover_strict(self, ind1, ind2):
        """
        Swaps ONLY:
        1. The entire 'initialization' block.
        2. The 'params' of the time_filter node.
        """
        c1, c2 = self.toolbox.clone(ind1), self.toolbox.clone(ind2)

        # Swap Init
        if random.random() < 0.6:
            c1["initialization"], c2["initialization"] = (
                c2["initialization"],
                c1["initialization"],
            )

        # Swap Time Filter Params
        t1 = self._find_time_node(c1)
        t2 = self._find_time_node(c2)
        if t1 and t2 and random.random() < 0.5:
            t1["params"], t2["params"] = t2["params"], t1["params"]

        return c1, c2

    def _find_time_node(self, ind):
        root = ind.get("filters", {})
        if "children" in root:
            for child in root["children"]:
                if child.get("type") == "time_filter":
                    return child
        return None

    def _mutate_time_filter(self, individual: dict, prob: float):
        node = self._find_time_node(individual)
        if node and random.random() < prob:
            pool = OPTIMIZATION_POOL["time_filter"]
            node["params"]["start_hour_utc"] = random.randint(*pool["start_hour_utc"])
            node["params"]["end_hour_utc"] = random.randint(*pool["end_hour_utc"])
            node["params"]["mode"] = random.choice(pool["mode"])

    def _mutate_initialization(self, individual: dict, prob: float):
        if "initialization" not in individual:
            return
        params = individual["initialization"]["params"]
        pool = OPTIMIZATION_POOL["initialization"]

        # Mutate scalars
        if random.random() < prob:
            params["sl_value"] = round(random.uniform(*pool["sl_value_atr"]), 2)
        if random.random() < prob:
            params["tp_value"] = round(random.uniform(*pool["tp_value_rr"]), 2)
        if random.random() < prob:
            params["move_sl_to_be_on_first_tp"] = random.choice(
                pool["move_sl_to_be_on_first_tp"]
            )
        if random.random() < prob:
            params["max_hold_candles"] = random.randint(*pool["max_hold_candles"])

        # Mutate Partials (Re-generate logic)
        if random.random() < prob:
            partials = []
            if random.random() < 0.6:  # 60% chance to have partials
                num = random.randint(1, pool["max_partial_exits"])
                rem_size = 100
                for _ in range(num):
                    size = random.randint(*pool["partial_size_pct"])
                    if rem_size - size < 10:
                        break
                    rr = round(random.uniform(*pool["partial_tp_value_rr"]), 2)
                    if rr >= params["tp_value"]:
                        continue  # Partial must be closer than TP
                    partials.append(
                        {"tp_type": "rr_multiplier", "tp_value": rr, "size_pct": size}
                    )
                    rem_size -= size
                partials.sort(key=lambda x: x["tp_value"])
            params["partial_exits"] = partials

    def _evaluate_fitness_robust(self, individual: dict) -> tuple:
        """
        Calculates fitness with 'Anti-Crash' logic.
        Punishes strategies that rely on single massive wins.
        """
        results = []
        for df in self.training_data.values():
            try:
                bt = FastVectorBacktester(df, individual)
                results.append(bt.run())
            except Exception:
                pass

        if not results:
            return (-99999.0,)

        avg_sortino = np.mean([r.get("sortino_ratio", -1.0) for r in results])
        avg_consistency = np.mean([r.get("consistency_score", 0.0) for r in results])
        total_pnl = np.mean([r.get("total_pnl_pct", 0.0) for r in results])
        max_dd = np.mean([r.get("max_dd", 100.0) for r in results])

        #  FITNESS FORMULA

        # 1. Base Score on Sortino (Risk-adjusted return)
        score = avg_sortino * 100

        # 2. Reward High PnL (Compounded), but log-scale to reduce "One Day" impact
        if total_pnl > 0:
            score += np.log1p(total_pnl) * 20
        else:
            score -= 1000  # Heavy penalty for losing money

        # 3. Heavy Penalty for Drawdown
        if max_dd > 30:  # If drawdown > 30%, punish severely
            score -= (max_dd - 30) * 10

        # 4. Consistency Multiplier
        # If consistency < 0.3 (money made in only 30% of months), score is crushed
        score *= avg_consistency**2

        return (score,)


if __name__ == "__main__":
    # (Same setup code as before)
    log_handler = TqdmLoggingHandler()
    log_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().handlers = [log_handler]
    logging.getLogger().setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy_file", type=str, required=True)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--pop_size", type=int, default=30)
    parser.add_argument("--output_dir", type=str, default="optimized_fixed")
    parser.add_argument("--max_cores", type=int, default=None)
    args = parser.parse_args()

    try:
        with open(args.strategy_file, "r") as f:
            template = json.load(f)
    except Exception as e:
        print(f"Error loading strategy: {e}")
        exit(1)

    data_path = Path(args.data_path)
    assets = [d for d in data_path.iterdir() if d.is_dir()][:15]  # Limit to 15 assets
    train_dfs = load_and_prepare_assets(assets)

    opt = StrategyOptimizer(
        template_strategy=template,
        training_data=train_dfs,
        run_config={"population_size": args.pop_size, "generations": args.generations},
    )

    pool = multiprocessing.Pool(processes=args.max_cores)
    try:
        results = opt.run(pool.imap)
    finally:
        pool.close()
        pool.join()

    out = Path(args.output_dir)
    out.mkdir(exist_ok=True)

    for i, res in enumerate(results[:5]):
        p = out / f"opt_strict_{i + 1}_fit_{res['fitness_score']:.0f}.json"
        with open(p, "w") as f:
            json.dump(res["strategy_json"], f, indent=4)
        kp = out / f"opt_strict_{i + 1}_kpi.json"
        with open(kp, "w") as f:
            json.dump(res["kpis_json"], f, indent=4)

    print("Strict optimization finished.")


try:
    import optuna
    from optuna.samplers import TPESampler
except ImportError:
    optuna = None
    TPESampler = None


class BayesianOptimizer:
    def __init__(
        self, objective_func, search_space, config_override=None, params=None, **kwargs
    ):
        self.objective_func = objective_func
        self.search_space = search_space or {}
        self.config = config_override or {}
        self.params = params or {}
        self.kwargs = kwargs
        self.best_value = None
        self.study = None

    def optimize(self, progress_callback_celery=None) -> Optional[Dict[str, Any]]:
        if optuna is None:
            raise RuntimeError("Optuna package is not installed or failed to import.")

        n_trials = self.config.get("n_trials", 100)
        timeout = self.config.get("timeout", None)
        direction = self.config.get("direction", "maximize")
        sampler_seed = self.config.get("sampler_seed", None)

        # Create TPESampler with seed
        sampler = TPESampler(seed=sampler_seed)

        # Create a study
        study_name = self.config.get("study_name_prefix", "optuna_study")
        self.study = optuna.create_study(
            direction=direction, sampler=sampler, study_name=study_name
        )

        # Define the objective wrapper to suggest parameters from search space
        def objective_wrapper(trial: optuna.Trial) -> float:
            trial_params = {}
            for key, spec in self.search_space.items():
                param_type = spec[0]
                bounds = spec[1]
                if param_type == "int":
                    trial_params[key] = trial.suggest_int(
                        key, int(bounds[0]), int(bounds[1])
                    )
                elif param_type == "float":
                    trial_params[key] = trial.suggest_float(
                        key, float(bounds[0]), float(bounds[1])
                    )
                elif param_type == "categorical":
                    # bounds is a list of categories
                    trial_params[key] = trial.suggest_categorical(key, bounds[0])

            # Combine the trial params into 'params' for the global objective
            kwargs_for_run = self.kwargs.copy()
            kwargs_for_run["params"] = trial_params

            # Call standard global objective function
            return self.objective_func(trial, **kwargs_for_run)

        # Define progress callback wrapper
        def optuna_callback(study, trial):
            if progress_callback_celery:
                try:
                    progress_callback_celery(study, trial)
                except Exception:
                    pass

        self.study.optimize(
            objective_wrapper,
            n_trials=n_trials,
            timeout=timeout,
            callbacks=[optuna_callback],
        )

        # Extract best params and best value
        try:
            best_trial = self.study.best_trial
            self.best_value = best_trial.value
            return best_trial.params
        except Exception:
            self.best_value = None
            return None

    def get_study_dataframe(self) -> pd.DataFrame:
        if self.study:
            return self.study.trials_dataframe()
        return pd.DataFrame()
