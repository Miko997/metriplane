from metriplane.streaming.ws_server import client_count

def test_client_count_exists() -> None:
    assert client_count() == 0
