<p align="center">
  <img src="starbridge-logo.png" alt="StarBridge" width="900">
</p>

# StarBridge

StarBridge is a deterministic GitHub discovery tool for finding people with similar repository interests and uncovering repositories you would likely miss through normal search, topics, or hashtags.

It does not use AI, embeddings, or semantic search.

---

## How it works

```text
seed repositories
→ public participants
→ their starred repositories
→ rare-interest overlap
→ new repositories
→ promoted seeds
→ recursive discovery
```

StarBridge uses the public GitHub graph around repositories and users, then recursively expands promising branches with A-RIR (Adaptive Recursive Rare-Interest Relay).

---

## Features

- Recursive multi-hop repository discovery
- Explicit seed mode: start from any owner/repository
- Adaptive request budget and frontier
- Rare-interest scoring
- Early-signal detection
- Local topic catalogs (AI, Security, OSINT, DevTools, etc.)
- Fast virtualized HTML reports for large result sets
- Persistent SQLite state and resume support
- Deterministic local feedback/calibration
- REST + GraphQL with fallback
- No external Python dependencies

---

## Requirements

- Python 3.11+
- GitHub Personal Access Token with Starring: Read-only

---

## Quick start

### Set your token in PowerShell

```powershell
$env:GITHUB_TOKEN = "github_pat_YOUR_TOKEN"
```

### Check access

```powershell
python .\starbridge.py --db .\starbridge.db doctor --user YOUR_GITHUB_LOGIN
```

### Run a scan

```powershell
python .\starbridge.py --db .\starbridge.db massive --user YOUR_GITHUB_LOGIN --mode adaptive --budget 1500 --open
```

### Start from a specific repository

```powershell
python .\starbridge.py --db .\starbridge.db massive --user YOUR_GITHUB_LOGIN --seed owner/repository --auto-seeds 0 --mode adaptive --budget 1500 --max-depth 3 --open
```

### Resume a scan

```powershell
python .\starbridge.py --db .\starbridge.db resume --scan-id 1 --add-budget 3000 --open
```

### Rebuild the HTML report without new GitHub requests

```powershell
python .\starbridge.py --db .\starbridge.db report --scan-id 1 --top-repos 50000 --open
```

---

## More commands

`COMMANDS_RU.md`
