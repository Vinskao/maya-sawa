"""2026-11-19: when the model cannot answer (allowance used up), the chat gets a soft reply instead of an error."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import qa


class Store:
    def similarity_search(self, *args, **kwargs): return []


class BrokenChain:
    def get_answer(self, *args, **kwargs): raise RuntimeError("insufficient_quota")


def client(monkeypatch):
    monkeypatch.setattr(qa, "enforce_qa_rate_limit", lambda request: None)
    monkeypatch.setattr(qa, "get_vector_store", lambda: Store())
    monkeypatch.setattr(qa, "get_qa_chain", lambda: BrokenChain())
    monkeypatch.setattr(qa, "get_chat_history", lambda: None)
    app = FastAPI()
    app.include_router(qa.router)
    return TestClient(app)


def test_failed_model_call_returns_the_soft_reply(monkeypatch):
    response = client(monkeypatch).post(f"{qa.router.prefix}/query", json={"text": "你好", "user_id": "u"})
    assert response.status_code == 200
    assert response.json() == {"success": True, "answer": qa.BUSY_ANSWER, "data": []}
    assert "上班" in qa.BUSY_ANSWER


def test_english_gets_the_english_reply():
    assert qa.busy_answer("english") == qa.BUSY_ANSWER_EN and qa.busy_answer("chinese") == qa.BUSY_ANSWER


def test_failed_document_search_also_gets_the_soft_reply(monkeypatch):
    class BrokenStore:
        def similarity_search(self, *args, **kwargs): raise RuntimeError("embedding quota")
    test_client = client(monkeypatch)
    monkeypatch.setattr(qa, "get_vector_store", lambda: BrokenStore())
    assert test_client.post(f"{qa.router.prefix}/query", json={"text": "你好", "user_id": "u"}).json()["answer"] == qa.BUSY_ANSWER
