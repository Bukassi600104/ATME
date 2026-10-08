"""Explicit decimal count formatting, independent of locale and decimal context."""

from __future__ import annotations

import math
import re
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from fractions import Fraction
from functools import lru_cache

ROUNDING = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP, "half_down": ROUND_HALF_DOWN,
            "floor": ROUND_FLOOR, "ceiling": ROUND_CEILING, "truncate": ROUND_DOWN}
_CANONICAL_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_MAX_VALUE = Decimal(1000000000000000000)
# At most62 fractional digits in a64-character positive canonical decimal.
# Sampling denominator is bounded by that scale times at most4096 levels.
MAX_COUNT_DENOMINATOR = 4096 * 10 ** 62
MAX_COUNT_NUMERATOR = 1000000000000000000 * MAX_COUNT_DENOMINATOR


class UnsupportedCount(ValueError):
    """Authored numbers or formatting cannot be sampled without changing meaning."""


def _context():
    return Context(prec=96, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])


def count_decimal(value: str) -> Decimal:
    if type(value) is not str or len(value) > 64 or not _CANONICAL_DECIMAL.fullmatch(value):
        raise UnsupportedCount("count values require canonical finite decimal strings")
    result = Decimal(value)
    if result.copy_abs() > _MAX_VALUE or result.is_zero() and value.startswith("-"):
        raise UnsupportedCount("count value exceeds its bounded magnitude or uses negative zero")
    return result


def _formatted_value(policy, value: Decimal) -> str:
    rounded = value.quantize(Decimal(1).scaleb(-policy.decimal_places), rounding=ROUNDING[policy.rounding])
    if rounded.is_zero():
        rounded = rounded.copy_abs()
    number = format(rounded, ("," if policy.grouping == "thousands" else "") + f".{policy.decimal_places}f")
    if policy.unit_placement == "none":
        return number
    if policy.unit_placement == "before":
        return policy.unit + policy.separator + number
    return number + policy.separator + policy.unit


def count_text(policy, progress: float) -> str:
    """Easing belongs to the shared clock; this helper selects one authored step."""
    if type(progress) not in (int, float) or not math.isfinite(progress) or not 0 <= progress <= 1:
        raise UnsupportedCount("count progress must be finite within zero and one")
    with localcontext(_context()):
        start, end = count_decimal(policy.start_value), count_decimal(policy.end_value)
        index = min(policy.step_count, int(Decimal(str(progress)) * policy.step_count))
        value = (start if index == 0 else end if index == policy.step_count
                 else start + (end - start) * Decimal(index) / Decimal(policy.step_count))
        return _formatted_value(policy, value)


def count_step_text(policy, index: int) -> str:
    if type(index) is not int or not 0 <= index <= policy.step_count:
        raise UnsupportedCount("count step must be an integer in the authored inventory")
    with localcontext(_context()):
        start, end = count_decimal(policy.start_value), count_decimal(policy.end_value)
        value = (start if index == 0 else end if index == policy.step_count
                 else start + (end - start) * Decimal(index) / Decimal(policy.step_count))
        return _formatted_value(policy, value)


def _clock_index(policy, start_ms: int, end_ms: int, at_ms: int, easing: str) -> int:
    """Same easing curves as the shared clock, with exact discrete boundaries."""
    if any(type(value) is not int for value in (start_ms, end_ms, at_ms)) or end_ms <= start_ms:
        raise UnsupportedCount("count requires a positive integer-clock interval")
    progress = min(Fraction(1), max(Fraction(0), Fraction(at_ms - start_ms, end_ms - start_ms)))
    if easing == "ease_in":
        progress *= progress
    elif easing == "ease_out":
        progress = 1 - (1 - progress) ** 2
    elif easing == "ease_in_out":
        progress = progress * progress * (3 - 2 * progress)
    elif easing != "linear":
        raise UnsupportedCount("count has an unknown clock easing")
    return progress.numerator * policy.step_count // progress.denominator


def count_at_ms(policy, start_ms: int, end_ms: int, at_ms: int, easing: str) -> str:
    return count_step_text(policy, _clock_index(policy, start_ms, end_ms, at_ms, easing))


def count_value_at_ms(policy, start_ms: int, end_ms: int, at_ms: int, easing: str) -> tuple[int, int]:
    index = _clock_index(policy, start_ms, end_ms, at_ms, easing)
    start, end = Fraction(count_decimal(policy.start_value)), Fraction(count_decimal(policy.end_value))
    value = start + (end - start) * Fraction(index, policy.step_count)
    return value.numerator, value.denominator


@lru_cache(maxsize=64)
def _validate_glyph_inventory(object_json: str, policy_json: str, style_version: str,
                              registry_version: str, profile_id: str, width: int, height: int) -> None:
    # Deferred imports keep the policy formatter independent of contract/paint
    # module initialization. Cache keys are immutable authored data and pins.
    from atme.render.style_bundle import resolve_contract_bundle
    from atme.render.v2_svg import _text, _text_role
    from atme.store.contracts_v2 import CountPolicy, TextObject

    obj, policy = TextObject.model_validate_json(object_json), CountPolicy.model_validate_json(policy_json)
    style, _, root = resolve_contract_bundle(style_version, registry_version)
    aspect = style.aspects["landscape-16:9" if profile_id == "LONG_FORM_16_9" else "portrait-9:16"]
    scale = width / aspect.width
    if abs(scale - height / aspect.height) > 1e-6:
        raise UnsupportedCount("count profile cannot uniformly scale the pinned style")
    role = _text_role(obj, style)
    font = next(font for font in style.fonts if font.id == role.font_id)
    for index in range(policy.step_count + 1):
        candidate = obj.model_copy(update={"text": count_step_text(policy, index)}, deep=True)
        _text(candidate, style.colors["ink"], font.family, font.weight, role.size_px * scale,
              role.line_height, role.max_characters_per_line, root / font.file)


def validate_count_glyphs(obj, policy, layout) -> None:
    profile = layout.output_profile
    _validate_glyph_inventory(obj.model_dump_json(), policy.model_dump_json(), layout.style_system_version,
                              layout.asset_registry_version, profile.profile_id, profile.width, profile.height)


def validate_count_display(token: str, *, nonblank: bool = False) -> None:
    if (type(token) is not str or len(token) > 128 or nonblank and not token.strip()
            or any(char in "\r\n\t\x85\u2028\u2029"
                   or not (32 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD
                           or 0x10000 <= ord(char) <= 0x10FFFF) for char in token)):
        raise UnsupportedCount("count display must be one bounded valid XML-safe line")


def validate_count_policy(policy) -> None:
    for token in (policy.unit, policy.separator, policy.start_text, policy.end_text):
        validate_count_display(token)
    if (policy.unit_placement == "none" and (policy.unit or policy.separator)
            or policy.unit_placement != "none" and not policy.unit):
        raise UnsupportedCount("count unit placement cannot carry ignored or empty unit fields")
    if (count_text(policy, 0) != policy.start_text or count_text(policy, 1) != policy.end_text):
        raise UnsupportedCount("count formatted endpoints must exactly match the declared policy")
