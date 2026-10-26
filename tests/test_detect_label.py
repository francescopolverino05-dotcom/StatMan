from statman.detect import label


class _R:
    status_code = 200
    def __init__(self, cost): self._c = cost
    def json(self):
        return {"usage": {"cost": self._c}, "choices": [{"message": {"content":
                '```json\n{"moments":[{"id":0,"team":"home","event":"pass","outcome":"success","shirt":"7"}]}\n```'}}]}


def test_parse_reply():
    assert label.parse_reply('x {"moments":[{"id":3}]} y') == [{"id": 3}]
    assert label.parse_reply("garbage") == []


def test_run_respects_cap():
    calls = []
    def poster(*a, **k):
        calls.append(1); return _R(0.01)
    content = [{"type": "text", "text": "hi"}]
    batches = [([0], content), ([1], content), ([2], content)]
    _, worst = label.estimate(content, 100)
    labels, spent, n = label.run(batches, "k", cap_usd=0.01 + worst - 1e-9, endpoint="x", max_tokens=100, poster=poster)
    assert n == len(calls) == 1 and labels[0]["team"] == "home" and spent <= 0.01 + worst + 1e-9
