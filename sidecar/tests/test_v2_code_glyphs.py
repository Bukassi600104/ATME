"""Pinned Unicode glyph existence/metrics, separate from eventual code paint."""

import importlib
import importlib.util
import struct
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest
from atme.render.code_font_bundle import load_code_font_bundle
from atme.store.contracts_v2 import TextObject
from test_v2_code_contract import code_object


def code_module():
    name = "atme.render.v2_code"
    assert importlib.util.find_spec(name) is not None, "native code glyph verifier is missing"
    return importlib.import_module(name)


def authored_code(text):
    raw = code_object()
    raw["text"] = text
    raw["code_payload"]["lines"] = [{"line_id": f"line-{index}", "spans": [
        {"span_id": f"span-{index}", "role": "plain", "text": line}] if line else []}
        for index, line in enumerate(text.split("\n"))]
    return TextObject.model_validate(raw)


def test_verified_glyph_metrics_cover_ascii_greek_accent_and_zero_advance_mark():
    module = code_module()
    obj = authored_code("x Ω é e\u0301\t\n")
    result = module.code_glyph_metrics(obj, load_code_font_bundle())
    glyphs = {glyph.codepoint: glyph for glyph in result.glyphs}
    assert result.units_per_em == 1000
    assert result.ascii_cell_advance_units == 600
    assert set(glyphs) == set(map(ord, "x Ω ée\u0301"))
    assert all(glyph.glyph_id > 0 for glyph in glyphs.values())
    assert glyphs[ord("Ω")].advance_units == 600
    assert glyphs[ord("é")].advance_units == 600
    assert glyphs[0x301].advance_units == 0  # a real combining glyph, not .notdef
    assert result.font_sha256 == "e6fd0d7e91550b3ed2b735d4312474362c4716edc4fc0577a0f61ed782d5aed1"
    assert result == module.code_glyph_metrics(obj, load_code_font_bundle())
    with pytest.raises(FrozenInstanceError):
        result.units_per_em = 1


@pytest.mark.parametrize("missing", ["漢", "😀", "\U0010ffff"])
def test_missing_unicode_glyphs_fail_instead_of_using_notdef_or_system_fallback(missing):
    module = code_module()
    with pytest.raises(ValueError, match="code glyph.*U\\+"):
        module.code_glyph_metrics(authored_code("x" + missing), load_code_font_bundle())


@pytest.mark.parametrize("fault", ["font", "manifest", "license", "extra", "digest"])
def test_glyph_proof_rebinds_actual_resource_pins_even_for_coherently_rehashed_rows(fault):
    module = code_module()
    bundle = load_code_font_bundle()
    if fault == "digest":
        changed = replace(bundle, inputs_sha256="0" * 64)
    elif fault == "extra":
        payload = b"extra"
        changed = replace(bundle, files=bundle.files + (("code-font-v1/extra", sha256(payload).hexdigest(), payload),))
    else:
        suffix = {"font": ".ttf", "manifest": ".json", "license": ".txt"}[fault]
        rows = tuple((name, sha256(payload + b"changed").hexdigest(), payload + b"changed")
                     if name.endswith(suffix) else (name, pin, payload) for name, pin, payload in bundle.files)
        changed = replace(bundle, files=rows)
    with pytest.raises(ValueError, match="code.font|code glyph.*resource"):
        module.code_glyph_metrics(authored_code("x"), changed)


def test_declared_legacy_code_has_no_glyph_admission_until_exact_payload_exists():
    module = code_module()
    with pytest.raises(ValueError, match="code_payload"):
        module.code_glyph_metrics(TextObject.model_validate(code_object(payload=False)), load_code_font_bundle())


def metric_algorithm_fixture():
    """Literal sfnt metadata fixture, never font/render/asset admission evidence."""
    bmp = (struct.pack(">7H", 4, 40, 0, 6, 4, 1, 2)
           + struct.pack(">3H", 32, 120, 65535) + b"\0\0"
           + struct.pack(">3H", 32, 120, 65535)
           + struct.pack(">3h", -31, -118, 1) + b"\0" * 6)
    full = struct.pack(">HHIII6I", 12, 0, 40, 0, 2, 32, 32, 1, 120, 120, 2)
    cmap = struct.pack(">HHHHIHHI", 0, 2, 3, 1, 20, 3, 10, 60) + bmp + full
    head = bytearray(54)
    struct.pack_into(">I", head, 12, 0x5F0F3CF5)
    struct.pack_into(">H", head, 18, 1000)
    maxp = struct.pack(">IH", 0x00010000, 3) + b"\0" * 26
    hhea = bytearray(36)
    struct.pack_into(">I", hhea, 0, 0x00010000)
    struct.pack_into(">H", hhea, 34, 2)
    hmtx = struct.pack(">HhHhh", 600, 0, 600, 1, -17)
    tables = {b"cmap": cmap, b"head": bytes(head), b"maxp": maxp,
              b"hhea": bytes(hhea), b"hmtx": hmtx}
    directory, data = bytearray(), bytearray()
    for tag, payload in sorted(tables.items()):
        directory.extend(struct.pack(">4sIII", tag, 0, 92 + len(data), len(payload)))
        data.extend(payload)
        data.extend(b"\0" * ((-len(data)) % 4))
    return bytes(struct.pack(">I4H", 0x00010000, 5, 64, 2, 16) + directory + data)


