"""Session summarization and indexing for Phase 2 of ATM.

Generates per-turn summaries and embeddings for semantic retrieval.
Stores summaries alongside session files for efficient loading.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class TurnSummary:
    """Summary of a single conversation turn."""
    turn_number: int
    timestamp: str
    summary: str  # 1-3 sentence summary
    embedding: list[float]  # 384-dim (sentence-transformers)
    importance_score: float  # 0-1 (decisions/changes weighted higher)
    full_message_id: str  # Reference to full message in session
    tokens_estimate: int  # For budget calculation
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnSummary:
        return cls(**data)


@dataclass
class SessionSummaryIndex:
    """Index of all turn summaries for a session."""
    session_id: str
    summaries: list[TurnSummary] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.metadata:
            self.metadata = {
                'version': '1.0',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'model_used': 'claude-3-5-sonnet',
                'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2',
                'embedding_dim': 384,
            }
    
    def add_summary(self, summary: TurnSummary) -> None:
        """Add a turn summary to the index."""
        self.summaries.append(summary)
        self.metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
    
    def get_summary(self, turn_number: int) -> TurnSummary | None:
        """Get summary for a specific turn."""
        for s in self.summaries:
            if s.turn_number == turn_number:
                return s
        return None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'summaries': [s.to_dict() for s in self.summaries],
            'metadata': self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionSummaryIndex:
        return cls(
            session_id=data['session_id'],
            summaries=[TurnSummary.from_dict(s) for s in data.get('summaries', [])],
            metadata=data.get('metadata', {}),
        )


def save_summary_index(
    index: SessionSummaryIndex,
    session_path: Path,
) -> Path:
    """Save summary index alongside session file.
    
    Args:
        index: SessionSummaryIndex to save
        session_path: Path to the session JSON file
    
    Returns:
        Path to the saved summary index
    
    Example:
        >>> session_path = Path('.port_sessions/agent/abc123.json')
        >>> summary_path = save_summary_index(index, session_path)
        >>> summary_path
        Path('.port_sessions/agent/abc123.summary.json')
    """
    summary_path = session_path.with_suffix('.summary.json')
    summary_path.write_text(
        json.dumps(index.to_dict(), indent=2),
        encoding='utf-8'
    )
    return summary_path


def load_summary_index(session_path: Path) -> SessionSummaryIndex | None:
    """Load summary index for a session.
    
    Args:
        session_path: Path to the session JSON file
    
    Returns:
        SessionSummaryIndex if it exists, None otherwise
    """
    summary_path = session_path.with_suffix('.summary.json')
    if not summary_path.exists():
        return None
    
    data = json.loads(summary_path.read_text(encoding='utf-8'))
    return SessionSummaryIndex.from_dict(data)


def estimate_importance_score(
    message: dict[str, Any],
    response: dict[str, Any] | None = None,
) -> float:
    """Estimate importance of a turn (0-1).
    
    Higher scores for turns with:
    - Code changes (git diffs, file edits)
    - Decisions (user choices, confirmations)
    - Errors (failures, debugging)
    - Summaries (conclusions, next steps)
    
    Args:
        message: User message dict
        response: Assistant response dict (optional)
    
    Returns:
        Importance score 0-1
    """
    score = 0.5  # Base score
    
    # Check for code-related keywords
    code_keywords = ['git', 'commit', 'diff', 'code', 'function', 'class', 'bug', 'fix']
    content = str(message.get('content', '')).lower()
    if response:
        content += ' ' + str(response.get('content', '')).lower()
    
    for keyword in code_keywords:
        if keyword in content:
            score += 0.1
    
    # Check for decision keywords
    decision_keywords = ['decide', 'choice', 'option', 'approach', 'design', 'plan']
    for keyword in decision_keywords:
        if keyword in content:
            score += 0.1
    
    # Check for error keywords
    error_keywords = ['error', 'fail', 'bug', 'issue', 'problem', 'debug']
    for keyword in error_keywords:
        if keyword in content:
            score += 0.15
    
    # Cap at 1.0
    return min(1.0, score)


def estimate_tokens_for_summary(summary: TurnSummary) -> int:
    """Estimate tokens in a summary (for budget calculation).
    
    Uses 4 chars ≈ 1 token heuristic.
    """
    text = summary.summary
    return max(1, len(text) // 4)


# Placeholder for embedding function (will be implemented in Phase 2)
def embed_text(text: str) -> list[float]:
    """Generate embedding for text.
    
    Phase 2 will implement this using sentence-transformers.
    For now, returns a dummy 384-dim vector.
    """
    # TODO: Implement with sentence-transformers
    # from sentence_transformers import SentenceTransformer
    # model = SentenceTransformer('all-MiniLM-L6-v2')
    # return model.encode(text).tolist()
    
    # Dummy implementation for testing
    np.random.seed(hash(text) % 2**32)
    return np.random.randn(384).tolist()
