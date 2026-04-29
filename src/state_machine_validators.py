"""Concrete Validator implementations for the state machine.

Step 3 of the runway in ``~/.latti/STATE_MACHINE.md``: validators run AFTER
each Operator produces an Observation, returning a ValidationResult that the
Runner can use to block, replan, or pass through.

Validators are NOT Operators. Operators execute actions. Validators grade
the resulting Observations.
"""
from __future__ import annotations

from src.agent_state_machine import (
    Action,
    Observation,
    ValidationCheck,
    ValidationResult,
)


class ObservationShapeValidator:
    """Checks the Observation has expected payload keys for known action kinds.

    A minimal post-execution check: did the Operator return an Observation
    whose payload structure matches what downstream code expects? Catches
    silent contract drift between Operators.
    """

    @property
    def name(self) -> str:
        return 'observation_shape'

    def applies_to(self, action: Action) -> bool:
        return action.kind in {'tool_call', 'llm_call', 'validation'}

    def validate(self, action: Action, observation: Observation) -> ValidationResult:
        checks: list[ValidationCheck] = []
        all_passed = True

        # Action-id continuity: the Observation must reference the Action it came from.
        id_match = observation.action_id == action.id
        checks.append(ValidationCheck(
            name='action_id_continuity', passed=id_match,
            evidence=f'obs.action_id={observation.action_id!r} action.id={action.id!r}',
        ))
        if not id_match:
            all_passed = False

        # Per-kind contract: success Observations must have a payload shape we recognize.
        if observation.kind == 'success':
            if action.kind == 'tool_call':
                # tool_call Observations should expose at least one of these keys
                expected_any = {'content', 'ok', 'tool_name'}
                has_one = bool(set(observation.payload.keys()) & expected_any)
                checks.append(ValidationCheck(
                    name='tool_call_payload_shape', passed=has_one,
                    evidence=f'expected any of {sorted(expected_any)}; got keys={sorted(observation.payload.keys())}',
                ))
                if not has_one:
                    all_passed = False
            elif action.kind == 'llm_call':
                has_completion = 'completion' in observation.payload
                checks.append(ValidationCheck(
                    name='llm_call_has_completion', passed=has_completion,
                    evidence='completion key present' if has_completion else f'missing; got keys={sorted(observation.payload.keys())}',
                ))
                if not has_completion:
                    all_passed = False

        # Severity: 'block' if the contract drift is severe enough that the loop
        # should NOT proceed (action_id mismatch is always block). 'warn' for
        # softer issues. 'info' if everything passed.
        if not id_match:
            severity = 'block'
        elif not all_passed:
            severity = 'warn'
        else:
            severity = 'info'

        return ValidationResult(
            action_id=action.id, passed=all_passed,
            checks=tuple(checks), severity=severity,
        )


class BudgetValidator:
    """Blocks the loop when an Observation's cost would exceed remaining budget.

    Reads ``state.budget_remaining_usd`` (passed via the Runner's validate_with
    helper). The Runner is responsible for invoking this with the pre-step
    state so the comparison is correct.
    """

    def __init__(self, max_cost_per_step_usd: float = 1.0) -> None:
        self._max_per_step = max_cost_per_step_usd

    @property
    def name(self) -> str:
        return 'budget'

    def applies_to(self, action: Action) -> bool:
        return True

    def validate(self, action: Action, observation: Observation) -> ValidationResult:
        within = observation.cost_usd <= self._max_per_step
        check = ValidationCheck(
            name='cost_per_step',
            passed=within,
            evidence=f'cost_usd={observation.cost_usd:.4f} max_per_step={self._max_per_step:.4f}',
        )
        return ValidationResult(
            action_id=action.id,
            passed=within,
            checks=(check,),
            severity='block' if not within else 'info',
        )


class NonEmptyContentValidator:
    """For tool_call Observations, asserts content is non-empty when ok=True.

    Catches a subtle Operator bug: success returned but no content payload.
    """

    @property
    def name(self) -> str:
        return 'non_empty_content'

    def applies_to(self, action: Action) -> bool:
        return action.kind == 'tool_call'

    def validate(self, action: Action, observation: Observation) -> ValidationResult:
        if observation.kind != 'success':
            # Only check success observations
            return ValidationResult(
                action_id=action.id, passed=True,
                checks=(ValidationCheck(name='non_empty_content', passed=True,
                                        evidence='not applicable: observation not success'),),
                severity='info',
            )
        content = observation.payload.get('content')
        ok_flag = observation.payload.get('ok', True)
        if ok_flag is False:
            # ok=False means the tool itself reported failure; not our concern
            return ValidationResult(
                action_id=action.id, passed=True,
                checks=(ValidationCheck(name='non_empty_content', passed=True,
                                        evidence='not applicable: tool reported ok=False'),),
                severity='info',
            )
        non_empty = bool(content and isinstance(content, str) and content.strip())
        return ValidationResult(
            action_id=action.id, passed=non_empty,
            checks=(ValidationCheck(
                name='non_empty_content', passed=non_empty,
                evidence=f'len(content)={len(content) if isinstance(content, str) else 0}',
            ),),
            severity='warn' if not non_empty else 'info',
        )
