import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from maya_sawa.services.blog_legacy import reject_legacy_article_write, reject_legacy_sync


def test_legacy_read_compatibility_but_no_mutations_when_blog_owns_db(monkeypatch):
    app = FastAPI()
    @app.api_route('/articles', methods=['GET', 'POST', 'DELETE'], dependencies=[Depends(reject_legacy_article_write)])
    def article():
        return {'legacy': True}
    client = TestClient(app)
    monkeypatch.setenv('BLOG_ENABLED', 'false')
    assert client.post('/articles').status_code == 200
    monkeypatch.setenv('BLOG_ENABLED', 'true')
    assert client.get('/articles').status_code == 200
    assert client.post('/articles').status_code == 410
    assert client.delete('/articles').status_code == 410
    with pytest.raises(HTTPException) as caught:
        reject_legacy_sync()
    assert caught.value.status_code == 410
