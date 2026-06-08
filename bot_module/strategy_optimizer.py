# bot_module/evolution_optimizer.py

import logging
import json
import random
import copy
import argparse
import sys
import os
from pathlib import Path
import multiprocessing
import numpy as np
from tqdm import tqdm
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

logger = logging.getLogger("bot_module.evolution")


class EvolutionOptimizer(GeneticStrategyFinder):
    """
    This class takes a ready-made strategy and allows it to EVOLVE.
    It can change the structure, add filters, and change parameters.
    """

    def __init__(self, template_strategy: dict, *args, **kwargs):
        self.template_strategy = template_strategy
        super().__init__(*args, **kwargs)

        # We do NOT override mate/mutate to strict ones.
        # We use standard DEAP methods from genetic_strategy_finder,
        # which allow changing the tree structure.

        # But we need to override the fitness function to "Safe"
        if hasattr(self.toolbox, "evaluate"):
            self.toolbox.unregister("evaluate")
        self.toolbox.register("evaluate", self._evaluate_fitness_safe_calmar)

    def run(self, map_function, progress_callback=None, checkpoint_file=None):
        # 1. CREATING POPULATION FROM TEMPLATE
        # Instead of random strategies, we create mutants from your strategy
        logger.info("🧬 Creating a population of mutants based on the original...")
        population = []

        # The first one is a pure original (to have something to compare with)
        population.append(creator.Individual(copy.deepcopy(self.template_strategy)))

        # The rest are mutants
        for _ in range(self.population_size - 1):
            ind = creator.Individual(copy.deepcopy(self.template_strategy))
            # Apply strong mutation immediately to scatter them in different directions
            self.toolbox.mutate(ind)
            population.append(ind)

        start_gen = 0

        logger.info(
            f"🚀 Starting Evolution: {self.generations} generations. Goal: Calmar Ratio."
        )

        for gen in range(start_gen, self.generations):
            logger.info(f"--- Generation {gen + 1}/{self.generations} ---")

            # Evaluation
            invalid_ind = [ind for ind in population if not ind.fitness.valid]
            fitnesses = list(
                tqdm(
                    map_function(self.toolbox.evaluate, invalid_ind),
                    total=len(invalid_ind),
                    desc=f"Gen {gen + 1} Eval",
                    unit="ind",
                    colour="cyan",  # Cyan color for evolution
                )
            )

            for ind, fit in zip(invalid_ind, fitnesses):
                ind.fitness.values = fit

            # Updating Hall of Fame
            self.hall_of_fame.update(population)
            best_ind = self.hall_of_fame[0]

            if progress_callback:
                progress_callback(
                    {
                        "current_generation": gen + 1,
                        "best_fitness_so_far": best_ind.fitness.values[0],
                    }
                )

            # Selection
            offspring = self.toolbox.select(population, len(population))
            offspring = [self.toolbox.clone(ind) for ind in offspring]

            # Crossover (structural)
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < self.cx_prob:
                    self.toolbox.mate(child1, child2)
                    del child1.fitness.values
                    del child2.fitness.values

            # Mutation (structural + parametric)
            for mutant in offspring:
                if random.random() < self.mut_prob:
                    self.toolbox.mutate(mutant)
                    del mutant.fitness.values

            # ELITISM: Top-1 always moves to the next generation without changes
            # If the original was the best - it will remain.
            # If a mutant becomes better - it will become the new king.
            offspring[0] = self.toolbox.clone(best_ind)

            population[:] = offspring

            # Saving checkpoint
            if checkpoint_file:
                try:
                    population_dicts = []
                    for ind in population:
                        d = dict(ind)
                        if hasattr(ind, "fitness") and ind.fitness.valid:
                            d["fitness_values"] = list(ind.fitness.values)
                        population_dicts.append(d)

                    hof_dicts = []
                    if self.hall_of_fame:
                        for ind in self.hall_of_fame:
                            d = dict(ind)
                            if hasattr(ind, "fitness") and ind.fitness.valid:
                                d["fitness_values"] = list(ind.fitness.values)
                            hof_dicts.append(d)

                    state = {
                        "population": population_dicts,
                        "generation": gen,
                        "hall_of_fame": hof_dicts,
                        "serialization_format": "json",
                    }
                    with open(checkpoint_file, "w") as cp_file:
                        json.dump(state, cp_file, indent=2)
                except Exception:
                    pass

            logger.info(f"Gen {gen + 1} done. Best: {best_ind.fitness.values[0]:.0f}")

        # Final
        final_results = []
        for i, individual in enumerate(self.hall_of_fame[:5]):
            try:
                bt = FastVectorBacktester(
                    next(iter(self.training_data.values())), individual
                )
                kpis = bt.run()
            except Exception:
                kpis = {}
            final_results.append(
                {
                    "fitness_score": individual.fitness.values[0],
                    "strategy_json": individual,
                    "kpis_json": kpis,
                }
            )

        return final_results

    def _evaluate_fitness_safe_calmar(self, individual: dict) -> tuple:
        results = []
        try:
            for df in self.training_data.values():
                bt = FastVectorBacktester(df, individual, use_oracle=False)
                res = bt.run()
                # Sanitization
                for k in [
                    "sortino_ratio",
                    "consistency_score",
                    "total_pnl_pct",
                    "max_dd",
                    "total_trades",
                ]:
                    val = res.get(k, 0.0)
                    if val is None or np.isnan(val) or np.isinf(val):
                        if k == "max_dd":
                            res[k] = 100.0
                        elif k == "total_pnl_pct":
                            res[k] = -100.0
                        else:
                            res[k] = 0.0
                results.append(res)
        except Exception:
            return (-99999.0,)

        if not results:
            return (-99999.0,)

        avg_sortino = np.mean([min(r["sortino_ratio"], 10.0) for r in results])
        avg_consistency = np.mean([r["consistency_score"] for r in results])
        total_pnl = np.mean([r["total_pnl_pct"] for r in results])
        max_dd = np.mean([r["max_dd"] for r in results])

        # Calculating both average and SUM of trades
        avg_trades_per_coin = np.mean([r["total_trades"] for r in results])
        total_trades_all_coins = sum([r["total_trades"] for r in results])

        # Laziness filter (minimum 20 trades per coin)
        if avg_trades_per_coin < 20:
            return (-5000.0,)

        # SCORE CALCULATION
        calmar = total_pnl / (max_dd + 0.1)
        score = (avg_sortino * 200) + (calmar * 500)

        # Activity bonus
        score += np.log1p(avg_trades_per_coin) * 50

        # Drawdown penalty (Exponential)
        if max_dd > 20:
            penalty = ((max_dd - 20) ** 2) * 50  # Increased penalty
            score -= penalty

        score *= avg_consistency**2

        if total_pnl < 0:
            score = -1000.0 + total_pnl
        if np.isnan(score) or np.isinf(score):
            score = -99999.0
        score = np.clip(score, -100000.0, 1000000.0)

        # Print to console ONLY if the strategy passed quality filters
        # DD < 25% and Profit > 0
        if total_pnl > 0 and max_dd < 25:
            log_msg = (
                f"[GOOD] PnL:{total_pnl:6.1f}% | "
                f"DD:{max_dd:4.1f}% | "
                f"TotTrds:{int(total_trades_all_coins):4d} | "  # TOTAL NUMBER OF TRADES
                f"Score:{int(score)}"
            )
            logger.info(log_msg)

        return (score,)


