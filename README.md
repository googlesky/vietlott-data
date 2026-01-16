# Vietlott Data

Daily updated Vietlott lottery data.

## Products

| Product | File | Description |
|---------|------|-------------|
| Power 655 | `data/power655.jsonl` | 6 numbers + bonus (7 total) from 1-55 |
| Power 645 | `data/power645.jsonl` | 6 numbers from 1-45 |
| Max 3D | `data/max3d.jsonl` | 20 three-digit numbers (flattened) |
| Max 3D Pro | `data/max3d_pro.jsonl` | 20 three-digit numbers (flattened) |
| Lotto 535 | `data/lotto535.jsonl` | 5 numbers from 1-35 |

## Data Format

Each line is a JSON object. The `result` field shape depends on the product:

```json
{"date": "2026-01-14", "id": "01234", "result": [1, 2, 3, 4, 5, 6], "process_time": "..."}
```

For Max 3D / Max 3D Pro:

```json
{"date": "2026-01-14", "id": "01030", "result": ["015", "517", "..."], "process_time": "..."}
```

Notes:
- Power 655 stores 7 numbers (6 main + bonus).
- Lotto 535 stores 5 numbers; any upstream bonus number is dropped.

## Data Sources & Update Strategy

- GitHub Actions uses the upstream dataset to avoid Vietlott 403 blocks.
- Local runs use direct crawling by default.
- Upstream source:

```
https://github.com/vietvudanh/vietlott-data
```

## Auto Update

Data is automatically updated daily at midnight Vietnam time (00:00 Asia/Ho_Chi_Minh, cron `0 17 * * *` UTC) via GitHub Actions.

## Manual Update

```bash
uv sync
uv run python update_data.py
```

If you want to force upstream sync locally (same as GitHub Actions):

```bash
GITHUB_ACTIONS=true uv run python update_data.py
```
