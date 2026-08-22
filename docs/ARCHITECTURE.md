# StarBridge 1.0 Architecture

## Core A-RIR loop

```text
Owner Star Profile
      ↓
Seed Portfolio Optimizer
      ↓
Repository Expansion
      ↓
Public Actors
      ↓
Actor Star Profiles
      ↓
Similarity 2.0
      ↓
New Repositories
      ↓
Seed Promotion
      └──────────────→ next hop
```

## Frontier priority

```text
priority = ExpectedYield × Novelty × Relevance × Confidence / Cost
```

Tasks are persisted in SQLite and survive interruption.

## Repository sources

```text
owner
contributors
forks
issues
pulls
comments
reviews
commits
releases
```

## Actor expansion

```text
public starred repositories
public owned repositories
recent public events
```

## Similarity 2.0

Person features:

```text
rare_overlap
weighted_jaccard
containment
temporal
seed_affinity
structural
```

Repository features:

```text
support_strength
supporter_diversity
global_rarity
local_rarity
temporal_velocity
activity_recency
no_topics
path_diversity
```

## Persistence

SQLite stores graph, snapshots, cache, frontier, scores, feedback, communities, paths and metrics.

## Read-only invariant

No GitHub write endpoint is used.