if __name__ == "__main__":
    # Logger setup
    log_handler = TqdmLoggingHandler()
    log_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().handlers = [log_handler]
    logging.getLogger().setLevel(logging.INFO)

    parser = argparse.ArgumentParser(description="Evolution Strategy Optimizer")
    parser.add_argument(
        "--strategy_file", type=str, required=True, help="Path to parent strategy"
    )
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop_size", type=int, default=50)
    parser.add_argument("--output_dir", type=str, default="evolved_strategies")
    parser.add_argument("--max_cores", type=int, default=None)

    args = parser.parse_args()

    # 1. Loading parent
    try:
        with open(args.strategy_file, "r") as f:
            template = json.load(f)
    except Exception as e:
        print(f"Error loading strategy: {e}")
        exit(1)

    # 2. Data
    data_path = Path(args.data_path)
    # Take more assets (30) so that structural changes are reliable
    assets = [d for d in data_path.iterdir() if d.is_dir()][:30]
    train_dfs = load_and_prepare_assets(assets)

    # 3. Evolution Initialization
    # Use the full gene pool from genetic_strategy_finder for mutations
    optimizer = EvolutionOptimizer(
        template_strategy=template,
        training_data=train_dfs,
        run_config={
            "population_size": args.pop_size,
            "generations": args.generations,
            "crossover_probability": 0.5,  # Slightly lower, so as not to break the structure too quickly
            "mutation_probability": 0.4,  # Fairly high mutation
        },
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)

    def save_callback(data):
        gen = data["current_generation"]
        # Saving Top-3
        for i, ind in enumerate(optimizer.hall_of_fame[:3]):
            try:
                fit = ind.fitness.values[0]
                fname = out_dir / f"gen_{gen}_rank_{i + 1}_EVO_fit_{fit:.0f}.json"
                with open(fname, "w") as f:
                    json.dump(ind, f, indent=4)
            except Exception:
                pass

    pool = multiprocessing.Pool(processes=args.max_cores, maxtasksperchild=1)
    try:
        # Delete the checkpoint to start from the parent
        ckpt = out_dir / "evo_checkpoint.pkl"
        if ckpt.exists():
            os.remove(ckpt)

        optimizer.run(
            pool.imap, progress_callback=save_callback, checkpoint_file=str(ckpt)
        )
    finally:
        pool.close()
        pool.join()

    print("Evolution finished.")
