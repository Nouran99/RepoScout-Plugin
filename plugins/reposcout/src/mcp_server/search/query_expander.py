"""Query expander — converts natural-language descriptions into ranked GitHub search queries."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ExpandedQuery:
    """A single expanded GitHub search query with metadata."""

    query: str
    label: str  # "direct" | "synonym" | "template" | "feature"
    priority: int  # lower = more specific/preferred


# ── Synonym map ───────────────────────────────────────────────────────────────
# Maps user-facing terms → list of GitHub search terms (in order of preference)

SYNONYMS: dict[str, list[str]] = {
    # App types
    "saas": ["saas boilerplate", "saas starter", "saas template", "multi-tenant"],
    "dashboard": ["admin dashboard", "analytics dashboard", "dashboard template", "admin panel"],
    "e-commerce": ["ecommerce", "online store", "shop", "marketplace", "storefront"],
    "ecommerce": ["ecommerce", "online store", "shop", "marketplace"],
    "shop": ["ecommerce", "online store", "shop"],
    "blog": ["blog", "cms", "content management", "publishing"],
    "cms": ["cms", "content management system", "headless cms"],
    "chat": ["chat app", "messaging", "real-time chat", "instant messaging"],
    "messaging": ["messaging app", "chat", "real-time messaging"],
    "task management": ["todo app", "task tracker", "project management", "kanban"],
    "todo": ["todo app", "task management", "task tracker"],
    "kanban": ["kanban board", "task management", "project management"],
    "api": ["rest api", "api boilerplate", "api starter", "backend api"],
    "rest api": ["rest api boilerplate", "api starter", "fastapi", "express api"],
    "graphql": ["graphql api", "graphql server", "graphql boilerplate"],
    "cli": ["cli tool", "command line", "terminal app", "cli framework"],
    "mobile": ["mobile app", "react native", "flutter app", "ionic"],
    "app": ["mobile app", "web app", "application"],
    "ai": ["ai app", "llm app", "machine learning", "ai boilerplate"],
    "llm": ["llm app", "llm boilerplate", "large language model", "ai chat"],
    "chatbot": ["chatbot", "ai chatbot", "llm chatbot", "conversational ai"],
    "rag": ["rag", "retrieval augmented generation", "rag pipeline", "document qa"],
    "agent": ["ai agent", "llm agent", "autonomous agent", "agentic"],
    "auth": ["authentication", "auth boilerplate", "login system", "user auth"],
    "authentication": ["auth", "jwt auth", "oauth", "user management"],
    "landing page": ["landing page", "marketing site", "static site", "promotional page"],
    "landing": ["landing page", "marketing site", "one-page"],
    "portfolio": ["portfolio", "personal website", "developer portfolio", "showcase"],
    "crm": ["crm", "customer relationship management", "sales pipeline", "contacts"],
    "social": ["social network", "social media", "community platform", "social app"],
    "social network": ["social network", "social media app", "community platform"],
    "video": ["video platform", "video streaming", "media player", "video app"],
    "streaming": ["video streaming", "live streaming", "media streaming"],
    "payment": ["payment integration", "billing", "subscription", "stripe integration"],
    "billing": ["billing system", "subscription management", "payment gateway"],
    "notification": ["notification system", "push notifications", "alert system", "email notifications"],
    "search": ["search engine", "full-text search", "elasticsearch", "search app"],
    "monitoring": ["monitoring dashboard", "observability", "metrics", "alerting"],
    "devtool": ["developer tool", "dev tool", "developer productivity", "tooling"],
    "dev tool": ["developer tool", "cli tool", "developer productivity"],
    "analytics": ["analytics dashboard", "data analytics", "reporting", "metrics"],
    "forum": ["forum", "community forum", "discussion board", "bulletin board"],
    "wiki": ["wiki", "knowledge base", "documentation site", "docs site"],
    "marketplace": ["marketplace", "platform", "multi-vendor", "listing"],
    "booking": ["booking system", "reservation", "scheduling", "calendar app"],
    "inventory": ["inventory management", "stock management", "warehouse"],
    "hr": ["hr management", "human resources", "employee management", "payroll"],
    "finance": ["finance app", "budgeting", "expense tracker", "accounting"],
    "healthcare": ["healthcare app", "medical", "health tracking", "telemedicine"],
    "education": ["e-learning", "learning management system", "lms", "online course"],
    "lms": ["learning management system", "e-learning platform", "course platform"],
    "game": ["game", "web game", "html5 game", "game engine"],
    "realtime": ["real-time", "websocket", "live updates", "real-time app"],
    "real-time": ["real-time app", "websocket", "live", "streaming"],
    "scraper": ["web scraper", "data scraper", "crawler", "data extraction"],
    "crawler": ["web crawler", "scraper", "spider", "data collection"],
    "microservices": ["microservices", "microservice architecture", "distributed system"],
    "serverless": ["serverless", "lambda", "cloud functions", "faas"],
    "pwa": ["progressive web app", "pwa", "offline-first", "service worker"],
    "admin": ["admin panel", "admin dashboard", "back office", "management panel"],
    "workflow": ["workflow automation", "business process", "automation tool"],
    "document": ["document editor", "collaborative editing", "rich text editor"],
    "spreadsheet": ["spreadsheet", "table editor", "data grid"],
    "calendar": ["calendar app", "scheduling", "event management"],
    "map": ["map application", "geolocation", "location app", "mapping"],
}

# ── Template suffixes appended to produce "starter template" variants ─────────
TEMPLATE_SUFFIXES: list[str] = [
    "boilerplate",
    "starter",
    "template",
    "scaffold",
    "starter kit",
]

# ── Framework aliases normalize user-provided language/framework names ─────────
FRAMEWORK_ALIASES: dict[str, str] = {
    # Python
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "starlette": "starlette",
    "litestar": "litestar",
    # JavaScript / TypeScript
    "react": "react",
    "next": "nextjs",
    "nextjs": "nextjs",
    "next.js": "nextjs",
    "vue": "vue",
    "nuxt": "nuxtjs",
    "nuxtjs": "nuxtjs",
    "nuxt.js": "nuxtjs",
    "svelte": "svelte",
    "sveltekit": "sveltekit",
    "angular": "angular",
    "remix": "remix",
    "solid": "solidjs",
    "solidjs": "solidjs",
    "astro": "astro",
    "express": "express",
    "nestjs": "nestjs",
    "nest": "nestjs",
    "koa": "koa",
    "hono": "hono",
    "elysia": "elysia",
    # Go
    "gin": "gin",
    "fiber": "fiber",
    "echo": "echo",
    "chi": "chi",
    # Ruby
    "rails": "rails",
    "sinatra": "sinatra",
    # Java / Kotlin
    "spring": "spring-boot",
    "spring boot": "spring-boot",
    "quarkus": "quarkus",
    "micronaut": "micronaut",
    # PHP
    "laravel": "laravel",
    "symfony": "symfony",
    # Rust
    "axum": "axum",
    "actix": "actix-web",
    "rocket": "rocket",
    # Mobile
    "flutter": "flutter",
    "react native": "react-native",
    "expo": "expo",
    # Databases
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "mongodb": "mongodb",
    "redis": "redis",
    "supabase": "supabase",
    "prisma": "prisma",
    "drizzle": "drizzle-orm",
    "sqlalchemy": "sqlalchemy",
    # AI / ML
    "langchain": "langchain",
    "llamaindex": "llamaindex",
    "llama-index": "llamaindex",
    "openai": "openai",
    "anthropic": "anthropic",
    "huggingface": "huggingface",
    # CSS / UI
    "tailwind": "tailwindcss",
    "tailwindcss": "tailwindcss",
    "shadcn": "shadcn-ui",
    "mui": "material-ui",
    "chakra": "chakra-ui",
    # Infrastructure
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "terraform": "terraform",
}


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation except hyphens/slashes."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _words(text: str) -> set[str]:
    """Return set of lowercase words/phrases from text (unigrams + bigrams)."""
    tokens = re.split(r"[\s,;./]+", _normalise(text))
    tokens = [t for t in tokens if t]
    unigrams = set(tokens)
    bigrams = {f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)}
    return unigrams | bigrams


def _detect_framework(description: str, language: str | None) -> str | None:
    """Return the canonical framework alias if one is found in the inputs."""
    combined = _normalise(f"{description} {language or ''}")
    # Try longer matches first (e.g. "spring boot" before "spring")
    for alias in sorted(FRAMEWORK_ALIASES, key=len, reverse=True):
        if alias in combined:
            return FRAMEWORK_ALIASES[alias]
    return None


def _detect_synonyms(words: set[str]) -> list[str]:
    """Return synonym search terms for any keyword matched in *words*."""
    found: list[str] = []
    # Sort by length descending so multi-word keys win over their substrings
    for key in sorted(SYNONYMS, key=len, reverse=True):
        if key in words:
            found.extend(SYNONYMS[key])
    return found


def _build_filter_suffix(language: str | None, min_stars: int | None) -> str:
    parts: list[str] = []
    if language:
        # Only add language: filter for plain language names, not framework aliases
        lang_lower = _normalise(language)
        # Check if it's a plain language (not a framework alias key that maps differently)
        canonical = FRAMEWORK_ALIASES.get(lang_lower)
        if canonical is None:  # plain language like "Python", "TypeScript"
            parts.append(f"language:{language}")
        # If it IS a framework alias, the framework name is already in the query
    if min_stars is not None:
        parts.append(f"stars:>={min_stars}")
    return (" " + " ".join(parts)) if parts else ""


class QueryExpander:
    """Expands a natural-language description into up to 5 GitHub search queries."""

    @staticmethod
    def expand(
        description: str,
        language: str | None = None,
        min_stars: int | None = None,
    ) -> list[ExpandedQuery]:
        """Generate up to 5 ranked GitHub search queries from a description.

        Args:
            description: Free-text description of the desired project.
            language: Optional programming language or framework filter.
            min_stars: Optional minimum star count filter.

        Returns:
            Up to 5 deduplicated ExpandedQuery objects ordered by priority.
        """
        desc_norm = _normalise(description)
        words = _words(desc_norm)
        if language:
            words |= _words(language)

        framework = _detect_framework(description, language)
        filter_suffix = _build_filter_suffix(language, min_stars)

        candidates: list[ExpandedQuery] = []
        seen_queries: set[str] = set()

        def _add(query: str, label: str, priority: int) -> None:
            full = (query + filter_suffix).strip()
            normalised_key = re.sub(r"\s+", " ", full.lower())
            if normalised_key not in seen_queries:
                seen_queries.add(normalised_key)
                candidates.append(ExpandedQuery(query=full, label=label, priority=priority))

        # 1. Direct query from the raw description
        if desc_norm:
            _add(desc_norm, "direct", 0)

        # 2. Framework-prefixed direct query (highest specificity)
        if framework and desc_norm:
            # Strip the framework name from description to avoid repetition
            desc_no_fw = re.sub(re.escape(framework), "", desc_norm).strip()
            if desc_no_fw:
                _add(f"{framework} {desc_no_fw}", "direct", 1)
            else:
                _add(framework, "direct", 1)

        # 3. Synonym-based queries (first two only — leave room for templates)
        syn_terms = _detect_synonyms(words)
        for i, term in enumerate(syn_terms[:2]):
            if framework:
                _add(f"{framework} {term}", "synonym", 10 + i)
            else:
                _add(term, "synonym", 10 + i)

        # 4. Template/boilerplate variants — first one slots in before remaining synonyms
        primary = framework or (syn_terms[0] if syn_terms else desc_norm)
        if primary:
            _add(f"{primary} {TEMPLATE_SUFFIXES[0]}", "template", 8)   # boilerplate
            for j, suffix in enumerate(TEMPLATE_SUFFIXES[1:], start=1):
                _add(f"{primary} {suffix}", "template", 15 + j)

        # Remaining synonyms after templates
        for i, term in enumerate(syn_terms[2:], start=2):
            if framework:
                _add(f"{framework} {term}", "synonym", 12 + i)
            else:
                _add(term, "synonym", 12 + i)

        # 5. Feature queries: individual words that appear in the synonym map
        for word in sorted(words):
            if word in SYNONYMS:
                for k, feat in enumerate(SYNONYMS[word][:2]):
                    lbl = "feature"
                    if framework:
                        _add(f"{framework} {feat}", lbl, 30 + k)
                    else:
                        _add(feat, lbl, 30 + k)

        # Sort by priority, return top 5
        candidates.sort(key=lambda q: q.priority)
        return candidates[:5]
