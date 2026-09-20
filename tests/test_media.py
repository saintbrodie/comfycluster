from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from comfycluster_common.assets import AssetMetadata, AssetRecord
from comfycluster_common.models import JobVisibility
from comfycluster_common.tenancy import Principal
from comfycluster_controller.assets import AssetRepository
from comfycluster_controller.media import (
    generate_video_poster,
    generate_video_preview,
    parse_ffprobe_payload,
    probe_video,
)


def test_parse_ffprobe_payload_extracts_video_metadata():
    result = parse_ffprobe_payload(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "nb_frames": "360",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "duration": "12.012",
                "bit_rate": "4200000",
            },
        }
    )

    assert result.width == 1920
    assert result.height == 1080
    assert result.duration_seconds == 12.012
    assert result.frame_count == 360
    assert result.frame_rate == 29.97003
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.container_format == "mov,mp4,m4a,3gp,3g2,mj2"
    assert result.bit_rate_bps == 4_200_000


def test_probe_video_is_optional_when_ffprobe_is_missing(monkeypatch, tmp_path):
    from comfycluster_controller import media

    monkeypatch.setattr(media, "resolve_media_binary", lambda *_args, **_kwargs: None)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not-a-real-video")
    assert probe_video(source) is None


def test_generate_video_derivatives_build_expected_ffmpeg_commands(monkeypatch, tmp_path):
    from comfycluster_controller import media

    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"generated")

    monkeypatch.setattr(media, "resolve_media_binary", lambda *_args, **_kwargs: "ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", fake_run)

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    poster = tmp_path / "poster.jpg"
    preview = tmp_path / "preview.mp4"

    assert generate_video_poster(source, poster, size=360, duration_seconds=20.0)
    assert generate_video_preview(
        source,
        preview,
        duration_seconds=20.0,
        preview_seconds=8.0,
        max_size=720,
    )
    assert poster.read_bytes() == b"generated"
    assert preview.read_bytes() == b"generated"
    assert any("-frames:v" in command for command in commands)
    assert any("libx264" in command for command in commands)


def test_video_filters_remain_tenant_scoped(tmp_path):
    repository = AssetRepository(tmp_path / "assets.db")
    try:
        visible = AssetRecord(
            asset_id=uuid4(),
            job_id=uuid4(),
            owner_user_id="alice",
            group_id="creative",
            visibility=JobVisibility.GROUP,
            filename="wan-output.mp4",
            media_type="video/mp4",
            size_bytes=123,
            storage_path=str(tmp_path / "wan-output.mp4"),
            metadata=AssetMetadata(
                video_codec="h264",
                audio_codec="aac",
                container_format="mov,mp4,m4a,3gp,3g2,mj2",
                duration_seconds=8.5,
            ),
        )
        hidden = AssetRecord(
            asset_id=uuid4(),
            job_id=uuid4(),
            owner_user_id="bob",
            group_id="other-team",
            visibility=JobVisibility.GROUP,
            filename="secret.mp4",
            media_type="video/mp4",
            size_bytes=456,
            storage_path=str(tmp_path / "secret.mp4"),
            metadata=AssetMetadata(video_codec="h265", duration_seconds=20.0),
        )
        repository.create(visible)
        repository.create(hidden)
        principal = Principal(user_id="alice", display_name="Alice", group_ids=["creative"])

        result = repository.query_for_principal(
            principal,
            video_codec="h264",
            min_duration_seconds=5,
            max_duration_seconds=10,
        )
        assert [item.asset_id for item in result] == [visible.asset_id]

        facets = repository.facets_for_principal(principal)
        assert facets["video_codecs"] == ["h264"]
        assert "h265" not in facets["video_codecs"]
    finally:
        repository.close()
