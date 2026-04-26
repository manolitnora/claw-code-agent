"""Comprehensive tests for Adaptive Tiered Memory (ATM) system.

Tests all 4 phases:
- Phase 1: Prompt Caching
- Phase 2: Hierarchical Summaries
- Phase 3: Adaptive Tiering
- Phase 4: Lazy Expansion
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.memory_expansion import (
    ExpansionTracker,
    detect_expansion_request,
    extract_turn_references,
    should_expand_memory,
)
from src.memory_retrieval import (
    QueryType,
    RetrievalBudget,
    classify_query,
    cosine_similarity,
    retrieve_context,
)
from src.prompt_cache import CacheStats, extract_cache_stats, wrap_system_prompt_for_caching
from src.session_summary import (
    SessionSummaryIndex,
    TurnSummary,
    estimate_importance_score,
    load_summary_index,
    save_summary_index,
)


# ============================================================================
# Phase 1: Prompt Caching Tests
# ============================================================================


class TestPromptCaching:
    """Tests for Phase 1: Prompt Caching."""

    def test_wrap_system_prompt_for_caching(self):
        """Test wrapping system prompt with cache_control."""
        prompt = "You are a helpful assistant."
        blocks = wrap_system_prompt_for_caching(prompt)
        
        assert len(blocks) == 1
        assert blocks[0]['type'] == 'text'
        assert blocks[0]['text'] == prompt
        assert blocks[0]['cache_control'] == {'type': 'ephemeral'}

    def test_cache_stats_calculation(self):
        """Test cache statistics calculation."""
        stats = CacheStats(
            cache_creation_tokens=1000,
            cache_read_tokens=5000,
            regular_input_tokens=2000,
        )
        
        assert stats.total_input_tokens == 8000
        assert stats.cache_hit_rate == pytest.approx(5000 / 8000)
        assert stats.cache_savings_usd() > 0

    def test_extract_cache_stats_from_usage(self):
        """Test extracting cache stats from API response."""
        usage = MagicMock()
        usage.cache_creation_input_tokens = 1000
        usage.cache_read_input_tokens = 5000
        usage.input_tokens = 2000
        
        stats = extract_cache_stats(usage)
        
        assert stats.cache_creation_tokens == 1000
        assert stats.cache_read_tokens == 5000
        assert stats.regular_input_tokens == 2000

    def test_cache_hit_rate_zero(self):
        """Test cache hit rate when no cache reads."""
        stats = CacheStats(
            cache_creation_tokens=0,
            cache_read_tokens=0,
            regular_input_tokens=1000,
        )
        
        assert stats.cache_hit_rate == 0.0

    def test_cache_savings_calculation(self):
        """Test USD savings calculation."""
        stats = CacheStats(
            cache_creation_tokens=0,
            cache_read_tokens=1_000_000,  # 1M tokens
            regular_input_tokens=0,
        )
        
        # Cache reads cost 90% less
        # rate_per_mtok = $0.0003 per million tokens
        # Regular cost per token: $0.0003 / 1_000_000 = $0.0000003
        # Cache cost per token: $0.0000003 * 0.1 = $0.00000003
        # Savings per token: $0.0000003 - $0.00000003 = $0.00000027
        # Savings for 1M tokens: $0.00000027 * 1_000_000 / 1_000_000 = $0.00027
        savings = stats.cache_savings_usd(rate_per_mtok=0.0003)
        assert savings == pytest.approx(0.00027, rel=0.01)


# ============================================================================
# Phase 2: Hierarchical Summaries Tests
# ============================================================================


class TestHierarchicalSummaries:
    """Tests for Phase 2: Hierarchical Summaries."""

    def test_turn_summary_creation(self):
        """Test creating a turn summary."""
        summary = TurnSummary(
            turn_number=1,
            timestamp="2026-04-27T00:00:00Z",
            summary="Fixed TUI footer bug by truncating status line.",
            embedding=[0.1] * 384,
            importance_score=0.8,
            full_message_id="msg_123",
            tokens_estimate=50,
        )
        
        assert summary.turn_number == 1
        assert len(summary.embedding) == 384
        assert summary.importance_score == 0.8

    def test_session_summary_index_creation(self):
        """Test creating a session summary index."""
        index = SessionSummaryIndex(session_id="abc123")
        
        assert index.session_id == "abc123"
        assert len(index.summaries) == 0
        assert 'version' in index.metadata

    def test_add_summary_to_index(self):
        """Test adding summaries to index."""
        index = SessionSummaryIndex(session_id="abc123")
        summary = TurnSummary(
            turn_number=1,
            timestamp="2026-04-27T00:00:00Z",
            summary="Test summary",
            embedding=[0.1] * 384,
            importance_score=0.5,
            full_message_id="msg_1",
            tokens_estimate=50,
        )
        
        index.add_summary(summary)
        
        assert len(index.summaries) == 1
        assert index.get_summary(1) == summary

    def test_save_and_load_summary_index(self, tmp_path):
        """Test saving and loading summary index."""
        session_path = tmp_path / "session.json"
        session_path.write_text("{}")  # Create dummy session file
        
        index = SessionSummaryIndex(session_id="abc123")
        summary = TurnSummary(
            turn_number=1,
            timestamp="2026-04-27T00:00:00Z",
            summary="Test summary",
            embedding=[0.1] * 384,
            importance_score=0.5,
            full_message_id="msg_1",
            tokens_estimate=50,
        )
        index.add_summary(summary)
        
        # Save
        save_summary_index(index, session_path)
        
        # Load
        loaded = load_summary_index(session_path)
        
        assert loaded is not None
        assert loaded.session_id == "abc123"
        assert len(loaded.summaries) == 1
        assert loaded.summaries[0].turn_number == 1

    def test_estimate_importance_score(self):
        """Test importance score estimation."""
        # Code-related message should have higher importance
        msg_code = {'content': 'git commit -m "fix: bug"'}
        score_code = estimate_importance_score(msg_code)
        
        # Generic message should have lower importance
        msg_generic = {'content': 'hello'}
        score_generic = estimate_importance_score(msg_generic)
        
        assert score_code > score_generic

    def test_importance_score_bounds(self):
        """Test that importance scores are bounded 0-1."""
        msg = {'content': 'git commit fix bug error issue problem'}
        score = estimate_importance_score(msg)
        
        assert 0.0 <= score <= 1.0


# ============================================================================
# Phase 3: Adaptive Tiering Tests
# ============================================================================


class TestAdaptiveTiering:
    """Tests for Phase 3: Adaptive Tiering."""

    def test_query_classification_factual(self):
        """Test classifying factual queries."""
        query = "What did we do on turn 42?"
        query_type = classify_query(query)
        
        assert query_type == QueryType.FACTUAL

    def test_query_classification_code_review(self):
        """Test classifying code review queries."""
        query = "Show me the code we wrote for the TUI."
        query_type = classify_query(query)
        
        assert query_type == QueryType.CODE_REVIEW

    def test_query_classification_debugging(self):
        """Test classifying debugging queries."""
        query = "What error did we encounter?"
        query_type = classify_query(query)
        
        assert query_type == QueryType.DEBUGGING

    def test_query_classification_planning(self):
        """Test classifying planning queries."""
        query = "What should we do next?"
        query_type = classify_query(query)
        
        assert query_type == QueryType.PLANNING

    def test_query_classification_reasoning(self):
        """Test classifying reasoning queries."""
        query = "Why did we choose this approach?"
        query_type = classify_query(query)
        
        assert query_type == QueryType.REASONING

    def test_cosine_similarity(self):
        """Test cosine similarity calculation."""
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        
        sim = cosine_similarity(a, b)
        assert sim == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        """Test cosine similarity for orthogonal vectors."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        
        sim = cosine_similarity(a, b)
        assert sim == pytest.approx(0.0, abs=1e-6)

    def test_retrieval_budget_allocation(self):
        """Test token budget allocation across tiers."""
        budget = RetrievalBudget(total_tokens=10000)
        
        assert budget.tier1_budget == 1000
        assert budget.tier2_budget == 7000
        assert budget.tier3_budget == 2000
        assert budget.tier1_budget + budget.tier2_budget + budget.tier3_budget == 10000

    def test_retrieve_context_with_summaries(self):
        """Test retrieving context with summaries."""
        # Create summary index
        index = SessionSummaryIndex(session_id="abc123")
        for i in range(5):
            summary = TurnSummary(
                turn_number=i,
                timestamp="2026-04-27T00:00:00Z",
                summary=f"Turn {i} summary",
                embedding=[0.1 * (i + 1)] * 384,
                importance_score=0.5,
                full_message_id=f"msg_{i}",
                tokens_estimate=50,
            )
            index.add_summary(summary)
        
        # Retrieve context
        query = "What did we do?"
        query_embedding = [0.1] * 384
        recent_messages = [{'role': 'user', 'content': f'msg {i}'} for i in range(3)]
        
        context, tokens_used = retrieve_context(
            query=query,
            query_embedding=query_embedding,
            summary_index=index,
            recent_messages=recent_messages,
        )
        
        assert len(context) > 0
        assert tokens_used > 0

    def test_retrieve_context_respects_budget(self):
        """Test that retrieval respects token budget."""
        budget = RetrievalBudget(total_tokens=100)
        
        # Create many summaries
        index = SessionSummaryIndex(session_id="abc123")
        for i in range(100):
            summary = TurnSummary(
                turn_number=i,
                timestamp="2026-04-27T00:00:00Z",
                summary=f"Turn {i} summary",
                embedding=[0.1] * 384,
                importance_score=0.5,
                full_message_id=f"msg_{i}",
                tokens_estimate=50,
            )
            index.add_summary(summary)
        
        query = "What did we do?"
        query_embedding = [0.1] * 384
        recent_messages = []
        
        context, tokens_used = retrieve_context(
            query=query,
            query_embedding=query_embedding,
            summary_index=index,
            recent_messages=recent_messages,
            budget=budget,
        )
        
        # Should not exceed budget
        assert tokens_used <= budget.total_tokens


