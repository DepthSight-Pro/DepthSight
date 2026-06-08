"""
Genome Analyzer Service
Analyzes backtests to discover and catalog "genes" (successful component combinations).
Uses DecisionTraceParser to extract triggered foundations from trades.
"""

import hashlib
import random
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from . import models
from .analytics_parsers import DecisionTraceParser

# Thresholds for gene discovery
MIN_SHARPE_RATIO = 1.0
MIN_TRADES = 20

# Gene naming components for procedural generation
PREFIXES = [
    "Volatilis",
    "Momentum",
    "Reversius",
    "Breakout",
    "Trend",
    "Oscillat",
    "Bollinger",
    "Stochastic",
    "Volume",
    "Moving",
    "Divergent",
    "Convergent",
]
SUFFIXES = [
    "RSI",
    "MACD",
    "ATR",
    "EMA",
    "SMA",
    "Bands",
    "Profile",
    "Channel",
    "Filter",
    "Indicator",
    "Foundation",
    "Management",
    "Exit",
    "Entry",
]
ENDINGS = ["us", "is", "icus", "ensis", "oides", "alis"]


class GenomeAnalyzer:
    """Service for discovering and managing strategy genes."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _generate_gene_id(components: List[str]) -> str:
        """Generate unique ID from component list."""
        sorted_components = sorted(components)
        component_str = ",".join(sorted_components)
        return hashlib.sha256(component_str.encode()).hexdigest()[:16]

    @staticmethod
    def _generate_scientific_name(components: List[str]) -> str:
        """Generate scientific-sounding name from components."""
        # Use first 2-3 components to generate name
        prefix = random.choice(PREFIXES)
        middle_parts = []

        for component in components[:2]:
            # Extract meaningful parts from component type
            parts = component.split("_")
            if len(parts) > 0:
                middle_parts.append(parts[0][:3])

        suffix = random.choice(SUFFIXES)
        ending = random.choice(ENDINGS)

        name_parts = [prefix] + middle_parts + [suffix + ending]
        return "-".join(name_parts)

    def _extract_foundation_combinations_from_trades(
        self, trades: List[models.BacktestTrade]
    ) -> List[Tuple[List[str], int, float, Dict[str, Any]]]:
        """
        Extract unique foundation combinations from trades with weighted analysis.
        Returns list of (combination, frequency, pnl_contribution, context) tuples.
        """
        combination_data = {}

        # Analyze both profitable and losing trades
        for trade in trades:
            if not trade.decision_trace_json or not trade.pnl:
                continue

            # Use DecisionTraceParser to extract triggered foundations
            parser = DecisionTraceParser(trade.decision_trace_json)
            foundations = parser.get_used_foundations()

            if len(foundations) < 2:  # Skip if less than 2 foundations
                continue

            # Sort to make combination order-independent
            combination = tuple(sorted(foundations))

            if combination not in combination_data:
                combination_data[combination] = {
                    "frequency": 0,
                    "total_pnl": 0.0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "volatility_sum": 0.0,
                    "trade_count_for_volatility": 0,
                }

            combination_data[combination]["frequency"] += 1
            combination_data[combination]["total_pnl"] += trade.pnl

            if trade.pnl > 0:
                combination_data[combination]["winning_trades"] += 1
            else:
                combination_data[combination]["losing_trades"] += 1

            # Context analysis: try to detect market regime
            # Use price movement as proxy for volatility
            if trade.entry_price and trade.exit_price:
                price_change_pct = (
                    abs((trade.exit_price - trade.entry_price) / trade.entry_price)
                    * 100
                )
                combination_data[combination]["volatility_sum"] += price_change_pct
                combination_data[combination]["trade_count_for_volatility"] += 1

        # Calculate weighted scores and context
        results = []
        for combo, data in combination_data.items():
            # Calculate win rate for this combination
            total = data["winning_trades"] + data["losing_trades"]
            win_rate = (data["winning_trades"] / total * 100) if total > 0 else 0

            # Calculate average volatility exposure
            avg_volatility = (
                (data["volatility_sum"] / data["trade_count_for_volatility"])
                if data["trade_count_for_volatility"] > 0
                else 0
            )

            # Context metadata
            context = {
                "win_rate": round(win_rate, 2),
                "avg_pnl": round(data["total_pnl"] / data["frequency"], 2)
                if data["frequency"] > 0
                else 0,
                "market_regime": self._classify_market_regime(avg_volatility),
                "avg_volatility": round(avg_volatility, 2),
            }

            results.append((list(combo), data["frequency"], data["total_pnl"], context))

        # Sort by PnL contribution (most valuable first)
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    @staticmethod
    def _classify_market_regime(avg_volatility: float) -> str:
        """Classify market regime based on average volatility."""
        if avg_volatility > 5.0:
            return "high_volatility"
        elif avg_volatility > 2.0:
            return "medium_volatility"
        elif avg_volatility > 0.5:
            return "trending"
        else:
            return "ranging"

    async def _create_or_get_gene(
        self,
        components: List[str],
        user_id: int,
        strategy_id: str,
        context: Dict[str, Any] = None,
    ) -> Optional[models.Gene]:
        """Create gene if it doesn't exist, or return existing one."""
        gene_id = self._generate_gene_id(components)

        # Check if gene already exists
        result = await self.db.execute(
            select(models.Gene).where(models.Gene.id == gene_id)
        )
        gene = result.scalar_one_or_none()

        if not gene:
            # Create new gene with context metadata
            name = self._generate_scientific_name(components)
            market_regime = (
                context.get("market_regime", "unknown") if context else "unknown"
            )
            win_rate = context.get("win_rate", 0) if context else 0

            description = f"Effective in {market_regime.replace('_', ' ')} conditions. Win rate: {win_rate:.1f}%. Combination: {', '.join(components[:3])}{'...' if len(components) > 3 else ''}"

            gene = models.Gene(
                id=gene_id,
                name=name,
                description=description,
                components=components,
                rarity=100.0,
                metadata_json=context,  # Use the new attribute name
                first_discovered_by=user_id,
            )
            self.db.add(gene)
            try:
                await self.db.flush()
            except IntegrityError:
                # Race condition - gene was created by another request
                await self.db.rollback()
                result = await self.db.execute(
                    select(models.Gene).where(models.Gene.id == gene_id)
                )
                gene = result.scalar_one_or_none()

        return gene

    async def _grant_gene_to_user(
        self, user_id: int, gene_id: str, strategy_id: str, source_type: str
    ) -> Optional[models.UserGene]:
        """Grant a gene to user if they don't have it yet."""
        try:
            user_gene = models.UserGene(
                user_id=user_id,
                gene_id=gene_id,
                source_strategy_id=strategy_id,
                source_type=source_type,
            )
            self.db.add(user_gene)
            await self.db.flush()
            return user_gene
        except IntegrityError:
            # User already has this gene
            await self.db.rollback()
            return None

    async def analyze_backtest(
        self, backtest_run: models.BacktestRun, source_type: str = "manual"
    ) -> List[models.UserGene]:
        """
        Analyze completed backtest and discover genes from winning foundation combinations.

        Args:
            backtest_run: Completed backtest run with trades
            source_type: Source of discovery ('manual', 'discovery_lab', 'optimizer', 'hybrid')

        Returns:
            List of newly unlocked user genes
        """
        newly_unlocked = []

        # Check if backtest meets minimum requirements
        kpi = backtest_run.kpi_results_json or {}
        sharpe_ratio = kpi.get("sharpe_ratio", 0)
        total_trades = kpi.get("total_trades", 0)

        if sharpe_ratio < MIN_SHARPE_RATIO or total_trades < MIN_TRADES:
            return newly_unlocked

        # Extract foundation combinations from actual trades
        if not backtest_run.trades:
            return newly_unlocked

        combinations_with_data = self._extract_foundation_combinations_from_trades(
            backtest_run.trades
        )
        if not combinations_with_data:
            return newly_unlocked

        # Create/get genes for each unique combination with positive PnL contribution
        for combo, frequency, total_pnl, context in combinations_with_data:
            # Only create genes for combinations that:
            # 1. Appeared multiple times (more reliable)
            # 2. Have positive PnL contribution
            # 3. Have good win rate (>50%)
            if frequency < 2 or total_pnl <= 0 or context.get("win_rate", 0) < 50:
                continue

            gene = await self._create_or_get_gene(
                components=combo,
                user_id=backtest_run.user_id,
                strategy_id=backtest_run.id,
                context=context,
            )

            if gene:
                user_gene = await self._grant_gene_to_user(
                    user_id=backtest_run.user_id,
                    gene_id=gene.id,
                    strategy_id=backtest_run.id,
                    source_type=source_type,
                )

                if user_gene:
                    newly_unlocked.append(user_gene)

        # Commit all changes
        if newly_unlocked:
            await self.db.commit()

        return newly_unlocked

    async def calculate_gene_rarity(self, gene_id: str) -> float:
        """
        Calculate rarity of a gene (% of users who have it).
        Should be called periodically.
        """
        # Count total users
        result = await self.db.execute(select(models.User))
        total_users = len(result.scalars().all())

        if total_users == 0:
            return 100.0

        # Count users with this gene
        result = await self.db.execute(
            select(models.UserGene).where(models.UserGene.gene_id == gene_id)
        )
        users_with_gene = len(result.scalars().all())

        rarity = (users_with_gene / total_users) * 100.0
        return round(rarity, 2)

    async def get_user_genes(
        self, user_id: int
    ) -> List[Tuple[models.Gene, models.UserGene]]:
        """Get all genes unlocked by user."""
        result = await self.db.execute(
            select(models.Gene, models.UserGene)
            .join(models.UserGene, models.Gene.id == models.UserGene.gene_id)
            .where(models.UserGene.user_id == user_id)
            .order_by(models.UserGene.unlocked_at.desc())
        )
        return result.all()

    async def get_gene_rarity_tier(self, rarity: float) -> str:
        """Determine rarity tier based on percentage."""
        if rarity < 1.0:
            return "LEGENDARY"
        elif rarity < 5.0:
            return "EPIC"
        elif rarity < 20.0:
            return "RARE"
        else:
            return "COMMON"
