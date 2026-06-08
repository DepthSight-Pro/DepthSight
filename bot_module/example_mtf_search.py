#!/usr/bin/env python3
"""
Multi-Timeframe genetic search WITHOUT tape data (PRODUCTION configuration).

Parameters:
- Population: 200 individuals
- Generations: 50
- Multithreading: 12 cores
- Memory saving: 70% (without tape data)
"""

from pathlib import Path
import logging
import multiprocessing
from bot_module.genetic_strategy_finder import (
    load_and_prepare_assets,
    GeneticStrategyFinder,
)

# Logging configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    logger.info("🚀 Starting Multi-Timeframe Strategy Search (PRODUCTION)")
    logger.info("=" * 70)

    # ==================== CONFIGURATION ====================

    # Directory with asset data
    DATA_DIR = Path("data_storage/binance/futures")

    # Automatic scanning of all assets in the directory
    if not DATA_DIR.exists():
        logger.error(f"❌ Data directory not found: {DATA_DIR}")
        return

    # Getting all subdirectories (each = asset)
    asset_paths = [
        p
        for p in DATA_DIR.iterdir()
        if p.is_dir() and (p / "kline_1m.parquet").exists()
    ]

    if not asset_paths:
        logger.error(f"❌ No assets with kline_1m.parquet found in {DATA_DIR}")
        return

    logger.info(f"🔍 Auto-discovered {len(asset_paths)} assets in {DATA_DIR}")
    logger.info(f"   Assets: {sorted([p.name for p in asset_paths])}")

    # Genetic algorithm parameters (PRODUCTION)
    POPULATION_SIZE = 500  # 🔥 Population (increased for better results)
    GENERATIONS = 100  # 🔥 Generations (increased for convergence)
    MAX_CORES = 12  # 🔥 CPU cores
    MAX_ROWS = 500000  # ~5 months of data on 1m

    # Checkpoint file for saving progress
    CHECKPOINT_FILE = "mtf_checkpoint.pkl"

    # Checking existence of paths
    existing_paths = [p for p in asset_paths if p.exists()]
    if not existing_paths:
        logger.error(
            "❌ No valid asset paths found! Please check your data_storage directory."
        )
        return

    logger.info(
        f"✅ Found {len(existing_paths)} assets: {[p.name for p in existing_paths]}"
    )

    # KEY OPTIMIZATION: include_tape=False
    # Memory saving: 750 MB → 225 MB for 5 timeframes!
    logger.info("\n📊 Loading data WITHOUT tape columns (include_tape=False)...")
    logger.info(f"   Max rows per asset: {MAX_ROWS:,} (~{MAX_ROWS // 43200} months)")

    mtf_data = load_and_prepare_assets(
        existing_paths,
        max_rows=MAX_ROWS,
        include_tape=False,  # 🔥 NO TAPE = 70% memory saved!
    )

    if not mtf_data:
        logger.error("❌ Failed to load any data!")
        return

    # Showing statistics of loaded data
    logger.info("\n📈 Loaded Multi-Timeframe Data:")
    total_memory_mb = 0
    total_bars_1m = 0

    for asset_name, timeframes in mtf_data.items():
        bars_1m = len(timeframes["1m"])
        total_bars_1m += bars_1m

        for tf, df in timeframes.items():
            memory_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
            total_memory_mb += memory_mb

    logger.info(f"  Assets: {len(mtf_data)}")
    logger.info(f"  Timeframes: {list(next(iter(mtf_data.values())).keys())}")
    logger.info(
        f"  Total 1m bars: {total_bars_1m:,} (~{total_bars_1m / 43200:.1f} months)"
    )
    logger.info(f"  💾 Total Memory: {total_memory_mb:.1f} MB")
    logger.info(f"  💡 Memory saved by excluding tape: ~{total_memory_mb * 2.3:.1f} MB")

    # Genetic algorithm configuration
    run_config = {
        "population_size": POPULATION_SIZE,  # (e.g. 100)
        "generations": GENERATIONS,
        # 🔥 CHAOS MODE:
        "crossover_probability": 0.2,  # WAS 0.7. Reducing to copy less of the old.
        "mutation_probability": 0.8,  # WAS 0.3. Increasing so that 80% of children mutate!
        "min_trades_for_prescreening": 10,  # Not important
    }

    logger.info("\n🧬 Genetic Algorithm Configuration:")
    logger.info(f"  - Population Size: {POPULATION_SIZE}")
    logger.info(f"  - Generations: {GENERATIONS}")
    logger.info(f"  - CPU Cores: {MAX_CORES}")
    logger.info(f"  - Checkpoint: {CHECKPOINT_FILE}")
    logger.info("  - Available Timeframes: ['1m', '5m', '15m', '1h', '4h']")
    logger.info(
        f"  - Estimated Runtime: ~{POPULATION_SIZE * GENERATIONS * len(existing_paths) / (MAX_CORES * 60):.0f}-{POPULATION_SIZE * GENERATIONS * len(existing_paths) / (MAX_CORES * 30):.0f} minutes"
    )

    # Creating genetic algorithm
    finder = GeneticStrategyFinder(mtf_data, run_config)

    # Multithreading setup
    logger.info(f"\n⚡ Initializing multiprocessing pool with {MAX_CORES} workers...")

    try:
        with multiprocessing.Pool(processes=MAX_CORES) as pool:
            logger.info("✅ Pool created successfully")
            logger.info(f"\n{'=' * 70}")
            logger.info("🏁 Starting evolution...")
            logger.info(f"{'=' * 70}\n")

            # Launching search with multithreading
            results = finder.run(
                map_function=pool.imap_unordered, checkpoint_file=CHECKPOINT_FILE
            )

        # Displaying top 5 strategies
        logger.info(f"\n{'=' * 70}")
        logger.info("🏆 TOP 5 STRATEGIES FOUND:")
        logger.info(f"{'=' * 70}\n")

        for i, result in enumerate(results[:5], 1):
            logger.info(f"\n{'─' * 70}")
            logger.info(f"Rank #{i} - Fitness Score: {result['fitness_score']:.4f}")
            logger.info(f"{'─' * 70}")

            strategy = result["strategy_json"]
            kpis = result["kpis_json"]

            # Extracting used timeframes
            timeframes_used = set()

            def extract_timeframes(node, timeframes_set):
                if isinstance(node, dict):
                    if "params" in node and "timeframe" in node["params"]:
                        timeframes_set.add(node["params"]["timeframe"])
                    if "children" in node:
                        for child in node["children"]:
                            extract_timeframes(child, timeframes_set)

            if "filters" in strategy:
                extract_timeframes(strategy["filters"], timeframes_used)
            if "entryConditions" in strategy:
                extract_timeframes(strategy["entryConditions"], timeframes_used)

            logger.info(f"📊 Timeframes Used: {sorted(timeframes_used)}")
            logger.info("📈 Performance Metrics:")
            logger.info(f"   - Total Trades: {kpis.get('total_trades', 0):.0f}")
            logger.info(f"   - Total PnL: {kpis.get('total_pnl_pct', 0):.2f}%")
            logger.info(f"   - Max DD: {kpis.get('max_dd', 0):.2f}%")
            logger.info(f"   - Sortino Ratio: {kpis.get('sortino_ratio', 0):.2f}")
            logger.info(f"   - Consistency: {kpis.get('consistency_score', 0):.2%}")

        logger.info(f"\n{'=' * 70}")
        logger.info("✅ SEARCH COMPLETED SUCCESSFULLY!")
        logger.info(f"{'=' * 70}")
        logger.info(
            "\n💡 Results saved. You can find the best strategies in Hall of Fame."
        )
        logger.info(f"💾 Checkpoint saved to: {CHECKPOINT_FILE}")

    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Search interrupted by user!")
        logger.info(f"💾 Progress saved to: {CHECKPOINT_FILE}")
        logger.info("💡 You can resume by running the script again.")

    except Exception as e:
        logger.error(f"\n❌ Error during search: {e}", exc_info=True)

    finally:
        logger.info("\n👋 Exiting...")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
