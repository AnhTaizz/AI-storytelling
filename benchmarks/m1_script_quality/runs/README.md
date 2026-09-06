# Run Record Contract

Every future experiment run should have a small manifest located here.

## Suggested Naming Convention
- RUN_0001_BASELINE_A
- RUN_0002_BASELINE_B

## Run Record Fields
Each run should eventually record:
- Run ID
- Timestamp
- Git commit
- Baseline
- Golden Story fixture ID
- Source hashes
- Prompt version
- Model/provider
- Model settings
- Input scope
- Output artifact
- Human evaluation artifact
- Failure report(s)
- Notes

## Source Hashing & Reproducibility
Future runs should record source hashes (Source file → SHA-256 → experiment manifest). This ensures we can verify if two baseline runs used the exact same source material without committing the source itself.

## Prompt Versioning Principle
Future baseline prompts must be committed and versioned. Do not hide prompt changes between runs. If a prompt changes, it must be distinguishable (e.g., Prompt v1 -> Run -> Result; Prompt v2 -> Run -> Result).