# ============================================================================
# Phase 4: Lazy Expansion Tests
# ============================================================================


class TestLazyExpansion:
    """Tests for Phase 4: Lazy Expansion."""

    def test_detect_expansion_request_show_me(self):
        """Test detecting 'show me' expansion requests."""
        response = "Can you show me the full code?"
        is_request, reason = detect_expansion_request(response)
        
        assert is_request is True
        assert "full" in reason.lower()

    def test_detect_expansion_request_expand(self):
        """Test detecting 'expand' expansion requests."""
        response = "Can you expand on that?"
        is_request, reason = detect_expansion_request(response)
        
        assert is_request is True

    def test_detect_expansion_request_no_request(self):
        """Test when there's no expansion request."""
        response = "That looks good to me."
        is_request, reason = detect_expansion_request(response)
        
        assert is_request is False

    def test_extract_turn_references(self):
        """Test extracting turn numbers from response."""
        response = "On turn 42, we fixed the bug. Then on turn 45, we tested it."
        turns = extract_turn_references(response)
        
        assert 42 in turns
        assert 45 in turns

    def test_extract_turn_references_range(self):
        """Test extracting turn ranges."""
        response = "We worked on turns 40-45."
        turns = extract_turn_references(response)
        
        assert 40 in turns
        assert 42 in turns
        assert 45 in turns

    def test_expansion_tracker_creation(self):
        """Test creating an expansion tracker."""
        tracker = ExpansionTracker(session_id="abc123")
        
        assert tracker.session_id == "abc123"
        assert tracker.total_expansions == 0
        assert tracker.total_tokens_saved == 0

    def test_expansion_tracker_record(self):
        """Test recording expansions."""
        tracker = ExpansionTracker(session_id="abc123")
        
        tracker.record_expansion(
            turn_number=1,
            query="Show me the code",
            expanded_turns=[42, 43],
            reason="User asked for full context",
            tokens_saved=500,
        )
        
        assert tracker.total_expansions == 1
        assert tracker.total_tokens_saved == 500

    def test_should_expand_memory_limit(self):
        """Test that expansion is limited."""
        tracker = ExpansionTracker(session_id="abc123")
        
        # Record max expansions
        for i in range(5):
            tracker.record_expansion(
                turn_number=i,
                query="Show me",
                expanded_turns=[i],
                reason="Test",
                tokens_saved=100,
            )
        
        # Next expansion should be rejected
        response = "Can you show me more?"
        should_expand = should_expand_memory(response, tracker, max_expansions_per_session=5)
        
        assert should_expand is False

    def test_expansion_rate_calculation(self):
        """Test expansion rate calculation."""
        tracker = ExpansionTracker(session_id="abc123")
        
        tracker.record_expansion(
            turn_number=10,
            query="Show me",
            expanded_turns=[5],
            reason="Test",
            tokens_saved=100,
        )
        
        rate = tracker.get_expansion_rate()
        assert rate == pytest.approx(1 / 10)


