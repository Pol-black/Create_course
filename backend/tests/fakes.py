"""Заглушка вместо настоящей модели: отдаёт заготовленные ответы."""

from types import SimpleNamespace


def make_response(content: str, finish_reason: str = "stop") -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class FakeClient:
    """Каждый вызов берёт следующий элемент списка: строка — ответ, исключение — бросается."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, SimpleNamespace):
            return reply
        return make_response(reply)
