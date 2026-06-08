# bot_module/dataset_generator.py

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import pandas as pd

# Use relative imports for integration into the project
try:
    from . import config
    from .trainer import Trainer
    from .ml_strategy import OnlineAgentStrategy
    from .depthsight_backtester import DepthSightBacktester
except ImportError:
    # Stubs for standalone run or if imports fail
    print(
        "Warning: Failed to import bot_module components in dataset_generator.py. Using mocks."
    )

    class MockConfig:
        ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT = 0.15
        ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT = 0.10
        ML_TRAINING_LABEL_LOOKAHEAD_BARS = 15

    class Trainer:
        async def _load_historical_data(self, *args, **kwargs):
            return {}

    class OnlineAgentStrategy:
        NAME = "OnlineAgentStrategy"

        @property
        def required_data_types(self):
            return {"kline_1m", "aggTrade"}

    class DepthSightBacktester:
        def __init__(self, *args, **kwargs):
            pass

        async def run_async(self):
            return {"training_data": []}

    config = MockConfig()

logger = logging.getLogger("bot_module.dataset_generator")


class DatasetGenerator:
    """
    Orchestrator for generating datasets for training ML models.
    Uses existing Trainer and DepthSightBacktester components.
    """

    def __init__(self, run_params: Dict[str, Any], user_id: int):
        """
        Initializes the generator.

        Args:
            run_params (Dict[str, Any]): Run parameters received from the API request.
                                         Contains 'symbols', 'start_date', 'end_date', etc.
            user_id (int): ID of the user for whom the dataset is being generated.
        """
        self.run_params = run_params
        self.user_id = user_id
        self.trainer = Trainer()  # Trainer is used as a utility for loading data

        # Extracting parameters for convenience
        self.symbol = self.run_params["symbols"][
            0
        ]  # Currently supporting only one symbol
        self.start_dt = datetime.fromisoformat(self.run_params["start_date"])
        self.end_dt = datetime.fromisoformat(self.run_params["end_date"])

        logger.info(
            f"DatasetGenerator initialized for User {self.user_id}, Symbol {self.symbol}, "
            f"Period [{self.start_dt.date()} to {self.end_dt.date()}]"
        )

    async def generate(self) -> Tuple[Optional[pd.DataFrame], Optional[List[str]]]:
        """
        The main method that performs the entire dataset generation process.

        Returns:
            Tuple (pd.DataFrame, List[str]) in case of success:
            - DataFrame: Ready dataset with features and target variable.
            - List[str]: List of feature column names.
            In case of error, returns (None, None).
        """
        try:
            # 1. Determine what data is needed based on the ML strategy
            ml_agent_instance = OnlineAgentStrategy()
            required_data_types = ml_agent_instance.required_data_types
            logger.info(
                f"Required data types for feature extraction: {required_data_types}"
            )

            # 2. Load historical data using Trainer
            historical_data = await self.trainer._load_historical_data(
                self.symbol, self.start_dt, self.end_dt, required_data_types
            )

            if not historical_data or not any(
                df is not None and not df.empty for df in historical_data.values()
            ):
                logger.error("Failed to load historical data for the specified period.")
                raise ValueError("Failed to load historical data.")

            logger.info(
                "Historical data loaded successfully. Initializing backtester for data collection."
            )

            # 3. Initialize DepthSightBacktester in a special data collection mode
            backtester = DepthSightBacktester(
                strategy_name=OnlineAgentStrategy.NAME,
                symbol=self.symbol,
                params={},  # Strategy parameters are not important, we are not trading
                historical_data=historical_data,
                initial_balance=10000,  # Not used, but required by the constructor
                min_trades_required=0,
                risk_params={"risk_pct_per_trade": 0.01},  # Not used
                execution_config={"commission_pct": 0, "slippage_pct": 0},  # Not used
                # Key flags to activate data collection mode
                ml_training_mode=True,
                collect_data_mode=True,
                ml_agent_instance=ml_agent_instance,
                # Configuration for calculating y_true
                ml_training_config={
                    "ML_TRAINING_LABEL_LOOKAHEAD_BARS": getattr(
                        config, "ML_TRAINING_LABEL_LOOKAHEAD_BARS", 15
                    )
                },
                y_true_min_move_pct=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT", 0.15
                ),
                y_true_max_drawdown_pct=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT", 0.10
                ),
            )

            # 4. Run the "backtest", which will actually just collect data
            results = await backtester.run_async()
            logger.info("Backtester run completed in data collection mode.")

            # 5. Processing the result
            if not results or "training_data" not in results:
                logger.error("Backtester did not return 'training_data' in results.")
                raise ValueError("Backtester did not return training data.")

            training_data_list = results.get("training_data")
            if not training_data_list:
                logger.warning(
                    "No training examples were generated. The period might be too short or data is missing."
                )
                return pd.DataFrame(), []  # Returning empty but valid objects

            # 6. Convert the list of dictionaries into a flat DataFrame
            # This is the most important part: we "expand" nested features

            # First, create a DataFrame from the list. Features will be in a single JSON column.
            initial_df = pd.DataFrame(training_data_list)

            # Extracting and normalizing JSON with features
            features_json = initial_df["raw_features_json"].apply(pd.Series)

            # Remove the original JSON column and merge with the expanded features
            final_df = pd.concat(
                [initial_df.drop(columns=["raw_features_json"]), features_json], axis=1
            )

            # Define the list of columns that are features
            # These are all columns except for service ones (`y_true`, `timestamp`, `strategy`, etc.)
            non_feature_cols = ["y_true", "timestamp_signal", "strategy"]
            feature_names = [
                col for col in final_df.columns if col not in non_feature_cols
            ]

            logger.info(
                f"Dataset generated successfully. Shape: {final_df.shape}. Features found: {len(feature_names)}"
            )

            return final_df, feature_names

        except Exception as e:
            logger.error(f"Error during dataset generation: {e}", exc_info=True)
            return None, None
