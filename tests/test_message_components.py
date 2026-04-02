from unittest.mock import AsyncMock, patch

import pytest

from astrbot.core.message.components import Image, Node, Record


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
