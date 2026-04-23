from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from astrbot.core.message.components import Image, Node, Record, Video


@pytest.mark.asyncio
async def test_node_to_dict_keeps_image_file_payload():
    node = Node(
        uin="10000",
        name="AstrBot",
        content=[Image("file:///tmp/test-image.png")],
    )

    payload = await node.to_dict()

    assert payload["type"] == "node"
    assert payload["data"]["user_id"] == "10000"
    assert payload["data"]["nickname"] == "AstrBot"
    assert payload["data"]["content"][0]["type"] == "image"
    assert payload["data"]["content"][0]["data"]["file"] == "file:///tmp/test-image.png"


@pytest.mark.asyncio
async def test_node_to_dict_keeps_record_base64_payload():
    record = Record("file:///tmp/test-audio.wav")
    node = Node(uin="10000", name="AstrBot", content=[record])

    with patch.object(Record, "convert_to_base64", AsyncMock(return_value="abc123")):
        payload = await node.to_dict()

    assert payload["type"] == "node"
    assert payload["data"]["content"] == [
        {"type": "record", "data": {"file": "base64://abc123"}}
    ]


@pytest.mark.asyncio
async def test_record_convert_to_file_path_uses_url_when_file_is_only_name(tmp_path):
    async def fake_download_file(url: str, path: str, show_progress: bool = False) -> None:
        Path(path).write_bytes(b"audio")

    record = Record(file="e2c6e2ea8d298f0aff705e08e1e2535b.amr", url="https://example.com/audio.amr")

    with (
        patch("astrbot.core.message.components.get_astrbot_temp_path", return_value=str(tmp_path)),
        patch("astrbot.core.message.components.download_file", side_effect=fake_download_file),
    ):
        resolved = await record.convert_to_file_path()

    assert Path(resolved).exists()
    assert Path(resolved).suffix == ".amr"


@pytest.mark.asyncio
async def test_record_convert_to_base64_uses_url_when_file_is_only_name(tmp_path):
    async def fake_download_file(url: str, path: str, show_progress: bool = False) -> None:
        Path(path).write_bytes(b"audio")

    record = Record(file="e2c6e2ea8d298f0aff705e08e1e2535b.amr", url="https://example.com/audio.amr")

    with (
        patch("astrbot.core.message.components.get_astrbot_temp_path", return_value=str(tmp_path)),
        patch("astrbot.core.message.components.download_file", side_effect=fake_download_file),
        patch("astrbot.core.message.components.file_to_base64", return_value="abc123"),
    ):
        resolved = await record.convert_to_base64()

    assert resolved == "abc123"


@pytest.mark.asyncio
async def test_video_convert_to_file_path_uses_url_when_file_is_only_name(tmp_path):
    async def fake_download_file(url: str, path: str, show_progress: bool = False) -> None:
        Path(path).write_bytes(b"video")

    video = Video(file="ca2a2de85023dd03e2ad18fcbc588471.mp4", url="https://example.com/video.mp4")

    with (
        patch("astrbot.core.message.components.get_astrbot_temp_path", return_value=str(tmp_path)),
        patch("astrbot.core.message.components.download_file", side_effect=fake_download_file),
    ):
        resolved = await video.convert_to_file_path()

    assert Path(resolved).exists()
    assert Path(resolved).suffix == ".mp4"
