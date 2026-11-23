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
