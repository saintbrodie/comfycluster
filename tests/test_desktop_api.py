from comfycluster_desktop.api import controller_http_base


def test_controller_http_base_from_ws_url():
    assert (
        controller_http_base("ws://render-controller:9320/api/v1/agents/ws")
        == "http://render-controller:9320"
    )


def test_controller_http_base_from_wss_url():
    assert (
        controller_http_base("wss://cluster.example/api/v1/agents/ws")
        == "https://cluster.example"
    )


def test_controller_http_base_preserves_plain_http():
    assert controller_http_base("http://127.0.0.1:9320") == "http://127.0.0.1:9320"
