# Paper → StarBridge 1.0 implementation matrix

| Paper direction | StarBridge 1.0 |
|---|---|
| A-RIR recursive relay | `StarBridgeEngine`, automatic seed promotion |
| Seed Portfolio | `SeedPortfolioOptimizer` |
| Multi-hop | `max_depth`, promoted seed frontier |
| Extended actor sources | owner/contributors/forks/issues/pulls/comments/reviews/commits/releases |
| Actor expansion | `actor_stars`, `actor_events`, `actor_repos` |
| Repository expansion | `repo_source`, `repo_detail` |
| Adaptive star depth | page yield EMA + person score |
| Recent profile | ordered `starred_at`, temporal scoring |
| Long-term profile | persistent historical stars + stratified pages |
| Stratified sampling | middle/old star pages for promising actors |
| Full owner profile | `/user/starred`, `--owner-star-pages 0` |
| REST + GraphQL | hybrid client + auto fallback |
| Request budget | persisted `budget_total/budget_used` |
| Adaptive scheduler | frontier priority formula |
| Yield model | `source_yield` EMA |
| Global rarity | star-count rarity |
| Local rarity | corpus IDF |
| Similarity 2.0 | six person features |
| Feedback calibration | `feedback`, `calibrate` |
| Persistent memory | SQLite cumulative graph |
| Negative memory | direct + pattern suppression, decay |
| Persistent frontier | `frontier_tasks` |
| Resume | `resume` command |
| Beam search | `actor_beam`, `repo_beam`, frontier pruning |
| Diversity pressure | ranking concentration penalty + seed portfolio diversity |
| Community discovery | deterministic union-find shared rare stars |
| Discovery paths | `discovery_paths`, report section |
| No-topics signal | feature + flag, not sole ranking condition |
| Temporal discovery | temporal velocity + Recent section |
| Early signal | `EARLY_SIGNAL` flag |
| Owner relay | `owner` source |
| Recent public activity | `actor_events` |
| No hidden stargazer reconstruction | architectural invariant |
| Conditional requests | SQLite ETag cache + If-None-Match |
| API rate awareness | rate headers + pause/resume |
| Wide/Deep/Adaptive | three presets |
| People/Repos/Communities/Paths | HTML report |
| Temporal holdout | `benchmark` command |
| Local calibration | deterministic coordinate search |
