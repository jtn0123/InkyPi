# pyright: reportMissingImports=false


def test_main_page(client):
    resp = client.get('/')
    assert resp.status_code == 200


