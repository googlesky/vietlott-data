# Vietlott Data

Daily updated Vietlott lottery data.

## Products

| Product | File | Description |
|---------|------|-------------|
| Power 655 | `data/power655.jsonl` | 6 numbers from 1-55 |
| Power 645 | `data/power645.jsonl` | 6 numbers from 1-45 |
| Max 3D | `data/max3d.jsonl` | 20 three-digit numbers |
| Max 3D Pro | `data/max3d_pro.jsonl` | 20 three-digit numbers |
| Lotto 535 | `data/lotto535.jsonl` | 5 numbers from 1-35 |

## Data Format

Each line is a JSON object:

```json
{"date": "2026-01-14", "id": "01234", "result": [1, 2, 3, 4, 5, 6], "process_time": "..."}
```

## Auto Update

Data is automatically updated daily at midnight (Vietnam time) via GitHub Actions.

## Manual Update

```bash
uv sync
uv run python update_data.py
```
