"""Reporting System for Retrieval Evaluation.

Generates comparison reports and leaderboard rankings.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.evaluation.schemas import (
    EvaluationReport,
    RetrievalStrategy,
)

logger = logging.getLogger(__name__)

# Default storage path for reports
DEFAULT_REPORTS_DIR = Path("storage/evaluation/reports")


class ReportGenerator:
    """Generates evaluation reports and comparisons."""

    def __init__(self, reports_dir: Optional[Path] = None):
        """Initialize report generator.

        Args:
            reports_dir: Directory to save reports. Defaults to storage/evaluation/reports.
        """
        self.reports_dir = reports_dir or DEFAULT_REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, report: EvaluationReport) -> Path:
        """Generate and save a full evaluation report.

        Args:
            report: The evaluation report to generate.

        Returns:
            Path to the saved report file.
        """
        # Save JSON report
        report_path = self.reports_dir / f"report_{report.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, default=str)

        # Generate markdown summary
        md_path = self.reports_dir / f"report_{report.timestamp.strftime('%Y%m%d_%H%M%S')}.md"
        md_content = self._generate_markdown(report)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info(f"Generated report: {report_path}")
        return report_path

    def _generate_markdown(self, report: EvaluationReport) -> str:
        """Generate markdown report content.

        Args:
            report: The evaluation report.

        Returns:
            Markdown formatted string.
        """
        lines = []
        lines.append("# Retrieval Evaluation Report")
        lines.append("")
        lines.append(f"**Dataset:** {report.dataset_name}")
        lines.append(f"**Generated:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"**Report ID:** {report.report_id}")
        lines.append("")

        # Leaderboard
        lines.append("## Leaderboard")
        lines.append("")
        lines.append("| Rank | Strategy | Recall@5 | Recall@10 | MRR | Precision@5 | Hit Rate | NDCG@5 | NDCG@10 | Latency (ms) | Composite |")
        lines.append("|------|----------|----------|-----------|-----|-------------|----------|--------|---------|--------------|-----------|")

        for entry in report.leaderboard:
            lines.append(
                f"| {entry['rank']} "
                f"| {entry['strategy']} "
                f"| {entry['avg_recall_at_5']:.4f} "
                f"| {entry['avg_recall_at_10']:.4f} "
                f"| {entry['avg_mrr']:.4f} "
                f"| {entry['avg_precision_at_5']:.4f} "
                f"| {entry['avg_hit_rate']:.4f} "
                f"| {entry.get('avg_ndcg_at_5', 0.0):.4f} "
                f"| {entry.get('avg_ndcg_at_10', 0.0):.4f} "
                f"| {entry['avg_latency_ms']:.2f} "
                f"| {entry['composite_score']:.4f} |"
            )

        lines.append("")

        # Detailed Results
        lines.append("## Detailed Results")
        lines.append("")

        for result in report.strategy_results:
            lines.append(f"### {result.strategy.value}")
            lines.append("")
            lines.append(f"- **Total Queries:** {result.total_queries}")
            lines.append(f"- **Avg Recall@5:** {result.avg_recall_at_5:.4f}")
            lines.append(f"- **Avg Recall@10:** {result.avg_recall_at_10:.4f}")
            lines.append(f"- **Avg MRR:** {result.avg_mrr:.4f}")
            lines.append(f"- **Avg Precision@5:** {result.avg_precision_at_5:.4f}")
            lines.append(f"- **Avg Precision@10:** {result.avg_precision_at_10:.4f}")
            lines.append(f"- **Avg Hit Rate:** {result.avg_hit_rate:.4f}")
            lines.append(f"- **Avg NDCG@5:** {result.avg_ndcg_at_5:.4f}")
            lines.append(f"- **Avg NDCG@10:** {result.avg_ndcg_at_10:.4f}")
            lines.append(f"- **Avg Latency:** {result.avg_latency_ms:.2f}ms")
            lines.append("")

            # Per-query breakdown
            lines.append("#### Per-Query Breakdown")
            lines.append("")
            lines.append("| Query ID | Query Text | Recall@5 | MRR | Hit Rate |")
            lines.append("|----------|------------|----------|-----|----------|")

            for qr in result.query_results:
                query_text = qr.query_text[:50] + "..." if len(qr.query_text) > 50 else qr.query_text
                lines.append(
                    f"| {qr.query_id} "
                    f"| {query_text} "
                    f"| {qr.recall_at_5:.4f} "
                    f"| {qr.mrr:.4f} "
                    f"| {qr.hit_rate:.0f} |"
                )

            lines.append("")

        return "\n".join(lines)

    def generate_comparison_table(
        self, reports: List[EvaluationReport]
    ) -> str:
        """Generate a comparison table across multiple reports.

        Args:
            reports: List of evaluation reports to compare.

        Returns:
            Markdown formatted comparison table.
        """
        lines = []
        lines.append("# Strategy Comparison Across Evaluations")
        lines.append("")
        lines.append("| Report | Strategy | Recall@5 | Recall@10 | MRR | Hit Rate | NDCG@5 |")
        lines.append("|--------|----------|----------|-----------|-----|----------|--------|")

        for report in reports:
            timestamp = report.timestamp.strftime('%Y-%m-%d %H:%M')
            for result in report.strategy_results:
                lines.append(
                    f"| {timestamp} "
                    f"| {result.strategy.value} "
                    f"| {result.avg_recall_at_5:.4f} "
                    f"| {result.avg_recall_at_10:.4f} "
                    f"| {result.avg_mrr:.4f} "
                    f"| {result.avg_hit_rate:.4f} "
                    f"| {result.avg_ndcg_at_5:.4f} |"
                )

        lines.append("")
        return "\n".join(lines)


class Leaderboard:
    """Manages leaderboard rankings."""

    def __init__(self, reports_dir: Optional[Path] = None):
        """Initialize leaderboard.

        Args:
            reports_dir: Directory containing reports.
        """
        self.reports_dir = reports_dir or DEFAULT_REPORTS_DIR

    def get_latest_leaderboard(self) -> Optional[List[Dict[str, Any]]]:
        """Get the latest leaderboard from saved reports.

        Returns:
            Latest leaderboard entries or None.
        """
        if not self.reports_dir.exists():
            return None

        report_files = sorted(self.reports_dir.glob("report_*.json"), reverse=True)
        if not report_files:
            return None

        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("leaderboard", [])
        except Exception as e:
            logger.error(f"Error loading latest leaderboard: {e}")
            return None

    def get_strategy_ranking(
        self, strategy: RetrievalStrategy
    ) -> Optional[Dict[str, Any]]:
        """Get the ranking for a specific strategy.

        Args:
            strategy: Retrieval strategy.

        Returns:
            Ranking entry or None.
        """
        leaderboard = self.get_latest_leaderboard()
        if not leaderboard:
            return None

        for entry in leaderboard:
            if entry.get("strategy") == strategy.value:
                return entry

        return None

    def format_leaderboard(self, leaderboard: List[Dict[str, Any]]) -> str:
        """Format leaderboard for display.

        Args:
            leaderboard: Leaderboard entries.

        Returns:
            Formatted string.
        """
        lines = []
        lines.append("=" * 80)
        lines.append("RETRIEVAL STRATEGY LEADERBOARD")
        lines.append("=" * 80)
        lines.append("")

        for entry in leaderboard:
            rank = entry.get("rank", "?")
            strategy = entry.get("strategy", "unknown")
            composite = entry.get("composite_score", 0.0)
            recall_5 = entry.get("avg_recall_at_5", 0.0)
            mrr = entry.get("avg_mrr", 0.0)
            latency = entry.get("avg_latency_ms", 0.0)

            lines.append(f"  #{rank} {strategy}")
            lines.append(f"      Composite Score: {composite:.4f}")
            lines.append(f"      Recall@5:        {recall_5:.4f}")
            lines.append(f"      MRR:             {mrr:.4f}")
            lines.append(f"      Latency:         {latency:.2f}ms")
            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)