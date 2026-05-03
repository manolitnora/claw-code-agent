#!/usr/bin/env python3
"""
MULTI-ARMED BANDIT FOR MODEL SELECTION

Uses Thompson Sampling to balance exploration vs exploitation.
Each model is an "arm" with a success rate and quality distribution.

Key insight: We don't just pick the best model; we explore alternatives
to discover if they might be better in the future.

Thompson Sampling:
1. For each arm, maintain Beta(α, β) distribution
2. Sample from each distribution
3. Pick the arm with highest sample
4. Update the distribution based on outcome

This naturally balances:
- Exploitation: pick models that have worked well
- Exploration: try models that might be better
"""

import random
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ArmStats:
    """Statistics for one model (arm)."""
    model: str
    successes: int = 0
    failures: int = 0
    total_quality: int = 0
    total_cost: int = 0
    total_outcomes: int = 0
    
    @property
    def success_rate(self) -> float:
        """Success rate (0-1)."""
        if self.total_outcomes == 0:
            return 0.5  # Neutral prior
        return self.successes / self.total_outcomes
    
    @property
    def avg_quality(self) -> float:
        """Average quality (0-100)."""
        if self.total_outcomes == 0:
            return 50  # Neutral prior
        return self.total_quality / self.total_outcomes
    
    @property
    def avg_cost(self) -> float:
        """Average cost (tokens)."""
        if self.total_outcomes == 0:
            return 0
        return self.total_cost / self.total_outcomes
    
    @property
    def cost_per_quality(self) -> float:
        """Cost efficiency (lower is better)."""
        if self.avg_quality == 0:
            return float('inf')
        return self.avg_cost / self.avg_quality


class MultiArmedBandit:
    """Thompson Sampling for model selection."""
    
    def __init__(self, models: List[str]):
        """Initialize bandit with list of models."""
        self.models = models
        self.arms: Dict[str, ArmStats] = {
            model: ArmStats(model=model)
            for model in models
        }
        self.history: List[Dict] = []
    
    def select_model(self) -> str:
        """
        Select a model using Thompson Sampling.
        
        Returns:
            Model name to use
        """
        # Sample from each arm's Beta distribution
        samples = {}
        for model in self.models:
            arm = self.arms[model]
            
            # Beta(α, β) where α = successes + 1, β = failures + 1
            alpha = arm.successes + 1
            beta = arm.failures + 1
            
            # Sample from Beta distribution
            sample = random.betavariate(alpha, beta)
            samples[model] = sample
        
        # Pick model with highest sample
        selected = max(samples, key=samples.get)
        return selected
    
    def record_outcome(
        self,
        model: str,
        success: bool,
        quality: int,
        cost: int
    ) -> None:
        """
        Record outcome of using a model.
        
        Args:
            model: Model name
            success: Whether task succeeded
            quality: Quality score (0-100)
            cost: Cost in tokens
        """
        if model not in self.arms:
            self.arms[model] = ArmStats(model=model)
        
        arm = self.arms[model]
        
        if success:
            arm.successes += 1
        else:
            arm.failures += 1
        
        arm.total_quality += quality
        arm.total_cost += cost
        arm.total_outcomes += 1
        
        # Record in history
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "success": success,
            "quality": quality,
            "cost": cost,
            "arm_stats": {
                "success_rate": arm.success_rate,
                "avg_quality": arm.avg_quality,
                "avg_cost": arm.avg_cost,
            }
        })
    
    def get_stats(self) -> Dict:
        """Get statistics for all arms."""
        return {
            model: {
                "success_rate": arm.success_rate,
                "avg_quality": arm.avg_quality,
                "avg_cost": arm.avg_cost,
                "cost_per_quality": arm.cost_per_quality,
                "successes": arm.successes,
                "failures": arm.failures,
                "total_outcomes": arm.total_outcomes,
            }
            for model, arm in self.arms.items()
        }
    
    def get_best_model(self, metric: str = "success_rate") -> Tuple[str, float]:
        """
        Get best model by metric.
        
        Args:
            metric: "success_rate", "avg_quality", or "cost_per_quality"
        
        Returns:
            (model_name, metric_value)
        """
        if metric == "success_rate":
            best = max(
                self.arms.items(),
                key=lambda x: x[1].success_rate
            )
        elif metric == "avg_quality":
            best = max(
                self.arms.items(),
                key=lambda x: x[1].avg_quality
            )
        elif metric == "cost_per_quality":
            best = min(
                self.arms.items(),
                key=lambda x: x[1].cost_per_quality
            )
        else:
            raise ValueError(f"Unknown metric: {metric}")
        
        return best[0], getattr(best[1], metric.replace("_", "_"))
    
    def recommend_switch(self, current_model: str, threshold: float = 0.1) -> Tuple[bool, str, str]:
        """
        Recommend switching to a different model if it's significantly better.
        
        Args:
            current_model: Current model in use
            threshold: Minimum improvement to recommend switch (0-1)
        
        Returns:
            (should_switch, reason, recommended_model)
        """
        if current_model not in self.arms:
            return False, "Unknown model", current_model
        
        current_arm = self.arms[current_model]
        current_success_rate = current_arm.success_rate
        
        # Find best alternative
        best_alt = None
        best_alt_rate = current_success_rate
        
        for model, arm in self.arms.items():
            if model == current_model:
                continue
            
            if arm.success_rate > best_alt_rate:
                best_alt = model
                best_alt_rate = arm.success_rate
        
        if best_alt is None:
            return False, "No better alternative", current_model
        
        improvement = best_alt_rate - current_success_rate
        
        if improvement > threshold:
            reason = f"{best_alt} has {improvement:.1%} better success rate"
            return True, reason, best_alt
        
        return False, "Improvement below threshold", current_model


