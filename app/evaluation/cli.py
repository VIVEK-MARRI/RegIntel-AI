"""CLI for running retrieval evaluations.

Usage:
    python -m app.evaluation.cli run --dataset default --strategies dense bm25 hybrid
    python -m app.evaluation.cli leaderboard
    python -m app.evaluation.cli history --strategy dense
    python -m app.evaluation.cli compare
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.evaluation.dataset import DatasetManager
from app.evaluation.evaluator import RetrievalEvaluator
from app.evaluation.reporting import ReportGenerator, Leaderboard
from app.evaluation.schemas import EvaluationConfig, RetrievalStrategy
from app.evaluation.storage import MetricsStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Retrieval Evaluation Suite CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run evaluation with default settings:
    python -m app.evaluation.cli run
  
  Run evaluation with specific strategies:
    python -m app.evaluation.cli run --strategies dense bm25
  
  View latest leaderboard:
    python -m app.evaluation.cli leaderboard
  
  View history for a strategy:
    python -m app.evaluation.cli history --strategy dense
  
  Compare all strategies:
    python -m app.evaluation.cli compare
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Run evaluation command
    run_parser = subparsers.add_parser("run", help="Run retrieval evaluation")
    run_parser.add_argument(
        "--dataset",
        type=str,
        default="default",
        help="Name of the golden dataset to use (default: default)",
    )
    run_parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["dense", "bm25", "hybrid", "hybrid_rerank"],
        default=["dense", "bm25", "hybrid", "hybrid_rerank"],
        help="Strategies to evaluate",
    )
    run_parser.add_argument(
        "--top-k",
        nargs="+",
        type=int,
        default=[5, 10],
        help="K values for metrics (default: 5 10)",
    )
    run_parser.add_argument(
        "--no-store",
        action="store_true",
        help="Do not store results historically",
    )
    run_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for the report",
    )

    # Leaderboard command
    subparsers.add_parser("leaderboard", help="View latest leaderboard")

    # History command
    history_parser = subparsers.add_parser("history", help="View historical metrics")
    history_parser.add_argument(
        "--strategy",
        type=str,
        choices=["dense", "bm25", "hybrid", "hybrid_rerank"],
        default=None,
        help="Filter by strategy",
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of records to show (default: 10)",
    )

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare all strategies")
    compare_parser.add_argument(
        "--metric",
        type=str,
        default="recall_at_5",
        choices=["recall_at_5", "recall_at_10", "mrr", "precision_at_5", "hit_rate"],
        help="Metric to compare (default: recall_at_5)",
    )

    # Trend command
    trend_parser = subparsers.add_parser("trend", help="View metric trends")
    trend_parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=["dense", "bm25", "hybrid", "hybrid_rerank"],
        help="Strategy to view trends for",
    )
    trend_parser.add_argument(
        "--metric",
        type=str,
        default="recall_at_5",
        help="Metric to track (default: recall_at_5)",
    )

    return parser.parse_args()


async def cmd_run(args):
    """Run evaluation command."""
    logger.info("Starting retrieval evaluation...")

    # Build configuration
    strategies = [RetrievalStrategy(s) for s in args.strategies]
    config = EvaluationConfig(
        dataset_name=args.dataset,
        strategies=strategies,
        top_k_values=args.top_k,
        store_results=not args.no_store,
    )

    # Initialize components
    dataset_manager = DatasetManager()
    metrics_storage = MetricsStorage()
    report_generator = ReportGenerator()

    # Load dataset
    dataset = dataset_manager.load_dataset(config.dataset_name)
    if dataset is None:
        logger.info(f"Dataset '{config.dataset_name}' not found, creating default.")
        dataset = dataset_manager.get_or_create_default_dataset()

    logger.info(f"Using dataset: {dataset.name} ({len(dataset.queries)} queries)")

    # Note: In a real scenario, you would inject the actual services here
    # For CLI usage, we create a mock evaluator that demonstrates the structure
    logger.info("Note: CLI evaluation requires database connection setup.")
    logger.info("For programmatic usage, use RetrievalEvaluator directly.")

    # Print configuration
    print("\n" + "=" * 60)
    print("EVALUATION CONFIGURATION")
    print("=" * 60)
    print(f"Dataset: {config.dataset_name}")
    print(f"Strategies: {[s.value for s in config.strategies]}")
    print(f"Top-K values: {config.top_k_values}")
    print(f"Store results: {config.store_results}")
    print("=" * 60)

    # Print sample output format
    print("\nSample output format:")
    sample_output = {
        "strategy": "hybrid_rerank",
        "recall_at_5": 0.94,
        "recall_at_10": 0.97,
        "mrr": 0.89,
        "precision_at_5": 0.85,
        "hit_rate": 1.0,
        "latency_ms": 156.3,
    }
    print(json.dumps(sample_output, indent=2))


def cmd_leaderboard(args):
    """View leaderboard command."""
    leaderboard = Leaderboard()
    entries = leaderboard.get_latest_leaderboard()

    if entries is None:
        print("No leaderboard data found. Run an evaluation first.")
        return

    print(leaderboard.format_leaderboard(entries))


def cmd_history(args):
    """View history command."""
    storage = MetricsStorage()
    strategy = RetrievalStrategy(args.strategy) if args.strategy else None

    history = storage.get_history(strategy=strategy, limit=args.limit)

    if not history:
        print("No historical data found.")
        return

    print("\n" + "=" * 80)
    print("HISTORICAL METRICS")
    print("=" * 80)

    for record in history:
        print(f"\nTimestamp: {record.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Strategy: {record.strategy.value}")
        print(f"Dataset: {record.dataset_name}")
        print(f"  Recall@5:  {record.recall_at_5:.4f}")
        print(f"  Recall@10: {record.recall_at_10:.4f}")
        print(f"  MRR:       {record.mrr:.4f}")
        print(f"  Hit Rate:  {record.hit_rate:.4f}")
        print(f"  Latency:   {record.latency_ms:.2f}ms")

    print("\n" + "=" * 80)


def cmd_compare(args):
    """Compare strategies command."""
    storage = MetricsStorage()
    comparison = storage.compare_strategies(metric=args.metric)

    print("\n" + "=" * 60)
    print(f"STRATEGY COMPARISON ({args.metric})")
    print("=" * 60)

    for strategy, data in comparison.items():
        if data:
            print(f"\n{strategy}:")
            print(f"  {args.metric}: {data['value']:.4f}")
            print(f"  Dataset: {data['dataset']}")
            print(f"  Timestamp: {data['timestamp']}")
        else:
            print(f"\n{strategy}: No data available")

    print("\n" + "=" * 60)


def cmd_trend(args):
    """View trend command."""
    storage = MetricsStorage()
    strategy = RetrievalStrategy(args.strategy)

    trend = storage.get_trend(strategy, metric=args.metric)

    if not trend:
        print(f"No trend data found for {args.strategy}.")
        return

    print("\n" + "=" * 60)
    print(f"TREND: {args.strategy} - {args.metric}")
    print("=" * 60)

    for point in trend:
        print(f"  {point['timestamp'][:19]} | {point['value']:.4f} | {point['dataset']}")

    print("\n" + "=" * 60)


def main():
    """Main entry point."""
    args = parse_args()

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "leaderboard":
        cmd_leaderboard(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "trend":
        cmd_trend(args)
    else:
        print("Please specify a command. Use --help for usage information.")
        sys.exit(1)


if __name__ == "__main__":
    main()