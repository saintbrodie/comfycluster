from pathlib import Path

from comfycluster_agent.assets import controller_http_base, discover_output_files


def test_controller_http_base_converts_agent_websocket_url():
    assert (
        controller_http_base("ws://controller:9320/api/v1/agents/ws")
        == "http://controller:9320"
    )
    assert (
        controller_http_base("wss://cluster.example/api/v1/agents/ws")
        == "https://cluster.example"
    )


def test_discover_output_files_resolves_comfy_history(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    output = comfy / "output" / "video"
    output.mkdir(parents=True)
    image = comfy / "output" / "result.png"
    image.write_bytes(b"png")
    video = output / "clip.mp4"
    video.write_bytes(b"video")

    files = discover_output_files(
        comfy,
        {
            "11": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]},
            "12": {"videos": [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]},
            "13": {"images": [{"filename": "preview.png", "type": "temp"}]},
        },
    )

    assert [(item.node_id, item.filename) for item in files] == [
        ("11", "result.png"),
        ("12", "clip.mp4"),
    ]


def test_discover_output_files_does_not_escape_output_root(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "output").mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    files = discover_output_files(
        comfy,
        {
            "1": {
                "files": [
                    {
                        "filename": "secret.txt",
                        "subfolder": "../../",
                        "type": "output",
                    }
                ]
            }
        },
    )

    assert files == []