# Test
if __name__ == "__main__":
    print("Testing Multi-Armed Bandit...\n")
    
    # Initialize bandit with 3 models
    bandit = MultiArmedBandit(["gpt-3.5", "gpt-4", "claude"])
    
    # Simulate outcomes
    outcomes = [
        ("gpt-3.5", True, 60, 1000),
        ("gpt-3.5", True, 65, 1100),
        ("gpt-3.5", False, 30, 900),
        ("gpt-4", True, 90, 3000),
        ("gpt-4", True, 92, 3100),
        ("claude", True, 85, 2500),
        ("claude", True, 88, 2600),
        ("gpt-3.5", True, 62, 1050),
        ("gpt-4", True, 91, 3050),
        ("claude", False, 40, 2400),
    ]
    
    for model, success, quality, cost in outcomes:
        bandit.record_outcome(model, success, quality, cost)
    
    # Get stats
    stats = bandit.get_stats()
    print("Arm Statistics:")
    for model, stat in stats.items():
        print(f"  {model}:")
        print(f"    Success rate: {stat['success_rate']:.1%}")
        print(f"    Avg quality: {stat['avg_quality']:.0f}")
        print(f"    Avg cost: {stat['avg_cost']:.0f}")
        print(f"    Cost per quality: {stat['cost_per_quality']:.2f}")
    
    # Get best model
    best_model, best_rate = bandit.get_best_model("success_rate")
    print(f"\nBest model (success rate): {best_model} ({best_rate:.1%})")
    
    # Recommend switch
    should_switch, reason, recommended = bandit.recommend_switch("gpt-3.5", threshold=0.1)
    print(f"\nSwitch from gpt-3.5? {should_switch}")
    print(f"  Reason: {reason}")
    print(f"  Recommended: {recommended}")
    
    # Select model using Thompson Sampling
    print("\nThompson Sampling selections (10 trials):")
    for i in range(10):
        selected = bandit.select_model()
        print(f"  Trial {i+1}: {selected}")
