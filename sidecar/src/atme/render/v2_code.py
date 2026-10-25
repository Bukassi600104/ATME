"""Owning code primitive's pinned glyph proof, not code painting/admission yet.

This private sfnt decoder is used only after the exact static font bundle is
reverified. It is not a font ingestion API or a syntax/semantic classifier.
OpenType cmap/hmtx rules: learn.microsoft.com/en-us/typography/opentype/spec/.
"""

from __future__ import annotations

import base64
import html
import io
import math
import struct
from dataclasses import dataclass, fields
from hashlib import sha256
from itertools import pairwise

import regex
from PIL import ImageFont

from atme.render.code_font_bundle import (
    CodeFontManifest,
    VerifiedCodeFontBundle,
    verify_code_font_bundle,
)
from atme.render.style_contracts import PaperInkStyle
from atme.store.contracts_v2 import CodeLine, CodePayload, CodeSpan, TextObject


class UnsupportedCode(ValueError):
    pass


@dataclass(frozen=True)
class CodeGlyphMetric:
    codepoint: int
    glyph_id: int
    advance_units: int
    left_side_bearing: int


@dataclass(frozen=True)
class CodeGlyphMetrics:
    font_sha256: str
    units_per_em: int
    ascii_cell_advance_units: int
    glyphs: tuple[CodeGlyphMetric, ...]


def _unpack(payload, offset, fmt):
    size = struct.calcsize(">" + fmt)
    if offset < 0 or offset + size > len(payload):
        raise UnsupportedCode("code glyph font table is truncated")
    return struct.unpack_from(">" + fmt, payload, offset)


def _tables(payload):
    if type(payload) is not bytes or len(payload) < 12:
        raise UnsupportedCode("code glyph font sfnt header is truncated")
    signature, count = _unpack(payload, 0, "IH")
    if signature != 0x00010000 or not 1 <= count <= 128:
        raise UnsupportedCode("code glyph font needs the pinned normal sfnt TTF")
    directory_end = 12 + count * 16
    if directory_end > len(payload):
        raise UnsupportedCode("code glyph font directory is truncated")
    result, spans = {}, []
    for index in range(count):
        tag, _, offset, length = _unpack(payload, 12 + index * 16, "4sIII")
        if (tag in result or offset < directory_end or offset % 4
                or length <= 0 or offset + length > len(payload)):
            raise UnsupportedCode("code glyph font has invalid/duplicate table bounds")
        result[tag] = payload[offset:offset + length]
        spans.append((offset, offset + length))
    ordered = sorted(spans)
    if any(end > next_start for (_, end), (next_start, _) in pairwise(ordered)):
        raise UnsupportedCode("code glyph font tables overlap")
    if not {b"cmap", b"head", b"maxp", b"hhea", b"hmtx"}.issubset(result):
        raise UnsupportedCode("code glyph font required table is missing")
    return result


def _cmap12(payload, num_glyphs):
    fmt, reserved, length, language, count = _unpack(payload, 0, "HHIII")
    if (fmt != 12 or reserved or language or not 1 <= count <= 65536
            or length != len(payload) or length != 16 + count * 12):
        raise UnsupportedCode("code glyph cmap12 has invalid header/length/count")
    mapping, previous = {}, -1
    for index in range(count):
        start, end, glyph = _unpack(payload, 16 + index * 12, "III")
        if (start > end or start <= previous or end > 0x10FFFF
                or start <= 0xDFFF and end >= 0xD800
                or glyph + end - start >= num_glyphs):
            raise UnsupportedCode("code glyph cmap12 has invalid scalar/group/glyph range")
        for codepoint in range(start, end + 1):
            value = glyph + codepoint - start
            if value:
                mapping[codepoint] = value
        previous = end
    return mapping


