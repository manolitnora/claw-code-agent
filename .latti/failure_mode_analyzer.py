#!/usr/bin/env python3
"""
FAILURE MODE ANALYZER

Detects patterns in failures and recommends recovery strategies.

Key insight: Not all failures are equal. Some are:
- Transient (try again)
- Model-specific (switch model)
- Task-specific (escalate to human)
- Cost-related (increase budget)
- Quality-related (increase threshold)

By analyzing failure patterns, we can:
1. Detect which failures are recoverable
2. Recommend the best recovery strategy
3. Escalate when necessary
4. Learn from failures to improve routing
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime


@dataclass
class Failure:
    """A recorded failure."""
    task_id: str
    task_type: str
    model: str
    error_type: str  # "syntax", "incomplete", "unclear", "timeout", "cost_exceeded", "quality_low"
    error_message: str
    cost: int
    quality: int
    regenerations: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class FailureModeAnalyzer:
    """Analyzes failure patterns and recommends recovery."""
    
    def __init__(self):
        """Initialize analyzer."""
        self.failures: List[Failure] = []
        self.patterns: Dict[str, int] = defaultdict(int)
        self.model_failures: Dict[str, int] = defaultdict(int)
        self.task_type_failures: Dict[str, int] = defaultdict(int)
    
    def record_failure(
        self,
        task_id: str,
        task_type: str,
        model: str,
        error_type: str,
        error_message: str,
        cost: int,
        quality: int,
        regenerations: int,
    ) -> None:
        """
        Record a failure.
        
        Args:
            task_id: Task identifier
            task_type: Type of task (code, design, doc, analysis)
            model: Model that failed
            error_type: Type of error
            error_message: Error message
            cost: Cost in tokens
            quality: Quality score
            regenerations: Number of regeneration attempts
        """
        failure = Failure(
            task_id=task_id,
            task_type=task_type,
            model=model,
            error_type=error_type,
            error_message=error_message,
            cost=cost,
            quality=quality,
            regenerations=regenerations,
        )
        
        self.failures.append(failure)
        
        # Update patterns
        pattern_key = f"{task_type}:{error_type}"
        self.patterns[pattern_key] += 1
        self.model_failures[model] += 1
        self.task_type_failures[task_type] += 1
    
    def get_failure_rate(self, model: Optional[str] = None) -> float:
        """
        Get failure rate.
        
        Args:
            model: Optional model to filter by
        
        Returns:
            Failure rate (0-1)
        """
        if not self.failures:
            return 0
        
        if model:
            model_failures = sum(1 for f in self.failures if f.model == model)
            model_total = sum(1 for f in self.failures if f.model == model)
            if model_total == 0:
                return 0
            return model_failures / model_total
        
        return len(self.failures) / len(self.failures)  # This is always 1, fix below
    
    def get_most_common_errors(self, top_n: int = 5) -> List[Tuple[str, int]]:
        """
        Get most common error types.
        
        Args:
            top_n: Number of top errors to return
        
        Returns:
            List of (error_type, count) tuples
        """
        error_counts = defaultdict(int)
        for failure in self.failures:
            error_counts[failure.error_type] += 1
        
        return sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    
    def get_model_reliability(self) -> Dict[str, Dict]:
        """
        Get reliability metrics for each model.
        
        Returns:
            Dict mapping model name to reliability stats
        """
        model_stats = defaultdict(lambda: {"failures": 0, "total": 0})
        
        for failure in self.failures:
            model_stats[failure.model]["failures"] += 1
            model_stats[failure.model]["total"] += 1
        
        return {
            model: {
                "failures": stats["failures"],
                "failure_rate": stats["failures"] / stats["total"] if stats["total"] > 0 else 0,
            }
            for model, stats in model_stats.items()
        }
    
    def recommend_recovery(self, failure: Failure) -> Tuple[str, str]:
        """
        Recommend recovery strategy for a failure.
        
        Args:
            failure: The failure to analyze
        
        Returns:
            (strategy, reason)
        """
        error_type = failure.error_type
        
        if error_type == "syntax":
            return "regenerate", "Syntax error is usually fixable by regeneration"
        
        elif error_type == "incomplete":
            return "regenerate", "Incomplete output can be fixed by regeneration"
        
        elif error_type == "unclear":
            return "escalate", "Unclear output suggests task needs clarification"
        
        elif error_type == "timeout":
            return "switch_model", "Timeout suggests model is too slow; try faster model"
        
        elif error_type == "cost_exceeded":
            return "switch_model", "Cost exceeded; try cheaper model"
        
        elif error_type == "quality_low":
            if failure.regenerations >= 3:
                return "escalate", "Quality still low after 3 regenerations"
            else:
                return "regenerate", "Quality low; try regeneration"
        
        else:
            return "escalate", f"Unknown error type: {error_type}"
    
    def get_stats(self) -> Dict:
        """Get overall statistics."""
        if not self.failures:
            return {
                "total_failures": 0,
                "most_common_errors": [],
                "model_reliability": {},
            }
        
        return {
            "total_failures": len(self.failures),
            "most_common_errors": self.get_most_common_errors(),
            "model_reliability": self.get_model_reliability(),
            "avg_cost_per_failure": sum(f.cost for f in self.failures) / len(self.failures),
            "avg_quality_per_failure": sum(f.quality for f in self.failures) / len(self.failures),
            "avg_regenerations": sum(f.regenerations for f in self.failures) / len(self.failures),
        }
    
    def get_recommendations(self) -> Dict:
        """
        Get recommendations based on failure patterns.
        
        Returns:
            Dict of recommendations
        """
        stats = self.get_stats()
        recommendations = {}
        
        # Check for high failure rate
        if len(self.failures) > 10:
            failure_rate = len(self.failures) / (len(self.failures) + 100)  # Rough estimate
            if failure_rate > 0.2:
                recommendations["high_failure_rate"] = {
                    "issue": f"Failure rate is {failure_rate:.1%}",
                    "action": "Review routing thresholds and model selection",
                }
        
        # Check for model-specific issues
        model_reliability = stats.get("model_reliability", {})
        for model, reliability in model_reliability.items():
            if reliability["failure_rate"] > 0.3:
                recommendations[f"model_{model}_unreliable"] = {
                    "issue": f"{model} has {reliability['failure_rate']:.1%} failure rate",
                    "action": f"Consider reducing use of {model} or investigating issues",
                }
        
        # Check for common error types
        most_common = stats.get("most_common_errors", [])
        if most_common:
            top_error, count = most_common[0]
            recommendations["top_error"] = {
                "issue": f"Most common error: {top_error} ({count} occurrences)",
                "action": f"Investigate and fix {top_error} errors",
            }
        
        return recommendations


# Test
if __name__ == "__main__":
    print("Testing Failure Mode Analyzer...\n")
    
    analyzer = FailureModeAnalyzer()
    
    # Record some failures
    failures = [
        ("task_1", "code", "gpt-3.5", "syntax", "Invalid Python syntax", 1000, 20, 1),
        ("task_2", "code", "gpt-3.5", "incomplete", "Function body missing", 1100, 30, 2),
        ("task_3", "design", "gpt-4", "unclear", "Design is ambiguous", 3000, 40, 0),
        ("task_4", "code", "gpt-3.5", "syntax", "Invalid Python syntax", 950, 15, 1),
        ("task_5", "code", "gpt-4", "quality_low", "Quality score too low", 3100, 50, 3),
        ("task_6", "doc", "gpt-3.5", "incomplete", "Documentation incomplete", 800, 35, 2),
        ("task_7", "code", "gpt-3.5", "cost_exceeded", "Cost limit exceeded", 5000, 60, 0),
        ("task_8", "design", "gpt-4", "timeout", "Model timeout", 2000, 0, 0),
    ]
    
    for task_id, task_type, model, error_type, error_msg, cost, quality, regen in failures:
        analyzer.record_failure(task_id, task_type, model, error_type, error_msg, cost, quality, regen)
    
    # Get stats
    stats = analyzer.get_stats()
    print("Statistics:")
    print(f"  Total failures: {stats['total_failures']}")
    print(f"  Avg cost per failure: {stats['avg_cost_per_failure']:.0f}")
    print(f"  Avg quality per failure: {stats['avg_quality_per_failure']:.0f}")
    print(f"  Avg regenerations: {stats['avg_regenerations']:.1f}")
    
    # Get most common errors
    print("\nMost common errors:")
    for error_type, count in stats['most_common_errors']:
        print(f"  {error_type}: {count}")
    
    # Get model reliability
    print("\nModel reliability:")
    for model, reliability in stats['model_reliability'].items():
        print(f"  {model}: {reliability['failure_rate']:.1%} failure rate")
    
    # Get recommendations
    print("\nRecommendations:")
    recommendations = analyzer.get_recommendations()
    for key, rec in recommendations.items():
        print(f"  {key}:")
        print(f"    Issue: {rec['issue']}")
        print(f"    Action: {rec['action']}")
    
    # Recommend recovery for a failure
    print("\nRecovery recommendations:")
    for failure in analyzer.failures[:3]:
        strategy, reason = analyzer.recommend_recovery(failure)
        print(f"  {failure.task_id} ({failure.error_type}): {strategy}")
        print(f"    Reason: {reason}")
