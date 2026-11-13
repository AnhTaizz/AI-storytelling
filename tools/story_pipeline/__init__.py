"""Story pipeline prototype v0: Story Brief -> Narrative Plan -> Script -> Critic -> Revision.

A vertical-slice prototype built while M4 (Story Extraction) is still open. It reads
source passages through the frozen M3 ingestion adapter and can later accept
upstream extraction output through the `story_facts/v0` seam (see facts.py).

Nothing here is frozen. See docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md.
"""

PIPELINE_VERSION = "STORY_PIPELINE_PROTOTYPE/v0"
