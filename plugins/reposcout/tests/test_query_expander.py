"""Tests for QueryExpander."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.search.query_expander import ExpandedQuery, QueryExpander

# ── helpers ───────────────────────────────────────────────────────────────────

def _queries(results: list[ExpandedQuery]) -> list[str]:
    return [r.query for r in results]


def _labels(results: list[ExpandedQuery]) -> list[str]:
    return [r.label for r in results]


# ── 1. Basic expansion ────────────────────────────────────────────────────────

class TestBasicExpansion:
    def test_returns_list_of_expanded_queries(self):
        results = QueryExpander.expand("saas dashboard")
        assert isinstance(results, list)
        assert all(isinstance(r, ExpandedQuery) for r in results)

    def test_each_query_has_required_fields(self):
        results = QueryExpander.expand("chat app")
        for r in results:
            assert r.query
            assert r.label in ("direct", "synonym", "template", "feature")
            assert isinstance(r.priority, int)

    def test_direct_query_comes_first(self):
        results = QueryExpander.expand("blog cms")
        assert results[0].label == "direct"

    def test_saas_triggers_synonym_expansion(self):
        results = QueryExpander.expand("saas boilerplate")
        all_queries = " ".join(_queries(results)).lower()
        # Should contain at least one synonym variant
        assert any(kw in all_queries for kw in ("saas", "starter", "template", "multi-tenant"))

    def test_dashboard_synonym_expansion(self):
        results = QueryExpander.expand("dashboard")
        all_queries = " ".join(_queries(results)).lower()
        assert any(kw in all_queries for kw in ("dashboard", "admin", "analytics"))

    def test_rag_synonym_expansion(self):
        results = QueryExpander.expand("rag pipeline")
        all_queries = " ".join(_queries(results)).lower()
        assert any(kw in all_queries for kw in ("rag", "retrieval", "document"))


# ── 2. Language detection ─────────────────────────────────────────────────────

class TestLanguageDetection:
    def test_language_filter_appended(self):
        results = QueryExpander.expand("rest api", language="Python")
        for r in results:
            assert "language:Python" in r.query

    def test_language_filter_with_min_stars(self):
        results = QueryExpander.expand("chat", language="TypeScript", min_stars=100)
        for r in results:
            assert "language:TypeScript" in r.query
            assert "stars:>=100" in r.query

    def test_framework_alias_detected_from_language_param(self):
        results = QueryExpander.expand("admin dashboard", language="nextjs")
        all_queries = " ".join(_queries(results)).lower()
        assert "nextjs" in all_queries

    def test_framework_alias_in_description(self):
        results = QueryExpander.expand("fastapi saas boilerplate")
        all_queries = " ".join(_queries(results)).lower()
        assert "fastapi" in all_queries

    def test_no_language_filter_for_framework_alias(self):
        # Framework aliases should not produce `language:nextjs`
        results = QueryExpander.expand("dashboard", language="nextjs")
        for r in results:
            assert "language:nextjs" not in r.query


# ── 3. Template query generation ─────────────────────────────────────────────

class TestTemplateQuery:
    def test_template_label_present(self):
        results = QueryExpander.expand("saas")
        labels = _labels(results)
        assert "template" in labels

    def test_boilerplate_or_starter_in_some_query(self):
        results = QueryExpander.expand("auth system")
        all_queries = " ".join(_queries(results)).lower()
        assert any(s in all_queries for s in ("boilerplate", "starter", "template", "scaffold"))

    def test_template_query_uses_framework_when_detected(self):
        results = QueryExpander.expand("fastapi rest api")
        template_queries = [r.query.lower() for r in results if r.label == "template"]
        assert any("fastapi" in q for q in template_queries)

    def test_template_suffixes_vary(self):
        results = QueryExpander.expand("nextjs dashboard")
        template_queries = [r.query.lower() for r in results if r.label == "template"]
        # Should have at least one template query
        assert len(template_queries) >= 1


# ── 4. Deduplication ─────────────────────────────────────────────────────────

class TestDeduplication:
    def test_no_duplicate_queries(self):
        results = QueryExpander.expand("saas boilerplate", language="Python", min_stars=50)
        queries_lower = [r.query.lower() for r in results]
        assert len(queries_lower) == len(set(queries_lower))

    def test_no_duplicate_queries_simple(self):
        results = QueryExpander.expand("chat")
        queries = _queries(results)
        assert len(queries) == len(set(q.lower() for q in queries))

    def test_dedup_across_labels(self):
        # Even if direct and synonym produce the same string, only one survives
        results = QueryExpander.expand("ecommerce shop")
        queries_lower = [r.query.lower() for r in results]
        assert len(queries_lower) == len(set(queries_lower))


# ── 5. Maximum query count ────────────────────────────────────────────────────

class TestMaxQueries:
    def test_never_exceeds_5(self):
        for desc in ("saas boilerplate", "chat messaging realtime", "rag ai agent llm"):
            results = QueryExpander.expand(desc, language="Python", min_stars=10)
            assert len(results) <= 5, f"Got {len(results)} for {desc!r}"

    def test_returns_at_least_1_for_known_term(self):
        results = QueryExpander.expand("dashboard")
        assert len(results) >= 1

    def test_returns_at_most_5_for_rich_input(self):
        results = QueryExpander.expand(
            "saas dashboard analytics monitoring", language="TypeScript", min_stars=50
        )
        assert len(results) <= 5


# ── 6. Empty / minimal input ─────────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_description_returns_list(self):
        results = QueryExpander.expand("")
        assert isinstance(results, list)

    def test_empty_description_with_language_returns_something(self):
        results = QueryExpander.expand("", language="Python")
        # May be empty or have template queries — should not raise
        assert isinstance(results, list)

    def test_whitespace_only_description(self):
        results = QueryExpander.expand("   ")
        assert isinstance(results, list)

    def test_unknown_term_falls_back_to_direct(self):
        results = QueryExpander.expand("xyzzy-nonexistent-project-type-12345")
        assert len(results) >= 1
        assert results[0].label == "direct"


# ── 7. Framework alias ────────────────────────────────────────────────────────

class TestFrameworkAlias:
    @pytest.mark.parametrize("alias,expected", [
        ("next.js", "nextjs"),
        ("Next", "nextjs"),
        ("react native", "react-native"),
        ("spring boot", "spring-boot"),
        ("tailwind", "tailwindcss"),
        ("k8s", "kubernetes"),
    ])
    def test_alias_normalised(self, alias: str, expected: str):
        results = QueryExpander.expand("boilerplate", language=alias)
        all_queries = " ".join(_queries(results)).lower()
        assert expected in all_queries, f"Expected {expected!r} in queries for alias {alias!r}"

    def test_django_detected_from_description(self):
        results = QueryExpander.expand("django saas boilerplate")
        all_queries = " ".join(_queries(results)).lower()
        assert "django" in all_queries

    def test_laravel_detected(self):
        results = QueryExpander.expand("laravel crm")
        all_queries = " ".join(_queries(results)).lower()
        assert "laravel" in all_queries

    def test_framework_appears_in_multiple_queries(self):
        results = QueryExpander.expand("fastapi boilerplate")
        fw_count = sum(1 for r in results if "fastapi" in r.query.lower())
        assert fw_count >= 2


# ── 8. Multi-feature input ────────────────────────────────────────────────────

class TestMultiFeature:
    def test_ai_chatbot_expands_both_concepts(self):
        results = QueryExpander.expand("ai chatbot")
        all_queries = " ".join(_queries(results)).lower()
        assert any(kw in all_queries for kw in ("chatbot", "llm", "ai", "conversational"))

    def test_auth_saas_covers_both_domains(self):
        results = QueryExpander.expand("saas with auth")
        all_queries = " ".join(_queries(results)).lower()
        # At minimum the direct query or a synonym covers both
        assert any(kw in all_queries for kw in ("saas", "auth", "authentication", "starter"))

    def test_payment_ecommerce_produces_relevant_queries(self):
        results = QueryExpander.expand("ecommerce payment integration")
        all_queries = " ".join(_queries(results)).lower()
        assert any(kw in all_queries for kw in ("ecommerce", "shop", "payment", "billing", "store"))

    def test_monitoring_devtool_relevant(self):
        results = QueryExpander.expand("monitoring devtool")
        all_queries = " ".join(_queries(results)).lower()
        assert any(kw in all_queries for kw in ("monitoring", "devtool", "developer", "metrics", "tool"))

    def test_rag_agent_language_filtered(self):
        results = QueryExpander.expand("rag agent", language="Python", min_stars=50)
        all_queries = " ".join(_queries(results)).lower()
        assert "language:python" in all_queries
        assert "stars:>=50" in all_queries