# ============================================================================
# Integration Tests
# ============================================================================


class TestATMIntegration:
    """Integration tests for the full ATM system."""

    def test_end_to_end_retrieval_pipeline(self, tmp_path):
        """Test end-to-end retrieval pipeline."""
        # Create session with summaries
        session_path = tmp_path / "session.json"
        session_path.write_text("{}")
        
        index = SessionSummaryIndex(session_id="abc123")
        for i in range(10):
            summary = TurnSummary(
                turn_number=i,
                timestamp="2026-04-27T00:00:00Z",
                summary=f"Turn {i}: Fixed bug in module {i % 3}",
                embedding=[0.1 * (i + 1)] * 384,
                importance_score=0.5 + (i % 3) * 0.1,
                full_message_id=f"msg_{i}",
                tokens_estimate=50,
            )
            index.add_summary(summary)
        
        # Save summaries
        save_summary_index(index, session_path)
        
        # Load and retrieve
        loaded_index = load_summary_index(session_path)
        assert loaded_index is not None
        
        query = "What bugs did we fix?"
        query_embedding = [0.1] * 384
        context, tokens = retrieve_context(
            query=query,
            query_embedding=query_embedding,
            summary_index=loaded_index,
            recent_messages=[],
        )
        
        assert len(context) > 0
        assert tokens > 0

    def test_cache_and_retrieval_combined(self):
        """Test combining caching and retrieval."""
        # Create cache
        system_prompt = "You are a helpful assistant."
        cached_blocks = wrap_system_prompt_for_caching(system_prompt)
        
        # Create retrieval context
        index = SessionSummaryIndex(session_id="abc123")
        summary = TurnSummary(
            turn_number=1,
            timestamp="2026-04-27T00:00:00Z",
            summary="Test summary",
            embedding=[0.1] * 384,
            importance_score=0.5,
            full_message_id="msg_1",
            tokens_estimate=50,
        )
        index.add_summary(summary)
        
        # Verify both work together
        assert len(cached_blocks) == 1
        assert len(index.summaries) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
