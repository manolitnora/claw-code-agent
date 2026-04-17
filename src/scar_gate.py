"""Behavioral Scar Gate — geometric pattern matching against past failures.
Adapted from NBA scar-schema.ts (S113) into behavioral space.
"""
from __future__ import annotations
import json, math, os
from dataclasses import dataclass, field
from pathlib import Path

SCARS_PATH = Path(os.path.expanduser("~/.latti/scars.json"))


def _has(text: str, phrases: list[str]) -> float:
    return 1.0 if any(p in text for p in phrases) else 0.0


def extract_features(prompt: str, response: str = "") -> dict[str, float]:
    """Extract behavioral features from the current situation."""
    r, p = response.lower(), prompt.lower()
    return {
        "asks_whats_next": _has(r, ["what would you", "what's next", "your call", "standing by", "would you like me to", "anything else"]),
        "verbose_response": min(1.0, len(r.split()) / 500) if response else 0.0,
        "identity_question": _has(p, ["who are you", "what are you", "tell me about yourself"]),
        "claims_computation": _has(r, ["when i computed", "i found that", "my analysis shows", "i measured", "when i ran"]),
        "uses_filler": _has(r, ["great question", "certainly", "i'd be happy to", "absolutely", "that's a great", "fascinating"]),
        "hedging": _has(r, ["your call", "up to you", "if you'd like", "we could"]),
        "narrating_actions": _has(r, ["let me", "i'll now", "i'm going to", "let me check"]),
        "trailing_question": 1.0 if response.strip().endswith("?") else 0.0,
        "ungrounded_vision": 1.0 if (_has(r, ["i envision", "imagine a world", "the future where"]) and not _has(r, ["i have", "i built", "exists", "currently"])) else 0.0,
        "borrowed_vocabulary": _has(r, ["the gradient knows", "which wolf", "the membrane", "pheromone", "the hand grips"]),
    }


@dataclass
class BehaviorScar:
    id: str
    lesson: str
    severity: float  # 0-1
    features: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "lesson": self.lesson, "severity": self.severity, "features": self.features}

    @classmethod
    def from_dict(cls, d: dict) -> BehaviorScar:
        return cls(id=d["id"], lesson=d["lesson"], severity=d.get("severity", 0.5), features=d.get("features", {}))


def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def scar_distance(features: dict[str, float], scar: BehaviorScar) -> float:
    """Weighted euclidean distance. Higher severity = larger scar shadow."""
    keys = sorted(set(list(features.keys()) + list(scar.features.keys())))
    a = [features.get(k, 0.0) for k in keys]
    b = [scar.features.get(k, 0.0) for k in keys]
    raw = _euclidean(a, b)
    return raw / (1.0 + scar.severity)

BLOCK_THRESHOLD = 0.15
WARN_THRESHOLD = 0.35


def check_scar_gate(features: dict[str, float], scars: list[BehaviorScar] | None = None) -> tuple[str, BehaviorScar | None, float]:
    """Returns (action, nearest_scar, distance). action: 'allow'|'warn'|'block'."""
    if scars is None:
        scars = load_scars()
    if not scars:
        return ("allow", None, float("inf"))
    min_dist, nearest = float("inf"), None
    for scar in scars:
        d = scar_distance(features, scar)
        if d < min_dist:
            min_dist, nearest = d, scar
    if min_dist < BLOCK_THRESHOLD:
        return ("block", nearest, min_dist)
    if min_dist < WARN_THRESHOLD:
        return ("warn", nearest, min_dist)
    return ("allow", nearest, min_dist)


def load_scars() -> list[BehaviorScar]:
    if not SCARS_PATH.exists():
        return []
    try:
        data = json.loads(SCARS_PATH.read_text())
        return [BehaviorScar.from_dict(s) for s in data]
    except Exception:
        return []


def save_scars(scars: list[BehaviorScar]) -> None:
    SCARS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCARS_PATH.write_text(json.dumps([s.to_dict() for s in scars], indent=2))


def add_scar(scar_id: str, lesson: str, severity: float, features: dict[str, float]) -> None:
    """Add a new scar (or update existing by id)."""
    scars = load_scars()
    existing = {s.id: i for i, s in enumerate(scars)}
    new = BehaviorScar(id=scar_id, lesson=lesson, severity=severity, features=features)
    if scar_id in existing:
        scars[existing[scar_id]] = new
    else:
        scars.append(new)
    save_scars(scars)
