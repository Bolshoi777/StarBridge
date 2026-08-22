#!/usr/bin/env python3
"""
StarBridge 1.0 — Adaptive Recursive Rare-Interest Relay (A-RIR)

Deterministic GitHub interest discovery without AI, embeddings, keyword search,
or reconstruction of GitHub's restricted repository-stargazer list.

Python 3.11+, standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import heapq
import html
import json
import math
import os
import random
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Sequence

VERSION = "1.0.4"
API_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
API_VERSION = "2026-03-10"
DEFAULT_MEDIA = "application/vnd.github+json"
STAR_MEDIA = "application/vnd.github.star+json"
USER_AGENT = f"StarBridge/{VERSION} (+local deterministic research tool)"

SOURCE_WEIGHTS: dict[str, float] = {
    "owner": 1.15,
    "contributors": 1.00,
    "forks": 0.70,
    "issues": 0.60,
    "pulls": 0.82,
    "comments": 0.58,
    "reviews": 0.88,
    "commits": 0.92,
    "releases": 1.00,
}
DEFAULT_SOURCES = tuple(SOURCE_WEIGHTS)

PERSON_DEFAULT_WEIGHTS: dict[str, float] = {
    "rare_overlap": 0.27,
    "weighted_jaccard": 0.19,
    "containment": 0.15,
    "temporal": 0.11,
    "seed_affinity": 0.12,
    "structural": 0.16,
}

REPO_DEFAULT_WEIGHTS: dict[str, float] = {
    "support_strength": 0.30,
    "supporter_diversity": 0.16,
    "global_rarity": 0.12,
    "local_rarity": 0.14,
    "temporal_velocity": 0.12,
    "activity_recency": 0.08,
    "no_topics": 0.04,
    "path_diversity": 0.04,
}

RELATION_WEIGHTS = {"star": 1.0, "owns": 0.68, "event": 0.38}


# Minimal built-in catalog taxonomy. If catalogs.json exists next to starbridge.py,
# that editable file is preferred.
DEFAULT_CATALOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "minimum_score": 2.5,
    "secondary_ratio": 0.55,
    "categories": [
        {"id":"ai_ml","label":"AI & ML","strong":["machine-learning","deep-learning","artificial-intelligence","large-language-model","llm","transformer","computer-vision","generative-ai","rag","ai-agent","ai-agents"],"weak":["ml","nlp","inference","embedding","agentic","language-model"],"phrases":["large language model","machine learning","deep learning","artificial intelligence","computer vision","generative ai","ai agent"]},
        {"id":"security","label":"SECURITY","strong":["cybersecurity","information-security","infosec","pentesting","penetration-testing","appsec","application-security","vulnerability","exploit","red-team","malware-analysis","reverse-engineering","fuzzing","forensics"],"weak":["security","scanner","audit","sandbox","threat-intelligence","blue-team","soc"],"phrases":["penetration testing","application security","reverse engineering","malware analysis","security testing"]},
        {"id":"osint","label":"OSINT","strong":["osint","open-source-intelligence","reconnaissance","recon","geoint","threat-intelligence"],"weak":["intelligence","investigation","geolocation","tracking"],"phrases":["open source intelligence","threat intelligence"]},
        {"id":"devtools","label":"DEVTOOLS","strong":["developer-tools","devtools","cli","sdk","code-generator","static-analysis","linter","formatter","debugger","build-tool","package-manager","ide","testing-framework"],"weak":["automation","toolkit","terminal","tui"],"phrases":["developer tool","command line tool","static analysis"]},
        {"id":"networking","label":"NETWORKING","strong":["networking","network-tools","tcp","udp","dns","vpn","proxy","traceroute","routing","bgp","packet-analysis","network-monitoring"],"weak":["network","latency","asn","icmp","socket","tunnel"],"phrases":["network monitoring","packet analysis","reverse proxy"]},
        {"id":"science","label":"SCIENCE","strong":["scientific-computing","research","physics","chemistry","biology","bioinformatics","neuroscience","brain-computer-interface","quantum-computing","mathematics","simulation"],"weak":["science","paper","experiment","academic"],"phrases":["scientific computing","brain computer interface","quantum computing"]},
    ],
}


PIXEL_FONT: dict[str, tuple[str, ...]] = {
    "S": ("11111", "10000", "11111", "00001", "11111"),
    "T": ("11111", "00100", "00100", "00100", "00100"),
    "A": ("01110", "10001", "11111", "10001", "10001"),
    "R": ("11110", "10001", "11110", "10100", "10010"),
    "B": ("11110", "10001", "11110", "10001", "11110"),
    "I": ("11111", "00100", "00100", "00100", "11111"),
    "D": ("11110", "10001", "10001", "10001", "11110"),
    "G": ("01111", "10000", "10111", "10001", "01110"),
    "E": ("11111", "10000", "11110", "10000", "11111"),
}


def print_pixel_logo() -> None:
    """Print a terminal-safe pixel logo at every CLI launch."""
    if os.environ.get("STARBRIDGE_NO_LOGO") == "1":
        return
    word = "STARBRIDGE"
    use_color = bool(getattr(sys.stdout, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")
    cyan = "\x1b[96m" if use_color else ""
    green = "\x1b[92m" if use_color else ""
    dim = "\x1b[90m" if use_color else ""
    reset = "\x1b[0m" if use_color else ""
    print()
    for row in range(5):
        parts: list[str] = []
        for ch in word:
            bits = PIXEL_FONT[ch][row]
            parts.append("".join("##" if b == "1" else "  " for b in bits))
        print(cyan + "  " + " ".join(parts) + reset)
    print(green + f"  STARBRIDGE {VERSION}  |  A-RIR DISCOVERY ENGINE" + reset)
    print(dim + "  adaptive recursive rare-interest relay  |  deterministic / no AI" + reset)
    print()


class StarBridgeError(RuntimeError):
    pass


class BudgetExhausted(StarBridgeError):
    pass


class RateLimitPause(StarBridgeError):
    pass


class RecoverableTaskError(StarBridgeError):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_now_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_date_cutoff(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return parse_iso(value)
        return dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD or ISO-8601 timestamp") from exc


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_log1p(value: float) -> float:
    return math.log1p(max(0.0, value))


def exp_saturate(value: float, scale: float = 1.0) -> float:
    if value <= 0:
        return 0.0
    return 1.0 - math.exp(-value / max(1e-9, scale))


def recency_weight(timestamp: str | None, half_life_days: float = 365.0, missing: float = 0.55) -> float:
    ts = parse_iso(timestamp)
    if ts is None:
        return missing
    age_days = max(0.0, (utcnow() - ts).total_seconds() / 86400.0)
    return math.exp(-math.log(2.0) * age_days / max(1.0, half_life_days))


def global_rarity(stars: int | None) -> float:
    count = max(0, int(stars or 0))
    return 1.0 / math.log2(2.0 + count)


def normalized_global_rarity(stars: int | None) -> float:
    # 0 stars -> 1.0; thousands -> low but non-zero.
    return clamp(global_rarity(stars))


def local_idf(total_profiles: int, document_frequency: int, alpha: float = 1.0) -> float:
    n = max(1, int(total_profiles))
    df = max(0, min(n, int(document_frequency)))
    return math.log((n + alpha) / (df + alpha)) + 1.0


def normalized_local_idf(total_profiles: int, document_frequency: int) -> float:
    value = local_idf(total_profiles, document_frequency)
    return clamp((value - 1.0) / max(1.0, math.log(max(2, total_profiles))))


def split_repo(value: str) -> tuple[str, str]:
    value = value.strip().strip("/")
    for prefix in ("https://github.com/", "http://github.com/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    value = value.removesuffix(".git")
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError(f"Repository must be OWNER/REPO: {value!r}")
    return parts[0], parts[1]


def normalize_repo(value: str) -> str:
    owner, repo = split_repo(value)
    return f"{owner}/{repo}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(*parts: Any) -> str:
    raw = "\x1f".join(str(x) for x in parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def ndcg(labels: Sequence[float], scores: Sequence[float]) -> float:
    if not labels or len(labels) != len(scores):
        return 0.0
    order = sorted(range(len(labels)), key=lambda i: scores[i], reverse=True)
    ideal = sorted(range(len(labels)), key=lambda i: labels[i], reverse=True)

    def dcg(indices: Sequence[int]) -> float:
        total = 0.0
        for rank, idx in enumerate(indices, 1):
            gain = (2.0 ** labels[idx]) - 1.0
            total += gain / math.log2(rank + 1.0)
        return total

    ideal_score = dcg(ideal)
    return dcg(order) / ideal_score if ideal_score > 0 else 0.0


@dataclass(slots=True)
class RepoRecord:
    full_name: str
    html_url: str
    description: str
    language: str
    stargazers_count: int
    topics: list[str]
    archived: bool
    fork: bool
    disabled: bool
    private: bool
    owner_login: str
    pushed_at: str | None
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_rest(cls, obj: Mapping[str, Any]) -> "RepoRecord":
        owner = obj.get("owner") if isinstance(obj.get("owner"), Mapping) else {}
        return cls(
            full_name=str(obj.get("full_name") or ""),
            html_url=str(obj.get("html_url") or ""),
            description=str(obj.get("description") or ""),
            language=str(obj.get("language") or ""),
            stargazers_count=int(obj.get("stargazers_count") or 0),
            topics=[str(x) for x in (obj.get("topics") or []) if x],
            archived=bool(obj.get("archived")),
            fork=bool(obj.get("fork")),
            disabled=bool(obj.get("disabled")),
            private=bool(obj.get("private")),
            owner_login=str(owner.get("login") or ""),
            pushed_at=obj.get("pushed_at"),
            created_at=obj.get("created_at"),
            updated_at=obj.get("updated_at"),
        )

    @classmethod
    def from_graphql(cls, obj: Mapping[str, Any]) -> "RepoRecord":
        language = obj.get("primaryLanguage") if isinstance(obj.get("primaryLanguage"), Mapping) else {}
        owner = obj.get("owner") if isinstance(obj.get("owner"), Mapping) else {}
        topics_obj = obj.get("repositoryTopics") if isinstance(obj.get("repositoryTopics"), Mapping) else {}
        nodes = topics_obj.get("nodes") if isinstance(topics_obj.get("nodes"), list) else []
        topics: list[str] = []
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            topic = node.get("topic") if isinstance(node.get("topic"), Mapping) else {}
            name = topic.get("name")
            if name:
                topics.append(str(name))
        return cls(
            full_name=str(obj.get("nameWithOwner") or ""),
            html_url=str(obj.get("url") or ""),
            description=str(obj.get("description") or ""),
            language=str(language.get("name") or ""),
            stargazers_count=int(obj.get("stargazerCount") or 0),
            topics=topics,
            archived=bool(obj.get("isArchived")),
            fork=bool(obj.get("isFork")),
            disabled=bool(obj.get("isDisabled")),
            private=bool(obj.get("isPrivate")),
            owner_login=str(owner.get("login") or ""),
            pushed_at=obj.get("pushedAt"),
            created_at=obj.get("createdAt"),
            updated_at=obj.get("updatedAt"),
        )


@dataclass(slots=True)
class StarRecord:
    repo: RepoRecord
    starred_at: str | None


@dataclass(slots=True)
class Task:
    id: int
    scan_id: int
    kind: str
    node_id: str
    source: str
    depth: int
    page_no: int
    url: str | None
    cursor_key: str
    payload: dict[str, Any]
    expected_yield: float
    novelty: float
    relevance: float
    confidence: float
    cost: float
    priority: float
    status: str
    attempts: int
    parent_task_id: int | None
    path: list[dict[str, str]]


@dataclass(slots=True)
class PersonResult:
    login: str
    score: float
    features: dict[str, float]
    overlap_repos: list[str]
    source_names: list[str]
    seed_names: list[str]
    paths: list[list[dict[str, str]]]
    star_count: int


@dataclass(slots=True)
class RepoResult:
    repo: RepoRecord
    score: float
    features: dict[str, float]
    supporters: list[dict[str, Any]]
    flags: list[str]
    paths: list[list[dict[str, str]]]
    new_since_previous: bool


@dataclass(slots=True)
class ScanConfig:
    user: str
    mode: str = "adaptive"
    budget: int = 4200
    max_depth: int = 4
    auto_seeds: int = 30
    seed_pool: int = 100
    actor_beam: int = 1000
    repo_beam: int = 5000
    source_pages: int = 2
    actor_star_pages: int = 20
    owner_star_pages: int = 100
    min_overlap: int = 1
    recent_days: int = 365
    history_sampling: str = "stratified"
    transport: str = "auto"
    graphql_batch: int = 8
    private_policy: str = "ignore"
    owner_cutoff: str | None = None
    sources: tuple[str, ...] = DEFAULT_SOURCES
    carry_people: int = 100
    repo_promotions_per_actor: int = 5
    event_pages: int = 1
    public_repo_pages: int = 1
    max_repo_stars: int = 0
    include_forks: bool = False
    include_archived: bool = False
    min_page_yield: int = 5
    ema_alpha: float = 0.45
    pause: float = 0.12
    retry_count: int = 3
    explicit_seeds: tuple[str, ...] = ()

    def normalized(self) -> "ScanConfig":
        data = asdict(self)
        data["sources"] = tuple(self.sources)
        data["explicit_seeds"] = tuple(self.explicit_seeds)
        return ScanConfig(**data)

    @classmethod
    def from_json(cls, raw: str) -> "ScanConfig":
        data = json.loads(raw)
        data["sources"] = tuple(data.get("sources") or DEFAULT_SOURCES)
        data["explicit_seeds"] = tuple(data.get("explicit_seeds") or ())
        return cls(**data)

    def to_json(self) -> str:
        data = asdict(self)
        data["sources"] = list(self.sources)
        data["explicit_seeds"] = list(self.explicit_seeds)
        return json_dumps(data)


class Storage:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS http_cache_v1 (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                accept TEXT NOT NULL,
                etag TEXT,
                body TEXT NOT NULL,
                headers_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                config_json TEXT NOT NULL,
                budget_total INTEGER NOT NULL,
                budget_used INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS repos (
                full_name TEXT PRIMARY KEY,
                html_url TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                stargazers_count INTEGER NOT NULL DEFAULT 0,
                topics_json TEXT NOT NULL DEFAULT '[]',
                archived INTEGER NOT NULL DEFAULT 0,
                fork INTEGER NOT NULL DEFAULT 0,
                disabled INTEGER NOT NULL DEFAULT 0,
                private INTEGER NOT NULL DEFAULT 0,
                owner_login TEXT NOT NULL DEFAULT '',
                pushed_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS users (
                login TEXT PRIMARY KEY,
                html_url TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                user_type TEXT NOT NULL DEFAULT 'User',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS user_stars (
                user_login TEXT NOT NULL,
                repo_full_name TEXT NOT NULL,
                starred_at TEXT,
                source TEXT NOT NULL DEFAULT 'rest',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                first_seen_scan INTEGER,
                last_seen_scan INTEGER,
                PRIMARY KEY(user_login, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS scan_owner_profile (
                scan_id INTEGER NOT NULL,
                repo_full_name TEXT NOT NULL,
                starred_at TEXT,
                PRIMARY KEY(scan_id, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS scan_candidates (
                scan_id INTEGER NOT NULL,
                user_login TEXT NOT NULL,
                relevance REAL NOT NULL DEFAULT 0,
                strength REAL NOT NULL DEFAULT 0,
                sources_json TEXT NOT NULL DEFAULT '[]',
                seeds_json TEXT NOT NULL DEFAULT '[]',
                paths_json TEXT NOT NULL DEFAULT '[]',
                first_depth INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(scan_id, user_login)
            );

            CREATE TABLE IF NOT EXISTS actor_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                repo_full_name TEXT NOT NULL,
                user_login TEXT NOT NULL,
                source TEXT NOT NULL,
                depth INTEGER NOT NULL,
                strength REAL NOT NULL,
                path_json TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                UNIQUE(scan_id, repo_full_name, user_login, source)
            );

            CREATE TABLE IF NOT EXISTS repo_support (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                user_login TEXT NOT NULL,
                repo_full_name TEXT NOT NULL,
                relation TEXT NOT NULL,
                occurred_at TEXT,
                depth INTEGER NOT NULL,
                path_json TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                UNIQUE(scan_id, user_login, repo_full_name, relation)
            );

            CREATE TABLE IF NOT EXISTS frontier_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                node_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                depth INTEGER NOT NULL,
                page_no INTEGER NOT NULL DEFAULT 1,
                url TEXT,
                cursor_key TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                expected_yield REAL NOT NULL DEFAULT 1,
                novelty REAL NOT NULL DEFAULT 1,
                relevance REAL NOT NULL DEFAULT 1,
                confidence REAL NOT NULL DEFAULT 1,
                cost REAL NOT NULL DEFAULT 1,
                priority REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                parent_task_id INTEGER,
                path_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                UNIQUE(scan_id, kind, node_id, source, depth, cursor_key)
            );

            CREATE INDEX IF NOT EXISTS idx_frontier_pending
            ON frontier_tasks(scan_id, status, priority DESC);

            CREATE TABLE IF NOT EXISTS seed_history (
                scan_id INTEGER NOT NULL,
                repo_full_name TEXT NOT NULL,
                depth INTEGER NOT NULL,
                reason TEXT NOT NULL,
                score REAL NOT NULL,
                parent_task_id INTEGER,
                path_json TEXT NOT NULL,
                promoted_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS source_yield (
                scan_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                pages INTEGER NOT NULL DEFAULT 0,
                items INTEGER NOT NULL DEFAULT 0,
                new_items INTEGER NOT NULL DEFAULT 0,
                ema REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(scan_id, source)
            );

            CREATE TABLE IF NOT EXISTS api_resources (
                scan_id INTEGER NOT NULL,
                resource TEXT NOT NULL,
                limit_value INTEGER,
                remaining INTEGER,
                used INTEGER,
                reset_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, resource)
            );

            CREATE TABLE IF NOT EXISTS transport_metrics (
                scan_id INTEGER NOT NULL,
                transport TEXT NOT NULL,
                requests INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0,
                items INTEGER NOT NULL DEFAULT 0,
                useful_items INTEGER NOT NULL DEFAULT 0,
                graphql_points INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(scan_id, transport)
            );

            CREATE TABLE IF NOT EXISTS repo_snapshots (
                scan_id INTEGER NOT NULL,
                repo_full_name TEXT NOT NULL,
                stargazers_count INTEGER NOT NULL,
                pushed_at TEXT,
                topics_json TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS star_snapshots (
                scan_id INTEGER NOT NULL,
                user_login TEXT NOT NULL,
                repo_full_name TEXT NOT NULL,
                starred_at TEXT,
                captured_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, user_login, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS scan_people_scores (
                scan_id INTEGER NOT NULL,
                user_login TEXT NOT NULL,
                score REAL NOT NULL,
                features_json TEXT NOT NULL,
                overlap_json TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                seeds_json TEXT NOT NULL,
                paths_json TEXT NOT NULL,
                star_count INTEGER NOT NULL,
                PRIMARY KEY(scan_id, user_login)
            );

            CREATE TABLE IF NOT EXISTS scan_repo_scores (
                scan_id INTEGER NOT NULL,
                repo_full_name TEXT NOT NULL,
                score REAL NOT NULL,
                features_json TEXT NOT NULL,
                supporters_json TEXT NOT NULL,
                flags_json TEXT NOT NULL,
                paths_json TEXT NOT NULL,
                new_since_previous INTEGER NOT NULL,
                PRIMARY KEY(scan_id, repo_full_name)
            );

            CREATE TABLE IF NOT EXISTS discovery_paths (
                scan_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                path_hash TEXT NOT NULL,
                path_json TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(scan_id, target_type, target_id, path_hash)
            );

            CREATE TABLE IF NOT EXISTS community_membership (
                scan_id INTEGER NOT NULL,
                community_id INTEGER NOT NULL,
                member_type TEXT NOT NULL,
                member_id TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1,
                PRIMARY KEY(scan_id, community_id, member_type, member_id)
            );

            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user TEXT NOT NULL,
                repo_full_name TEXT NOT NULL,
                rating INTEGER,
                action TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                owner_user TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(owner_user, key)
            );

            CREATE TABLE IF NOT EXISTS scan_metrics (
                scan_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value REAL NOT NULL,
                text_value TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(scan_id, key)
            );
            """
        )
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(self.SCHEMA_VERSION),),
        )
        self.conn.commit()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def create_scan(self, config: ScanConfig) -> int:
        now = utc_now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO scans(owner_user,mode,status,started_at,updated_at,config_json,budget_total,budget_used)
            VALUES(?,?, 'running', ?, ?, ?, ?, 0)
            """,
            (config.user, config.mode, now, now, config.to_json(), int(config.budget)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def scan_row(self, scan_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not row:
            raise StarBridgeError(f"Scan {scan_id} not found")
        return row

    def latest_scan(self, owner_user: str | None = None) -> int | None:
        if owner_user:
            row = self.conn.execute(
                "SELECT id FROM scans WHERE owner_user=? ORDER BY id DESC LIMIT 1", (owner_user,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return int(row["id"]) if row else None

    def latest_finished_scan_before(self, scan_id: int, owner_user: str) -> int | None:
        row = self.conn.execute(
            """
            SELECT id FROM scans
            WHERE owner_user=? AND id<? AND status='finished'
            ORDER BY id DESC LIMIT 1
            """,
            (owner_user, scan_id),
        ).fetchone()
        return int(row["id"]) if row else None

    def update_scan_status(self, scan_id: int, status: str, note: str = "") -> None:
        finished = utc_now_iso() if status == "finished" else None
        self.conn.execute(
            "UPDATE scans SET status=?,note=?,updated_at=?,finished_at=COALESCE(?,finished_at) WHERE id=?",
            (status, note, utc_now_iso(), finished, scan_id),
        )
        self.conn.commit()

    def add_budget(self, scan_id: int, amount: int) -> None:
        self.conn.execute(
            "UPDATE scans SET budget_total=budget_total+?,updated_at=? WHERE id=?",
            (max(0, int(amount)), utc_now_iso(), scan_id),
        )
        self.conn.commit()

    def budget_state(self, scan_id: int) -> tuple[int, int]:
        row = self.scan_row(scan_id)
        return int(row["budget_total"]), int(row["budget_used"])

    def consume_budget(self, scan_id: int, amount: int = 1) -> None:
        total, used = self.budget_state(scan_id)
        if used + amount > total:
            raise BudgetExhausted(f"Request budget exhausted: {used}/{total}")
        self.conn.execute(
            "UPDATE scans SET budget_used=budget_used+?,updated_at=? WHERE id=?",
            (amount, utc_now_iso(), scan_id),
        )
        self.conn.commit()

    def refund_budget(self, scan_id: int, amount: int = 1) -> None:
        self.conn.execute(
            "UPDATE scans SET budget_used=MAX(0,budget_used-?),updated_at=? WHERE id=?",
            (amount, utc_now_iso(), scan_id),
        )
        self.conn.commit()

    def cache_get(self, url: str, accept: str) -> tuple[str | None, Any, dict[str, str]] | None:
        key = stable_hash("GET", accept, url)
        row = self.conn.execute(
            "SELECT etag,body,headers_json FROM http_cache_v1 WHERE cache_key=?", (key,)
        ).fetchone()
        if not row:
            return None
        return row["etag"], json.loads(row["body"]), json.loads(row["headers_json"])

    def cache_put(self, url: str, accept: str, etag: str | None, body: Any, headers: Mapping[str, str]) -> None:
        key = stable_hash("GET", accept, url)
        self.conn.execute(
            """
            INSERT INTO http_cache_v1(cache_key,url,accept,etag,body,headers_json,fetched_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
                etag=excluded.etag,body=excluded.body,headers_json=excluded.headers_json,fetched_at=excluded.fetched_at
            """,
            (key, url, accept, etag, json_dumps(body), json_dumps(dict(headers)), utc_now_iso()),
        )
        self.conn.commit()

    def save_repo(self, repo: RepoRecord, scan_id: int | None = None) -> None:
        if not repo.full_name:
            return
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO repos(full_name,html_url,description,language,stargazers_count,topics_json,archived,fork,disabled,private,
                              owner_login,pushed_at,created_at,updated_at,first_seen_at,last_seen_at,times_seen)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            ON CONFLICT(full_name) DO UPDATE SET
                html_url=excluded.html_url,description=excluded.description,language=excluded.language,
                stargazers_count=excluded.stargazers_count,topics_json=excluded.topics_json,archived=excluded.archived,
                fork=excluded.fork,disabled=excluded.disabled,private=excluded.private,owner_login=excluded.owner_login,
                pushed_at=excluded.pushed_at,created_at=excluded.created_at,updated_at=excluded.updated_at,
                last_seen_at=excluded.last_seen_at,times_seen=repos.times_seen+1
            """,
            (
                repo.full_name, repo.html_url, repo.description, repo.language, repo.stargazers_count,
                json_dumps(repo.topics), int(repo.archived), int(repo.fork), int(repo.disabled), int(repo.private),
                repo.owner_login, repo.pushed_at, repo.created_at, repo.updated_at, now, now,
            ),
        )
        if scan_id is not None:
            self.conn.execute(
                """
                INSERT INTO repo_snapshots(scan_id,repo_full_name,stargazers_count,pushed_at,topics_json,captured_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(scan_id,repo_full_name) DO UPDATE SET
                    stargazers_count=excluded.stargazers_count,pushed_at=excluded.pushed_at,
                    topics_json=excluded.topics_json,captured_at=excluded.captured_at
                """,
                (scan_id, repo.full_name, repo.stargazers_count, repo.pushed_at, json_dumps(repo.topics), now),
            )
        self.conn.commit()

    def get_repo(self, full_name: str) -> RepoRecord | None:
        row = self.conn.execute("SELECT * FROM repos WHERE full_name=?", (full_name,)).fetchone()
        if not row:
            return None
        return RepoRecord(
            full_name=row["full_name"], html_url=row["html_url"], description=row["description"],
            language=row["language"], stargazers_count=int(row["stargazers_count"]),
            topics=json.loads(row["topics_json"] or "[]"), archived=bool(row["archived"]),
            fork=bool(row["fork"]), disabled=bool(row["disabled"]), private=bool(row["private"]),
            owner_login=row["owner_login"], pushed_at=row["pushed_at"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_user(self, obj: Mapping[str, Any] | str) -> None:
        if isinstance(obj, str):
            login = obj
            html_url = f"https://github.com/{login}"
            avatar = ""
            user_type = "User"
        else:
            login = str(obj.get("login") or "")
            html_url = str(obj.get("html_url") or obj.get("url") or f"https://github.com/{login}")
            avatar = str(obj.get("avatar_url") or obj.get("avatarUrl") or "")
            user_type = str(obj.get("type") or "User")
        if not login:
            return
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO users(login,html_url,avatar_url,user_type,first_seen_at,last_seen_at,times_seen)
            VALUES(?,?,?,?,?,?,1)
            ON CONFLICT(login) DO UPDATE SET
                html_url=excluded.html_url,avatar_url=excluded.avatar_url,user_type=excluded.user_type,
                last_seen_at=excluded.last_seen_at,times_seen=users.times_seen+1
            """,
            (login, html_url, avatar, user_type, now, now),
        )
        self.conn.commit()

    def save_star(self, scan_id: int, user_login: str, star: StarRecord, source: str = "rest") -> bool:
        self.save_repo(star.repo, scan_id)
        now = utc_now_iso()
        existing = self.conn.execute(
            "SELECT 1 FROM user_stars WHERE user_login=? AND repo_full_name=?",
            (user_login, star.repo.full_name),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO user_stars(user_login,repo_full_name,starred_at,source,first_seen_at,last_seen_at,first_seen_scan,last_seen_scan)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(user_login,repo_full_name) DO UPDATE SET
                starred_at=COALESCE(excluded.starred_at,user_stars.starred_at),source=excluded.source,
                last_seen_at=excluded.last_seen_at,last_seen_scan=excluded.last_seen_scan
            """,
            (user_login, star.repo.full_name, star.starred_at, source, now, now, scan_id, scan_id),
        )
        self.conn.execute(
            """
            INSERT INTO star_snapshots(scan_id,user_login,repo_full_name,starred_at,captured_at)
            VALUES(?,?,?,?,?) ON CONFLICT(scan_id,user_login,repo_full_name) DO UPDATE SET
            starred_at=COALESCE(excluded.starred_at,star_snapshots.starred_at),captured_at=excluded.captured_at
            """,
            (scan_id, user_login, star.repo.full_name, star.starred_at, now),
        )
        self.conn.commit()
        return existing is None

    def save_owner_profile(self, scan_id: int, user_login: str, stars: Sequence[StarRecord], private_policy: str,
                           cutoff: dt.datetime | None) -> list[StarRecord]:
        kept: list[StarRecord] = []
        for star in stars:
            ts = parse_iso(star.starred_at)
            if cutoff is not None and ts is not None and ts >= cutoff:
                continue
            if star.repo.private and private_policy == "ignore":
                continue
            self.save_star(scan_id, user_login, star, source="owner")
            self.conn.execute(
                "INSERT OR REPLACE INTO scan_owner_profile(scan_id,repo_full_name,starred_at) VALUES(?,?,?)",
                (scan_id, star.repo.full_name, star.starred_at),
            )
            kept.append(star)
        self.conn.commit()
        return kept

    def owner_profile(self, scan_id: int) -> list[StarRecord]:
        rows = self.conn.execute(
            """
            SELECT p.starred_at,r.* FROM scan_owner_profile p JOIN repos r ON r.full_name=p.repo_full_name
            WHERE p.scan_id=?
            """,
            (scan_id,),
        ).fetchall()
        return [self._row_to_star(row) for row in rows]

    def _row_to_star(self, row: sqlite3.Row) -> StarRecord:
        repo = RepoRecord(
            full_name=row["full_name"], html_url=row["html_url"], description=row["description"],
            language=row["language"], stargazers_count=int(row["stargazers_count"]),
            topics=json.loads(row["topics_json"] or "[]"), archived=bool(row["archived"]), fork=bool(row["fork"]),
            disabled=bool(row["disabled"]), private=bool(row["private"]), owner_login=row["owner_login"],
            pushed_at=row["pushed_at"], created_at=row["created_at"], updated_at=row["updated_at"],
        )
        return StarRecord(repo=repo, starred_at=row["starred_at"])

    def user_star_records(self, login: str, public_only: bool = True) -> list[StarRecord]:
        sql = (
            "SELECT us.starred_at,r.* FROM user_stars us JOIN repos r ON r.full_name=us.repo_full_name "
            "WHERE us.user_login=?"
        )
        params: list[Any] = [login]
        if public_only:
            sql += " AND r.private=0"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_star(row) for row in rows]

    def add_candidate(self, scan_id: int, login: str, relevance: float, strength: float, source: str, seed: str,
                      depth: int, path: Sequence[Mapping[str, str]]) -> None:
        if not login:
            return
        row = self.conn.execute(
            "SELECT * FROM scan_candidates WHERE scan_id=? AND user_login=?", (scan_id, login)
        ).fetchone()
        if row:
            sources = set(json.loads(row["sources_json"] or "[]")); sources.add(source)
            seeds = set(json.loads(row["seeds_json"] or "[]"));
            if seed: seeds.add(seed)
            paths = json.loads(row["paths_json"] or "[]")
            p = list(path)
            if p and p not in paths:
                paths.append(p)
            self.conn.execute(
                """
                UPDATE scan_candidates SET relevance=MAX(relevance,?),strength=strength+?,sources_json=?,seeds_json=?,paths_json=?
                WHERE scan_id=? AND user_login=?
                """,
                (relevance, strength, json_dumps(sorted(sources)), json_dumps(sorted(seeds)), json_dumps(paths[:20]), scan_id, login),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO scan_candidates(scan_id,user_login,relevance,strength,sources_json,seeds_json,paths_json,first_depth)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (scan_id, login, relevance, strength, json_dumps([source]), json_dumps([seed] if seed else []),
                 json_dumps([list(path)] if path else []), depth),
            )
        self.conn.commit()

    def candidate_row(self, scan_id: int, login: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM scan_candidates WHERE scan_id=? AND user_login=?", (scan_id, login)
        ).fetchone()

    def candidate_logins(self, scan_id: int, limit: int | None = None) -> list[str]:
        sql = "SELECT user_login FROM scan_candidates WHERE scan_id=? ORDER BY relevance DESC,strength DESC"
        params: list[Any] = [scan_id]
        if limit is not None:
            sql += " LIMIT ?"; params.append(limit)
        return [str(r[0]) for r in self.conn.execute(sql, params).fetchall()]

    def add_actor_edge(self, scan_id: int, repo: str, login: str, source: str, depth: int, strength: float,
                       path: Sequence[Mapping[str, str]]) -> bool:
        before = self.conn.total_changes
        self.conn.execute(
            """
            INSERT OR IGNORE INTO actor_edges(scan_id,repo_full_name,user_login,source,depth,strength,path_json,seen_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (scan_id, repo, login, source, depth, strength, json_dumps(list(path)), utc_now_iso()),
        )
        self.conn.commit()
        return self.conn.total_changes > before

    def add_repo_support(self, scan_id: int, login: str, repo: str, relation: str, occurred_at: str | None, depth: int,
                         path: Sequence[Mapping[str, str]]) -> bool:
        before = self.conn.total_changes
        self.conn.execute(
            """
            INSERT OR IGNORE INTO repo_support(scan_id,user_login,repo_full_name,relation,occurred_at,depth,path_json,seen_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (scan_id, login, repo, relation, occurred_at, depth, json_dumps(list(path)), utc_now_iso()),
        )
        self.conn.commit()
        return self.conn.total_changes > before

    def add_discovery_path(self, scan_id: int, target_type: str, target_id: str, path: Sequence[Mapping[str, str]],
                           score: float = 0.0) -> None:
        path_list = list(path)
        if not path_list:
            return
        path_hash = stable_hash(json_dumps(path_list))
        self.conn.execute(
            """
            INSERT INTO discovery_paths(scan_id,target_type,target_id,path_hash,path_json,score)
            VALUES(?,?,?,?,?,?) ON CONFLICT(scan_id,target_type,target_id,path_hash) DO UPDATE SET score=MAX(score,excluded.score)
            """,
            (scan_id, target_type, target_id, path_hash, json_dumps(path_list), float(score)),
        )
        self.conn.commit()

    def promote_seed(self, scan_id: int, repo: str, depth: int, reason: str, score: float,
                     parent_task_id: int | None, path: Sequence[Mapping[str, str]]) -> bool:
        before = self.conn.total_changes
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seed_history(scan_id,repo_full_name,depth,reason,score,parent_task_id,path_json,promoted_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (scan_id, repo, depth, reason, score, parent_task_id, json_dumps(list(path)), utc_now_iso()),
        )
        self.conn.commit()
        return self.conn.total_changes > before

    def seed_names(self, scan_id: int) -> set[str]:
        return {str(r[0]) for r in self.conn.execute("SELECT repo_full_name FROM seed_history WHERE scan_id=?", (scan_id,))}

    def enqueue_task(self, scan_id: int, kind: str, node_id: str, *, source: str = "", depth: int = 0,
                     page_no: int = 1, url: str | None = None, cursor_key: str | None = None,
                     payload: Mapping[str, Any] | None = None, expected_yield: float = 1.0, novelty: float = 1.0,
                     relevance: float = 1.0, confidence: float = 1.0, cost: float = 1.0,
                     parent_task_id: int | None = None, path: Sequence[Mapping[str, str]] = ()) -> int | None:
        priority = (max(0.01, expected_yield) * max(0.05, novelty) * max(0.05, relevance) * max(0.05, confidence)) / max(0.1, cost)
        key = cursor_key or stable_hash(url or "", page_no, json_dumps(payload or {}))[:24]
        now = utc_now_iso()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO frontier_tasks(scan_id,kind,node_id,source,depth,page_no,url,cursor_key,payload_json,
                expected_yield,novelty,relevance,confidence,cost,priority,status,attempts,parent_task_id,path_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',0,?,?,?,?)
            """,
            (scan_id, kind, node_id, source, depth, page_no, url, key, json_dumps(dict(payload or {})),
             expected_yield, novelty, relevance, confidence, cost, priority, parent_task_id,
             json_dumps(list(path)), now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None

    def reset_in_progress(self, scan_id: int) -> None:
        self.conn.execute(
            "UPDATE frontier_tasks SET status='pending',updated_at=? WHERE scan_id=? AND status='in_progress'",
            (utc_now_iso(), scan_id),
        )
        self.conn.commit()

    def pop_task(self, scan_id: int) -> Task | None:
        row = self.conn.execute(
            """
            SELECT * FROM frontier_tasks WHERE scan_id=? AND status='pending'
            ORDER BY priority DESC, depth ASC, id ASC LIMIT 1
            """,
            (scan_id,),
        ).fetchone()
        if not row:
            return None
        self.conn.execute(
            "UPDATE frontier_tasks SET status='in_progress',attempts=attempts+1,updated_at=? WHERE id=?",
            (utc_now_iso(), row["id"]),
        )
        self.conn.commit()
        return self._row_to_task(row)

    def pending_actor_star_first_tasks(self, scan_id: int, limit: int) -> list[Task]:
        rows = self.conn.execute(
            """
            SELECT * FROM frontier_tasks
            WHERE scan_id=? AND status='pending' AND kind='actor_stars' AND page_no=1
            ORDER BY priority DESC,id ASC LIMIT ?
            """,
            (scan_id, limit),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def claim_tasks(self, task_ids: Sequence[int]) -> None:
        if not task_ids:
            return
        placeholders = ",".join("?" for _ in task_ids)
        self.conn.execute(
            f"UPDATE frontier_tasks SET status='in_progress',attempts=attempts+1,updated_at=? WHERE id IN ({placeholders})",
            [utc_now_iso(), *task_ids],
        )
        self.conn.commit()

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=int(row["id"]), scan_id=int(row["scan_id"]), kind=row["kind"], node_id=row["node_id"],
            source=row["source"], depth=int(row["depth"]), page_no=int(row["page_no"]), url=row["url"],
            cursor_key=row["cursor_key"], payload=json.loads(row["payload_json"] or "{}"),
            expected_yield=float(row["expected_yield"]), novelty=float(row["novelty"]),
            relevance=float(row["relevance"]), confidence=float(row["confidence"]), cost=float(row["cost"]),
            priority=float(row["priority"]), status=row["status"], attempts=int(row["attempts"]),
            parent_task_id=row["parent_task_id"], path=json.loads(row["path_json"] or "[]"),
        )

    def finish_task(self, task_id: int, status: str = "done", error: str = "") -> None:
        self.conn.execute(
            "UPDATE frontier_tasks SET status=?,last_error=?,updated_at=? WHERE id=?",
            (status, error[:1000], utc_now_iso(), task_id),
        )
        self.conn.commit()

    def pending_count(self, scan_id: int) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM frontier_tasks WHERE scan_id=? AND status='pending'", (scan_id,)
        ).fetchone()[0])

    def prune_frontier(self, scan_id: int, actor_beam: int, repo_beam: int) -> None:
        # Keep highest priority pending actor and repository tasks. Completed work is never deleted.
        self._prune_kind(scan_id, "actor_stars", actor_beam)
        self._prune_kind(scan_id, "actor_events", max(50, actor_beam // 2))
        self._prune_kind(scan_id, "actor_repos", max(50, actor_beam // 2))
        self._prune_kind(scan_id, "repo_source", repo_beam * max(1, len(DEFAULT_SOURCES)))
        self._prune_kind(scan_id, "repo_detail", repo_beam)

    def _prune_kind(self, scan_id: int, kind: str, limit: int) -> None:
        ids = [int(r[0]) for r in self.conn.execute(
            "SELECT id FROM frontier_tasks WHERE scan_id=? AND status='pending' AND kind=? ORDER BY priority DESC,id ASC",
            (scan_id, kind),
        ).fetchall()]
        for task_id in ids[max(0, limit):]:
            self.finish_task(task_id, "pruned", "beam limit")

    def source_yield_update(self, scan_id: int, source: str, items: int, new_items: int, alpha: float) -> float:
        row = self.conn.execute(
            "SELECT * FROM source_yield WHERE scan_id=? AND source=?", (scan_id, source)
        ).fetchone()
        prev_ema = float(row["ema"]) if row else 0.0
        current = float(new_items)
        ema = current if not row else alpha * current + (1.0 - alpha) * prev_ema
        self.conn.execute(
            """
            INSERT INTO source_yield(scan_id,source,pages,items,new_items,ema)
            VALUES(?,?,1,?,?,?) ON CONFLICT(scan_id,source) DO UPDATE SET
            pages=pages+1,items=items+excluded.items,new_items=new_items+excluded.new_items,ema=excluded.ema
            """,
            (scan_id, source, items, new_items, ema),
        )
        self.conn.commit()
        return ema

    def update_api_resource(self, scan_id: int, headers: Mapping[str, str]) -> None:
        resource = str(headers.get("x-ratelimit-resource") or "unknown")
        if resource == "unknown" and not any(k.startswith("x-ratelimit") for k in headers):
            return
        def to_int(name: str) -> int | None:
            value = headers.get(name)
            return int(value) if value and str(value).isdigit() else None
        reset = headers.get("x-ratelimit-reset")
        reset_at = None
        if reset and str(reset).isdigit():
            reset_at = dt.datetime.fromtimestamp(int(reset), tz=dt.timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO api_resources(scan_id,resource,limit_value,remaining,used,reset_at,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(scan_id,resource) DO UPDATE SET
            limit_value=excluded.limit_value,remaining=excluded.remaining,used=excluded.used,reset_at=excluded.reset_at,updated_at=excluded.updated_at
            """,
            (scan_id, resource, to_int("x-ratelimit-limit"), to_int("x-ratelimit-remaining"),
             to_int("x-ratelimit-used"), reset_at, utc_now_iso()),
        )
        self.conn.commit()

    def transport_metric(self, scan_id: int, transport: str, *, requests: int = 0, cache_hits: int = 0,
                         items: int = 0, useful_items: int = 0, graphql_points: int = 0) -> None:
        self.conn.execute(
            """
            INSERT INTO transport_metrics(scan_id,transport,requests,cache_hits,items,useful_items,graphql_points)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(scan_id,transport) DO UPDATE SET
            requests=requests+excluded.requests,cache_hits=cache_hits+excluded.cache_hits,items=items+excluded.items,
            useful_items=useful_items+excluded.useful_items,graphql_points=graphql_points+excluded.graphql_points
            """,
            (scan_id, transport, requests, cache_hits, items, useful_items, graphql_points),
        )
        self.conn.commit()

    def total_profiles_and_df(self, repo_names: Iterable[str] | None = None) -> tuple[int, dict[str, int]]:
        total = int(self.conn.execute("SELECT COUNT(DISTINCT user_login) FROM user_stars").fetchone()[0])
        df: dict[str, int] = {}
        if repo_names is None:
            rows = self.conn.execute(
                "SELECT repo_full_name,COUNT(DISTINCT user_login) AS n FROM user_stars GROUP BY repo_full_name"
            ).fetchall()
            df = {str(r["repo_full_name"]): int(r["n"]) for r in rows}
        else:
            names = list(dict.fromkeys(repo_names))
            for i in range(0, len(names), 500):
                chunk = names[i:i+500]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"SELECT repo_full_name,COUNT(DISTINCT user_login) AS n FROM user_stars WHERE repo_full_name IN ({placeholders}) GROUP BY repo_full_name",
                    chunk,
                ).fetchall()
                df.update({str(r["repo_full_name"]): int(r["n"]) for r in rows})
        return max(1, total), df

    def previous_repo_names(self, scan_id: int, owner_user: str) -> set[str]:
        prev = self.latest_finished_scan_before(scan_id, owner_user)
        if prev is None:
            return set()
        return {str(r[0]) for r in self.conn.execute(
            "SELECT repo_full_name FROM scan_repo_scores WHERE scan_id=?", (prev,)
        ).fetchall()}

    def save_people_scores(self, scan_id: int, people: Sequence[PersonResult]) -> None:
        self.conn.execute("DELETE FROM scan_people_scores WHERE scan_id=?", (scan_id,))
        for p in people:
            self.conn.execute(
                """
                INSERT INTO scan_people_scores(scan_id,user_login,score,features_json,overlap_json,sources_json,seeds_json,paths_json,star_count)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (scan_id, p.login, p.score, json_dumps(p.features), json_dumps(p.overlap_repos),
                 json_dumps(p.source_names), json_dumps(p.seed_names), json_dumps(p.paths), p.star_count),
            )
        self.conn.commit()

    def save_repo_scores(self, scan_id: int, repos: Sequence[RepoResult]) -> None:
        self.conn.execute("DELETE FROM scan_repo_scores WHERE scan_id=?", (scan_id,))
        for r in repos:
            self.conn.execute(
                """
                INSERT INTO scan_repo_scores(scan_id,repo_full_name,score,features_json,supporters_json,flags_json,paths_json,new_since_previous)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (scan_id, r.repo.full_name, r.score, json_dumps(r.features), json_dumps(r.supporters),
                 json_dumps(r.flags), json_dumps(r.paths), int(r.new_since_previous)),
            )
        self.conn.commit()

    def feedback_add(self, owner_user: str, repo: str, rating: int | None, action: str) -> None:
        if rating is not None and rating not in {1,2,3,4,5}:
            raise StarBridgeError("rating must be 1..5")
        if action not in {"", "ignored", "saved", "interesting", "hide"}:
            raise StarBridgeError("action must be ignored, saved, interesting, hide, or empty")
        self.conn.execute(
            "INSERT INTO user_feedback(owner_user,repo_full_name,rating,action,created_at) VALUES(?,?,?,?,?)",
            (owner_user, normalize_repo(repo), rating, action, utc_now_iso()),
        )
        self.conn.commit()

    def suppression_penalty(self, owner_user: str, repo: str) -> float:
        # Direct negative memory plus deterministic pattern memory (language/topics).
        rows = self.conn.execute(
            "SELECT rating,action,created_at FROM user_feedback WHERE owner_user=? AND repo_full_name=?",
            (owner_user, repo),
        ).fetchall()
        penalty = 0.0
        for row in rows:
            age = parse_iso(row["created_at"])
            age_days = (utcnow() - age).total_seconds()/86400 if age else 0.0
            decay = math.exp(-age_days / 180.0)
            rating = row["rating"]
            action = row["action"]
            if action in {"ignored", "hide"} or (rating is not None and int(rating) <= 2):
                penalty += 0.06 * decay
            if action == "saved" or (rating is not None and int(rating) >= 4):
                penalty -= 0.04 * decay

        target = self.get_repo(repo)
        if target is not None:
            target_topics = set(target.topics)
            pattern_rows = self.conn.execute(
                """
                SELECT f.rating,f.action,f.created_at,r.language,r.topics_json
                FROM user_feedback f JOIN repos r ON r.full_name=f.repo_full_name
                WHERE f.owner_user=? AND f.repo_full_name<>?
                ORDER BY f.id DESC LIMIT 250
                """, (owner_user, repo),
            ).fetchall()
            pattern = 0.0
            for row in pattern_rows:
                negative = row["action"] in {"ignored", "hide"} or (row["rating"] is not None and int(row["rating"]) <= 2)
                positive = row["action"] == "saved" or (row["rating"] is not None and int(row["rating"]) >= 4)
                if not negative and not positive:
                    continue
                other_topics = set(json.loads(row["topics_json"] or "[]"))
                topic_overlap = len(target_topics & other_topics) / max(1, len(target_topics | other_topics)) if (target_topics or other_topics) else 0.0
                lang_match = 1.0 if target.language and target.language == str(row["language"] or "") else 0.0
                similarity = 0.65 * topic_overlap + 0.35 * lang_match
                if similarity < 0.20:
                    continue
                age = parse_iso(row["created_at"]); age_days = (utcnow() - age).total_seconds()/86400 if age else 0.0
                decay = math.exp(-age_days / 240.0)
                if negative:
                    pattern += 0.012 * similarity * decay
                elif positive:
                    pattern -= 0.008 * similarity * decay
            penalty += clamp(pattern, -0.10, 0.18)
        return clamp(penalty, 0.0, 0.40)

    def setting_get(self, owner_user: str, key: str, default: Any) -> Any:
        row = self.conn.execute(
            "SELECT value_json FROM settings WHERE owner_user=? AND key=?", (owner_user, key)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def setting_set(self, owner_user: str, key: str, value: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO settings(owner_user,key,value_json,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(owner_user,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at
            """,
            (owner_user, key, json_dumps(value), utc_now_iso()),
        )
        self.conn.commit()

    def scan_metric_set(self, scan_id: int, key: str, value: float, text: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO scan_metrics(scan_id,key,value,text_value) VALUES(?,?,?,?)
            ON CONFLICT(scan_id,key) DO UPDATE SET value=excluded.value,text_value=excluded.text_value
            """,
            (scan_id, key, float(value), text),
        )
        self.conn.commit()


class GitHubClient:
    def __init__(self, storage: Storage, token: str | None, *, scan_id: int | None = None,
                 pause_seconds: float = 0.12, retry_count: int = 3):
        self.storage = storage
        self.token = token
        self.scan_id = scan_id
        self.pause_seconds = max(0.0, float(pause_seconds))
        self.retry_count = max(0, int(retry_count))
        self.graphql_disabled_reason: str | None = None

    def set_scan(self, scan_id: int | None) -> None:
        self.scan_id = scan_id

    def _headers(self, accept: str, etag: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    @staticmethod
    def _links(link_header: str | None) -> dict[str, str]:
        result: dict[str, str] = {}
        if not link_header:
            return result
        for chunk in link_header.split(","):
            m = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', chunk)
            if m:
                result[m.group(2)] = m.group(1)
        return result

    def _consume(self, amount: int = 1) -> None:
        if self.scan_id is not None:
            self.storage.consume_budget(self.scan_id, amount)

    def _record_headers(self, headers: Mapping[str, str]) -> None:
        if self.scan_id is not None:
            self.storage.update_api_resource(self.scan_id, headers)

    def _record_transport(self, transport: str, **kwargs: int) -> None:
        if self.scan_id is not None:
            self.storage.transport_metric(self.scan_id, transport, **kwargs)

    def request_json(self, path_or_url: str, *, accept: str = DEFAULT_MEDIA,
                     method: str = "GET", body: Mapping[str, Any] | None = None,
                     allow_cache: bool = True) -> tuple[Any, dict[str, str], bool]:
        url = path_or_url if path_or_url.startswith("http") else API_BASE + path_or_url
        method = method.upper()
        cached = self.storage.cache_get(url, accept) if method == "GET" and allow_cache else None
        etag = cached[0] if cached else None
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            self._consume(1)
            headers = self._headers(accept, etag if method == "GET" else None)
            if payload is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    data = json.loads(raw) if raw else None
                    resp_headers = {k.lower(): v for k, v in response.headers.items()}
                    self._record_headers(resp_headers)
                    if method == "GET" and allow_cache:
                        self.storage.cache_put(url, accept, resp_headers.get("etag"), data, resp_headers)
                    self._record_transport("rest", requests=1, items=len(data) if isinstance(data, list) else int(data is not None))
                    if self.pause_seconds:
                        time.sleep(self.pause_seconds)
                    return data, resp_headers, False
            except urllib.error.HTTPError as exc:
                resp_headers = {k.lower(): v for k, v in exc.headers.items()}
                self._record_headers(resp_headers)
                if exc.code == 304 and cached is not None:
                    # Authenticated conditional requests returning 304 do not consume primary rate limit.
                    if self.scan_id is not None and self.token:
                        self.storage.refund_budget(self.scan_id, 1)
                    self._record_transport("rest", requests=1, cache_hits=1,
                                           items=len(cached[1]) if isinstance(cached[1], list) else int(cached[1] is not None))
                    return cached[1], cached[2], True

                raw = exc.read().decode("utf-8", errors="replace")
                message = raw
                try:
                    obj = json.loads(raw)
                    message = str(obj.get("message") or raw)
                except json.JSONDecodeError:
                    pass

                if exc.code in {403, 429}:
                    remaining = resp_headers.get("x-ratelimit-remaining")
                    retry_after = resp_headers.get("retry-after")
                    reset = resp_headers.get("x-ratelimit-reset")
                    lower = message.lower()
                    is_rate = remaining == "0" or "rate limit" in lower or "secondary rate" in lower
                    if is_rate:
                        wait = 0
                        if retry_after and retry_after.isdigit():
                            wait = int(retry_after)
                        elif remaining == "0" and reset and reset.isdigit():
                            wait = max(0, int(reset) - int(time.time()) + 2)
                        elif "secondary" in lower:
                            wait = 60 * (2 ** min(attempt, 3))
                        if wait and wait <= 30 and attempt < self.retry_count:
                            print(f"[rate] GitHub asks to wait {wait}s; retrying ...", file=sys.stderr)
                            time.sleep(wait)
                            continue
                        when = ""
                        if reset and reset.isdigit():
                            when = dt.datetime.fromtimestamp(int(reset), tz=dt.timezone.utc).isoformat()
                        raise RateLimitPause(
                            f"GitHub rate limit paused the scan. {message}" + (f" Reset: {when}" if when else "")
                        ) from exc

                if exc.code in {404, 409, 422}:
                    raise RecoverableTaskError(f"GitHub {exc.code} for {url}: {message}") from exc
                if exc.code in {500, 502, 503, 504} and attempt < self.retry_count:
                    time.sleep(min(8.0, 1.5 * (2 ** attempt)))
                    last_error = exc
                    continue
                raise StarBridgeError(f"GitHub API returned {exc.code} for {url}: {message}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.retry_count:
                    time.sleep(min(8.0, 1.5 * (2 ** attempt)))
                    continue
                raise StarBridgeError(f"Network error for {url}: {exc.reason}") from exc

        raise StarBridgeError(f"Request failed for {url}: {last_error}")

    def graphql(self, query: str, variables: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        if not self.token:
            raise StarBridgeError("GraphQL transport requires a GitHub token")
        self._consume(1)
        payload = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
        headers = self._headers(DEFAULT_MEDIA)
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(GRAPHQL_URL, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read().decode("utf-8", errors="replace")
                obj = json.loads(raw) if raw else {}
                resp_headers = {k.lower(): v for k, v in response.headers.items()}
                self._record_headers(resp_headers)
                if obj.get("errors"):
                    raise StarBridgeError("GraphQL errors: " + "; ".join(str(e.get("message") or e) for e in obj["errors"]))
                data = obj.get("data") or {}
                rate = data.get("rateLimit") if isinstance(data, Mapping) else None
                cost = int(rate.get("cost") or 0) if isinstance(rate, Mapping) else 0
                self._record_transport("graphql", requests=1, graphql_points=cost)
                if self.pause_seconds:
                    time.sleep(self.pause_seconds)
                return dict(data), resp_headers
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            headers_l = {k.lower(): v for k, v in exc.headers.items()}
            self._record_headers(headers_l)
            if exc.code in {403, 429}:
                raise RateLimitPause(f"GraphQL rate limit/forbidden: {raw}") from exc
            raise StarBridgeError(f"GraphQL HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise StarBridgeError(f"GraphQL network error: {exc.reason}") from exc

    def viewer(self) -> dict[str, Any]:
        data, _, _ = self.request_json("/user", allow_cache=False)
        if not isinstance(data, Mapping):
            raise StarBridgeError("Unexpected /user response")
        return dict(data)

    def rate_limit(self) -> dict[str, Any]:
        data, _, _ = self.request_json("/rate_limit", allow_cache=False)
        return dict(data) if isinstance(data, Mapping) else {}

    def get_repo(self, full_name: str) -> RepoRecord:
        owner, repo = split_repo(full_name)
        data, _, _ = self.request_json(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}")
        if not isinstance(data, Mapping):
            raise RecoverableTaskError(f"Unexpected repository response for {full_name}")
        return RepoRecord.from_rest(data)

    def get_star_page_rest(self, username: str, *, url: str | None = None, authenticated_self: bool = False
                           ) -> tuple[list[StarRecord], str | None, dict[str, str]]:
        if url is None:
            if authenticated_self:
                path = "/user/starred?sort=created&direction=desc&per_page=100"
            else:
                path = f"/users/{urllib.parse.quote(username)}/starred?sort=created&direction=desc&per_page=100"
        else:
            path = url
        data, headers, _ = self.request_json(path, accept=STAR_MEDIA)
        if not isinstance(data, list):
            raise RecoverableTaskError(f"Expected star list for {username}")
        stars: list[StarRecord] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            if isinstance(item.get("repo"), Mapping):
                repo_obj = item["repo"]
                starred_at = item.get("starred_at")
            else:
                repo_obj = item
                starred_at = None
            repo = RepoRecord.from_rest(repo_obj)
            if repo.full_name:
                stars.append(StarRecord(repo=repo, starred_at=str(starred_at) if starred_at else None))
        next_url = self._links(headers.get("link")).get("next")
        return stars, next_url, headers

    def get_all_owner_stars(self, username: str, max_pages: int, private_policy: str,
                            cutoff: dt.datetime | None) -> list[StarRecord]:
        # Prefer /user/starred for the authenticated owner, as specified by the paper.
        authenticated_self = False
        if self.token:
            try:
                viewer = self.viewer()
                authenticated_self = str(viewer.get("login") or "").lower() == username.lower()
            except StarBridgeError:
                authenticated_self = False
        url: str | None = None
        out: list[StarRecord] = []
        page = 1
        while True:
            if max_pages > 0 and page > max_pages:
                break
            stars, next_url, _ = self.get_star_page_rest(username, url=url, authenticated_self=authenticated_self and page == 1)
            for star in stars:
                if star.repo.private and private_policy == "ignore":
                    continue
                ts = parse_iso(star.starred_at)
                if cutoff is not None and ts is not None and ts >= cutoff:
                    continue
                out.append(star)
            if not next_url:
                break
            url = next_url
            page += 1
        return out

    def repo_source_page(self, full_name: str, source: str, *, url: str | None = None) -> tuple[list[Mapping[str, Any]], str | None]:
        owner, repo = split_repo(full_name)
        if url is None:
            q_owner = urllib.parse.quote(owner); q_repo = urllib.parse.quote(repo)
            if source == "contributors":
                path = f"/repos/{q_owner}/{q_repo}/contributors?anon=false&per_page=100"
            elif source == "forks":
                path = f"/repos/{q_owner}/{q_repo}/forks?sort=newest&per_page=100"
            elif source == "issues":
                path = f"/repos/{q_owner}/{q_repo}/issues?state=all&sort=updated&direction=desc&per_page=100"
            elif source == "pulls":
                path = f"/repos/{q_owner}/{q_repo}/pulls?state=all&sort=updated&direction=desc&per_page=100"
            elif source == "comments":
                path = f"/repos/{q_owner}/{q_repo}/issues/comments?sort=updated&direction=desc&per_page=100"
            elif source == "reviews":
                path = f"/repos/{q_owner}/{q_repo}/pulls/comments?sort=updated&direction=desc&per_page=100"
            elif source == "commits":
                path = f"/repos/{q_owner}/{q_repo}/commits?per_page=100"
            elif source == "releases":
                path = f"/repos/{q_owner}/{q_repo}/releases?per_page=100"
            else:
                raise RecoverableTaskError(f"Unknown repository source: {source}")
        else:
            path = url
        data, headers, _ = self.request_json(path)
        if not isinstance(data, list):
            raise RecoverableTaskError(f"Expected list from {source} for {full_name}")
        return [x for x in data if isinstance(x, Mapping)], self._links(headers.get("link")).get("next")

    def public_events_page(self, username: str, *, url: str | None = None) -> tuple[list[Mapping[str, Any]], str | None]:
        path = url or f"/users/{urllib.parse.quote(username)}/events/public?per_page=100"
        data, headers, _ = self.request_json(path)
        if not isinstance(data, list):
            raise RecoverableTaskError(f"Expected events list for {username}")
        return [x for x in data if isinstance(x, Mapping)], self._links(headers.get("link")).get("next")

    def public_repos_page(self, username: str, *, url: str | None = None) -> tuple[list[RepoRecord], str | None]:
        path = url or f"/users/{urllib.parse.quote(username)}/repos?type=owner&sort=updated&direction=desc&per_page=100"
        data, headers, _ = self.request_json(path)
        if not isinstance(data, list):
            raise RecoverableTaskError(f"Expected repositories list for {username}")
        repos = [RepoRecord.from_rest(x) for x in data if isinstance(x, Mapping)]
        return [r for r in repos if r.full_name], self._links(headers.get("link")).get("next")

    def graphql_star_batch_first(self, usernames: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not usernames:
            return {}
        fields: list[str] = []
        variables_decl: list[str] = []
        variables: dict[str, str] = {}
        for i, username in enumerate(usernames):
            alias = f"u{i}"
            var = f"login{i}"
            variables_decl.append(f"${var}: String!")
            variables[var] = username
            fields.append(
                f"""
                {alias}: user(login: ${var}) {{
                  login
                  starredRepositories(first: 100, orderBy: {{field: STARRED_AT, direction: DESC}}) {{
                    totalCount
                    isOverLimit
                    pageInfo {{ hasNextPage endCursor }}
                    edges {{
                      cursor
                      starredAt
                      node {{
                        nameWithOwner
                        url
                        description
                        stargazerCount
                        isArchived
                        isFork
                        isDisabled
                        isPrivate
                        pushedAt
                        createdAt
                        updatedAt
                        owner {{ login }}
                        primaryLanguage {{ name }}
                        repositoryTopics(first: 10) {{ nodes {{ topic {{ name }} }} }}
                      }}
                    }}
                  }}
                }}
                """
            )
        query = "query(" + ", ".join(variables_decl) + ") {\n" + "\n".join(fields) + "\nrateLimit { cost remaining resetAt }\n}"
        data, _ = self.graphql(query, variables)
        result: dict[str, dict[str, Any]] = {}
        for i, username in enumerate(usernames):
            node = data.get(f"u{i}")
            if not isinstance(node, Mapping):
                result[username] = {"stars": [], "has_next": False, "is_over_limit": False, "total_count": 0}
                continue
            conn = node.get("starredRepositories") if isinstance(node.get("starredRepositories"), Mapping) else {}
            edges = conn.get("edges") if isinstance(conn.get("edges"), list) else []
            stars: list[StarRecord] = []
            for edge in edges:
                if not isinstance(edge, Mapping) or not isinstance(edge.get("node"), Mapping):
                    continue
                repo = RepoRecord.from_graphql(edge["node"])
                if repo.full_name and not repo.private:
                    stars.append(StarRecord(repo, str(edge.get("starredAt") or "") or None))
            page_info = conn.get("pageInfo") if isinstance(conn.get("pageInfo"), Mapping) else {}
            result[username] = {
                "stars": stars,
                "has_next": bool(page_info.get("hasNextPage")),
                "end_cursor": page_info.get("endCursor"),
                "is_over_limit": bool(conn.get("isOverLimit")),
                "total_count": int(conn.get("totalCount") or len(stars)),
            }
        return result


class ScoringEngine:
    def __init__(self, storage: Storage, scan_id: int, config: ScanConfig):
        self.storage = storage
        self.scan_id = scan_id
        self.config = config
        self.owner_stars = storage.owner_profile(scan_id)
        self.owner_map = {s.repo.full_name: s for s in self.owner_stars}
        self.owner_names = set(self.owner_map)
        self.seed_names = storage.seed_names(scan_id)
        self.explicit_seed_names = {normalize_repo(x) for x in config.explicit_seeds}
        # Explicit-only seed runs are a repository-centric discovery mode. In that mode
        # a person may be relevant because the crawl reached them structurally from the
        # requested seed even when they share zero repositories with the owner's small
        # personal star profile. This is essential for external seed discovery.
        self.explicit_focus_mode = bool(self.explicit_seed_names) and config.auto_seeds == 0
        self.total_profiles, self.df = storage.total_profiles_and_df()
        self.person_weights = self._normalized_weights(
            storage.setting_get(config.user, "person_weights", PERSON_DEFAULT_WEIGHTS),
            PERSON_DEFAULT_WEIGHTS,
        )
        self.repo_weights = self._normalized_weights(
            storage.setting_get(config.user, "repo_weights", REPO_DEFAULT_WEIGHTS),
            REPO_DEFAULT_WEIGHTS,
        )

    @staticmethod
    def _normalized_weights(value: Any, defaults: Mapping[str, float]) -> dict[str, float]:
        result = dict(defaults)
        if isinstance(value, Mapping):
            for k in result:
                try:
                    result[k] = max(0.0, float(value.get(k, result[k])))
                except (TypeError, ValueError):
                    pass
        total = sum(result.values()) or 1.0
        return {k: v / total for k, v in result.items()}

    def repo_interest_weight(self, repo: RepoRecord) -> float:
        df = self.df.get(repo.full_name, 0)
        g = normalized_global_rarity(repo.stargazers_count)
        l = normalized_local_idf(self.total_profiles, df)
        return max(0.02, (g ** 0.65) * ((0.25 + 0.75 * l) ** 0.75))

    def person_score_one(self, login: str, *, require_overlap: bool = True) -> PersonResult | None:
        stars = self.storage.user_star_records(login, public_only=True)
        if not stars:
            return None
        cand_map = {s.repo.full_name: s for s in stars}
        overlap = set(cand_map) & self.owner_names

        candidate = self.storage.candidate_row(self.scan_id, login)
        sources: list[str] = []
        structural_seeds: list[str] = []
        paths: list[list[dict[str, str]]] = []
        if candidate:
            sources = json.loads(candidate["sources_json"] or "[]")
            structural_seeds = json.loads(candidate["seeds_json"] or "[]")
            paths = json.loads(candidate["paths_json"] or "[]")

        # Normal scans require overlap with the owner's stars. Explicit-seed scans need
        # a second admissibility path: structural connection to the requested seed.
        # With --auto-seeds 0 every promoted seed descends from an explicit seed, so any
        # non-empty structural seed edge is part of the focus lineage and stays eligible
        # across recursive hops.
        focus_bridge = False
        if self.explicit_seed_names:
            structural_set = set(structural_seeds)
            focus_bridge = bool(structural_set & self.explicit_seed_names)
            if self.explicit_focus_mode and structural_set:
                focus_bridge = True
        if require_overlap and len(overlap) < self.config.min_overlap and not focus_bridge:
            return None

        all_names = self.owner_names | set(cand_map)
        if any(name not in self.df for name in all_names):
            self.total_profiles, new_df = self.storage.total_profiles_and_df(all_names)
            self.df.update(new_df)

        def w(name: str) -> float:
            star = self.owner_map.get(name) or cand_map.get(name)
            assert star is not None
            return self.repo_interest_weight(star.repo)

        overlap_weight = sum(w(name) for name in overlap)
        owner_total = sum(w(name) for name in self.owner_names) or 1.0
        cand_total = sum(w(name) for name in cand_map) or 1.0
        union_weight = sum(w(name) for name in all_names) or 1.0

        rare_overlap = exp_saturate(overlap_weight, 1.6)
        weighted_jaccard = clamp(overlap_weight / union_weight)
        containment = clamp(overlap_weight / min(owner_total, cand_total))

        temporal_terms: list[float] = []
        for name in overlap:
            temporal_terms.append(math.sqrt(
                recency_weight(self.owner_map[name].starred_at, 720.0)
                * recency_weight(cand_map[name].starred_at, 720.0)
            ))
        temporal = statistics.fmean(temporal_terms) if temporal_terms else 0.0

        starred_seeds = set(cand_map) & self.seed_names
        seed_count = len(starred_seeds | set(structural_seeds))
        seed_affinity = exp_saturate(seed_count, max(1.0, min(4.0, len(self.seed_names) / 4.0)))
        structural = exp_saturate(len(set(sources)) + 0.35 * len(paths), 2.4)

        features = {
            "rare_overlap": clamp(rare_overlap),
            "weighted_jaccard": clamp(weighted_jaccard),
            "containment": clamp(containment),
            "temporal": clamp(temporal),
            "seed_affinity": clamp(seed_affinity),
            "structural": clamp(structural),
        }
        score = sum(features[k] * self.person_weights[k] for k in self.person_weights)
        overlap_sorted = sorted(overlap, key=lambda n: w(n), reverse=True)
        return PersonResult(
            login=login,
            score=clamp(score),
            features=features,
            overlap_repos=overlap_sorted,
            source_names=sorted(set(sources)),
            seed_names=sorted(starred_seeds | set(structural_seeds)),
            paths=paths[:10],
            star_count=len(cand_map),
        )

    def person_qualifies(self, person: PersonResult | None) -> bool:
        if person is None:
            return False
        if len(person.overlap_repos) >= self.config.min_overlap:
            return True
        seeds = set(person.seed_names)
        if not seeds or not self.explicit_seed_names:
            return False
        if seeds & self.explicit_seed_names:
            return True
        return self.explicit_focus_mode

    def score_people(self) -> list[PersonResult]:
        people: list[PersonResult] = []
        for login in self.storage.candidate_logins(self.scan_id, self.config.actor_beam):
            person = self.person_score_one(login, require_overlap=True)
            if person is not None:
                people.append(person)
        people.sort(key=lambda p: (p.score, len(p.overlap_repos)), reverse=True)
        return people

    def score_repos(self, people: Sequence[PersonResult]) -> list[RepoResult]:
        people_map = {p.login: p for p in people}
        rows = self.storage.conn.execute(
            "SELECT * FROM repo_support WHERE scan_id=? ORDER BY id", (self.scan_id,)
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        repo_names: set[str] = set()
        for row in rows:
            # Never recommend something the user already starred, nor the explicit
            # repository that was supplied as the starting point of a focus scan.
            if row["repo_full_name"] in self.owner_names or row["repo_full_name"] in self.explicit_seed_names:
                continue
            grouped[str(row["repo_full_name"])].append(row)
            repo_names.add(str(row["repo_full_name"]))
        self.total_profiles, extra_df = self.storage.total_profiles_and_df(repo_names)
        self.df.update(extra_df)

        previous = self.storage.previous_repo_names(self.scan_id, self.config.user)
        cutoff_recent = utcnow() - dt.timedelta(days=self.config.recent_days)
        results: list[RepoResult] = []

        for full_name, support_rows in grouped.items():
            repo = self.storage.get_repo(full_name)
            if repo is None or repo.private or repo.disabled:
                continue
            if repo.fork and not self.config.include_forks:
                continue
            if repo.archived and not self.config.include_archived:
                continue
            if self.config.max_repo_stars > 0 and repo.stargazers_count > self.config.max_repo_stars:
                continue

            supporter_entries: list[dict[str, Any]] = []
            strength_raw = 0.0
            distinct_supporters: set[str] = set()
            recent_supporters: set[str] = set()
            path_hashes: set[str] = set()
            paths: list[list[dict[str, str]]] = []

            for row in support_rows:
                login = str(row["user_login"])
                person = people_map.get(login)
                if person is None:
                    continue
                relation = str(row["relation"])
                relation_weight = RELATION_WEIGHTS.get(relation, 0.25)
                occurred_at = row["occurred_at"]
                temporal = recency_weight(occurred_at, max(30.0, self.config.recent_days * 0.8), missing=0.45)
                contribution = person.score * relation_weight * (0.35 + 0.65 * temporal)
                strength_raw += contribution
                distinct_supporters.add(login)
                ts = parse_iso(occurred_at)
                if ts and ts >= cutoff_recent:
                    recent_supporters.add(login)
                path = json.loads(row["path_json"] or "[]")
                if path:
                    h = stable_hash(json_dumps(path))
                    if h not in path_hashes:
                        path_hashes.add(h)
                        paths.append(path)
                supporter_entries.append({
                    "login": login,
                    "person_score": round(person.score, 6),
                    "relation": relation,
                    "occurred_at": occurred_at,
                    "contribution": round(contribution, 6),
                })

            if not supporter_entries:
                continue

            support_strength = exp_saturate(strength_raw, 1.25)
            supporter_diversity = exp_saturate(len(distinct_supporters), 2.2)
            g_rarity = normalized_global_rarity(repo.stargazers_count)
            l_rarity = normalized_local_idf(self.total_profiles, self.df.get(full_name, 0))
            temporal_velocity = exp_saturate(len(recent_supporters), 1.8)
            activity_recency = recency_weight(repo.pushed_at, 365.0, missing=0.30)
            no_topics = 1.0 if not repo.topics else 0.0
            path_diversity = exp_saturate(len(path_hashes), 2.5)

            features = {
                "support_strength": clamp(support_strength),
                "supporter_diversity": clamp(supporter_diversity),
                "global_rarity": clamp(g_rarity),
                "local_rarity": clamp(l_rarity),
                "temporal_velocity": clamp(temporal_velocity),
                "activity_recency": clamp(activity_recency),
                "no_topics": no_topics,
                "path_diversity": clamp(path_diversity),
            }
            score = sum(features[k] * self.repo_weights[k] for k in self.repo_weights)
            penalty = self.storage.suppression_penalty(self.config.user, full_name)
            score *= (1.0 - penalty)

            flags: list[str] = []
            if not repo.topics:
                flags.append("NO_TOPICS")
            if repo.stargazers_count <= 500:
                flags.append("RARE")
            if full_name not in previous:
                flags.append("NEW")
            early_signal = (
                repo.stargazers_count <= 1500
                and len(distinct_supporters) >= 2
                and len(recent_supporters) >= 2
                and activity_recency >= 0.20
            )
            if early_signal:
                flags.append("EARLY_SIGNAL")
                score = min(1.0, score * 1.08)

            supporter_entries.sort(key=lambda x: x["contribution"], reverse=True)
            paths.sort(key=len)
            result = RepoResult(
                repo=repo,
                score=clamp(score),
                features=features,
                supporters=supporter_entries[:30],
                flags=flags,
                paths=paths[:10],
                new_since_previous=full_name not in previous,
            )
            results.append(result)
            for path in result.paths:
                self.storage.add_discovery_path(self.scan_id, "repo", full_name, path, result.score)

        # Diversity pressure: reduce repeated dominance by a single top supporter while preserving score order quality.
        results.sort(key=lambda r: r.score, reverse=True)
        supporter_seen: Counter[str] = Counter()
        adjusted: list[RepoResult] = []
        for result in results:
            top = result.supporters[0]["login"] if result.supporters else ""
            concentration = supporter_seen[top]
            if top:
                result.score *= 1.0 / (1.0 + 0.025 * concentration)
                supporter_seen[top] += 1
            adjusted.append(result)
        adjusted.sort(key=lambda r: r.score, reverse=True)
        return adjusted


class SeedPortfolioOptimizer:
    """Greedy seed portfolio. Before actor neighborhoods exist, metadata diversity is the proxy.
    Later multi-hop promotion uses graph/path novelty and therefore supplies the actor-diversity part of the paper.
    """

    def __init__(self, count: int, pool: int):
        self.count = max(0, count)
        self.pool = max(self.count, pool)

    def base_value(self, star: StarRecord) -> float:
        repo = star.repo
        if repo.archived or repo.disabled or repo.private:
            return 0.0
        if repo.fork:
            return 0.0
        rarity = normalized_global_rarity(repo.stargazers_count)
        recency = recency_weight(star.starred_at, 900.0)
        activity = recency_weight(repo.pushed_at, 900.0, missing=0.4)
        no_topics = 1.08 if not repo.topics else 1.0
        return rarity * (0.55 + 0.25 * recency + 0.20 * activity) * no_topics

    def select(self, owner_stars: Sequence[StarRecord], explicit: Sequence[str]) -> list[tuple[str, float, str]]:
        explicit_norm = [normalize_repo(x) for x in explicit]
        by_name = {s.repo.full_name: s for s in owner_stars}
        candidates = sorted(owner_stars, key=self.base_value, reverse=True)[: self.pool]
        selected: list[tuple[str, float, str]] = []
        seen: set[str] = set()
        used_languages: Counter[str] = Counter()
        used_topics: Counter[str] = Counter()
        used_owners: Counter[str] = Counter()

        for name in explicit_norm:
            selected.append((name, 10.0, "explicit"))
            seen.add(name)
            star = by_name.get(name)
            if star:
                used_languages[star.repo.language or "?"] += 1
                used_owners[star.repo.owner_login or "?"] += 1
                used_topics.update(star.repo.topics)

        while len([x for x in selected if x[2] != "explicit"]) < self.count:
            best: tuple[float, StarRecord] | None = None
            for star in candidates:
                repo = star.repo
                if repo.full_name in seen:
                    continue
                base = self.base_value(star)
                if base <= 0:
                    continue
                lang_bonus = 1.0 / (1.0 + 0.20 * used_languages[repo.language or "?"])
                owner_bonus = 1.0 / (1.0 + 0.25 * used_owners[repo.owner_login or "?"])
                topic_hits = sum(used_topics[t] for t in repo.topics)
                topic_bonus = 1.0 / (1.0 + 0.07 * topic_hits)
                marginal = base * lang_bonus * owner_bonus * topic_bonus
                if best is None or marginal > best[0]:
                    best = (marginal, star)
            if best is None:
                break
            score, star = best
            repo = star.repo
            selected.append((repo.full_name, score, "portfolio"))
            seen.add(repo.full_name)
            used_languages[repo.language or "?"] += 1
            used_owners[repo.owner_login or "?"] += 1
            used_topics.update(repo.topics)
        return selected



class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: str) -> str:
        self.add(x)
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


class StarBridgeEngine:
    """A-RIR runtime: adaptive frontier + recursive repository/person expansion."""

    def __init__(self, storage: Storage, client: GitHubClient, config: ScanConfig, scan_id: int):
        self.storage = storage
        self.client = client
        self.config = config.normalized()
        self.scan_id = scan_id
        self.client.set_scan(scan_id)
        self.owner = config.user
        self.owner_lower = config.user.lower()
        self.graphql_enabled = bool(client.token) and config.transport in {"auto", "graphql"}
        self._task_counter = 0
        self._last_score_refresh = 0

    def _eligible_repo(self, repo: RepoRecord) -> bool:
        if not repo.full_name or repo.private or repo.disabled:
            return False
        if repo.archived and not self.config.include_archived:
            return False
        if repo.fork and not self.config.include_forks:
            return False
        if self.config.max_repo_stars > 0 and repo.stargazers_count > self.config.max_repo_stars:
            return False
        return True

    def _repo_novelty(self, repo: RepoRecord) -> float:
        rarity = normalized_global_rarity(repo.stargazers_count)
        topic_bonus = 1.0 if not repo.topics else 0.72
        activity = recency_weight(repo.pushed_at, 900.0, missing=0.4)
        return clamp(0.55 * rarity + 0.20 * topic_bonus + 0.25 * activity, 0.05, 1.0)

    def _path_extend(self, path: Sequence[Mapping[str, str]], kind: str, value: str) -> list[dict[str, str]]:
        result = [dict(x) for x in path]
        node = {"type": kind, "id": value}
        if not result or result[-1] != node:
            result.append(node)
        return result

    def _source_expected_yield(self, source: str) -> float:
        row = self.storage.conn.execute(
            "SELECT ema FROM source_yield WHERE scan_id=? AND source=?", (self.scan_id, source)
        ).fetchone()
        if row and float(row["ema"] or 0) > 0:
            return max(1.0, float(row["ema"]))
        defaults = {
            "contributors": 35.0, "forks": 30.0, "issues": 22.0, "pulls": 20.0,
            "comments": 30.0, "reviews": 22.0, "commits": 28.0, "releases": 8.0,
            "owner": 1.0, "actor_stars": 55.0, "events": 20.0, "public_repos": 12.0,
        }
        return defaults.get(source, 10.0)

    def _enqueue_repo_expansion(
        self,
        repo: RepoRecord,
        *,
        depth: int,
        reason: str,
        relevance: float,
        path: Sequence[Mapping[str, str]],
        parent_task_id: int | None = None,
    ) -> bool:
        if depth > self.config.max_depth or not self._eligible_repo(repo):
            return False
        path2 = self._path_extend(path, "repo", repo.full_name)
        promoted = self.storage.promote_seed(
            self.scan_id, repo.full_name, depth, reason, relevance, parent_task_id, path2
        )
        if not promoted:
            return False
        self.storage.save_repo(repo, self.scan_id)
        novelty = self._repo_novelty(repo)
        # Owner is a zero-network-cost source, represented as a frontier task for reproducibility.
        if "owner" in self.config.sources and repo.owner_login and repo.owner_login.lower() != self.owner_lower:
            self.storage.enqueue_task(
                self.scan_id, "repo_source", repo.full_name, source="owner", depth=depth, page_no=1,
                expected_yield=1.0, novelty=novelty, relevance=relevance,
                confidence=1.0, cost=0.15, parent_task_id=parent_task_id, path=path2,
            )
        for source in self.config.sources:
            if source == "owner":
                continue
            if source not in SOURCE_WEIGHTS:
                continue
            self.storage.enqueue_task(
                self.scan_id, "repo_source", repo.full_name, source=source, depth=depth, page_no=1,
                expected_yield=self._source_expected_yield(source), novelty=novelty,
                relevance=relevance, confidence=0.85, cost=1.0,
                parent_task_id=parent_task_id, path=path2,
            )
        return True

    @staticmethod
    def _is_bot_login(login: str, user_type: str = "") -> bool:
        low = login.lower()
        return user_type.lower() == "bot" or low.endswith("[bot]") or low.endswith("-bot") or low == "github-actions"

    def _extract_actors(self, source: str, items: Sequence[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any], float]]:
        found: dict[str, tuple[Mapping[str, Any], float]] = {}

        def add(obj: Any, strength: float = 1.0) -> None:
            if not isinstance(obj, Mapping):
                return
            login = str(obj.get("login") or "")
            if not login or login.lower() == self.owner_lower or self._is_bot_login(login, str(obj.get("type") or "")):
                return
            old = found.get(login)
            if old is None or strength > old[1]:
                found[login] = (obj, strength)

        for item in items:
            if source == "contributors":
                contributions = int(item.get("contributions") or 0)
                add(item, 1.0 + min(0.8, math.log1p(contributions) / 10.0))
            elif source == "forks":
                add(item.get("owner"), 1.0)
            elif source in {"issues", "pulls", "comments", "reviews"}:
                add(item.get("user"), 1.0)
            elif source == "commits":
                add(item.get("author"), 1.0)
                add(item.get("committer"), 0.85)
            elif source == "releases":
                add(item.get("author"), 1.0)
        return [(login, obj, strength) for login, (obj, strength) in found.items()]

    def _add_actor_from_repo(
        self, login: str, user_obj: Mapping[str, Any] | str, *, repo: str, source: str,
        depth: int, relevance: float, strength: float, path: Sequence[Mapping[str, str]],
        parent_task_id: int | None,
    ) -> bool:
        if not login or login.lower() == self.owner_lower or self._is_bot_login(login):
            return False
        self.storage.save_user(user_obj)
        actor_path = self._path_extend(path, "user", login)
        edge_new = self.storage.add_actor_edge(
            self.scan_id, repo, login, source, depth, strength, actor_path
        )
        source_weight = SOURCE_WEIGHTS.get(source, 0.5)
        candidate_relevance = clamp(relevance * source_weight * (0.75 + 0.25 * min(2.0, strength)), 0.01, 1.0)
        self.storage.add_candidate(
            self.scan_id, login, candidate_relevance, strength * source_weight,
            source, repo, depth, actor_path,
        )
        self.storage.add_discovery_path(self.scan_id, "person", login, actor_path, candidate_relevance)
        if edge_new:
            self.storage.enqueue_task(
                self.scan_id, "actor_stars", login, source="stars", depth=depth,
                page_no=1, expected_yield=self._source_expected_yield("actor_stars"),
                novelty=0.85, relevance=candidate_relevance, confidence=0.90, cost=1.0,
                parent_task_id=parent_task_id, path=actor_path,
            )
        return edge_new

    def _process_repo_source(self, task: Task) -> None:
        repo = self.storage.get_repo(task.node_id)
        if repo is None:
            try:
                repo = self.client.get_repo(task.node_id)
                self.storage.save_repo(repo, self.scan_id)
            except RecoverableTaskError:
                self.storage.finish_task(task.id, "failed", "repository unavailable")
                return
        if task.source == "owner":
            new = 0
            if repo.owner_login:
                new = int(self._add_actor_from_repo(
                    repo.owner_login, repo.owner_login, repo=repo.full_name, source="owner",
                    depth=task.depth, relevance=task.relevance, strength=1.0,
                    path=task.path, parent_task_id=task.id,
                ))
            self.storage.source_yield_update(self.scan_id, "owner", 1, new, self.config.ema_alpha)
            self.storage.finish_task(task.id)
            return

        items, next_url = self.client.repo_source_page(repo.full_name, task.source, url=task.url)
        actors = self._extract_actors(task.source, items)
        new_count = 0
        for login, obj, strength in actors:
            if self._add_actor_from_repo(
                login, obj, repo=repo.full_name, source=task.source, depth=task.depth,
                relevance=task.relevance, strength=strength, path=task.path, parent_task_id=task.id,
            ):
                new_count += 1
        ema = self.storage.source_yield_update(
            self.scan_id, task.source, len(items), new_count, self.config.ema_alpha
        )
        if next_url and task.page_no < self.config.source_pages and (
            new_count >= self.config.min_page_yield or task.page_no == 1 or ema >= self.config.min_page_yield
        ):
            self.storage.enqueue_task(
                self.scan_id, "repo_source", repo.full_name, source=task.source, depth=task.depth,
                page_no=task.page_no + 1, url=next_url,
                expected_yield=max(1.0, ema), novelty=task.novelty,
                relevance=task.relevance, confidence=max(0.4, task.confidence * 0.94), cost=1.0,
                parent_task_id=task.id, path=task.path,
            )
        self.storage.finish_task(task.id)

    @staticmethod
    def _page_url(base_url: str, page_no: int) -> str:
        parsed = urllib.parse.urlsplit(base_url)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        query["page"] = [str(page_no)]
        query["per_page"] = ["100"]
        encoded = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, encoded, parsed.fragment))

    def _enqueue_stratified_star_pages(self, task: Task, total_pages: int) -> None:
        if self.config.history_sampling != "stratified" or task.page_no != 1 or total_pages < 4:
            return
        if task.relevance < 0.08:
            return
        max_pages = total_pages if self.config.actor_star_pages <= 0 else min(total_pages, self.config.actor_star_pages)
        if max_pages < 4:
            return
        pages = sorted({max(2, max_pages // 2), max_pages})
        base = f"{API_BASE}/users/{urllib.parse.quote(task.node_id)}/starred?sort=created&direction=desc&per_page=100"
        for page_no in pages:
            self.storage.enqueue_task(
                self.scan_id, "actor_stars", task.node_id, source="stars", depth=task.depth,
                page_no=page_no, url=self._page_url(base, page_no),
                expected_yield=max(2.0, task.expected_yield * 0.45), novelty=task.novelty * 0.9,
                relevance=task.relevance, confidence=task.confidence * 0.82, cost=1.0,
                parent_task_id=task.id, path=task.path,
            )

    def _save_actor_stars(self, task: Task, stars: Sequence[StarRecord], *, source: str,
                          next_url: str | None = None, has_next: bool | None = None,
                          response_headers: Mapping[str, str] | None = None, total_count: int | None = None) -> int:
        new_count = 0
        useful: list[tuple[float, StarRecord, list[dict[str, str]]]] = []
        for star in stars:
            if star.repo.private:
                continue
            is_new = self.storage.save_star(self.scan_id, task.node_id, star, source=source)
            star_path = self._path_extend(task.path, "repo", star.repo.full_name)
            self.storage.add_repo_support(
                self.scan_id, task.node_id, star.repo.full_name, "star", star.starred_at,
                task.depth, star_path,
            )
            if is_new:
                new_count += 1
            if self._eligible_repo(star.repo):
                rarity = normalized_global_rarity(star.repo.stargazers_count)
                recent = recency_weight(star.starred_at, max(90.0, self.config.recent_days * 0.9), missing=0.4)
                no_topics = 1.10 if not star.repo.topics else 1.0
                score = task.relevance * (0.56 * rarity + 0.30 * recent + 0.14 * recency_weight(star.repo.pushed_at, 540.0, 0.35)) * no_topics
                useful.append((score, star, star_path))

        ema = self.storage.source_yield_update(
            self.scan_id, "actor_stars", len(stars), new_count, self.config.ema_alpha
        )
        if task.page_no == 1:
            pages_total = 0
            if total_count is not None and total_count > 0:
                pages_total = max(1, math.ceil(total_count / 100))
            elif response_headers:
                last_url = self.client._links(response_headers.get("link")).get("last")
                if last_url:
                    try:
                        q = urllib.parse.parse_qs(urllib.parse.urlsplit(last_url).query)
                        pages_total = int((q.get("page") or ["0"])[0])
                    except (TypeError, ValueError):
                        pages_total = 0
            if pages_total:
                self._enqueue_stratified_star_pages(task, pages_total)
        # Dynamic person score becomes more meaningful after every page.
        scoring = ScoringEngine(self.storage, self.scan_id, self.config)
        person = scoring.person_score_one(task.node_id, require_overlap=False)
        pscore = person.score if person else task.relevance
        qualifies = scoring.person_qualifies(person)

        if qualifies:
            # Expand a strong person's current activity and owned repositories only once.
            if pscore >= 0.10:
                self.storage.enqueue_task(
                    self.scan_id, "actor_events", task.node_id, source="events", depth=task.depth,
                    page_no=1, expected_yield=self._source_expected_yield("events"), novelty=0.85,
                    relevance=pscore, confidence=0.70, cost=1.0, parent_task_id=task.id, path=task.path,
                )
                self.storage.enqueue_task(
                    self.scan_id, "actor_repos", task.node_id, source="public_repos", depth=task.depth,
                    page_no=1, expected_yield=self._source_expected_yield("public_repos"), novelty=0.80,
                    relevance=pscore, confidence=0.75, cost=1.0, parent_task_id=task.id, path=task.path,
                )

            # Automatic seed promotion: top rare/recent repos of strong candidates become next-hop seeds.
            if task.depth < self.config.max_depth:
                useful.sort(key=lambda x: x[0], reverse=True)
                promoted = 0
                for seed_score, star, star_path in useful:
                    if promoted >= self.config.repo_promotions_per_actor:
                        break
                    if star.repo.full_name in scoring.owner_names:
                        continue
                    if seed_score < 0.055:
                        continue
                    if self._enqueue_repo_expansion(
                        star.repo, depth=task.depth + 1, reason=f"star:{task.node_id}",
                        relevance=clamp(0.55 * pscore + 0.45 * seed_score),
                        path=star_path, parent_task_id=task.id,
                    ):
                        promoted += 1

        # Adaptive page depth. GraphQL is first-page exploration; deeper pages switch to REST.
        more_available = bool(next_url) if next_url is not None else bool(has_next)
        if more_available and task.page_no < self.config.actor_star_pages:
            continue_deep = (
                self.config.history_sampling == "exhaustive"
                or task.page_no < 2
                or new_count >= self.config.min_page_yield
                or ema >= self.config.min_page_yield
                or (qualifies and pscore >= 0.18)
            )
            if continue_deep:
                page_no = task.page_no + 1
                url = next_url
                if url is None:
                    # First page may have been GraphQL; switch to REST page 2.
                    url = (f"{API_BASE}/users/{urllib.parse.quote(task.node_id)}/starred"
                           f"?sort=created&direction=desc&per_page=100&page={page_no}")
                self.storage.enqueue_task(
                    self.scan_id, "actor_stars", task.node_id, source="stars", depth=task.depth,
                    page_no=page_no, url=url, expected_yield=max(1.0, ema), novelty=task.novelty,
                    relevance=max(task.relevance, pscore), confidence=max(0.45, task.confidence * 0.97),
                    cost=1.0, parent_task_id=task.id, path=task.path,
                )
        return new_count

    def _process_actor_stars_rest(self, task: Task) -> None:
        stars, next_url, headers = self.client.get_star_page_rest(task.node_id, url=task.url, authenticated_self=False)
        self._save_actor_stars(task, stars, source="rest", next_url=next_url, response_headers=headers)
        self.storage.finish_task(task.id)

    def _process_actor_events(self, task: Task) -> None:
        events, next_url = self.client.public_events_page(task.node_id, url=task.url)
        new_count = 0
        seen_repos: set[str] = set()
        for event in events:
            repo_obj = event.get("repo") if isinstance(event.get("repo"), Mapping) else {}
            repo_name = str(repo_obj.get("name") or "")
            if not repo_name or repo_name in seen_repos:
                continue
            seen_repos.add(repo_name)
            created_at = str(event.get("created_at") or "") or None
            event_path = self._path_extend(task.path, "repo", repo_name)
            if self.storage.add_repo_support(
                self.scan_id, task.node_id, repo_name, "event", created_at,
                task.depth, event_path,
            ):
                new_count += 1
            repo = self.storage.get_repo(repo_name)
            if repo is None:
                self.storage.enqueue_task(
                    self.scan_id, "repo_detail", repo_name, source="event", depth=task.depth + 1,
                    page_no=1, payload={"actor": task.node_id, "relation": "event", "occurred_at": created_at},
                    expected_yield=1.0, novelty=0.75, relevance=task.relevance * 0.65,
                    confidence=0.55, cost=1.0, parent_task_id=task.id, path=event_path,
                )
            elif task.depth < self.config.max_depth and self._eligible_repo(repo) and task.relevance >= 0.16:
                self._enqueue_repo_expansion(
                    repo, depth=task.depth + 1, reason=f"event:{task.node_id}",
                    relevance=task.relevance * 0.58, path=event_path, parent_task_id=task.id,
                )
        ema = self.storage.source_yield_update(self.scan_id, "events", len(events), new_count, self.config.ema_alpha)
        if next_url and task.page_no < self.config.event_pages and new_count >= self.config.min_page_yield:
            self.storage.enqueue_task(
                self.scan_id, "actor_events", task.node_id, source="events", depth=task.depth,
                page_no=task.page_no + 1, url=next_url, expected_yield=max(1.0, ema), novelty=task.novelty,
                relevance=task.relevance, confidence=task.confidence * 0.9, cost=1.0,
                parent_task_id=task.id, path=task.path,
            )
        self.storage.finish_task(task.id)

    def _process_actor_repos(self, task: Task) -> None:
        repos, next_url = self.client.public_repos_page(task.node_id, url=task.url)
        new_count = 0
        ranked: list[tuple[float, RepoRecord, list[dict[str, str]]]] = []
        for repo in repos:
            self.storage.save_repo(repo, self.scan_id)
            p = self._path_extend(task.path, "repo", repo.full_name)
            if self.storage.add_repo_support(
                self.scan_id, task.node_id, repo.full_name, "owns", repo.updated_at,
                task.depth, p,
            ):
                new_count += 1
            if self._eligible_repo(repo):
                s = task.relevance * (0.62 * self._repo_novelty(repo) + 0.38 * recency_weight(repo.pushed_at, 480.0, 0.35))
                ranked.append((s, repo, p))
        ranked.sort(key=lambda x: x[0], reverse=True)
        if task.depth < self.config.max_depth and task.relevance >= 0.14:
            for score, repo, p in ranked[: max(1, self.config.repo_promotions_per_actor // 2)]:
                if score >= 0.06:
                    self._enqueue_repo_expansion(
                        repo, depth=task.depth + 1, reason=f"owner:{task.node_id}",
                        relevance=score, path=p, parent_task_id=task.id,
                    )
        ema = self.storage.source_yield_update(
            self.scan_id, "public_repos", len(repos), new_count, self.config.ema_alpha
        )
        if next_url and task.page_no < self.config.public_repo_pages and new_count >= self.config.min_page_yield:
            self.storage.enqueue_task(
                self.scan_id, "actor_repos", task.node_id, source="public_repos", depth=task.depth,
                page_no=task.page_no + 1, url=next_url, expected_yield=max(1.0, ema),
                novelty=task.novelty, relevance=task.relevance, confidence=task.confidence * 0.9,
                cost=1.0, parent_task_id=task.id, path=task.path,
            )
        self.storage.finish_task(task.id)

    def _process_repo_detail(self, task: Task) -> None:
        repo = self.client.get_repo(task.node_id)
        self.storage.save_repo(repo, self.scan_id)
        actor = str(task.payload.get("actor") or "")
        relation = str(task.payload.get("relation") or "event")
        occurred_at = task.payload.get("occurred_at")
        if actor:
            self.storage.add_repo_support(
                self.scan_id, actor, repo.full_name, relation,
                str(occurred_at) if occurred_at else None, task.depth, task.path,
            )
        if task.depth <= self.config.max_depth and task.relevance >= 0.09 and self._eligible_repo(repo):
            self._enqueue_repo_expansion(
                repo, depth=task.depth, reason=f"{task.source}:{actor or 'detail'}",
                relevance=task.relevance, path=task.path, parent_task_id=task.id,
            )
        self.storage.finish_task(task.id)

    def _process_task(self, task: Task) -> None:
        try:
            if task.kind == "repo_source":
                self._process_repo_source(task)
            elif task.kind == "actor_stars":
                self._process_actor_stars_rest(task)
            elif task.kind == "actor_events":
                self._process_actor_events(task)
            elif task.kind == "actor_repos":
                self._process_actor_repos(task)
            elif task.kind == "repo_detail":
                self._process_repo_detail(task)
            else:
                self.storage.finish_task(task.id, "failed", f"unknown task kind: {task.kind}")
        except RecoverableTaskError as exc:
            self.storage.finish_task(task.id, "failed", str(exc))
        except (BudgetExhausted, RateLimitPause):
            # Put task back for resume.
            self.storage.conn.execute(
                "UPDATE frontier_tasks SET status='pending',updated_at=? WHERE id=?", (utc_now_iso(), task.id)
            )
            self.storage.conn.commit()
            raise
        except StarBridgeError as exc:
            # A transient task error should not destroy the whole crawl unless it is repeated.
            if task.attempts < max(1, self.config.retry_count):
                self.storage.conn.execute(
                    "UPDATE frontier_tasks SET status='pending',last_error=?,updated_at=? WHERE id=?",
                    (str(exc)[:1000], utc_now_iso(), task.id),
                )
                self.storage.conn.commit()
            else:
                self.storage.finish_task(task.id, "failed", str(exc))

    def _try_graphql_batch(self) -> bool:
        if not self.graphql_enabled or self.config.graphql_batch <= 1:
            return False
        tasks = self.storage.pending_actor_star_first_tasks(self.scan_id, self.config.graphql_batch)
        if len(tasks) < 2:
            return False
        # Prioritize a batch only when these tasks are near the top of the frontier.
        tasks = tasks[: self.config.graphql_batch]
        ids = [t.id for t in tasks]
        self.storage.claim_tasks(ids)
        try:
            result = self.client.graphql_star_batch_first([t.node_id for t in tasks])
        except (StarBridgeError, RateLimitPause) as exc:
            self.storage.conn.executemany(
                "UPDATE frontier_tasks SET status='pending',last_error=?,updated_at=? WHERE id=?",
                [(str(exc)[:800], utc_now_iso(), task_id) for task_id in ids],
            )
            self.storage.conn.commit()
            if self.config.transport == "graphql":
                raise
            self.graphql_enabled = False
            self.client.graphql_disabled_reason = str(exc)
            print(f"[graphql] disabled for this scan: {exc}", file=sys.stderr)
            return False

        for task in tasks:
            item = result.get(task.node_id) or {}
            stars = item.get("stars") if isinstance(item.get("stars"), list) else []
            try:
                self._save_actor_stars(
                    task, stars, source="graphql", has_next=bool(item.get("has_next")),
                    total_count=int(item.get("total_count") or len(stars))
                )
                self.storage.finish_task(task.id)
                self.storage.transport_metric(
                    self.scan_id, "graphql", items=len(stars), useful_items=len(stars)
                )
                if item.get("is_over_limit"):
                    self.storage.scan_metric_set(
                        self.scan_id, f"graphql_overlimit:{task.node_id}", 1.0,
                        "GitHub marked starredRepositories isOverLimit; deeper pages switch to REST.",
                    )
            except Exception as exc:  # task-local integrity; don't lose the rest of batch
                self.storage.finish_task(task.id, "failed", str(exc))
        return True

    def _carry_previous_people(self) -> None:
        if self.config.carry_people <= 0:
            return
        prev = self.storage.latest_finished_scan_before(self.scan_id, self.owner)
        if prev is None:
            return
        rows = self.storage.conn.execute(
            "SELECT user_login,score,paths_json FROM scan_people_scores WHERE scan_id=? ORDER BY score DESC LIMIT ?",
            (prev, self.config.carry_people),
        ).fetchall()
        for row in rows:
            login = str(row["user_login"])
            if login.lower() == self.owner_lower:
                continue
            score = float(row["score"] or 0)
            paths = json.loads(row["paths_json"] or "[]")
            path = paths[0] if paths else [{"type": "carry", "id": f"scan:{prev}"}, {"type": "user", "id": login}]
            self.storage.add_candidate(
                self.scan_id, login, score * 0.85, score, "carry", f"scan:{prev}", 0, path
            )
            self.storage.enqueue_task(
                self.scan_id, "actor_stars", login, source="stars", depth=0, page_no=1,
                expected_yield=self._source_expected_yield("actor_stars"), novelty=0.65,
                relevance=max(0.05, score * 0.85), confidence=0.88, cost=1.0, path=path,
            )

    def initialize_new_scan(self) -> list[StarRecord]:
        print(f"[1/6] Loading owner star profile for @{self.owner} ...")
        cutoff = parse_date_cutoff(self.config.owner_cutoff)
        owner_stars = self.client.get_all_owner_stars(
            self.owner, self.config.owner_star_pages, self.config.private_policy, cutoff
        )
        owner_stars = self.storage.save_owner_profile(
            self.scan_id, self.owner, owner_stars, self.config.private_policy, cutoff
        )
        if not owner_stars:
            raise StarBridgeError(
                "No usable starred repositories were returned for the owner. Check login, token and visibility."
            )
        print(f"      owner profile: {len(owner_stars)} repositories")

        # Explicit seeds not already present in owner profile are resolved from public metadata.
        by_name = {s.repo.full_name: s for s in owner_stars}
        for value in self.config.explicit_seeds:
            name = normalize_repo(value)
            if name in by_name:
                continue
            try:
                repo = self.client.get_repo(name)
                self.storage.save_repo(repo, self.scan_id)
                by_name[name] = StarRecord(repo, None)
            except RecoverableTaskError as exc:
                print(f"[seed] skip {name}: {exc}", file=sys.stderr)

        optimizer = SeedPortfolioOptimizer(self.config.auto_seeds, self.config.seed_pool)
        seeds = optimizer.select(owner_stars, self.config.explicit_seeds)
        print(f"[2/6] Selected {len(seeds)} initial seeds ...")
        if self.config.explicit_seeds and self.config.auto_seeds == 0:
            print("      focus mode: explicit seed lineage; owner-star overlap is not required for seed-connected actors")
        for name, score, reason in seeds:
            repo = self.storage.get_repo(name)
            if repo is None and name in by_name:
                repo = by_name[name].repo
            if repo is None:
                continue
            p = [{"type": "owner", "id": self.owner}, {"type": "seed", "id": repo.full_name}]
            self._enqueue_repo_expansion(
                repo, depth=0, reason=reason, relevance=clamp(score, 0.05, 1.0), path=p
            )
        self._carry_previous_people()
        return owner_stars

    def crawl(self) -> str:
        print("[3/6] Adaptive recursive crawl ...")
        note = ""
        while True:
            total, used = self.storage.budget_state(self.scan_id)
            if used >= total:
                note = f"budget exhausted ({used}/{total}); resume with extra budget"
                break
            try:
                if self._try_graphql_batch():
                    self._task_counter += 1
                else:
                    task = self.storage.pop_task(self.scan_id)
                    if task is None:
                        note = "frontier exhausted"
                        break
                    self._process_task(task)
                    self._task_counter += 1
                if self._task_counter % 40 == 0:
                    self.storage.prune_frontier(self.scan_id, self.config.actor_beam, self.config.repo_beam)
                if self._task_counter % 25 == 0:
                    total, used = self.storage.budget_state(self.scan_id)
                    pending = self.storage.pending_count(self.scan_id)
                    candidates = len(self.storage.candidate_logins(self.scan_id))
                    seeds = len(self.storage.seed_names(self.scan_id))
                    print(f"      requests {used}/{total} | pending {pending} | people {candidates} | seeds {seeds}")
            except BudgetExhausted as exc:
                note = str(exc)
                break
            except RateLimitPause as exc:
                note = str(exc)
                break
            except KeyboardInterrupt:
                note = "interrupted by user; run resume to continue"
                break
        return note

    def score_and_finalize(self, *, finish_if_empty: bool = True) -> tuple[list[PersonResult], list[RepoResult]]:
        print("[4/6] Scoring people and repositories ...")
        scoring = ScoringEngine(self.storage, self.scan_id, self.config)
        people = scoring.score_people()
        repos = scoring.score_repos(people)
        self.storage.save_people_scores(self.scan_id, people)
        self.storage.save_repo_scores(self.scan_id, repos)
        self._build_communities(people, repos)
        self._save_metrics(people, repos)
        print(f"      scored: {len(people)} people, {len(repos)} repositories")
        return people, repos

    def _build_communities(self, people: Sequence[PersonResult], repos: Sequence[RepoResult]) -> None:
        self.storage.conn.execute("DELETE FROM community_membership WHERE scan_id=?", (self.scan_id,))
        top_people = list(people[: min(700, self.config.actor_beam)])
        if not top_people:
            self.storage.conn.commit()
            return
        logins = {p.login for p in top_people}
        uf = UnionFind()
        for login in logins:
            uf.add(login)
        repo_users: dict[str, list[str]] = defaultdict(list)
        rows = self.storage.conn.execute(
            "SELECT user_login,repo_full_name FROM repo_support WHERE scan_id=? AND relation='star'",
            (self.scan_id,),
        ).fetchall()
        for row in rows:
            login = str(row["user_login"])
            if login in logins:
                repo_users[str(row["repo_full_name"])].append(login)
        # Use rare-ish shared repositories as deterministic community bridges.
        for repo_name, users in repo_users.items():
            unique = sorted(set(users))
            if len(unique) < 2 or len(unique) > 40:
                continue
            repo = self.storage.get_repo(repo_name)
            if repo is not None and repo.stargazers_count > 50000:
                continue
            root = unique[0]
            for other in unique[1:]:
                uf.union(root, other)
        comps: dict[str, list[str]] = defaultdict(list)
        for login in logins:
            comps[uf.find(login)].append(login)
        comps_sorted = sorted((v for v in comps.values() if len(v) >= 2), key=len, reverse=True)
        person_score = {p.login: p.score for p in people}
        community_id = 1
        for members in comps_sorted[:100]:
            for login in members:
                self.storage.conn.execute(
                    "INSERT OR REPLACE INTO community_membership(scan_id,community_id,member_type,member_id,weight) VALUES(?,?,?,?,?)",
                    (self.scan_id, community_id, "user", login, float(person_score.get(login, 0.0))),
                )
            member_set = set(members)
            repo_weight: Counter[str] = Counter()
            for result in repos[:3000]:
                supporters = {str(s.get("login")) for s in result.supporters}
                overlap_n = len(supporters & member_set)
                if overlap_n:
                    repo_weight[result.repo.full_name] += overlap_n
            for repo_name, weight in repo_weight.most_common(25):
                self.storage.conn.execute(
                    "INSERT OR REPLACE INTO community_membership(scan_id,community_id,member_type,member_id,weight) VALUES(?,?,?,?,?)",
                    (self.scan_id, community_id, "repo", repo_name, float(weight)),
                )
            community_id += 1
        self.storage.conn.commit()

    def _save_metrics(self, people: Sequence[PersonResult], repos: Sequence[RepoResult]) -> None:
        total, used = self.storage.budget_state(self.scan_id)
        self.storage.scan_metric_set(self.scan_id, "people", len(people))
        self.storage.scan_metric_set(self.scan_id, "repos", len(repos))
        self.storage.scan_metric_set(self.scan_id, "seeds", len(self.storage.seed_names(self.scan_id)))
        self.storage.scan_metric_set(self.scan_id, "pending", self.storage.pending_count(self.scan_id))
        self.storage.scan_metric_set(self.scan_id, "budget_used", used)
        self.storage.scan_metric_set(self.scan_id, "budget_total", total)
        self.storage.scan_metric_set(self.scan_id, "early_signals", sum("EARLY_SIGNAL" in r.flags for r in repos))
        self.storage.scan_metric_set(self.scan_id, "no_topics", sum("NO_TOPICS" in r.flags for r in repos))
        self.storage.scan_metric_set(self.scan_id, "new_repos", sum(r.new_since_previous for r in repos))

    def run_new(self) -> tuple[list[PersonResult], list[RepoResult], str]:
        try:
            self.initialize_new_scan()
            note = self.crawl()
            people, repos = self.score_and_finalize()
            pending = self.storage.pending_count(self.scan_id)
            status = "paused" if pending else "finished"
            self.storage.update_scan_status(self.scan_id, status, note)
            return people, repos, note
        except Exception as exc:
            self.storage.update_scan_status(self.scan_id, "failed", str(exc))
            raise

    def resume(self) -> tuple[list[PersonResult], list[RepoResult], str]:
        self.storage.reset_in_progress(self.scan_id)
        self.storage.update_scan_status(self.scan_id, "running", "")
        note = self.crawl()
        people, repos = self.score_and_finalize()
        pending = self.storage.pending_count(self.scan_id)
        status = "paused" if pending else "finished"
        self.storage.update_scan_status(self.scan_id, status, note)
        return people, repos, note


@dataclass(slots=True)
class CatalogClassification:
    primary_id: str
    primary_label: str
    category_ids: list[str]
    category_labels: list[str]
    subcategories: list[str]
    scores: dict[str, float]
    matches: dict[str, list[str]]


class CatalogEngine:
    """Deterministic local multi-label repository cataloging. No AI and no API calls."""

    def __init__(self, config: Mapping[str, Any], source_path: Path | None = None):
        self.config = dict(config)
        self.source_path = source_path
        self.minimum_score = float(self.config.get("minimum_score", 2.5))
        self.secondary_ratio = float(self.config.get("secondary_ratio", 0.55))
        raw = self.config.get("categories")
        self.categories: list[dict[str, Any]] = [dict(x) for x in raw] if isinstance(raw, list) else []
        self.by_id = {str(x.get("id")): x for x in self.categories if x.get("id")}

    @classmethod
    def load(cls, path: Path | None = None) -> "CatalogEngine":
        if path is None:
            env = os.environ.get("STARBRIDGE_CATALOGS")
            path = Path(env).expanduser() if env else Path(__file__).resolve().with_name("catalogs.json")
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, Mapping) or not isinstance(data.get("categories"), list):
                    raise ValueError("root must contain a categories array")
                return cls(data, path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"[catalog] warning: cannot load {path}: {exc}; using built-in taxonomy", file=sys.stderr)
        return cls(DEFAULT_CATALOG_CONFIG, None)

    @staticmethod
    def _norm(value: Any) -> str:
        text = str(value or "").lower().replace("_", "-")
        text = re.sub(r"[^a-z0-9+#.\-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _contains(cls, text: str, term: str) -> bool:
        t = cls._norm(term)
        if not t:
            return False
        # Treat hyphens/spaces as equivalent while retaining useful tokens such as c++ and llama.cpp.
        text2 = text.replace("-", " ")
        t2 = t.replace("-", " ")
        pattern = r"(?<![a-z0-9])" + re.escape(t2).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return re.search(pattern, text2) is not None

    def classify(self, repo: RepoRecord | Mapping[str, Any]) -> CatalogClassification:
        if isinstance(repo, RepoRecord):
            full_name, description, language, topics = repo.full_name, repo.description, repo.language, repo.topics
        else:
            repo_map = dict(repo)
            full_name = str(repo_map.get("repo_full_name") or repo_map.get("full_name") or "")
            description = str(repo_map.get("description") or "")
            language = str(repo_map.get("language") or "")
            raw_topics = repo_map.get("topics") if "topics" in repo_map else repo_map.get("topics_json")
            if isinstance(raw_topics, str):
                try:
                    raw_topics = json.loads(raw_topics)
                except json.JSONDecodeError:
                    raw_topics = []
            topics = [str(x) for x in (raw_topics or [])]

        name_text = self._norm(full_name)
        desc_text = self._norm(description)
        topic_texts = [self._norm(x) for x in topics]
        lang_text = self._norm(language)
        combined = " ".join([name_text, desc_text, *topic_texts])

        scores: dict[str, float] = {}
        match_map: dict[str, list[str]] = {}
        sub_map: dict[str, list[str]] = {}

        for cat in self.categories:
            cid = str(cat.get("id") or "")
            if not cid:
                continue
            score = 0.0
            matches: list[str] = []
            seen: set[tuple[str, str]] = set()

            def add(term: str, field: str, points: float) -> None:
                nonlocal score
                key = (term, field)
                if key in seen:
                    return
                seen.add(key)
                score += points
                matches.append(f"{field}:{term}")

            for term in [str(x) for x in (cat.get("strong") or [])]:
                if any(self._contains(t, term) for t in topic_texts): add(term, "topic", 6.0)
                if self._contains(name_text, term): add(term, "name", 4.0)
                if self._contains(desc_text, term): add(term, "description", 3.0)
            for term in [str(x) for x in (cat.get("weak") or [])]:
                if any(self._contains(t, term) for t in topic_texts): add(term, "topic", 3.5)
                if self._contains(name_text, term): add(term, "name", 2.0)
                if self._contains(desc_text, term): add(term, "description", 1.0)
            for term in [str(x) for x in (cat.get("phrases") or [])]:
                if self._contains(combined, term): add(term, "phrase", 3.0)
            for term in [str(x) for x in (cat.get("languages") or [])]:
                if lang_text == self._norm(term): add(term, "language", 1.0)

            scores[cid] = score
            match_map[cid] = matches

            subs: list[tuple[int, str]] = []
            for label, terms in (cat.get("subcategories") or {}).items():
                if not isinstance(terms, list):
                    continue
                hits = sum(1 for term in terms if self._contains(combined, str(term)))
                if hits:
                    subs.append((hits, str(label)))
            subs.sort(key=lambda x: (-x[0], x[1].lower()))
            sub_map[cid] = [label for _, label in subs[:4]]

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if not ranked or ranked[0][1] < self.minimum_score:
            return CatalogClassification(
                primary_id="other", primary_label="OTHER", category_ids=["other"], category_labels=["OTHER"],
                subcategories=[], scores=scores, matches={},
            )

        primary_id, primary_score = ranked[0]
        selected = [
            cid for cid, score in ranked
            if score >= self.minimum_score and score >= primary_score * self.secondary_ratio
        ]
        selected = selected[:4]
        labels = [str(self.by_id[cid].get("label") or cid) for cid in selected]
        primary_label = str(self.by_id[primary_id].get("label") or primary_id)
        subs: list[str] = []
        for cid in selected:
            for label in sub_map.get(cid, []):
                if label not in subs:
                    subs.append(label)
        useful_matches = {cid: match_map.get(cid, [])[:16] for cid in selected if match_map.get(cid)}
        return CatalogClassification(
            primary_id=primary_id,
            primary_label=primary_label,
            category_ids=selected,
            category_labels=labels,
            subcategories=subs[:8],
            scores={cid: round(scores[cid], 3) for cid in selected},
            matches=useful_matches,
        )

    def classify_rows(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, CatalogClassification]:
        out: dict[str, CatalogClassification] = {}
        for row in rows:
            name = str(row["repo_full_name"] if "repo_full_name" in row.keys() else row["full_name"])
            out[name] = self.classify(row)
        return out

    def counts(self, classifications: Mapping[str, CatalogClassification]) -> list[tuple[str, str, int]]:
        counts: Counter[str] = Counter()
        for item in classifications.values():
            counts.update(item.category_ids)
        result: list[tuple[str, str, int]] = []
        for cat in self.categories:
            cid = str(cat.get("id") or "")
            if cid:
                result.append((cid, str(cat.get("label") or cid), int(counts[cid])))
        result.append(("other", "OTHER", int(counts["other"])))
        return result


class HtmlReport:
    def __init__(self, storage: Storage, scan_id: int):
        self.storage = storage
        self.scan_id = scan_id
        row = storage.scan_row(scan_id)
        self.config = ScanConfig.from_json(str(row["config_json"]))
        self.scan_row = row
        self.catalog_engine = CatalogEngine.load()
        self.last_catalog_counts: list[tuple[str, str, int]] = []
        self.last_catalog_total = 0

    def print_catalog_summary(self) -> None:
        print("\n[CATEGORIES]")
        print(f"[ {'ALL':<20} {self.last_catalog_total:>6} ]")
        for _cid, label, count in self.last_catalog_counts:
            print(f"[ {label:<20} {count:>6} ]")
        print("  multi-label: one repository may appear in several catalogs")

    @staticmethod
    def _esc(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    def _load_people(self, limit: int = 500) -> list[sqlite3.Row]:
        return self.storage.conn.execute(
            "SELECT * FROM scan_people_scores WHERE scan_id=? ORDER BY score DESC LIMIT ?",
            (self.scan_id, limit),
        ).fetchall()

    def _load_repos(self, limit: int = 10000) -> list[sqlite3.Row]:
        return self.storage.conn.execute(
            "SELECT s.*,r.* FROM scan_repo_scores s JOIN repos r ON r.full_name=s.repo_full_name "
            "WHERE s.scan_id=? AND r.private=0 ORDER BY s.score DESC LIMIT ?",
            (self.scan_id, limit),
        ).fetchall()

    @staticmethod
    def _safe_js_json(value: Any) -> str:
        # Safe for embedding directly inside a <script> block.
        return (
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\\u2028", "\\\\u2028")
            .replace("\\u2029", "\\\\u2029")
        )

    def generate(self, path: Path, *, top_people: int = 500, top_repos: int = 10000) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        people = self._load_people(top_people)
        repos = self._load_repos(top_repos)
        catalog_map = self.catalog_engine.classify_rows(repos)
        self.last_catalog_total = len(repos)
        self.last_catalog_counts = self.catalog_engine.counts(catalog_map)
        total, used = self.storage.budget_state(self.scan_id)
        seeds = len(self.storage.seed_names(self.scan_id))
        pending = self.storage.pending_count(self.scan_id)
        early = sum("EARLY_SIGNAL" in json.loads(r["flags_json"] or "[]") for r in repos)
        new_count = sum(bool(r["new_since_previous"]) for r in repos)
        communities = self._community_data()
        transports = self.storage.conn.execute(
            "SELECT * FROM transport_metrics WHERE scan_id=? ORDER BY transport", (self.scan_id,)
        ).fetchall()
        api_rows = self.storage.conn.execute(
            "SELECT * FROM api_resources WHERE scan_id=? ORDER BY resource", (self.scan_id,)
        ).fetchall()

        repo_data: list[dict[str, Any]] = []
        category_index: dict[str, list[int]] = defaultdict(list)
        early_ids: list[int] = []
        recent_ids: list[int] = []

        for idx, row in enumerate(repos):
            flags = json.loads(row["flags_json"] or "[]")
            supporters = json.loads(row["supporters_json"] or "[]")
            features = json.loads(row["features_json"] or "{}")
            paths = json.loads(row["paths_json"] or "[]")
            topics = json.loads(row["topics_json"] or "[]")
            classification = catalog_map.get(str(row["repo_full_name"])) or self.catalog_engine.classify(row)
            first_seen = parse_iso(str(row["first_seen_at"] or ""))
            first_seen_epoch = int(first_seen.timestamp()) if first_seen else 0
            rarity_sort = float(features.get("global_rarity", 0.0)) + float(features.get("local_rarity", 0.0))
            recent_sort = max(float(features.get("temporal_velocity", 0.0)), float(features.get("activity_recency", 0.0)))
            classification_json = {
                "primary": classification.primary_label,
                "categories": classification.category_labels,
                "subcategories": classification.subcategories,
                "scores": classification.scores,
                "matches": classification.matches,
            }
            support_short = [
                {"login": str(s.get("login") or ""), "score": float(s.get("person_score") or 0.0)}
                for s in supporters[:6]
            ]
            search_text = " ".join([
                str(row["repo_full_name"] or ""), str(row["description"] or ""), str(row["language"] or ""),
                " ".join(str(x) for x in topics), " ".join(flags),
                " ".join(classification.category_labels), " ".join(classification.subcategories),
            ]).lower()
            item = {
                "id": idx,
                "name": str(row["repo_full_name"] or ""),
                "url": str(row["html_url"] or ""),
                "description": str(row["description"] or ""),
                "language": str(row["language"] or ""),
                "stars": int(row["stargazers_count"] or 0),
                "topics": [str(x) for x in topics[:12]],
                "score": float(row["score"] or 0.0),
                "supporters": support_short,
                "supporterCount": len(supporters),
                "flags": flags,
                "categories": classification.category_ids,
                "categoryLabels": classification.category_labels,
                "subcategories": classification.subcategories[:8],
                "classification": classification_json,
                "features": features,
                "paths": paths[:5],
                "rarity": rarity_sort,
                "recent": recent_sort,
                "isNew": 1 if bool(row["new_since_previous"]) else 0,
                "isEarly": 1 if "EARLY_SIGNAL" in flags else 0,
                "firstSeen": first_seen_epoch,
                "search": search_text,
            }
            repo_data.append(item)
            for cid in classification.category_ids:
                category_index[str(cid)].append(idx)
            if item["isEarly"]:
                early_ids.append(idx)
            if float(features.get("temporal_velocity", 0.0)) >= 0.35:
                recent_ids.append(idx)

        category_index["all"] = list(range(len(repo_data)))

        def spotlight_card(idx: int) -> str:
            item = repo_data[idx]
            cat_badges = "".join(
                f'<span class="cat-badge">{self._esc(x)}</span>' for x in item["categoryLabels"]
            )
            sub_badges = "".join(
                f'<span class="sub-badge">{self._esc(x)}</span>' for x in item["subcategories"][:4]
            )
            badges = "".join(f'<span class="badge">{self._esc(x)}</span>' for x in item["flags"])
            support_txt = ", ".join(f"@{self._esc(s['login'])} ({s['score']:.3f})" for s in item["supporters"])
            topic_txt = " · ".join(self._esc(x) for x in item["topics"][:8]) or "без topics"
            return f'''<article class="card spotlight-card">
              <div class="title-row"><a href="{self._esc(item['url'])}" target="_blank" rel="noreferrer">{self._esc(item['name'])}</a><strong>{item['score']:.4f}</strong></div>
              <div class="catalog-badges">{cat_badges}{sub_badges}</div><div class="badges">{badges}</div>
              <p>{self._esc(item['description']) or '—'}</p>
              <div class="meta">★ {item['stars']} · {self._esc(item['language']) or '—'} · {topic_txt}</div>
              <div class="meta">Поддержка: {support_txt or '—'}</div>
            </article>'''

        SPOTLIGHT_LIMIT = 30
        early_cards = "\n".join(spotlight_card(i) for i in early_ids[:SPOTLIGHT_LIMIT])
        recent_cards = "\n".join(spotlight_card(i) for i in recent_ids[:SPOTLIGHT_LIMIT])
        early_note = f"<p class='meta'>Показаны первые {min(len(early_ids), SPOTLIGHT_LIMIT)} из {len(early_ids)}. Полный набор доступен через фильтры ниже.</p>" if len(early_ids) > SPOTLIGHT_LIMIT else ""
        recent_note = f"<p class='meta'>Показаны первые {min(len(recent_ids), SPOTLIGHT_LIMIT)} из {len(recent_ids)}. Полный набор доступен через фильтры ниже.</p>" if len(recent_ids) > SPOTLIGHT_LIMIT else ""

        path_rows = self.storage.conn.execute(
            "SELECT target_type,target_id,path_json,score FROM discovery_paths WHERE scan_id=? ORDER BY score DESC LIMIT 80",
            (self.scan_id,),
        ).fetchall()
        path_cards = []
        for pr in path_rows:
            nodes = json.loads(pr["path_json"] or "[]")
            chain = " → ".join(str(n.get("id") or "") for n in nodes if isinstance(n, Mapping))
            path_cards.append(
                f"<article class='card'><div class='title-row'><strong>{self._esc(pr['target_type'])}: {self._esc(pr['target_id'])}</strong><span>{float(pr['score']):.4f}</span></div>"
                f"<p class='meta'>{self._esc(chain)}</p></article>"
            )
        people_rows = []
        for row in people:
            overlap = json.loads(row["overlap_json"] or "[]")
            sources = json.loads(row["sources_json"] or "[]")
            people_rows.append(
                f"<tr><td><a href=\"https://github.com/{self._esc(row['user_login'])}\" target=\"_blank\">@{self._esc(row['user_login'])}</a></td>"
                f"<td>{float(row['score']):.4f}</td><td>{int(row['star_count'])}</td>"
                f"<td>{self._esc(', '.join(overlap[:8]))}</td><td>{self._esc(', '.join(sources))}</td></tr>"
            )
        community_html = []
        for cid, users, crepos in communities:
            community_html.append(
                f"<article class='card'><div class='title-row'><strong>Community {cid}</strong><span>{len(users)} people</span></div>"
                f"<p>{self._esc(', '.join('@'+u for u in users[:30]))}</p>"
                f"<p class='meta'>{self._esc(' · '.join(crepos[:20]))}</p></article>"
            )
        transport_html = "".join(
            f"<tr><td>{self._esc(r['transport'])}</td><td>{int(r['requests'])}</td><td>{int(r['cache_hits'])}</td>"
            f"<td>{int(r['items'])}</td><td>{int(r['graphql_points'])}</td></tr>" for r in transports
        ) or "<tr><td colspan='5'>—</td></tr>"
        api_html = "".join(
            f"<tr><td>{self._esc(r['resource'])}</td><td>{self._esc(r['limit_value'])}</td>"
            f"<td>{self._esc(r['remaining'])}</td><td>{self._esc(r['reset_at'])}</td></tr>" for r in api_rows
        ) or "<tr><td colspan='4'>—</td></tr>"

        category_buttons = [f'<button class="cat-btn active" data-cat="all">ALL <span>{len(repos)}</span></button>']
        for cid, label, count in self.last_catalog_counts:
            category_buttons.append(
                f'<button class="cat-btn" data-cat="{self._esc(cid)}">{self._esc(label)} <span>{count}</span></button>'
            )
        category_html = "".join(category_buttons)
        repo_json = self._safe_js_json(repo_data)
        category_index_json = self._safe_js_json(dict(category_index))
        early_ids_json = self._safe_js_json(early_ids)
        recent_ids_json = self._safe_js_json(recent_ids)

        doc = f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StarBridge {VERSION} — scan {self.scan_id}</title>
<style>
:root{{--bg:#0b0f14;--panel:#121923;--panel2:#17212e;--text:#e9f0f7;--muted:#93a4b5;--line:#283545;--link:#78b9ff;--good:#86efac;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1500px;margin:auto;padding:24px}}h1,h2{{margin:.4em 0}}a{{color:var(--link);text-decoration:none}}a:hover{{text-decoration:underline}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:16px 0 24px}}.stat,.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}}
.stat b{{font-size:22px;display:block}}.stat span,.meta{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(370px,1fr));gap:12px}}
.title-row{{display:flex;justify-content:space-between;gap:12px;align-items:center;font-size:16px}}.badge{{display:inline-block;padding:2px 7px;border:1px solid #39516b;border-radius:999px;margin:5px 5px 0 0;font-size:11px;color:#b9d8f5}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:12px;overflow:hidden}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:var(--panel2);position:sticky;top:0}}pre{{white-space:pre-wrap;color:#c7d7e7}}section{{margin:28px 0}}
.notice{{padding:12px;border-left:3px solid var(--good);background:var(--panel)}}
.catalog-panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:18px 0}}
.catalog-buttons{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}}.cat-btn{{background:var(--panel2);border:1px solid #39516b;color:var(--text);padding:8px 11px;border-radius:9px;cursor:pointer}}
.catalog-status{{margin-top:10px;color:#b9d8f5;font-weight:600}}
.cat-btn:hover{{border-color:var(--link)}}.cat-btn.active{{background:#17324a;border-color:#78b9ff;color:#dff0ff}}.cat-btn span{{color:var(--muted);margin-left:4px}}
.cat-badge{{display:inline-block;padding:3px 8px;border-radius:7px;margin:5px 5px 0 0;background:#14351f;border:1px solid #2f7a49;color:#a7f3c1;font-size:11px;font-weight:700}}
.sub-badge{{display:inline-block;padding:3px 7px;border-radius:7px;margin:5px 5px 0 0;background:#2b223d;border:1px solid #594477;color:#d7c4ff;font-size:10px}}
.controls{{display:grid;grid-template-columns:minmax(260px,1fr) 220px 150px;gap:10px;align-items:end}}
.controls label{{color:var(--muted);font-size:12px}}.controls input,.controls select{{width:100%;padding:10px;background:var(--panel2);border:1px solid var(--line);color:var(--text);border-radius:8px;margin:4px 0 0}}
.visible-count{{color:var(--muted);margin:6px 0 12px}}
.virtual-wrap{{position:relative}}#repoCards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.v-spacer{{width:100%;pointer-events:none}}
.repo-card{{height:340px;min-height:340px;overflow:hidden;display:flex;flex-direction:column}}.repo-card p{{margin:10px 0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.repo-card .meta.clamp{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}.repo-card .detail-row{{margin-top:auto;display:flex;flex-wrap:wrap;gap:6px;padding-top:8px}}
.detail-btn{{background:#17283a;border:1px solid #39516b;color:#cae4ff;border-radius:7px;padding:5px 8px;cursor:pointer;font-size:11px}}.detail-btn:hover{{border-color:var(--link)}}
#detailModal{{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:999;display:none;align-items:center;justify-content:center;padding:24px}}#detailModal.open{{display:flex}}
.modal-box{{max-width:980px;width:min(980px,96vw);max-height:86vh;overflow:auto;background:var(--panel);border:1px solid #39516b;border-radius:14px;padding:16px;box-shadow:0 20px 60px #000}}
.modal-head{{display:flex;justify-content:space-between;gap:10px;align-items:center}}.modal-close{{background:var(--panel2);border:1px solid #39516b;color:var(--text);border-radius:8px;padding:6px 10px;cursor:pointer}}
.virtual-hint{{font-size:12px;color:var(--muted);margin-top:4px}}
@media(max-width:1100px){{#repoCards{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:720px){{#repoCards{{grid-template-columns:1fr}}.controls{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>StarBridge {VERSION} <small>scan #{self.scan_id}</small></h1>
<p class="notice">A-RIR: рекурсивный детерминированный поиск через публичный граф интересов. AI/embeddings не используются.</p>
<div class="grid">
<div class="stat"><b>{len(repos)}</b><span>repositories</span></div><div class="stat"><b>{len(people)}</b><span>people</span></div>
<div class="stat"><b>{early}</b><span>early signals</span></div><div class="stat"><b>{new_count}</b><span>new vs previous</span></div>
<div class="stat"><b>{seeds}</b><span>promoted seeds</span></div><div class="stat"><b>{used}/{total}</b><span>request budget</span></div>
<div class="stat"><b>{pending}</b><span>frontier pending</span></div><div class="stat"><b>{len(communities)}</b><span>communities</span></div>
</div>
<section class="catalog-panel"><h2>Categories</h2><p class="meta">Локальная multi-label классификация по GitHub topics, названию, описанию и language. Категории используют заранее построенные индексы, поэтому переключение не перебирает DOM-карточки.</p><div class="catalog-buttons" id="catalogButtons">{category_html}</div><div class="catalog-status" id="catalogStatus">Selected: ALL · {len(repos)} repositories</div></section>
<section><h2>Early Signals</h2><p class="meta" id="earlyNote"></p><div class="cards" id="earlyCards"></div></section>
<section><h2>Recent discoveries</h2><p class="meta" id="recentNote"></p><div class="cards" id="recentCards"></div></section>
<section id="repositoriesSection"><h2>Repositories</h2>
<div class="controls">
<label>Search<input id="filter" placeholder="Название / описание / language / flags / categories"></label>
<label>Sort<select id="sort">
<option value="score">StarBridge Score</option><option value="newest">Newest discovery</option><option value="early">Early Signal</option>
<option value="rare">Rarest</option><option value="supporters">Most supporters</option><option value="stars-asc">Fewest GitHub stars</option>
<option value="stars-desc">Most GitHub stars</option><option value="recent">Recent activity</option>
</select></label>
<label>Categories<select id="catMode"><option value="any">ANY selected</option><option value="all">ALL selected</option></select></label>
</div><div class="visible-count" id="visibleCount"></div><div class="virtual-hint">Virtualized rendering: в DOM одновременно находятся только карточки около текущей области прокрутки.</div>
<div id="repoVirtual" class="virtual-wrap"><div id="topSpacer" class="v-spacer"></div><div id="repoCards"></div><div id="bottomSpacer" class="v-spacer"></div></div></section>
<section><h2>People</h2><div style="overflow:auto"><table><thead><tr><th>User</th><th>Score</th><th>Known stars</th><th>Rare overlap</th><th>Sources</th></tr></thead><tbody>{''.join(people_rows)}</tbody></table></div></section>
<section><h2>Communities</h2><div class="cards">{''.join(community_html) or '<p>Недостаточно связей для устойчивых кластеров.</p>'}</div></section>
<section><h2>Discovery paths</h2><div class="cards">{''.join(path_cards) or '<p>Пути ещё не накоплены.</p>'}</div></section>
<section><h2>Transport / API</h2><div style="overflow:auto"><table><thead><tr><th>Transport</th><th>Requests</th><th>Cache hits</th><th>Items</th><th>GraphQL points</th></tr></thead><tbody>{transport_html}</tbody></table></div>
<div style="overflow:auto;margin-top:10px"><table><thead><tr><th>Resource</th><th>Limit</th><th>Remaining</th><th>Reset</th></tr></thead><tbody>{api_html}</tbody></table></div></section>
<section><h2>Scan configuration</h2><pre>{self._esc(json.dumps(asdict(self.config), ensure_ascii=False, indent=2, default=list))}</pre></section>
<div id="detailModal"><div class="modal-box"><div class="modal-head"><strong id="modalTitle"></strong><button class="modal-close" id="modalClose">Close</button></div><pre id="modalBody"></pre></div></div>
<script>
const repoData={repo_json};
const categoryIndex={category_index_json};
const earlyIds={early_ids_json};
const recentIds={recent_ids_json};
const f=document.getElementById('filter'), sortSel=document.getElementById('sort'), modeSel=document.getElementById('catMode');
const grid=document.getElementById('repoCards'), buttons=[...document.querySelectorAll('.cat-btn')], countEl=document.getElementById('visibleCount');
const virtual=document.getElementById('repoVirtual'), topSpacer=document.getElementById('topSpacer'), bottomSpacer=document.getElementById('bottomSpacer');
const earlyGrid=document.getElementById('earlyCards'), recentGrid=document.getElementById('recentCards');
const earlyNoteEl=document.getElementById('earlyNote'), recentNoteEl=document.getElementById('recentNote'), catalogStatus=document.getElementById('catalogStatus');
const modal=document.getElementById('detailModal'), modalTitle=document.getElementById('modalTitle'), modalBody=document.getElementById('modalBody');
let viewIds=categoryIndex.all.slice(), renderState='', searchTimer=null;
const CARD_H=340, GAP=12, ROW_H=CARD_H+GAP, OVERSCAN=8;
function esc(s){{return String(s??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]))}}
function cols(){{const w=grid.clientWidth||window.innerWidth;return w>1100?3:(w>720?2:1)}}
function selectedCats(){{return buttons.filter(b=>b.classList.contains('active')&&b.dataset.cat!=='all').map(b=>b.dataset.cat)}}
function idsForCategories(selected,mode){{
  if(!selected.length)return categoryIndex.all.slice();
  const lists=selected.map(x=>categoryIndex[x]||[]);
  if(mode==='all'){{
    lists.sort((a,b)=>a.length-b.length); let base=lists[0].slice();
    for(let i=1;i<lists.length;i++){{const s=new Set(lists[i]);base=base.filter(x=>s.has(x));if(!base.length)break}}
    return base;
  }}
  const seen=new Set(), out=[]; for(const list of lists)for(const id of list)if(!seen.has(id)){{seen.add(id);out.push(id)}} return out;
}}
function comparator(kind){{return {{
  score:(a,b)=>repoData[b].score-repoData[a].score,
  newest:(a,b)=>(repoData[b].isNew-repoData[a].isNew)||(repoData[b].firstSeen-repoData[a].firstSeen)||(repoData[b].score-repoData[a].score),
  early:(a,b)=>(repoData[b].isEarly-repoData[a].isEarly)||(repoData[b].score-repoData[a].score),
  rare:(a,b)=>(repoData[b].rarity-repoData[a].rarity)||(repoData[b].score-repoData[a].score),
  supporters:(a,b)=>(repoData[b].supporterCount-repoData[a].supporterCount)||(repoData[b].score-repoData[a].score),
  'stars-asc':(a,b)=>(repoData[a].stars-repoData[b].stars)||(repoData[b].score-repoData[a].score),
  'stars-desc':(a,b)=>(repoData[b].stars-repoData[a].stars)||(repoData[b].score-repoData[a].score),
  recent:(a,b)=>(repoData[b].recent-repoData[a].recent)||(repoData[b].score-repoData[a].score)
}}[kind]}}
function selectedLabels(){{
  const selected=selectedCats();
  if(!selected.length)return ['ALL'];
  return selected.map(cid=>{{
    const b=buttons.find(x=>x.dataset.cat===cid);
    return b?b.childNodes[0].textContent.trim():cid;
  }});
}}
function spotlightCardHTML(item){{
  const cats=item.categoryLabels.map(x=>`<span class="cat-badge">${{esc(x)}}</span>`).join('');
  const subs=item.subcategories.slice(0,4).map(x=>`<span class="sub-badge">${{esc(x)}}</span>`).join('');
  const badges=item.flags.map(x=>`<span class="badge">${{esc(x)}}</span>`).join('');
  const topics=item.topics.slice(0,8).map(esc).join(' · ')||'без topics';
  const support=item.supporters.map(s=>`@${{esc(s.login)}} (${{Number(s.score).toFixed(3)}})`).join(', ')||'—';
  const safeUrl=String(item.url||'').toLowerCase().startsWith('https://github.com/')?esc(item.url):'#';
  return `<article class="card spotlight-card"><div class="title-row"><a href="${{safeUrl}}" target="_blank" rel="noreferrer">${{esc(item.name)}}</a><strong>${{Number(item.score).toFixed(4)}}</strong></div><div>${{cats}}${{subs}}</div><div>${{badges}}</div><p>${{esc(item.description||'—')}}</p><div class="meta">★ ${{item.stars}} · ${{esc(item.language||'—')}} · ${{topics}}</div><div class="meta">Поддержка: ${{support}}</div></article>`;
}}
function renderSpotlights(selected, mode){{
  const allowedIds=idsForCategories(selected,mode);
  const allowed=selected.length?new Set(allowedIds):null;
  const filterBase=base=>allowed?base.filter(id=>allowed.has(id)):base.slice();
  const early=filterBase(earlyIds), recent=filterBase(recentIds);
  const LIMIT=30;
  earlyGrid.innerHTML=early.slice(0,LIMIT).map(id=>spotlightCardHTML(repoData[id])).join('') ||
    '<p class="meta">В выбранной категории нет результатов с флагом EARLY_SIGNAL.</p>';
  recentGrid.innerHTML=recent.slice(0,LIMIT).map(id=>spotlightCardHTML(repoData[id])).join('') ||
    '<p class="meta">В выбранной категории пока нет достаточно сильных свежих сигналов.</p>';
  earlyNoteEl.textContent=`Selected catalogs: ${{selectedLabels().join(' + ')}} · Early Signals: ${{early.length}}${{early.length>LIMIT?` · shown first ${{LIMIT}}`:''}}`;
  recentNoteEl.textContent=`Selected catalogs: ${{selectedLabels().join(' + ')}} · Recent discoveries: ${{recent.length}}${{recent.length>LIMIT?` · shown first ${{LIMIT}}`:''}}`;
}}
function applyRepoView(){{
  const selected=selectedCats(), mode=modeSel.value, q=f.value.trim().toLowerCase();
  let ids=idsForCategories(selected,mode);
  const categoryOnlyCount=ids.length;
  if(q)ids=ids.filter(id=>repoData[id].search.includes(q));
  ids.sort(comparator(sortSel.value)); viewIds=ids; renderState='';
  const labels=selectedLabels().join(' + ');
  catalogStatus.textContent=`Selected: ${{labels}} · ${{categoryOnlyCount}} repositories`;
  countEl.textContent=`Visible ${{viewIds.length}} / ${{repoData.length}}`;
  renderSpotlights(selected,mode);
  renderVirtualWindow(true);
}}
function repoCardHTML(item){{
  const cats=item.categoryLabels.map(x=>`<span class="cat-badge">${{esc(x)}}</span>`).join('');
  const subs=item.subcategories.slice(0,4).map(x=>`<span class="sub-badge">${{esc(x)}}</span>`).join('');
  const badges=item.flags.map(x=>`<span class="badge">${{esc(x)}}</span>`).join('');
  const topics=item.topics.slice(0,8).map(esc).join(' · ')||'без topics';
  const support=item.supporters.map(s=>`@${{esc(s.login)}} (${{Number(s.score).toFixed(3)}})`).join(', ')||'—';
  const safeUrl=String(item.url||'').toLowerCase().startsWith('https://github.com/')?esc(item.url):'#';
  return `<article class="card repo-card" data-id="${{item.id}}"><div class="title-row"><a href="${{safeUrl}}" target="_blank" rel="noreferrer">${{esc(item.name)}}</a><strong>${{Number(item.score).toFixed(4)}}</strong></div><div>${{cats}}${{subs}}</div><div>${{badges}}</div><p>${{esc(item.description||'—')}}</p><div class="meta clamp">★ ${{item.stars}} · ${{esc(item.language||'—')}} · ${{topics}}</div><div class="meta clamp">Поддержка: ${{support}}</div><div class="detail-row"><button class="detail-btn" data-kind="classification" data-id="${{item.id}}">Classification</button><button class="detail-btn" data-kind="features" data-id="${{item.id}}">Факторы</button><button class="detail-btn" data-kind="paths" data-id="${{item.id}}">Discovery paths</button></div></article>`;
}}
function renderVirtualWindow(force=false){{
  const c=cols(), totalRows=Math.ceil(viewIds.length/c), sectionTop=virtual.getBoundingClientRect().top+window.scrollY;
  const localY=Math.max(0,window.scrollY-sectionTop), firstVisible=Math.floor(localY/ROW_H);
  const viewportRows=Math.ceil(window.innerHeight/ROW_H)+OVERSCAN*2;
  const maxStartRow=Math.max(0,totalRows-1);
  const startRow=Math.min(maxStartRow,Math.max(0,firstVisible-OVERSCAN)), endRow=Math.min(totalRows,startRow+viewportRows);
  const start=startRow*c, end=Math.min(viewIds.length,endRow*c), state=`${{c}}:${{start}}:${{end}}:${{viewIds.length}}`;
  topSpacer.style.height=`${{startRow*ROW_H}}px`; bottomSpacer.style.height=`${{Math.max(0,(totalRows-endRow)*ROW_H)}}px`;
  if(!force&&state===renderState)return; renderState=state;
  grid.innerHTML=viewIds.slice(start,end).map(id=>repoCardHTML(repoData[id])).join('');
  const rendered=end-start; countEl.textContent=`Visible ${{viewIds.length}} / ${{repoData.length}} · rendered ${{rendered}}`;
}}
buttons.forEach(btn=>btn.addEventListener('click',()=>{{
  if(btn.dataset.cat==='all'){{buttons.forEach(b=>b.classList.toggle('active',b.dataset.cat==='all'));}}
  else{{buttons.find(b=>b.dataset.cat==='all').classList.remove('active');btn.classList.toggle('active');if(!selectedCats().length)buttons.find(b=>b.dataset.cat==='all').classList.add('active')}}
  applyRepoView();
}}));
f.addEventListener('input',()=>{{clearTimeout(searchTimer);searchTimer=setTimeout(applyRepoView,120)}});sortSel.addEventListener('change',applyRepoView);modeSel.addEventListener('change',applyRepoView);
window.addEventListener('scroll',()=>requestAnimationFrame(()=>renderVirtualWindow(false)),{{passive:true}});window.addEventListener('resize',()=>{{renderState='';requestAnimationFrame(()=>renderVirtualWindow(true))}});
grid.addEventListener('click',e=>{{const b=e.target.closest('.detail-btn');if(!b)return;const item=repoData[Number(b.dataset.id)],kind=b.dataset.kind;const payload=kind==='classification'?item.classification:(kind==='features'?item.features:item.paths);modalTitle.textContent=`${{item.name}} — ${{kind}}`;modalBody.textContent=JSON.stringify(payload,null,2);modal.classList.add('open')}});
document.getElementById('modalClose').addEventListener('click',()=>modal.classList.remove('open'));modal.addEventListener('click',e=>{{if(e.target===modal)modal.classList.remove('open')}});document.addEventListener('keydown',e=>{{if(e.key==='Escape')modal.classList.remove('open')}});
applyRepoView();
</script>
</main></body></html>'''
        path.write_text(doc, encoding="utf-8")
        return path

    def _community_data(self) -> list[tuple[int, list[str], list[str]]]:
        rows = self.storage.conn.execute(
            "SELECT * FROM community_membership WHERE scan_id=? ORDER BY community_id,member_type,weight DESC",
            (self.scan_id,),
        ).fetchall()
        grouped: dict[int, dict[str, list[str]]] = defaultdict(lambda: {"user": [], "repo": []})
        for row in rows:
            grouped[int(row["community_id"])][str(row["member_type"])].append(str(row["member_id"]))
        return [(cid, data["user"], data["repo"]) for cid, data in sorted(grouped.items())]


class Calibrator:
    def __init__(self, storage: Storage, owner_user: str):
        self.storage = storage
        self.owner = owner_user

    def calibrate_repo_weights(self, min_feedback: int = 5) -> tuple[dict[str, float], float, int]:
        feedback = self.storage.conn.execute(
            """
            SELECT repo_full_name,AVG(COALESCE(rating,
              CASE action WHEN 'saved' THEN 5 WHEN 'interesting' THEN 4 WHEN 'ignored' THEN 2 WHEN 'hide' THEN 1 ELSE 3 END)) AS label
            FROM user_feedback WHERE owner_user=? GROUP BY repo_full_name
            """, (self.owner,),
        ).fetchall()
        labels_by_repo = {str(r["repo_full_name"]): float(r["label"]) for r in feedback}
        if len(labels_by_repo) < min_feedback:
            raise StarBridgeError(f"Need at least {min_feedback} rated repositories; have {len(labels_by_repo)}")
        samples: list[tuple[str, dict[str, float], float]] = []
        for repo, label in labels_by_repo.items():
            row = self.storage.conn.execute(
                """
                SELECT s.features_json FROM scan_repo_scores s JOIN scans sc ON sc.id=s.scan_id
                WHERE sc.owner_user=? AND s.repo_full_name=? ORDER BY s.scan_id DESC LIMIT 1
                """, (self.owner, repo),
            ).fetchone()
            if row:
                feat = json.loads(row["features_json"] or "{}")
                if all(k in feat for k in REPO_DEFAULT_WEIGHTS):
                    samples.append((repo, {k: float(feat[k]) for k in REPO_DEFAULT_WEIGHTS}, label))
        if len(samples) < min_feedback:
            raise StarBridgeError(f"Only {len(samples)} feedback items have stored feature vectors; need {min_feedback}")

        current = ScoringEngine._normalized_weights(
            self.storage.setting_get(self.owner, "repo_weights", REPO_DEFAULT_WEIGHTS), REPO_DEFAULT_WEIGHTS
        )

        def objective(weights: Mapping[str, float]) -> float:
            scores = [sum(feat[k] * weights[k] for k in weights) for _, feat, _ in samples]
            labels = [label for _, _, label in samples]
            return ndcg(labels, scores)

        best = current
        best_obj = objective(best)
        factors = [0.60, 0.80, 1.00, 1.25, 1.60]
        for _ in range(4):
            improved = False
            for key in list(best):
                for factor in factors:
                    trial = dict(best)
                    trial[key] *= factor
                    total = sum(trial.values()) or 1.0
                    trial = {k: v / total for k, v in trial.items()}
                    score = objective(trial)
                    if score > best_obj + 1e-9:
                        best, best_obj, improved = trial, score, True
            if not improved:
                break
        self.storage.setting_set(self.owner, "repo_weights", best)
        return best, best_obj, len(samples)


class Benchmark:
    def __init__(self, storage: Storage, scan_id: int):
        self.storage = storage
        self.scan_id = scan_id
        row = storage.scan_row(scan_id)
        self.config = ScanConfig.from_json(str(row["config_json"]))

    def temporal_holdout(self, cutoff: dt.datetime, allow_leakage: bool = False) -> dict[str, Any]:
        configured = parse_date_cutoff(self.config.owner_cutoff)
        if not allow_leakage:
            if configured is None or abs((configured - cutoff).total_seconds()) > 60:
                raise StarBridgeError(
                    "Leakage-safe benchmark requires the scan to have been created with --owner-cutoff equal to --cutoff. "
                    "Run a new scan with --owner-cutoff YYYY-MM-DD, or pass --allow-leakage only for diagnostic use."
                )
        holdout_rows = self.storage.conn.execute(
            """
            SELECT us.repo_full_name,us.starred_at FROM user_stars us JOIN repos r ON r.full_name=us.repo_full_name
            WHERE us.user_login=? AND r.private=0 AND us.starred_at IS NOT NULL
            """, (self.config.user,),
        ).fetchall()
        holdout = {
            str(r["repo_full_name"]) for r in holdout_rows
            if (parse_iso(r["starred_at"]) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)) >= cutoff
        }
        train = {s.repo.full_name for s in self.storage.owner_profile(self.scan_id)}
        holdout -= train
        ranked_rows = self.storage.conn.execute(
            "SELECT repo_full_name,score FROM scan_repo_scores WHERE scan_id=? ORDER BY score DESC", (self.scan_id,)
        ).fetchall()
        ranked = [str(r["repo_full_name"]) for r in ranked_rows]
        metrics: dict[str, Any] = {
            "scan_id": self.scan_id,
            "cutoff": cutoff.isoformat(),
            "holdout_count": len(holdout),
            "ranked_count": len(ranked),
            "leakage_safe": bool(configured is not None and abs((configured - cutoff).total_seconds()) <= 60),
        }
        for k in (100, 500, 1000):
            top = ranked[:k]
            hits = len(set(top) & holdout)
            metrics[f"hits@{k}"] = hits
            metrics[f"recall@{k}"] = hits / len(holdout) if holdout else 0.0
            metrics[f"precision@{k}"] = hits / max(1, len(top))
        return metrics


def mode_defaults(mode: str) -> dict[str, Any]:
    if mode == "wide":
        return dict(budget=4200, max_depth=2, auto_seeds=60, seed_pool=180, actor_beam=1800,
                    repo_beam=7000, source_pages=1, actor_star_pages=4, carry_people=180,
                    repo_promotions_per_actor=3, event_pages=1, public_repo_pages=1)
    if mode == "deep":
        return dict(budget=4200, max_depth=5, auto_seeds=18, seed_pool=80, actor_beam=650,
                    repo_beam=3500, source_pages=3, actor_star_pages=30, carry_people=80,
                    repo_promotions_per_actor=7, event_pages=2, public_repo_pages=2)
    return dict(budget=4200, max_depth=4, auto_seeds=30, seed_pool=110, actor_beam=1100,
                repo_beam=5500, source_pages=2, actor_star_pages=20, carry_people=120,
                repo_promotions_per_actor=5, event_pages=1, public_repo_pages=1)


def build_config(args: argparse.Namespace) -> ScanConfig:
    defaults = mode_defaults(args.mode)
    def pick(name: str) -> Any:
        value = getattr(args, name, None)
        return defaults.get(name) if value is None else value
    sources = tuple(x.strip() for x in (args.sources or ",".join(DEFAULT_SOURCES)).split(",") if x.strip())
    unknown = sorted(set(sources) - set(DEFAULT_SOURCES))
    if unknown:
        raise StarBridgeError("Unknown sources: " + ", ".join(unknown))
    return ScanConfig(
        user=args.user,
        mode=args.mode,
        budget=int(pick("budget")),
        max_depth=int(pick("max_depth")),
        auto_seeds=int(pick("auto_seeds")),
        seed_pool=int(pick("seed_pool")),
        actor_beam=int(pick("actor_beam")),
        repo_beam=int(pick("repo_beam")),
        source_pages=int(pick("source_pages")),
        actor_star_pages=int(pick("actor_star_pages")),
        owner_star_pages=int(args.owner_star_pages),
        min_overlap=int(args.min_overlap),
        recent_days=int(args.recent_days),
        history_sampling=args.history_sampling,
        transport=args.transport,
        graphql_batch=int(args.graphql_batch),
        private_policy=args.private_policy,
        owner_cutoff=args.owner_cutoff,
        sources=sources,
        carry_people=int(pick("carry_people")),
        repo_promotions_per_actor=int(pick("repo_promotions_per_actor")),
        event_pages=int(pick("event_pages")),
        public_repo_pages=int(pick("public_repo_pages")),
        max_repo_stars=int(args.max_repo_stars),
        include_forks=bool(args.include_forks),
        include_archived=bool(args.include_archived),
        min_page_yield=int(args.min_page_yield),
        ema_alpha=float(args.ema_alpha),
        pause=float(args.pause),
        retry_count=int(args.retries),
        explicit_seeds=tuple(args.seed or ()),
    )


def add_scan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user", required=True, help="GitHub login of the profile whose interests are the reference")
    parser.add_argument("--mode", choices=["adaptive", "wide", "deep"], default="adaptive")
    parser.add_argument("--budget", type=int, default=None, help="REST/GraphQL request budget for this scan")
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--auto-seeds", type=int, default=None)
    parser.add_argument("--seed-pool", type=int, default=None)
    parser.add_argument("--actor-beam", type=int, default=None)
    parser.add_argument("--repo-beam", type=int, default=None)
    parser.add_argument("--source-pages", type=int, default=None)
    parser.add_argument("--actor-star-pages", type=int, default=None)
    parser.add_argument("--owner-star-pages", type=int, default=0, help="0 = load the complete owner star list until pagination ends")
    parser.add_argument("--min-overlap", type=int, default=1)
    parser.add_argument("--recent-days", type=int, default=365)
    parser.add_argument("--history-sampling", choices=["recent", "stratified", "exhaustive"], default="stratified")
    parser.add_argument("--transport", choices=["auto", "rest", "graphql"], default="auto")
    parser.add_argument("--graphql-batch", type=int, default=8)
    parser.add_argument("--private-policy", choices=["ignore", "local-only"], default="ignore")
    parser.add_argument("--owner-cutoff", default=None, help="Leakage-safe benchmark cutoff, YYYY-MM-DD")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--carry-people", type=int, default=None)
    parser.add_argument("--repo-promotions-per-actor", type=int, default=None)
    parser.add_argument("--event-pages", type=int, default=None)
    parser.add_argument("--public-repo-pages", type=int, default=None)
    parser.add_argument("--max-repo-stars", type=int, default=0, help="0 = no popularity cutoff")
    parser.add_argument("--include-forks", action="store_true")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--min-page-yield", type=int, default=5)
    parser.add_argument("--ema-alpha", type=float, default=0.45)
    parser.add_argument("--pause", type=float, default=0.12)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--seed", action="append", default=[], help="Explicit OWNER/REPO seed; repeatable")
    parser.add_argument("--report", default=None, help="HTML report path")
    parser.add_argument("--top-people", type=int, default=500)
    parser.add_argument("--top-repos", type=int, default=10000)
    parser.add_argument("--open", action="store_true", dest="open_report")


def parser_build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="starbridge.py",
        description="StarBridge 1.0 — adaptive recursive rare-interest discovery on GitHub",
    )
    p.add_argument("--db", default="starbridge_1_0.db", help="SQLite database path")
    p.add_argument("--token", default=None, help="GitHub token; prefer GITHUB_TOKEN environment variable")
    p.add_argument("--version", action="version", version=f"StarBridge {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Verify token, login and API access without crawling")
    doctor.add_argument("--user", required=True)

    massive = sub.add_parser("massive", help="Start a new A-RIR scan")
    add_scan_args(massive)

    resume = sub.add_parser("resume", help="Continue a paused scan from its persistent frontier")
    resume.add_argument("--scan-id", type=int, default=None)
    resume.add_argument("--add-budget", type=int, default=0)
    resume.add_argument("--report", default=None)
    resume.add_argument("--top-people", type=int, default=500)
    resume.add_argument("--top-repos", type=int, default=10000)
    resume.add_argument("--open", action="store_true", dest="open_report")

    report = sub.add_parser("report", help="Regenerate HTML from the local database; no GitHub requests")
    report.add_argument("--scan-id", type=int, default=None)
    report.add_argument("--report", default=None)
    report.add_argument("--top-people", type=int, default=500)
    report.add_argument("--top-repos", type=int, default=10000)
    report.add_argument("--open", action="store_true", dest="open_report")

    feedback = sub.add_parser("feedback", help="Record local feedback for deterministic calibration")
    feedback.add_argument("--user", required=True)
    feedback.add_argument("--repo", required=True)
    feedback.add_argument("--rating", type=int, choices=range(1, 6), default=None)
    feedback.add_argument("--action", choices=["saved", "interesting", "ignored", "hide", ""], default="")

    cal = sub.add_parser("calibrate", help="Calibrate repository score weights using local feedback")
    cal.add_argument("--user", required=True)
    cal.add_argument("--min-feedback", type=int, default=5)

    bench = sub.add_parser("benchmark", help="Temporal holdout benchmark")
    bench.add_argument("--scan-id", type=int, required=True)
    bench.add_argument("--cutoff", required=True, help="YYYY-MM-DD")
    bench.add_argument("--allow-leakage", action="store_true")

    sub.add_parser("selftest", help="Run built-in offline deterministic tests")
    return p


def cmd_doctor(storage: Storage, client: GitHubClient, user: str) -> int:
    print(f"StarBridge {VERSION} doctor")
    print(f"Database: {storage.path}")
    print(f"Token: {'present' if client.token else 'missing'}")
    try:
        if client.token:
            viewer = client.viewer()
            print(f"Authenticated viewer: @{viewer.get('login')}")
        repo_data, _, _ = client.request_json("/repos/octocat/Hello-World")
        print(f"Public repository API: OK ({repo_data.get('full_name') if isinstance(repo_data, Mapping) else 'response'})")
        stars, _, _ = client.get_star_page_rest(user, authenticated_self=False)
        print(f"Public stars for @{user}: OK ({len(stars)} items on first page)")
        rate = client.rate_limit()
        resources = rate.get("resources") if isinstance(rate, Mapping) else {}
        core = resources.get("core") if isinstance(resources, Mapping) else {}
        if isinstance(core, Mapping):
            print(f"REST core: remaining {core.get('remaining')} / {core.get('limit')}; reset {core.get('reset')}")
        if client.token:
            try:
                gql = client.graphql_star_batch_first([user])
                print(f"GraphQL starredRepositories: OK ({len(gql.get(user, {}).get('stars', []))} items)")
            except StarBridgeError as exc:
                print(f"GraphQL: unavailable ({exc}); REST mode remains usable")
        print("Doctor result: OK")
        return 0
    except StarBridgeError as exc:
        print(f"Doctor result: FAILED — {exc}", file=sys.stderr)
        return 2


def _report_path(value: str | None, scan_id: int) -> Path:
    return Path(value) if value else Path(f"starbridge_scan_{scan_id}.html")


def offline_selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.db"
        st = Storage(db)
        try:
            assert normalized_global_rarity(10) > normalized_global_rarity(10000)
            assert local_idf(100, 1) > local_idf(100, 80)
            cfg = ScanConfig(user="alice", budget=100, auto_seeds=2, seed_pool=10, sources=("owner", "contributors"))
            scan = st.create_scan(cfg)
            def rr(name: str, stars: int, topics: list[str], owner: str = "x") -> RepoRecord:
                return RepoRecord(name, f"https://github.com/{name}", "", "Python", stars, topics,
                                  False, False, False, False, owner, utc_now_iso(), utc_now_iso(), utc_now_iso())
            owner_stars = [StarRecord(rr("a/rare", 10, []), utc_now_iso()),
                           StarRecord(rr("b/common", 100000, ["x"]), utc_now_iso()),
                           StarRecord(rr("c/rare2", 20, ["y"]), utc_now_iso())]
            st.save_owner_profile(scan, "alice", owner_stars, "ignore", None)
            selected = SeedPortfolioOptimizer(2, 10).select(owner_stars, [])
            assert len(selected) == 2 and selected[0][0] in {"a/rare", "c/rare2"}
            # Synthetic candidate with rare overlap and a recommendation.
            st.save_user("bob")
            st.add_candidate(scan, "bob", 0.8, 1.0, "contributors", "a/rare", 0,
                             [{"type":"seed","id":"a/rare"},{"type":"user","id":"bob"}])
            st.save_star(scan, "bob", StarRecord(rr("a/rare", 10, []), utc_now_iso()))
            st.save_star(scan, "bob", StarRecord(rr("d/new", 15, []), utc_now_iso()))
            st.add_repo_support(scan, "bob", "d/new", "star", utc_now_iso(), 0,
                                [{"type":"user","id":"bob"},{"type":"repo","id":"d/new"}])
            st.promote_seed(scan, "a/rare", 0, "test", 1.0, None, [])
            scoring = ScoringEngine(st, scan, cfg)
            people = scoring.score_people()
            assert people and people[0].login == "bob" and people[0].score > 0
            repos = scoring.score_repos(people)
            assert repos and repos[0].repo.full_name == "d/new" and "NO_TOPICS" in repos[0].flags
            # Persistent frontier priority / resume.
            t1 = st.enqueue_task(scan, "actor_stars", "u1", source="stars", relevance=0.2, expected_yield=10)
            t2 = st.enqueue_task(scan, "actor_stars", "u2", source="stars", relevance=0.8, expected_yield=10)
            popped = st.pop_task(scan)
            assert popped is not None and popped.node_id == "u2"
            st.reset_in_progress(scan)
            # Feedback calibration dataset.
            for i in range(6):
                name = f"z/r{i}"
                repo = rr(name, 10 + i, [])
                st.save_repo(repo, scan)
                feat = {k: (0.9 - i*0.05 if k == "support_strength" else 0.2 + i*0.02) for k in REPO_DEFAULT_WEIGHTS}
                st.conn.execute(
                    "INSERT OR REPLACE INTO scan_repo_scores(scan_id,repo_full_name,score,features_json,supporters_json,flags_json,paths_json,new_since_previous) VALUES(?,?,?,?,?,?,?,1)",
                    (scan, name, 0.5, json_dumps(feat), "[]", "[]", "[]"),
                )
                st.feedback_add("alice", name, 5-i//2, "")
            st.conn.commit()
            weights, obj, n = Calibrator(st, "alice").calibrate_repo_weights(5)
            assert abs(sum(weights.values()) - 1.0) < 1e-9 and n >= 5 and 0 <= obj <= 1
            # Report generation.
            st.save_people_scores(scan, people); st.save_repo_scores(scan, repos)
            report = HtmlReport(st, scan).generate(Path(td) / "report.html")
            report_text = report.read_text(encoding="utf-8")
            assert report.exists() and "StarBridge" in report_text and "Categories" in report_text
            c = CatalogEngine.load().classify(rr("x/llm-security", 12, ["llm", "application-security"]))
            assert "ai_ml" in c.category_ids and "security" in c.category_ids
        finally:
            st.close()
    print("Selftest: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    print_pixel_logo()
    args = parser_build().parse_args(argv)
    if args.command == "selftest":
        offline_selftest()
        return 0

    db_path = Path(args.db).expanduser().resolve()
    storage = Storage(db_path)
    token = args.token or os.environ.get("GITHUB_TOKEN") or None
    client = GitHubClient(storage, token)
    try:
        if args.command == "doctor":
            return cmd_doctor(storage, client, args.user)

        if args.command == "feedback":
            storage.feedback_add(args.user, normalize_repo(args.repo), args.rating, args.action)
            print(f"Feedback saved for {normalize_repo(args.repo)}")
            return 0

        if args.command == "calibrate":
            weights, score, count = Calibrator(storage, args.user).calibrate_repo_weights(args.min_feedback)
            print(f"Calibrated on {count} repositories; nDCG={score:.6f}")
            print(json.dumps(weights, ensure_ascii=False, indent=2))
            return 0

        if args.command == "benchmark":
            cutoff = parse_date_cutoff(args.cutoff)
            assert cutoff is not None
            metrics = Benchmark(storage, args.scan_id).temporal_holdout(cutoff, args.allow_leakage)
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
            return 0

        if args.command == "report":
            scan_id = args.scan_id or storage.latest_scan()
            if scan_id is None:
                raise StarBridgeError("No scans in the database")
            reporter = HtmlReport(storage, scan_id)
            out = reporter.generate(
                _report_path(args.report, scan_id), top_people=args.top_people, top_repos=args.top_repos
            )
            reporter.print_catalog_summary()
            print(f"Report: {out.resolve()}")
            if args.open_report:
                webbrowser.open(out.resolve().as_uri())
            return 0

        if args.command == "massive":
            cfg = build_config(args)
            if cfg.budget <= 0:
                raise StarBridgeError("--budget must be > 0")
            if cfg.transport == "graphql" and not token:
                raise StarBridgeError("--transport graphql requires GITHUB_TOKEN or --token")
            scan_id = storage.create_scan(cfg)
            client = GitHubClient(storage, token, scan_id=scan_id, pause_seconds=cfg.pause, retry_count=cfg.retry_count)
            engine = StarBridgeEngine(storage, client, cfg, scan_id)
            people, repos, note = engine.run_new()
            print("[5/6] Building HTML report ...")
            reporter = HtmlReport(storage, scan_id)
            out = reporter.generate(
                _report_path(args.report, scan_id), top_people=args.top_people, top_repos=args.top_repos
            )
            print(f"[6/6] Done. scan={scan_id} people={len(people)} repos={len(repos)}")
            reporter.print_catalog_summary()
            print(f"Report: {out.resolve()}")
            if note:
                print(f"State: {note}")
            if storage.pending_count(scan_id):
                print(f"Resume: py .\\starbridge.py --db \"{db_path}\" resume --scan-id {scan_id} --add-budget 3000 --open")
            if args.open_report:
                webbrowser.open(out.resolve().as_uri())
            return 0

        if args.command == "resume":
            scan_id = args.scan_id or storage.latest_scan()
            if scan_id is None:
                raise StarBridgeError("No scans in the database")
            row = storage.scan_row(scan_id)
            cfg = ScanConfig.from_json(str(row["config_json"]))
            if args.add_budget > 0:
                storage.add_budget(scan_id, args.add_budget)
            client = GitHubClient(storage, token, scan_id=scan_id, pause_seconds=cfg.pause, retry_count=cfg.retry_count)
            engine = StarBridgeEngine(storage, client, cfg, scan_id)
            people, repos, note = engine.resume()
            reporter = HtmlReport(storage, scan_id)
            out = reporter.generate(
                _report_path(args.report, scan_id), top_people=args.top_people, top_repos=args.top_repos
            )
            print(f"Resumed scan {scan_id}: people={len(people)} repos={len(repos)} pending={storage.pending_count(scan_id)}")
            reporter.print_catalog_summary()
            print(f"Report: {out.resolve()}")
            if note:
                print(f"State: {note}")
            if args.open_report:
                webbrowser.open(out.resolve().as_uri())
            return 0

        raise StarBridgeError(f"Unknown command: {args.command}")
    except StarBridgeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
