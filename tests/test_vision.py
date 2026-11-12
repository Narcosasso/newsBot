import json
from types import SimpleNamespace

import pytest

from cardbot.recognition.vision import SCHEMA, CardVision, VisionError, parse_response

GOOD = {
    "is_pokemon_card": True, "language": "ja", "name": "リザードンex", "set_code": "SV2a", "number": "006",
    "set_total": "165", "regulation_mark": "G", "rarity": "RR", "variant_hint": "holo", "is_promo": False,
    "stamp": None, "confidence": 0.9, "notes": None,
}


def resp(text=None, stop="end_turn"):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(stop_reason=stop, content=content)


def test_schema_requires_every_field():
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])
    assert SCHEMA["additionalProperties"] is False


def test_parse_good_response():
    r = parse_response(resp(json.dumps(GOOD)))
    assert r.language == "ja" and r.number == "006" and r.variant_hint == "holo"


@pytest.mark.parametrize("response", [resp(None), resp("{not json"), resp(json.dumps({"foo": 1})),
                                      resp(json.dumps(GOOD), stop="refusal"),
                                      resp(json.dumps(GOOD), stop="max_tokens")])
def test_bad_responses_raise(response):
    with pytest.raises(VisionError):
        parse_response(response)


async def test_request_shape():
    captured = {}

    class Messages:
        async def create(self, **kw):
            captured.update(kw)
            return resp(json.dumps(GOOD))

    client = SimpleNamespace(beta=SimpleNamespace(messages=Messages()))
    result = await CardVision("k", model="claude-opus-5-5", client=client).read_card(b"\xff\xd8", "image/jpeg")
    assert result.name == "リザードンex"
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"]["schema"] is SCHEMA
    assert captured["fallbacks"] == "default"
    image = captured["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"


async def test_without_api_key_photos_are_disabled_with_a_helpful_message():
    from cardbot.recognition.vision import DisabledVision, make_vision

    vision = make_vision("", "claude-opus-5-5", "medium")
    assert isinstance(vision, DisabledVision)
    with pytest.raises(VisionError, match="MEW 006"):
        await vision.read_card(b"x")
    assert isinstance(make_vision("k", "claude-opus-5-5", "medium"), CardVision)
