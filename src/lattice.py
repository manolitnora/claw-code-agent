"""Lattice — a self-improving computation that nests inside other lattices.

A Lattice has:
  - dimensions: what it measures
  - cost_fn: how far from good
  - detectors: what patterns to catch
  - solve(): Monte Carlo to find the minimum
  - sublattices: lattices inside this lattice

The operations:
  - meet: what's shared between two lattice states (intersection)
  - join: what emerges from combining two lattice states (union)
  - feedback: inner lattice output changes outer lattice cost function

A Lattice inside a Lattice inherits the algorithm but has its own dimensions.
The solver at every level is the same solve(). The domain is the plug.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .lattice_solver import solve, SolveResult


@dataclass
class LatticeState:
    """A point in the lattice — scores across all dimensions."""
    scores: dict[str, float]
    cost: float
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def meet(self, other: 'LatticeState') -> 'LatticeState':
        """What's shared — minimum of each dimension (intersection)."""
        shared = {k: min(self.scores.get(k, 0), other.scores.get(k, 0))
                  for k in set(self.scores) | set(other.scores)}
        return LatticeState(
            scores=shared,
            cost=sum((1 - v) ** 2 for v in shared.values()),
            timestamp=time.time(),
        )

    def join(self, other: 'LatticeState') -> 'LatticeState':
        """What emerges — maximum of each dimension (union)."""
        merged = {k: max(self.scores.get(k, 0), other.scores.get(k, 0))
                  for k in set(self.scores) | set(other.scores)}
        return LatticeState(
            scores=merged,
            cost=sum((1 - v) ** 2 for v in merged.values()),
            timestamp=time.time(),
        )


Detector = Callable[[str], float]  # input → score (0.0 bad, 1.0 good)
Probe = Callable[[], str]          # () → response text


@dataclass
class Lattice:
    """A self-improving computation that nests inside other lattices."""

    name: str
    dimensions: list[str]
    detectors: dict[str, Detector]
    probes: dict[str, Probe]
    sublattices: list['Lattice'] = field(default_factory=list)
    history: list[LatticeState] = field(default_factory=list)
    corrections: list[dict[str, str]] = field(default_factory=list)

    def measure(self) -> LatticeState:
        """Probe all dimensions and return current state."""
        scores = {}
        for dim in self.dimensions:
            probe = self.probes.get(dim)
            detector = self.detectors.get(dim)
            if probe and detector:
                response = probe()
                scores[dim] = detector(response)
            else:
                scores[dim] = 0.0

        state = LatticeState(
            scores=scores,
            cost=sum((1 - v) ** 2 for v in scores.values()),
            timestamp=time.time(),
        )
        self.history.append(state)
        return state

    def optimize(self, rounds: int = 5) -> LatticeState:
        """Run the optimization loop: measure → find weakest → correct → repeat."""
        for r in range(rounds):
            state = self.measure()

            # Find weakest dimension
            if not state.scores:
                break
            weakest = min(state.scores, key=state.scores.get)

            if state.scores[weakest] >= 0.9:
                break  # all dimensions good enough

            # Generate correction for weakest dimension
            correction = {
                "dimension": weakest,
                "score": state.scores[weakest],
                "round": r + 1,
            }
            self.corrections.append(correction)

            # Propagate to sublattices
            for sub in self.sublattices:
                if weakest in sub.dimensions:
                    sub.optimize(rounds=1)

        return self.history[-1] if self.history else LatticeState(scores={}, cost=float('inf'))

    def feedback(self, child_state: LatticeState) -> None:
        """Receive feedback from a sublattice — its output changes our cost landscape."""
        if not self.history:
            return
        current = self.history[-1]
        # Join: child's improvements propagate upward
        improved = current.join(child_state)
        self.history.append(improved)

    def add_sublattice(self, child: 'Lattice') -> None:
        """Nest a lattice inside this one."""
        self.sublattices.append(child)

    def status(self, indent: int = 0) -> str:
        """Show the lattice state, recursively."""
        prefix = "  " * indent
        lines = [f"{prefix}Lattice: {self.name}"]
        if self.history:
            last = self.history[-1]
            for dim in self.dimensions:
                s = last.scores.get(dim, 0)
                bar = "█" * int(s * 10) + "░" * (10 - int(s * 10))
                lines.append(f"{prefix}  {dim:20} {bar} {s:.2f}")
            lines.append(f"{prefix}  cost: {last.cost:.4f}")
        else:
            lines.append(f"{prefix}  (not measured)")
        lines.append(f"{prefix}  corrections: {len(self.corrections)}")
        lines.append(f"{prefix}  history: {len(self.history)} states")

        for sub in self.sublattices:
            lines.append(sub.status(indent + 1))

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dimensions": self.dimensions,
            "corrections": self.corrections,
            "history": [
                {"scores": s.scores, "cost": s.cost, "timestamp": s.timestamp}
                for s in self.history[-10:]  # last 10 states
            ],
            "sublattices": [s.to_dict() for s in self.sublattices],
        }


# ═══════════════════════════════════════════════════
# Factory: build the Latti stack as nested lattices
# ═══════════════════════════════════════════════════

def build_latti_stack() -> Lattice:
    """Build the full Latti lattice stack.

    Meta-lattice
      └── Behavioral lattice
           └── Precision lattice (sublattice of behavioral)
    """

    # Precision sublattice — the surgeon
    precision = Lattice(
        name="precision",
        dimensions=["brevity", "no_filler", "no_trailing_q", "no_narration"],
        detectors={},  # wired at runtime
        probes={},     # wired at runtime
    )

    # Behavioral lattice — the full behavioral space
    behavioral = Lattice(
        name="behavioral",
        dimensions=["sycophancy", "performance", "precision", "grounding", "honesty", "self_awareness"],
        detectors={},
        probes={},
        sublattices=[precision],
    )

    # Meta lattice — the stack itself
    meta = Lattice(
        name="meta",
        dimensions=["correction_coverage", "convergence_rate", "regression_stability"],
        detectors={},
        probes={},
        sublattices=[behavioral],
    )

    return meta
