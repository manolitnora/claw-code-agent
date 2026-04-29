"""Concrete Controller implementations for the state machine.

Step 5 of the runway in ``~/.latti/STATE_MACHINE.md``: Controllers pick the
next Action given a State. Rule-based controllers fire on known-shape
transitions (cheap, deterministic). LLM-based controllers handle ambiguity
(expensive, non-deterministic). Compose via ``FallbackController`` so the
rule path is tried first and the LLM is reached only when no rule matched.

A Controller returns a typed ``PolicyDecision`` (not a bare Action) so the
runner records rationale + decided_by metadata with every choice.
"""
from __future__ import annotations

from typing import Callable

from src.agent_state_machine import (
    Action,
    Controller,
    Goal,
    PolicyDecision,
    State,
)


# Type alias: a rule is (predicate, action_factory).
# - predicate(state, goal) → bool: should this rule fire?
# - action_factory(state, goal) → Action | None: what Action does it propose?
Predicate = Callable[[State, 'Goal | None'], bool]
ActionFactory = Callable[[State, 'Goal | None'], 'Action | None']
Rule = tuple[Predicate, ActionFactory, str]  # last element is the rule's name


class RuleBasedController:
    """Picks the first rule whose predicate fires.

    Rules are tuples ``(predicate, action_factory, rule_name)``. The first
    rule whose predicate returns True is used to build the Action. The
    resulting PolicyDecision carries ``decided_by='rule'`` and the rule's
    name as the rationale.

    If no predicate matches, returns ``None`` so a fallback Controller can
    take over.
    """

    def __init__(self, rules: list[Rule], name: str = 'rule_based') -> None:
        self._rules: tuple[Rule, ...] = tuple(rules)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def pick(self, state: State, goal: Goal | None = None) -> PolicyDecision | None:
        for predicate, factory, rule_name in self._rules:
            try:
                fires = predicate(state, goal)
            except Exception:
                # A misbehaving rule should not break the controller chain.
                continue
            if not fires:
                continue
            try:
                action = factory(state, goal)
            except Exception:
                continue
            if action is None:
                continue
            return PolicyDecision(
                at_state_turn_id=state.turn_id,
                chose=action,
                rationale=f'rule_fired: {rule_name}',
                decided_by='rule',
                confidence=1.0,
            )
        return None


class FixedActionController:
    """Always emits the same Action. Useful for tests and trivial loops."""

    def __init__(self, action: Action, name: str = 'fixed_action') -> None:
        self._action = action
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def pick(self, state: State, goal: Goal | None = None) -> PolicyDecision | None:
        return PolicyDecision(
            at_state_turn_id=state.turn_id,
            chose=self._action,
            rationale=f'fixed: {self._name}',
            decided_by='rule',
            confidence=1.0,
        )


class FallbackController:
    """Tries primary; if primary returns None, tries fallback.

    The classic "rules first, LLM second" composition: pass a
    RuleBasedController as primary and an LLM-driven Controller as fallback.
    The fallback's PolicyDecision will carry ``decided_by`` from whichever
    Controller produced it.
    """

    def __init__(
        self,
        primary: Controller,
        fallback: Controller,
        name: str = 'fallback',
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def pick(self, state: State, goal: Goal | None = None) -> PolicyDecision | None:
        decision = self._primary.pick(state, goal)
        if decision is not None:
            return decision
        return self._fallback.pick(state, goal)


class HaltController:
    """Always returns None — signals the loop to halt.

    Useful as the terminal element of a fallback chain when the design says
    "if no rule fires AND no LLM is available, just stop."
    """

    @property
    def name(self) -> str:
        return 'halt'

    def pick(self, state: State, goal: Goal | None = None) -> PolicyDecision | None:
        return None
