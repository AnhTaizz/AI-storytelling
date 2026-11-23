import json
from types import SimpleNamespace


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class Error(Exception):
    def __init__(self, code=429, *, quota="", delay=None, header=None):
        super().__init__("test-key-not-real-1")
        self.code = code
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": quota}]}]
        if delay is not None:
            details.append({"@type": "google.rpc.RetryInfo", "retryDelay": delay})
        self.details = {"error": {"details": details}}
        self.response = SimpleNamespace(headers={"Retry-After": header})


def settings(*labels):
    source = {"GEMINI_MODEL": "gemini-3.8-flash", "GEMINI_FREE_MODELS": "gemini-3.8-flash,gemini-3.6-flash"}
    for n, label in enumerate(labels, 1):
        source.update({f"GEMINI_API_KEY_{n}": f"test-key-not-real-{n}",
                       f"GEMINI_PROJECT_BILLING_{n}": "FREE_TIER_CONFIRMED",
                       f"GEMINI_PROJECT_LABEL_{n}": label})
    return source


GROQ_TEST_KEY = "test-groq-key-not-real-1"


def groq_settings(*labels):
    source = {}
    for n, label in enumerate(labels, 1):
        source[f"GROQ_API_KEY_{n}"] = f"test-groq-key-not-real-{n}"
        if label:
            source[f"GROQ_ORG_LABEL_{n}"] = label
    return source


class FakeGroq:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls = []
        self.factory_calls = []

    def factory(self, key):
        self.factory_calls.append(key)

        def generate(**args):
            self.calls.append((key, args))
            if self.actions:
                action = self.actions.pop(0)
                if isinstance(action, Exception):
                    raise action
                return action
            return SimpleNamespace(text='{"status":"ok"}', usage={"total_tokens": 14},
                                   model=args["model"], headers={}, status=200)

        return SimpleNamespace(generate=generate)


OPENROUTER_TEST_KEY = "test-openrouter-key-not-real-1"
OPENROUTER_MODEL = "test/model:free"
OPENROUTER_KEY_COUNTS = {
    "is_free_tier": True, "free_model_daily_requests": {"used": 1, "limit": 50, "remaining": 49},
    "limit": 0, "limit_remaining": 0, "usage_daily": 0.0,
}


def openrouter_settings(*labels):
    source = {}
    for number, label in enumerate(labels, 1):
        source[f"OPENROUTER_API_KEY_{number}"] = f"test-openrouter-key-not-real-{number}"
        if label:
            source[f"OPENROUTER_ACCOUNT_LABEL_{number}"] = label
    return source


def openrouter_body(**fields):
    return {"model": OPENROUTER_MODEL, "choices": [{"message": {"content": '{"status":"ok"}'}}],
            "id": "completion-id", "usage": {"total_tokens": 14, "cost": 0}} | fields


class FakeOpenRouterHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body) if body is not None else None, timeout))
        status, response_headers, data = self.responses.pop(0)
        return status, response_headers, data if isinstance(data, bytes) else json.dumps(data).encode()


class FakeOpenRouter:
    def __init__(self, *actions, key_info=None):
        self.actions = list(actions)
        self.key_info = OPENROUTER_KEY_COUNTS if key_info is None else key_info
        self.calls = []
        self.factory_calls = []

    def factory(self, key):
        self.factory_calls.append(key)

        def key_info():
            self.calls.append(("key", key, None))
            if isinstance(self.key_info, Exception):
                raise self.key_info
            return self.key_info

        def generate(**args):
            self.calls.append(("generate", key, args))
            if self.actions:
                action = self.actions.pop(0)
                if isinstance(action, Exception):
                    raise action
                return action
            return SimpleNamespace(text='{"status":"ok"}', usage={"total_tokens": 14},
                                   model=OPENROUTER_MODEL, headers={}, status=200, response_id=None, cost=0)

        return SimpleNamespace(key_info=key_info, generate=generate)
