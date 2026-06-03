# Dataset Folder

Private challenge data should stay local and must not be published to GitHub.

The current pipeline can read the updated challenge dataset directly from the
local `updated_docs/` folder:

```bash
python -m pipeline.run --input updated_docs --output events.jsonl
```

If you prefer using this `data/` folder instead, place equivalent private files
here locally:

- layout PNG or `store_layout.json`
- POS CSV file
- sample event JSONL file
- CCTV/video clips

The repository intentionally tracks only this README. Dataset files, generated
events, and database files are ignored.