def _cmap4(payload, num_glyphs):
    fmt, length, language, twice_count = _unpack(payload, 0, "HHHH")
    count = twice_count // 2
    if (fmt != 4 or language or not count or twice_count % 2
            or length != len(payload) or length < 16 + 8 * count):
        raise UnsupportedCode("code glyph cmap4 has invalid header/length/count")
    if _unpack(payload, 14 + count * 2, "H")[0]:
        raise UnsupportedCode("code glyph cmap4 has a nonzero reserved field")
    mapping, previous = {}, -1
    for index in range(count):
        end = _unpack(payload, 14 + index * 2, "H")[0]
        start = _unpack(payload, 16 + count * 2 + index * 2, "H")[0]
        delta = _unpack(payload, 16 + count * 4 + index * 2, "h")[0]
        pointer = 16 + count * 6 + index * 2
        relative = _unpack(payload, pointer, "H")[0]
        if start > end or start <= previous or relative % 2:
            raise UnsupportedCode("code glyph cmap4 has invalid segment/range offset")
        for codepoint in range(start, end + 1):
            if relative:
                address = pointer + relative + 2 * (codepoint - start)
                if address < 16 + count * 8:
                    raise UnsupportedCode("code glyph cmap4 points outside glyph array")
                glyph = _unpack(payload, address, "H")[0]
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            else:
                glyph = (codepoint + delta) & 0xFFFF
            if glyph >= num_glyphs or glyph and 0xD800 <= codepoint <= 0xDFFF:
                raise UnsupportedCode("code glyph cmap4 has an invalid glyph/scalar")
            if glyph:
                mapping[codepoint] = glyph
        previous = end
    if previous != 0xFFFF:
        raise UnsupportedCode("code glyph cmap4 is missing its sentinel segment")
    return mapping


def _unicode_cmap(payload, num_glyphs):
    version, count = _unpack(payload, 0, "HH")
    if version or not 1 <= count <= 32 or 4 + count * 8 > len(payload):
        raise UnsupportedCode("code glyph cmap directory has invalid bounds/count")
    maps12, maps4, identifiers, spans = {}, [], set(), set()
    for index in range(count):
        platform, encoding, offset = _unpack(payload, 4 + index * 8, "HHI")
        identifier = (platform, encoding)
        if identifier in identifiers or offset < 4 + count * 8:
            raise UnsupportedCode("code glyph cmap has duplicate/invalid encoding records")
        identifiers.add(identifier)
        fmt = _unpack(payload, offset, "H")[0]
        if identifier not in {(0, 3), (0, 4), (3, 1), (3, 10)}:
            raise UnsupportedCode("code glyph pinned font has an unapproved cmap encoding")
        if fmt not in {4, 12}:
            raise UnsupportedCode("code glyph pinned font has an unsupported cmap format")
        length = _unpack(payload, offset + (4 if fmt == 12 else 2), "I" if fmt == 12 else "H")[0]
        if length <= 0 or offset + length > len(payload):
            raise UnsupportedCode("code glyph cmap subtable is truncated")
        spans.add((offset, offset + length))  # exact shared subtable aliases are valid
        subtable = payload[offset:offset + length]
        if fmt == 12:
            if identifier not in {(0, 4), (3, 10)}:
                raise UnsupportedCode("code glyph full repertoire has an invalid encoding")
            maps12[identifier] = _cmap12(subtable, num_glyphs)
        else:
            if identifier not in {(0, 3), (3, 1)}:
                raise UnsupportedCode("code glyph BMP table has an invalid encoding")
            maps4.append(_cmap4(subtable, num_glyphs))
    ordered = sorted(spans)
    if any(end > next_start for (_, end), (next_start, _) in pairwise(ordered)):
        raise UnsupportedCode("code glyph cmap subtables partially overlap")
    selected = maps12.get((3, 10))
    if (selected is None or not maps4 or any(mapping != selected for mapping in maps12.values())
            or any(any(selected.get(codepoint) != glyph for codepoint, glyph in mapping.items())
                   for mapping in maps4)):
        raise UnsupportedCode("code glyph Unicode cmap mappings are missing or inconsistent")
    return selected


def _decode_code_font_metrics(payload):
    """Pure decoder; production caller must first verify the exact bundled SHA."""
    tables = _tables(payload)
    head, maxp, hhea, hmtx = (tables[key] for key in (b"head", b"maxp", b"hhea", b"hmtx"))
    if (len(head) < 54 or len(maxp) < 32 or len(hhea) < 36
            or _unpack(head, 12, "I")[0] != 0x5F0F3CF5
            or _unpack(maxp, 0, "I")[0] != 0x00010000
            or _unpack(hhea, 0, "I")[0] != 0x00010000
            or _unpack(hhea, 32, "h")[0] != 0):
        raise UnsupportedCode("code glyph font has invalid required metric headers")
    units = _unpack(head, 18, "H")[0]
    num_glyphs = _unpack(maxp, 4, "H")[0]
    count = _unpack(hhea, 34, "H")[0]
    if (not 16 <= units <= 16384 or not 1 <= count <= num_glyphs
            or len(hmtx) != count * 4 + (num_glyphs - count) * 2):
        raise UnsupportedCode("code glyph font hmtx has invalid length/count/units")
    metrics = [_unpack(hmtx, index * 4, "Hh") for index in range(count)]
    final_advance = metrics[-1][0]
    metrics.extend((final_advance, _unpack(hmtx, count * 4 + index * 2, "h")[0])
                   for index in range(num_glyphs - count))
    return units, _unicode_cmap(tables[b"cmap"], num_glyphs), tuple(metrics)


