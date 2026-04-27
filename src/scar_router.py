"""
Scar Router: Route problems to models based on past scars.

When a new problem arrives, the router searches for similar past problems
and applies their lessons to choose the best model and configuration.
"""

from __future__ import annotations

from typing import Optional
from .scar_index import ScarIndex, Scar
from .frontier_optimizations import detect_reasoning_intensity


class ScarRouter:
    """Routes problems to models based on past scars."""
    
    def __init__(self, scar_index: Optional[ScarIndex] = None):
        """Initialize the scar router.
        
        Args:
            scar_index: ScarIndex instance. If None, creates a new one.
        """
        self.scar_index = scar_index or ScarIndex()
    
    def route_problem(
        self,
        problem_description: str,
        default_intensity: Optional[str] = None,
    ) -> dict:
        """Route a problem to a model based on past scars.
        
        Args:
            problem_description: Description of the problem
            default_intensity: If no scar found, use this intensity.
                             If None, auto-detect.
        
        Returns:
            Dict with:
              - model: Recommended model
              - intensity: Problem intensity
              - scar_matched: Scar that influenced the decision (or None)
              - lesson: The lesson from the matched scar (or None)
              - reasoning: Explanation of the routing decision
        """
        # Find similar scars
        similar_scars = self.scar_index.find_similar_scars(
            problem_description,
            max_results=5,
        )
        
        # If no scars found, use default routing
        if not similar_scars:
            if default_intensity is None:
                default_intensity = detect_reasoning_intensity(problem_description)
            
            model = self._get_model_for_intensity(default_intensity)
            return {
                "model": model,
                "intensity": default_intensity,
                "scar_matched": None,
                "lesson": None,
                "reasoning": f"No similar scars found. Using default routing for {default_intensity} intensity.",
            }
        
        # Analyze scars to find the best lesson
        best_scar = self._select_best_scar(similar_scars)
        
        if best_scar is None:
            # All scars were failures; use default routing
            if default_intensity is None:
                default_intensity = detect_reasoning_intensity(problem_description)
            
            model = self._get_model_for_intensity(default_intensity)
            return {
                "model": model,
                "intensity": default_intensity,
                "scar_matched": None,
                "lesson": None,
                "reasoning": "Similar scars all failed. Using default routing.",
            }
        
        # Use the lesson from the best scar
        model = best_scar.model_used
        intensity = self._intensity_for_model(model)
        
        return {
            "model": model,
            "intensity": intensity,
            "scar_matched": best_scar.id,
            "lesson": best_scar.lesson,
            "reasoning": f"Scar {best_scar.id} shows {best_scar.model_used} succeeded on similar problem. Using it.",
        }
    
    def _select_best_scar(self, scars: list[Scar]) -> Optional[Scar]:
        """Select the best scar to learn from.
        
        Prioritizes:
        1. Successful scars (outcome == "success")
        2. Most recent
        3. Cheapest
        """
        # Filter to successful scars
        successful = [s for s in scars if s.outcome == "success"]
        
        if successful:
            # Sort by timestamp (most recent first)
            successful.sort(key=lambda s: s.timestamp, reverse=True)
            return successful[0]
        
        # If no successful scars, return None (use default routing)
        return None
    
    def _get_model_for_intensity(self, intensity: str) -> str:
        """Get the model for a given intensity level."""
        mapping = {
            "trivial": "claude-sonnet-4.6",
            "standard": "claude-sonnet-4.6",
            "hard": "openai/o1",
            "research": "openai/o3-mini",
        }
        return mapping.get(intensity, "claude-sonnet-4.6")
    
    def _intensity_for_model(self, model: str) -> str:
        """Get the intensity level for a given model."""
        if "o1" in model or "o3" in model:
            return "hard"
        return "standard"
    
    def record_outcome(
        self,
        problem_description: str,
        model_used: str,
        cost: float,
        outcome: str,
        session_id: str,
        reasoning_tokens: int = 0,
    ) -> Scar:
        """Record the outcome of a problem as a scar.
        
        Args:
            problem_description: What was the problem?
            model_used: Which model was used?
            cost: Cost in dollars
            outcome: "success", "failure", or "partial"
            session_id: Which session created this scar
            reasoning_tokens: If extended thinking was used
            
        Returns:
            The created Scar
        """
        # Generate lesson based on outcome
        if outcome == "success":
            lesson = f"{model_used} succeeded on this type of problem."
        elif outcome == "failure":
            lesson = f"{model_used} failed on this type of problem. Try a more capable model."
        else:
            lesson = f"{model_used} partially solved this. May need extended thinking."
        
        return self.scar_index.record_scar(
            problem_description=problem_description,
            model_used=model_used,
            cost=cost,
            outcome=outcome,
            lesson=lesson,
            session_id=session_id,
            reasoning_tokens=reasoning_tokens,
        )
