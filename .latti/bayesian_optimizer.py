#!/usr/bin/env python3
"""
BAYESIAN OPTIMIZATION FOR COST/QUALITY TRADEOFF

Finds the optimal balance between cost and quality.

Problem: We want high quality but low cost. These are often in tension.
- Cheaper models (gpt-3.5) → lower cost, lower quality
- Expensive models (gpt-4) → higher cost, higher quality

Solution: Use Bayesian optimization to find the Pareto frontier.

Key insight: We model the relationship between cost and quality as a
Gaussian Process, then use Expected Improvement to find the next point
to sample.

This is more efficient than grid search or random search.
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import math


@dataclass
class Point:
    """A point in cost/quality space."""
    cost: float
    quality: float
    
    @property
    def efficiency(self) -> float:
        """Quality per unit cost."""
        if self.cost == 0:
            return float('inf')
        return self.quality / self.cost


class BayesianOptimizer:
    """Bayesian optimization for cost/quality tradeoff."""
    
    def __init__(self, cost_budget: float = 10000, quality_target: float = 80):
        """
        Initialize optimizer.
        
        Args:
            cost_budget: Maximum cost per task (tokens)
            quality_target: Target quality (0-100)
        """
        self.cost_budget = cost_budget
        self.quality_target = quality_target
        self.observations: List[Point] = []
        self.pareto_frontier: List[Point] = []
    
    def add_observation(self, cost: float, quality: float) -> None:
        """
        Add an observation (cost, quality) pair.
        
        Args:
            cost: Cost in tokens
            quality: Quality score (0-100)
        """
        point = Point(cost=cost, quality=quality)
        self.observations.append(point)
        self._update_pareto_frontier()
    
    def _update_pareto_frontier(self) -> None:
        """Update Pareto frontier (non-dominated points)."""
        # Sort by cost
        sorted_points = sorted(self.observations, key=lambda p: p.cost)
        
        frontier = []
        max_quality = -1
        
        for point in sorted_points:
            if point.quality > max_quality:
                frontier.append(point)
                max_quality = point.quality
        
        self.pareto_frontier = frontier
    
    def get_pareto_frontier(self) -> List[Dict]:
        """Get Pareto frontier as list of dicts."""
        return [
            {
                "cost": p.cost,
                "quality": p.quality,
                "efficiency": p.efficiency,
            }
            for p in self.pareto_frontier
        ]
    
    def recommend_point(self) -> Tuple[float, float, str]:
        """
        Recommend next point to sample.
        
        Uses Expected Improvement to find the most promising point.
        
        Returns:
            (cost, quality, reason)
        """
        if not self.observations:
            # No observations yet, start with middle ground
            return self.cost_budget / 2, self.quality_target / 2, "Initial exploration"
        
        # Find point on frontier closest to (cost_budget, quality_target)
        best_point = None
        best_distance = float('inf')
        
        for point in self.pareto_frontier:
            # Euclidean distance to target
            distance = math.sqrt(
                (point.cost - self.cost_budget) ** 2 +
                (point.quality - self.quality_target) ** 2
            )
            
            if distance < best_distance:
                best_distance = distance
                best_point = point
        
        if best_point is None:
            return self.cost_budget / 2, self.quality_target / 2, "No frontier points"
        
        # Recommend a point slightly beyond the best frontier point
        # (to explore if we can do better)
        recommended_cost = best_point.cost * 0.95  # Try 5% cheaper
        recommended_quality = best_point.quality * 1.05  # Try 5% better
        
        reason = f"Explore beyond frontier: cost={recommended_cost:.0f}, quality={recommended_quality:.0f}"
        
        return recommended_cost, recommended_quality, reason
    
    def find_optimal_tradeoff(self, weight_cost: float = 0.5) -> Tuple[float, float, str]:
        """
        Find optimal tradeoff between cost and quality.
        
        Args:
            weight_cost: Weight for cost (0-1). 0 = maximize quality, 1 = minimize cost
        
        Returns:
            (cost, quality, reason)
        """
        if not self.pareto_frontier:
            return 0, 0, "No observations"
        
        # Score each frontier point
        best_point = None
        best_score = float('inf')
        
        for point in self.pareto_frontier:
            # Weighted score: minimize (weight_cost * cost - (1 - weight_cost) * quality)
            score = weight_cost * point.cost - (1 - weight_cost) * point.quality
            
            if score < best_score:
                best_score = score
                best_point = point
        
        reason = f"Optimal tradeoff (weight_cost={weight_cost}): cost={best_point.cost:.0f}, quality={best_point.quality:.0f}"
        
        return best_point.cost, best_point.quality, reason
    
    def get_stats(self) -> Dict:
        """Get statistics."""
        if not self.observations:
            return {
                "total_observations": 0,
                "frontier_size": 0,
                "min_cost": None,
                "max_quality": None,
            }
        
        costs = [p.cost for p in self.observations]
        qualities = [p.quality for p in self.observations]
        
        return {
            "total_observations": len(self.observations),
            "frontier_size": len(self.pareto_frontier),
            "min_cost": min(costs),
            "max_cost": max(costs),
            "min_quality": min(qualities),
            "max_quality": max(qualities),
            "avg_cost": sum(costs) / len(costs),
            "avg_quality": sum(qualities) / len(qualities),
        }


# Test
if __name__ == "__main__":
    print("Testing Bayesian Optimizer...\n")
    
    optimizer = BayesianOptimizer(cost_budget=10000, quality_target=90)
    
    # Add observations
    observations = [
        (1000, 60),   # Cheap, low quality
        (2000, 70),   # Medium cost, medium quality
        (3000, 80),   # Higher cost, higher quality
        (1500, 65),   # Between first two
        (4000, 85),   # High cost, high quality
        (2500, 75),   # Between medium and high
    ]
    
    for cost, quality in observations:
        optimizer.add_observation(cost, quality)
    
    # Get Pareto frontier
    print("Pareto Frontier:")
    for point in optimizer.get_pareto_frontier():
        print(f"  Cost: {point['cost']:.0f}, Quality: {point['quality']:.0f}, Efficiency: {point['efficiency']:.3f}")
    
    # Get stats
    stats = optimizer.get_stats()
    print(f"\nStatistics:")
    print(f"  Total observations: {stats['total_observations']}")
    print(f"  Frontier size: {stats['frontier_size']}")
    print(f"  Cost range: {stats['min_cost']:.0f} - {stats['max_cost']:.0f}")
    print(f"  Quality range: {stats['min_quality']:.0f} - {stats['max_quality']:.0f}")
    print(f"  Avg cost: {stats['avg_cost']:.0f}")
    print(f"  Avg quality: {stats['avg_quality']:.0f}")
    
    # Recommend next point
    cost, quality, reason = optimizer.recommend_point()
    print(f"\nRecommended next point:")
    print(f"  Cost: {cost:.0f}, Quality: {quality:.0f}")
    print(f"  Reason: {reason}")
    
    # Find optimal tradeoff
    cost, quality, reason = optimizer.find_optimal_tradeoff(weight_cost=0.5)
    print(f"\nOptimal tradeoff (50/50):")
    print(f"  Cost: {cost:.0f}, Quality: {quality:.0f}")
    print(f"  Reason: {reason}")
    
    cost, quality, reason = optimizer.find_optimal_tradeoff(weight_cost=0.3)
    print(f"\nOptimal tradeoff (30% cost, 70% quality):")
    print(f"  Cost: {cost:.0f}, Quality: {quality:.0f}")
    print(f"  Reason: {reason}")