def fixture_table(payload, tag):
    count = struct.unpack_from(">H", payload, 4)[0]
    for index in range(count):
        row = 12 + index * 16
        name, _, offset, length = struct.unpack_from(">4sIII", payload, row)
        if name == tag:
            return row, offset, length
    raise AssertionError(f"test fixture has no table {tag!r}")


def test_hmtx_trailing_glyph_reuses_final_advance_but_owns_its_bearing():
    module = code_module()
    units, mapping, metrics = module._decode_code_font_metrics(metric_algorithm_fixture())
    assert units == 1000
    assert mapping == {32: 1, 120: 2}
    assert metrics == ((600, 0), (600, 1), (600, -17))


@pytest.mark.parametrize("fault", ["header", "directory", "duplicate", "misalignment", "overlap",
    "missing", "head_magic", "units", "glyph_count", "metric_count", "metric_length",
    "cmap_record", "cmap_length", "cmap_count", "cmap_group", "cmap_order", "cmap_scalar",
    "cmap_glyph", "cmap_ambiguity", "bmp_subset", "bmp_pointer", "bmp_sentinel"])
def test_private_sfnt_decoder_rejects_malformed_bounds_unicode_and_metrics(fault):
    module = code_module()
    payload = bytearray(metric_algorithm_fixture())
    cmap_row, cmap, _ = fixture_table(payload, b"cmap")
    bmp, full = cmap + 20, cmap + 60
    if fault == "header":
        payload[:4] = b"OTTO"
    elif fault == "directory":
        payload = payload[:24]
    elif fault == "duplicate":
        payload[28:32] = b"cmap"
    elif fault == "misalignment":
        struct.pack_into(">I", payload, cmap_row + 8, cmap + 1)
    elif fault == "overlap":
        row, _, _ = fixture_table(payload, b"head")
        struct.pack_into(">I", payload, row + 8, cmap)
    elif fault == "missing":
        payload[cmap_row:cmap_row + 4] = b"NOPE"
    elif fault in {"head_magic", "units", "glyph_count", "metric_count", "metric_length"}:
        tag = {"head_magic": b"head", "units": b"head", "glyph_count": b"maxp",
               "metric_count": b"hhea", "metric_length": b"hmtx"}[fault]
        row, offset, length = fixture_table(payload, tag)
        if fault == "metric_length":
            struct.pack_into(">I", payload, row + 12, length - 2)
        else:
            field = {"head_magic": 12, "units": 18, "glyph_count": 4, "metric_count": 34}[fault]
            struct.pack_into(">I" if fault == "head_magic" else ">H", payload, offset + field, 0)
    elif fault == "cmap_record":
        struct.pack_into(">H", payload, cmap + 12, 1)
    elif fault == "cmap_length":
        struct.pack_into(">I", payload, full + 4, 10000)
    elif fault == "cmap_count":
        struct.pack_into(">I", payload, full + 12, 65537)
    elif fault == "cmap_group":
        struct.pack_into(">I", payload, full + 16, 33)
    elif fault == "cmap_order":
        struct.pack_into(">II", payload, full + 28, 32, 32)
    elif fault == "cmap_scalar":
        struct.pack_into(">II", payload, full + 28, 0xD800, 0xD800)
    elif fault == "cmap_glyph":
        struct.pack_into(">I", payload, full + 24, 3)
    elif fault == "cmap_ambiguity":
        struct.pack_into(">HH", payload, cmap + 12, 3, 1)
    elif fault == "bmp_subset":
        struct.pack_into(">h", payload, bmp + 28, -30)
    elif fault == "bmp_pointer":
        struct.pack_into(">H", payload, bmp + 34, 2)
    else:
        struct.pack_into(">H", payload, bmp + 18, 65534)
    with pytest.raises(ValueError, match="code glyph"):
        module._decode_code_font_metrics(bytes(payload))
