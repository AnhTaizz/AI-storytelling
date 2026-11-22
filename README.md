# Story Intelligence Platform

AI-powered Story Intelligence and Narrative Production Platform.

**Current stage:** M1–M3 complete and frozen. M4 — Story Extraction in progress.

**Product purpose:** Transform long-form narrative sources (Light Novels, Manga, Web Novels) into grounded, engaging storytelling outputs. The first major product outcome is a high-quality grounded YouTube script.

**Implementation:** M2 Canonical Story Model and M3 Light Novel ingestion are implemented and frozen. M4 Story Extraction is in research. An end-to-end script pipeline prototype (Brief → Plan → Script → Critic → Revision) is available: see [Story Pipeline Prototype v0](docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md). Current status: [Project State](docs/PROJECT_STATE.md).

## Bắt đầu nhanh

### Chạy một tập từ dữ liệu mẫu

Từ thư mục gốc repo, dùng Python 3.13 trở lên. Sao chép [`.env.example`](.env.example) thành `.env` rồi điền `GEMINI_API_KEY_1` và `GEMINI_MODEL`. Lệnh dưới chạy một tập gồm chương 1 theo [manifest mẫu tiếng Nhật](data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml). Xem cách chọn model trong [hướng dẫn pipeline](docs/guides/HUONG_DAN_PIPELINE.md).

```sh
python -m pip install -r requirements-canonical-story.txt -r requirements-story-extraction-gemini.txt
python -m tools.story_pipeline.run_pipeline --chapters 1
```

### Tìm bản nháp và báo cáo duyệt

Mở thư mục lần chạy trong `.local/story_pipeline_runs/<id>/`. Đường dẫn cụ thể được in ở dòng `run dir:`.

- `script_final.md` chứa bản nháp kịch bản. `script_final.txt` chỉ chứa lời dẫn.
- `report.md` ghi kết quả kiểm tra và lý do nếu bản nháp **Cần duyệt**.
- `review.html` là trang duyệt để đọc kịch bản cạnh brief và nguyên văn nguồn.

### Tìm code và chạy test offline

Mã pipeline nằm trong [`tools/story_pipeline/`](tools/story_pipeline/), với [`run_pipeline.py`](tools/story_pipeline/run_pipeline.py) là điểm chạy một tập. Bộ test offline nằm trong [`tests/story_pipeline/`](tests/story_pipeline/) và chạy bằng mô hình giả.

```sh
python -m tools.ci.run_tests --suite story_pipeline
```

## Foundation Documents

- [Product Vision](docs/PRODUCT_VISION.md)
- [MVP Scope](docs/MVP_SCOPE.md)
- [Architectural Principles](docs/ARCHITECTURAL_PRINCIPLES.md)
- [Target Architecture](docs/TARGET_ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions](docs/DECISIONS.md)
- [Project State](docs/PROJECT_STATE.md)