def code_glyph_metrics(obj: TextObject, bundle: VerifiedCodeFontBundle) -> CodeGlyphMetrics:
    """Glyph existence/declared advances only; this cannot admit rendered code."""
    if (type(obj) is not TextObject or obj.object_type != "code" or obj.code_payload is None):
        raise UnsupportedCode("code glyph proof requires an exact code_payload")
    nodes = [(obj, TextObject), (obj.code_payload, CodePayload)]
    nodes.extend((line, CodeLine) for line in obj.code_payload.lines)
    nodes.extend((span, CodeSpan) for line in obj.code_payload.lines for span in line.spans)
    if any(type(node) is not model or set(node.__dict__) != set(model.model_fields)
           or node.model_extra for node, model in nodes):
        raise UnsupportedCode("code glyph proof has unknown authored payload fields/classes")
    obj = TextObject.model_validate(obj.model_dump(mode="json"))
    manifest, files = _checked_code_resources(bundle)
    units, mapping, metrics = _decode_code_font_metrics(files[manifest.font.file])
    cells = {metrics[mapping[codepoint]][0] for codepoint in range(32, 127)}
    if cells != {units * manifest.typography.advance_em}:
        raise UnsupportedCode("code glyph ASCII cell differs from the pinned metrics")
    glyphs = []
    for codepoint in sorted({ord(char) for char in obj.text if char not in "\t\n"}):
        glyph = mapping.get(codepoint, 0)
        if not glyph:
            raise UnsupportedCode(f"unsupported code glyph U+{codepoint:04X}; no font fallback")
        advance, bearing = metrics[glyph]
        glyphs.append(CodeGlyphMetric(codepoint, glyph, advance, bearing))
    return CodeGlyphMetrics(manifest.font.sha256, units, cells.pop(), tuple(glyphs))


def _checked_code_resources(bundle):
    if (type(bundle) is not VerifiedCodeFontBundle or type(bundle.files) is not tuple
            or set(bundle.__dict__) != {item.name for item in fields(VerifiedCodeFontBundle)}):
        raise UnsupportedCode("code glyph proof needs exact immutable resource inputs")
    files = {}
    for row in bundle.files:
        if (type(row) is not tuple or len(row) != 3 or type(row[0]) is not str
                or type(row[1]) is not str or type(row[2]) is not bytes
                or row[0] in files or sha256(row[2]).hexdigest() != row[1]):
            raise UnsupportedCode("code glyph resource row is invalid")
        files[row[0]] = row[2]
    verified = verify_code_font_bundle(files.__getitem__)
    if verified != bundle:
        raise UnsupportedCode("code glyph resource inputs differ from exact verified pins")
    return CodeFontManifest.model_validate_json(verified.manifest_json), files


def code_font_css(bundle: VerifiedCodeFontBundle) -> str:
    """Embed the same checked bytes used for measurement and native rasterization."""
    manifest, files = _checked_code_resources(bundle)
    payload = base64.b64encode(files[manifest.font.file]).decode("ascii")
    return (f"@font-face{{font-family:'{manifest.font.family}';font-style:normal;"
            f"font-weight:{manifest.font.weight};src:url(data:font/ttf;base64,{payload})}}")


