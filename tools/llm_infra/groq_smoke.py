"""Make one small JSON-mode request with the configured Free plan Groq router."""
import argparse
import json
import time

from tools.llm_infra.gemini_config import merged_settings, state_path
from tools.llm_infra.groq_config import inspect_groq_settings
from tools.llm_infra.groq_router import GroqRouter, GroqTransportError
from tools.llm_infra.groq_transport import GroqClient
from tools.llm_infra.quota_state import QuotaStateStore
from tools.story_extraction.gemini_key_pool_v1 import GeminiConfigError


def main(argv=None, *, environ=None, client_factory=GroqClient, clock=time.time, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    start = clock()
    report = {"slot_id": None, "scope": None, "model": None}
    try:
        settings = merged_settings(args.env_file, environ)
        config = inspect_groq_settings(settings, args.model)
        config.check_eligible()
        model = report["model"] = config.model_chain[0]
        store = QuotaStateStore(state_path(settings), clock=clock)
        router = GroqRouter(config, store, client_factory, clock=clock, sleep=sleep)
        record = router.generate("Respond with a JSON object.", 'Return {"status":"ok"}', model,
                                 {"temperature": 0, "max_output_tokens": 128,
                                  "response_mime_type": "application/json"}, "groq-smoke")
        report.update(slot_id=record["slot_id"], scope=record["scope"],
                      outcome="SUCCESS", latency_seconds=record["latency_seconds"])
    except (GroqTransportError, GeminiConfigError, OSError) as error:
        report.update(outcome=error.code if isinstance(error, GroqTransportError) else "CONFIG_ERROR",
                      latency_seconds=max(0, clock() - start))
    print(json.dumps(report))
    return int(report["outcome"] != "SUCCESS")


if __name__ == "__main__":
    raise SystemExit(main())
