# Story Intelligence Platform

AI-powered Story Intelligence and Narrative Production Platform.

**Current stage:** M1–M3 complete and frozen. M4 — Story Extraction in progress.

**Product purpose:** Transform long-form narrative sources (Light Novels, Manga, Web Novels) into grounded, engaging storytelling outputs. The first major product outcome is a high-quality grounded YouTube script.

**Implementation:** M2 Canonical Story Model and M3 Light Novel ingestion are implemented and frozen. M4 Story Extraction is in research. An end-to-end script pipeline prototype (Brief → Plan → Script → Critic → Revision) is available: see [Story Pipeline Prototype v0](docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md). Current status: [Project State](docs/PROJECT_STATE.md).

## Vietnamese light-novel recaps

The CLI defaults to a third-person Vietnamese retelling at 40–50% of the full episode
in Vietnamese. The percentage applies to narration length. CORE plot events still need
coverage in the spoken script. Cross-language runs estimate the full translated length
during the existing brief call. Supply a known full count for a measured comparison.
Other channel formats can select a separate YAML profile using `--profile`.

```bash
python -m tools.story_pipeline.run_pipeline --chapters 1
python -m tools.story_pipeline.run_pipeline --chapters 2-3 --recap --full-target-units 4000
```

[Length measurement, per-stage models and usage](docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md#episode-budgets-and-model-routing)

## Foundation Documents

- [Product Vision](docs/PRODUCT_VISION.md)
- [MVP Scope](docs/MVP_SCOPE.md)
- [Architectural Principles](docs/ARCHITECTURAL_PRINCIPLES.md)
- [Target Architecture](docs/TARGET_ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions](docs/DECISIONS.md)
- [Project State](docs/PROJECT_STATE.md)