def code_svg(obj: TextObject, style: PaperInkStyle, scale: float, bundle: VerifiedCodeFontBundle,
             *, write_fraction: float | None = None) -> str:
    """Paint exact authored code runs; no lexer, reflow, normalization or tabs in SVG.

    Glyph metadata is checked first, and the same frozen bytes supply actual
    FreeType measurement. The caller must supply them to the shared native
    rasterizer too. This primitive alone is not Split/public admission.
    """
    glyphs = code_glyph_metrics(obj, bundle)
    if (type(scale) not in {int, float} or not math.isfinite(scale) or not 0 < scale <= 100
            or write_fraction is not None and (type(write_fraction) not in {int, float}
                or not math.isfinite(write_fraction) or not 0 <= write_fraction <= 1)):
        raise UnsupportedCode("code scale/write fraction must be finite and within range")
    if (obj.style.text != "text.code" or obj.style.stroke or obj.style.fill or obj.style.effect
            or obj.geometry.points or obj.geometry.corner_radius is not None or obj.asset_id is not None):
        raise UnsupportedCode("code requires explicit code typography and unstyled authored bounds")
    style = PaperInkStyle.model_validate(style.model_dump(mode="json"))
    manifest = CodeFontManifest.model_validate_json(bundle.manifest_json)
    files = {name: payload for name, _, payload in bundle.files}
    measuring = ImageFont.truetype(io.BytesIO(files[manifest.font.file]), 1000)
    size = manifest.typography.size_px * scale
    unit_scale = size / 1000
    pitch = size * manifest.typography.line_height
    bounds = obj.geometry.bounds
    if len(obj.code_payload.lines) * pitch > bounds.height:
        raise UnsupportedCode("code authored lines exceed their height; no reflow")
    tab_step = obj.code_payload.tab_size * glyphs.ascii_cell_advance_units / glyphs.units_per_em * 1000
    roles = {"plain": "ink", "identifier": "ink", "punctuation": "ink",
             "operator": "accent", "keyword": "accent", "literal": "success", "comment": "muted"}
    graphemes = regex.findall(r"\X", obj.text)
    boundaries, offset = {0}, 0
    for grapheme in graphemes:
        offset += len(grapheme)
        boundaries.add(offset)
    count = len(graphemes) if write_fraction is None else math.floor(len(graphemes) * write_fraction)
    # Choose the whole-object grapheme prefix before visiting authored spans.
    # Span/role boundaries can bisect a combining sequence, not its write clock.
    remaining, painted, lines = sum(len(part) for part in graphemes[:count]), False, []
    authored_offset = 0

    def number(value):
        return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"

    for index, line in enumerate(obj.code_payload.lines):
        text = "".join(span.text for span in line.spans)
        if len(text) > manifest.typography.max_characters_per_line:
            raise UnsupportedCode("code line exceeds authored character limit; no reflow")
        base, segment, snippets, pending_x = 0.0, "", [], None
        for span in line.spans:
            for part_index, part in enumerate(span.text.split("\t")):
                if part_index:
                    cursor = base + measuring.getlength(segment)
                    base = (math.floor(cursor / tab_step + 1e-10) + 1) * tab_step
                    segment = ""
                    remaining -= 1  # authored TAB counts as a grapheme, never a painted glyph
                    authored_offset += 1
                    pending_x = bounds.x + base * unit_scale
                if not part:
                    continue
                cursor = base + measuring.getlength(segment)
                end = base + measuring.getlength(segment + part)
                box = measuring.getbbox(part, anchor="ls")
                if (end * unit_scale > bounds.width or (cursor + box[0]) * unit_scale < -1e-4
                        or (cursor + box[2]) * unit_scale > bounds.width + 1e-4
                        or size + index * pitch + box[1] * unit_scale < -1e-4
                        or size + index * pitch + box[3] * unit_scale > bounds.height + 1e-4):
                    raise UnsupportedCode("code actual glyph/advance exceeds authored bounds; no clipping")
                painted |= measuring.getmask(part).getbbox() is not None
                visible = part[:max(0, remaining)]
                remaining -= len(part)
                segment += part
                if visible:
                    # A new authored token run must not acquire a ligature from
                    # its differently attributed neighbor. Explicit x starts a
                    # native shaping chunk, except inside a combining cluster.
                    position_x = (pending_x if pending_x is not None else
                                  bounds.x + cursor * unit_scale if authored_offset in boundaries else None)
                    position = f' x="{number(position_x)}"' if position_x is not None else ""
                    snippets.append(f'<tspan{position} fill="{style.colors[roles[span.role]]}" '
                        f'data-code-span="{html.escape(span.span_id, quote=True)}">'
                        f'{html.escape(visible, quote=True)}</tspan>')
                    pending_x = None
                authored_offset += len(part)
        # Tabs at the end still consume authored advance and must fit.
        if (base + measuring.getlength(segment)) * unit_scale > bounds.width:
            raise UnsupportedCode("code tab/trailing-space advance exceeds authored width")
        lines.append(f'<text x="{number(bounds.x)}" y="{number(bounds.y + size + index * pitch)}" '
                     f'data-code-line="{html.escape(line.line_id, quote=True)}">{"".join(snippets)}</text>')
        remaining -= 1  # LF separating authored lines; final decrement cannot paint content
        authored_offset += 1
    if not painted:
        raise UnsupportedCode("code has no intended painted glyph run")
    return (f'<g font-family="{html.escape(manifest.font.family, quote=True)}" font-weight="400" '
            f'font-size="{number(size)}" xml:space="preserve">{"".join(lines)}</g>')
