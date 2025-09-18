from coding_in_parallel import llm


class DummyClient:
    def __init__(self):
        self.seen = []

    def complete(self, prompt: str, **_: object) -> str:
        self.seen.append(prompt)
        return "{}"


def test_set_client_overrides_default():
    dummy = DummyClient()
    llm.set_client(dummy)
    llm.complete("hello")
    assert dummy.seen == ["hello"]

