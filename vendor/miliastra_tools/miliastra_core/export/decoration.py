from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from miliastra_core.protobuf.wire import (
    WireField,
    encode_packed_varints,
    first_bytes,
    first_varint,
    len_field,
    parse_fields,
    rebuild_message,
    set_bytes,
    set_fixed32,
    set_varint,
    varint_field,
)


HEADER_SIZE = 20
FOOTER_SIZE = 4
MAX_DECORATIONS_PER_PARENT = 999
DEFAULT_WRAPPER_TEMPLATE_ID = 10005018
DEFAULT_DECORATION_ID_START = 0x40000001
WRAPPER_SCALE_REDUCTION = 0.004
MIN_WRAPPER_SCALE = 0.01


WRAPPER_MODE_BOUNDING_BOX = "BOUNDING_BOX"
WRAPPER_MODE_SHRINK_HIDE = "SHRINK_HIDE"
WRAPPER_MODE_RANDOM_GROUP_OBJECT = "RANDOM_GROUP_OBJECT"
WRAPPER_MODES = frozenset(
    {
        WRAPPER_MODE_BOUNDING_BOX,
        WRAPPER_MODE_SHRINK_HIDE,
        WRAPPER_MODE_RANDOM_GROUP_OBJECT,
    }
)


@dataclass(frozen=True)
class DecorationGroup:
    parent_position: tuple[float, float, float]
    parent_scale: tuple[float, float, float]
    objects: tuple[dict[str, Any], ...]
    parent_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    parent_object_index: int | None = None
    parent_name: str | None = None
    parent_group: str | None = None
    parent_anchor: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class GeometryBounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    center: tuple[float, float, float]
    bottom_center: tuple[float, float, float]
    size: tuple[float, float, float]


def _vec3(item: dict[str, Any], key: str, default: Sequence[float]) -> tuple[float, float, float]:
    value = item.get(key, default)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{key} must be [x,y,z]")
    result = tuple(float(component) for component in value)
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{key} 包含非有限数")
    return result


def reduce_wrapper_scale(scale: Sequence[float]) -> tuple[float, float, float]:
    """Lower every wrapper scale axis by 0.004 while keeping it valid."""
    source = _vec3({"value": scale}, "value", (1.0, 1.0, 1.0))
    if any(value <= 0 for value in source):
        raise ValueError("父空模型原始 scale 三轴必须 > 0")
    return tuple(max(MIN_WRAPPER_SCALE, value - WRAPPER_SCALE_REDUCTION) for value in source)


def _rotated_half_extents(
    scale: tuple[float, float, float],
    rotation_deg: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return world AABB half extents for an Rx/Ry/Rz rotated centered box."""
    hx, hy, hz = (abs(value) / 2.0 for value in scale)
    rx, ry, rz = (math.radians(value) for value in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    # Rz * Ry * Rx. Absolute rows transform local half extents into AABB extents.
    rotation = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    return tuple(
        abs(row[0]) * hx + abs(row[1]) * hy + abs(row[2]) * hz
        for row in rotation
    )


def _rotation_matrix(rotation_deg: Sequence[float]) -> tuple[tuple[float, float, float], ...]:
    """Return the exporter rotation matrix (Rz * Ry * Rx)."""
    rx, ry, rz = (math.radians(value) for value in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )

def _inverse_rotate(vector: Sequence[float], rotation_deg: Sequence[float]) -> tuple[float, float, float]:
    matrix = _rotation_matrix(rotation_deg)
    return tuple(sum(matrix[column][row] * vector[column] for column in range(3)) for row in range(3))

def _local_rotation(
    world_rotation: Sequence[float], parent_rotation: Sequence[float]
) -> tuple[float, float, float]:
    """Return R_parent^-1 * R_world as exporter XYZ Euler angles."""
    parent = _rotation_matrix(parent_rotation)
    world = _rotation_matrix(world_rotation)
    matrix = tuple(
        tuple(sum(parent[index][row] * world[index][column] for index in range(3)) for column in range(3))
        for row in range(3)
    )
    y = math.asin(max(-1.0, min(1.0, -matrix[2][0])))
    cosine_y = math.cos(y)
    if abs(cosine_y) > 1e-8:
        x = math.atan2(matrix[2][1], matrix[2][2])
        z = math.atan2(matrix[1][0], matrix[0][0])
    else:
        x = math.atan2(-matrix[1][2], matrix[1][1])
        z = 0.0
    return tuple(math.degrees(value) for value in (x, y, z))


def geometry_bounds(objects: Sequence[dict[str, Any]]) -> GeometryBounds:
    """Merged rotation-aware AABB and the empty-model bottom-center anchor."""
    if not objects:
        raise ValueError("无法计算空对象组的几何边界")
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    for item in objects:
        position = _vec3(item, "position", (0.0, 0.0, 0.0))
        rotation = _vec3(item, "rotation", (0.0, 0.0, 0.0))
        scale = _vec3(item, "scale", (1.0, 1.0, 1.0))
        if any(value <= 0 for value in scale):
            raise ValueError("scale 三轴必须 > 0")
        extents = _rotated_half_extents(scale, rotation)
        for axis in range(3):
            minimum[axis] = min(minimum[axis], position[axis] - extents[axis])
            maximum[axis] = max(maximum[axis], position[axis] + extents[axis])
    minimum_tuple = tuple(minimum)
    maximum_tuple = tuple(maximum)
    center = tuple((minimum[axis] + maximum[axis]) / 2.0 for axis in range(3))
    bottom_center = (center[0], minimum[1], center[2])
    size = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    return GeometryBounds(minimum_tuple, maximum_tuple, center, bottom_center, size)


def geometry_center(objects: Sequence[dict[str, Any]]) -> tuple[float, float, float]:
    """Geometric center of the merged, rotation-aware AABB."""
    return geometry_bounds(objects).center


def place_objects_on_backing(
    objects: Sequence[dict[str, Any]],
    backing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Place centered box objects directly on the backing's top surface."""
    backing_position = _vec3(backing, "position", (0.0, 0.0, 0.0))
    backing_scale = _vec3(backing, "scale", (1.0, 1.0, 1.0))
    if any(value <= 0 for value in backing_scale):
        raise ValueError("叠底 scale 三轴必须 > 0")
    backing_top_y = backing_position[1] + backing_scale[1] / 2.0

    placed: list[dict[str, Any]] = []
    for item in objects:
        position = list(_vec3(item, "position", (0.0, 0.0, 0.0)))
        scale = _vec3(item, "scale", (1.0, 1.0, 1.0))
        if any(value <= 0 for value in scale):
            raise ValueError("线稿对象 scale 三轴必须 > 0")
        # 方块原点位于几何中心。让每个线条方块的底面与叠底顶面严格相接。
        position[1] = backing_top_y + scale[1] / 2.0
        placed_item = dict(item)
        placed_item["position"] = position
        placed.append(placed_item)
    return placed


def group_objects_for_decoration(
    objects: Sequence[dict[str, Any]],
    max_per_parent: int = MAX_DECORATIONS_PER_PARENT,
    *,
    parent_position: Sequence[float] | None = None,
    parent_scale: Sequence[float] | None = None,
    fixed_parent_scale: float | None = None,
) -> list[DecorationGroup]:
    maximum = int(max_per_parent)
    if not 1 <= maximum <= MAX_DECORATIONS_PER_PARENT:
        raise ValueError(f"每个空模型的装饰物数量必须位于 1..{MAX_DECORATIONS_PER_PARENT}")
    if fixed_parent_scale is not None and (
        parent_position is not None or parent_scale is not None
    ):
        raise ValueError(
            "fixed_parent_scale 不能与 parent_position 或 parent_scale 同时提供"
        )
    if (parent_position is None) != (parent_scale is None):
        raise ValueError("parent_position 与 parent_scale 必须同时省略或同时提供")
    resolved_fixed_scale: float | None = None
    if fixed_parent_scale is not None:
        try:
            resolved_fixed_scale = float(fixed_parent_scale)
        except (TypeError, ValueError) as exc:
            raise ValueError("fixed_parent_scale 必须是有限正数") from exc
        if not math.isfinite(resolved_fixed_scale) or resolved_fixed_scale <= 0:
            raise ValueError("fixed_parent_scale 必须是有限正数")
    if not objects:
        return []

    if resolved_fixed_scale is not None:
        fixed_scale = (resolved_fixed_scale,) * 3
        groups: list[DecorationGroup] = []
        for start in range(0, len(objects), maximum):
            chunk = tuple(objects[start : start + maximum])
            groups.append(
                DecorationGroup(geometry_bounds(chunk).center, fixed_scale, chunk)
            )
        return groups

    bounds = geometry_bounds(objects)
    # 自动模式使用整批包围盒底面中心；实体主体模式使用调用方成对提供的
    # 位置和目标缩放。分组只用于满足 999 上限，所有分组共享同一变换。
    shared_position = (
        bounds.bottom_center
        if parent_position is None
        else _vec3({"value": parent_position}, "value", bounds.bottom_center)
    )
    requested_scale = (
        bounds.size
        if parent_scale is None
        else _vec3({"value": parent_scale}, "value", bounds.size)
    )
    # 包装主体三轴均沿用既有“原目标值 - 0.004”补偿。子装饰物后续以这个
    # 最终父缩放做逆变换，因此显示几何不会随父缩放补偿而改变。
    shared_scale = reduce_wrapper_scale(requested_scale)
    groups: list[DecorationGroup] = []
    for start in range(0, len(objects), maximum):
        chunk = tuple(objects[start : start + maximum])
        groups.append(DecorationGroup(shared_position, shared_scale, chunk))
    return groups


def _patch_payload(
    fields: list[WireField],
    field_number: int,
    context: str,
    patch: Callable[[list[WireField]], None],
) -> None:
    payload = first_bytes(fields, field_number)
    nested = [] if payload is None else parse_fields(payload, context=context)
    patch(nested)
    set_bytes(fields, field_number, rebuild_message(nested))


def _component(
    fields: list[WireField], container_field: int, component_type: int
) -> tuple[int, list[WireField]] | None:
    for index, field in enumerate(fields):
        if field.number != container_field or field.wire_type != 2:
            continue
        nested = parse_fields(bytes(field.value), context=f"component {component_type}")
        if first_varint(nested, 1) == component_type:
            return index, nested
    return None


def _patch_component_payload(
    fields: list[WireField],
    *,
    container_field: int,
    component_type: int,
    payload_field: int,
    context: str,
    patch: Callable[[list[WireField]], None],
    create_if_missing: bool = True,
) -> None:
    found = _component(fields, container_field, component_type)
    if found is None:
        if not create_if_missing:
            return
        payload: list[WireField] = []
        patch(payload)
        component = rebuild_message(
            [varint_field(1, component_type), len_field(payload_field, rebuild_message(payload))]
        )
        fields.append(len_field(container_field, component))
        return
    index, component = found
    _patch_payload(component, payload_field, context, patch)
    fields[index] = fields[index].with_value(rebuild_message(component))


def _set_vec3(fields: list[WireField], value: tuple[float, float, float]) -> None:
    for number, component in enumerate(value, start=1):
        set_fixed32(fields, number, component)


def _patch_transform_payload(
    fields: list[WireField],
    position: tuple[float, float, float],
    rotation: tuple[float, float, float],
    scale: tuple[float, float, float],
) -> None:
    _patch_payload(fields, 1, "transform position", lambda nested: _set_vec3(nested, position))
    _patch_payload(fields, 2, "transform rotation", lambda nested: _set_vec3(nested, rotation))
    _patch_payload(fields, 3, "transform scale", lambda nested: _set_vec3(nested, scale))


def _rgba(item: dict[str, Any]) -> tuple[int, int, int, int]:
    value = item.get("color", item.get("rgb"))
    rgb = (255, 255, 255)
    opacity = 100.0
    if isinstance(value, (list, tuple)):
        if len(value) not in (3, 4):
            raise ValueError("color must be [r,g,b] or [r,g,b,opacity]")
        rgb = tuple(int(component) for component in value[:3])
        if len(value) == 4:
            opacity = float(value[3])
    elif isinstance(value, dict):
        raw_rgb = value.get("rgb", (value.get("r", 255), value.get("g", 255), value.get("b", 255)))
        if not isinstance(raw_rgb, (list, tuple)) or len(raw_rgb) != 3:
            raise ValueError("color.rgb must be [r,g,b]")
        rgb = tuple(int(component) for component in raw_rgb)
        opacity = float(value.get("opacity", value.get("alpha_percent", 100.0)))
        if "alpha" in value:
            opacity = int(value["alpha"]) / 255.0 * 100.0
    elif value is not None:
        raise ValueError(f"unsupported color format: {value!r}")
    if any(not 0 <= component <= 255 for component in rgb):
        raise ValueError("RGB 必须位于 0..255")
    alpha = round(max(0.0, min(100.0, opacity)) / 100.0 * 255.0)
    return rgb[0], rgb[1], rgb[2], alpha


def _patch_parent_asset(
    template: bytes,
    *,
    parent_id: int,
    name: str,
    position: tuple[float, float, float],
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    decoration_metas: Sequence[bytes],
    decoration_ids: Sequence[int],
    wrapper_template_id: int,
    wrapper_static: bool,
    wrapper_collision: bool,
    wrapper_climb: bool,
    wrapper_enable_out_of_range_run: bool,
    wrapper_out_of_range_display_mode: int,
    scale: tuple[float, float, float],
    color: tuple[int, int, int, int] | None = None,
) -> bytes:
    asset = parse_fields(template, context="decoration parent asset")
    meta = first_bytes(asset, 1)
    if meta is None:
        raise ValueError("装饰物包装模板的主元件缺少 meta")
    meta_fields = parse_fields(meta, context="parent meta")
    set_varint(meta_fields, 4, parent_id)
    set_bytes(asset, 1, rebuild_message(meta_fields))
    set_bytes(asset, 3, name.encode("utf-8"))

    first_dependency = next((index for index, field in enumerate(asset) if field.number == 2), None)
    asset = [field for field in asset if field.number != 2]
    insert_at = first_dependency if first_dependency is not None else 1
    asset[insert_at:insert_at] = [len_field(2, item) for item in decoration_metas]

    entity_blob = first_bytes(asset, 12)
    if entity_blob is None:
        raise ValueError("装饰物包装模板的主元件缺少 entity_data")
    entity = parse_fields(entity_blob, context="parent entity wrapper")
    set_varint(entity, 4, wrapper_template_id)
    data_blob = first_bytes(entity, 1)
    if data_blob is None:
        raise ValueError("装饰物包装模板的主元件缺少 entity core")
    data = parse_fields(data_blob, context="parent entity core")
    set_varint(data, 1, parent_id)
    set_varint(data, 8, wrapper_template_id)

    template_blob = first_bytes(data, 2)
    template_ref = [] if template_blob is None else parse_fields(template_blob, context="parent template ref")
    set_varint(template_ref, 1, wrapper_template_id)
    set_varint(template_ref, 2, 1)
    set_bytes(data, 2, rebuild_message(template_ref))

    def patch_name(payload: list[WireField]) -> None:
        set_bytes(payload, 1, name.encode("utf-8"))
        payload[:] = [field for field in payload if not (field.number == 2 and field.wire_type == 0)]
        if wrapper_static:
            set_varint(payload, 2, 1)

    _patch_component_payload(
        data,
        container_field=5,
        component_type=1,
        payload_field=11,
        context="parent name",
        patch=patch_name,
    )
    _patch_component_payload(
        data,
        container_field=5,
        component_type=40,
        payload_field=50,
        context="parent decoration refs",
        patch=lambda payload: set_bytes(payload, 501, encode_packed_varints(decoration_ids)),
    )
    _patch_component_payload(
        data,
        container_field=6,
        component_type=1,
        payload_field=11,
        context="parent transform",
        patch=lambda payload: _patch_transform_payload(
            payload, position, rotation, scale
        ),
    )

    def patch_collider(payload: list[WireField]) -> None:
        payload[:] = [field for field in payload if field.number not in (1, 2)]
        if wrapper_collision:
            set_varint(payload, 1, 1)
        if wrapper_climb:
            set_varint(payload, 2, 1)

    _patch_component_payload(
        data,
        container_field=6,
        component_type=5,
        payload_field=15,
        context="parent collider",
        patch=patch_collider,
    )

    def patch_run(payload: list[WireField]) -> None:
        payload[:] = [field for field in payload if field.number not in (1, 501)]
        set_varint(payload, 1 if wrapper_enable_out_of_range_run else 501, 1)

    _patch_component_payload(
        data,
        container_field=6,
        component_type=12,
        payload_field=22,
        context="parent out-of-range run",
        patch=patch_run,
    )

    def patch_display_mode(payload: list[WireField]) -> None:
        payload[:] = [field for field in payload if field.number != 2]
        if wrapper_out_of_range_display_mode:
            set_varint(payload, 2, wrapper_out_of_range_display_mode)

    _patch_component_payload(
        data,
        container_field=6,
        component_type=20,
        payload_field=30,
        context="parent out-of-range display",
        patch=patch_display_mode,
    )
    if color is not None:
        def patch_color(payload: list[WireField]) -> None:
            r, g, b, a = color
            rgb = (r << 16) | (g << 8) | b
            payload[:] = [field for field in payload if field.number not in (1, 3, 4, 5, 6, 9)]
            set_varint(payload, 1, 1)
            set_varint(payload, 3, (a << 24) | rgb)
            set_fixed32(payload, 4, a * 100.0 / 255.0)
            set_varint(payload, 5, rgb)
            set_varint(payload, 6, 6700)
            set_varint(payload, 9, 0)

        _patch_component_payload(
            data,
            container_field=6,
            component_type=22,
            payload_field=32,
            context="parent color",
            patch=patch_color,
        )
    set_bytes(entity, 1, rebuild_message(data))
    set_bytes(asset, 12, rebuild_message(entity))
    return rebuild_message(asset)


def _patch_decoration_asset(
    template: bytes,
    *,
    decoration_id: int,
    owner_id: int,
    item: dict[str, Any],
    local_position: tuple[float, float, float],
    local_scale: tuple[float, float, float],
    no_transparency: bool = False,
) -> tuple[bytes, bytes, dict[str, Any]]:
    asset = parse_fields(template, context="decoration resource asset")
    meta_blob = first_bytes(asset, 1)
    if meta_blob is None:
        raise ValueError("装饰物模板缺少 meta")
    meta = parse_fields(meta_blob, context="decoration meta")
    set_varint(meta, 4, decoration_id)
    patched_meta = rebuild_message(meta)
    set_bytes(asset, 1, patched_meta)

    template_id = int(item.get("template_id", item.get("type_id", item.get("type"))))
    name = str(item.get("name") or f"Decoration_{decoration_id}")
    rotation = _vec3(item, "rotation", (0.0, 0.0, 0.0))
    world_scale = _vec3(item, "scale", (1.0, 1.0, 1.0))
    if any(value <= 0 for value in world_scale) or any(value <= 0 for value in local_scale):
        raise ValueError("scale 三轴必须 > 0")
    r, g, b, a = _rgba(item)
    custom_color_enabled = bool(item.get("custom_color_enabled", True))
    collision = bool(item.get("enable_collision", item.get("collision", True)))
    climb = bool(item.get("enable_climb", item.get("climb", True)))
    run_out_of_range = bool(item.get("enable_out_of_range_run", False))
    display_mode = int(item.get("out_of_range_display_mode", 0))
    if display_mode not in (0, 1, 2):
        raise ValueError("out_of_range_display_mode 必须为 0、1 或 2")
    set_bytes(asset, 3, name.encode("utf-8"))

    wrapper_blob = first_bytes(asset, 21)
    if wrapper_blob is None:
        raise ValueError("装饰物模板缺少 decoration_data")
    wrapper = parse_fields(wrapper_blob, context="decoration wrapper")
    decoration_blob = first_bytes(wrapper, 1)
    if decoration_blob is None:
        raise ValueError("装饰物模板缺少 decoration body")
    decoration = parse_fields(decoration_blob, context="decoration body")
    set_varint(decoration, 1, decoration_id)
    set_varint(decoration, 2, template_id)

    def patch_collider(payload: list[WireField]) -> None:
        set_varint(payload, 1, int(collision))
        set_varint(payload, 2, int(climb))

    _patch_component_payload(
        decoration,
        container_field=4,
        component_type=1,
        payload_field=11,
        context="decoration name",
        patch=lambda payload: set_bytes(payload, 1, name.encode("utf-8")),
    )
    _patch_component_payload(
        decoration,
        container_field=4,
        component_type=40,
        payload_field=50,
        context="decoration owner",
        patch=lambda payload: set_varint(payload, 502, owner_id),
    )
    _patch_component_payload(
        decoration,
        container_field=5,
        component_type=1,
        payload_field=11,
        context="decoration transform",
        patch=lambda payload: _patch_transform_payload(payload, local_position, rotation, local_scale),
    )

    def patch_color(payload: list[WireField]) -> None:
        if not custom_color_enabled:
            payload[:] = [field for field in payload if field.number not in (1, 3, 4, 5, 6, 9)]
            return
        alpha = 255 if no_transparency else a
        rgb = (r << 16) | (g << 8) | b
        set_varint(payload, 1, 1)
        set_varint(payload, 3, (alpha << 24) | rgb)
        set_fixed32(payload, 4, alpha * 100.0 / 255.0)
        set_varint(payload, 5, rgb)
        set_varint(payload, 6, 6700)
        set_varint(payload, 9, 0)

    _patch_component_payload(
        decoration,
        container_field=5,
        component_type=22,
        payload_field=32,
        context="decoration color",
        patch=patch_color,
        create_if_missing=custom_color_enabled,
    )
    _patch_component_payload(
        decoration,
        container_field=5,
        component_type=5,
        payload_field=15,
        context="decoration collider",
        patch=patch_collider,
    )

    def patch_run(payload: list[WireField]) -> None:
        payload[:] = [field for field in payload if field.number not in (1, 501)]
        set_varint(payload, 1 if run_out_of_range else 501, 1)

    _patch_component_payload(
        decoration,
        container_field=5,
        component_type=12,
        payload_field=22,
        context="decoration out-of-range run",
        patch=patch_run,
        create_if_missing=False,
    )

    def patch_display_mode(payload: list[WireField]) -> None:
        payload[:] = [field for field in payload if field.number != 2]
        if display_mode:
            set_varint(payload, 2, display_mode)

    _patch_component_payload(
        decoration,
        container_field=5,
        component_type=20,
        payload_field=30,
        context="decoration out-of-range display",
        patch=patch_display_mode,
        create_if_missing=False,
    )
    set_bytes(wrapper, 1, rebuild_message(decoration))
    set_bytes(asset, 21, rebuild_message(wrapper))
    record = {
        "decoration_id": decoration_id,
        "owner_id": owner_id,
        "template_id": template_id,
        "name": name,
        "local_position": list(local_position),
        "rotation": list(rotation),
        "scale": list(local_scale),
        "world_scale": list(world_scale),
        "rgba": [r, g, b, 255 if no_transparency else a] if custom_color_enabled else None,
        "enable_native_collision": collision,
        "enable_climb": climb,
        "enable_out_of_range_run": run_out_of_range,
        "out_of_range_display_mode": display_mode,
    }
    return rebuild_message(asset), patched_meta, record


def _load_template(path: Path) -> tuple[bytearray, bytes, bytes, list[WireField]]:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE + FOOTER_SIZE:
        raise ValueError(f"装饰物包装模板不是有效 GIA：{path}")
    header = bytearray(data[:HEADER_SIZE])
    payload_size = int.from_bytes(header[16:20], "big")
    payload_end = HEADER_SIZE + payload_size
    if payload_end + FOOTER_SIZE != len(data):
        raise ValueError("装饰物包装模板的 payload 长度与文件大小不一致")
    payload = data[HEADER_SIZE:payload_end]
    return header, data[payload_end:], payload, parse_fields(payload, context="GIA root")


def build_decorated_gia(
    *,
    objects: Sequence[dict[str, Any]],
    decoration_template_path: Path,
    output_path: Path,
    max_per_parent: int = MAX_DECORATIONS_PER_PARENT,
    wrapper_template_id: int = DEFAULT_WRAPPER_TEMPLATE_ID,
    entity_id_start: int = 1_078_400_000,
    decoration_id_start: int = DEFAULT_DECORATION_ID_START,
    wrapper_static: bool = False,
    wrapper_collision: bool = False,
    wrapper_climb: bool = False,
    wrapper_enable_out_of_range_run: bool = False,
    wrapper_out_of_range_display_mode: int = 0,
    no_transparency_export: bool = False,
    standalone_entity_assets: Sequence[bytes] = (),
    standalone_entity_records: Sequence[dict[str, Any]] = (),
    parent_position: Sequence[float] | None = None,
    parent_scale: Sequence[float] | None = None,
    fixed_parent_scale: float | None = None,
    parent_name_prefix: str = "DecorationGroup",
    parent_ids: Sequence[int] | None = None,
    wrapper_mode: str = WRAPPER_MODE_BOUNDING_BOX,
    wrapper_hidden_scale: float = MIN_WRAPPER_SCALE,
    random_seed: int | None = 0,
    decoration_groups: Sequence[DecorationGroup] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Build one or more decorated wrapper entities from an editor-exported template.

    The template's parent must already use ``wrapper_template_id``. Template IDs are
    patched for identity consistency, but this function does not convert an empty
    model parent into a visible primitive or another entity type.
    """
    if not objects:
        raise ValueError("没有可包装的装饰物")
    if wrapper_climb and not wrapper_collision:
        raise ValueError("包装主体启用攀爬时必须同时启用碰撞")
    if int(wrapper_out_of_range_display_mode) not in (0, 1, 2):
        raise ValueError("空模型超范围显示模式必须为 0、1 或 2")
    resolved_wrapper_mode = str(wrapper_mode).strip().upper()
    if resolved_wrapper_mode not in WRAPPER_MODES:
        raise ValueError(f"wrapper_mode 必须是 {', '.join(sorted(WRAPPER_MODES))}")
    if decoration_groups is not None:
        if resolved_wrapper_mode == WRAPPER_MODE_RANDOM_GROUP_OBJECT:
            raise ValueError("自定义父级配置请使用缩小空模型或空模型包围盒模式")
        groups = list(decoration_groups)
        if not 1 <= int(max_per_parent) <= MAX_DECORATIONS_PER_PARENT:
            raise ValueError(f"每个父级的装饰物数量必须位于 1..{MAX_DECORATIONS_PER_PARENT}")
        if not groups or any(not group.objects or len(group.objects) > int(max_per_parent) for group in groups):
            raise ValueError("自定义父级分组不能为空或超过每组数量上限")
        if sorted(id(item) for group in groups for item in group.objects) != sorted(map(id, objects)):
            raise ValueError("自定义父级分组必须恰好覆盖每个输入物体一次")
        names = [group.parent_name for group in groups]
        if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names):
            raise ValueError("自定义父实体名称必须非空且唯一")
        for group in groups:
            if group.parent_object_index is not None:
                raise ValueError("自定义父级分组必须使用空模型父实体")
            _vec3({"position": group.parent_position}, "position", (0.0, 0.0, 0.0))
            _vec3({"rotation": group.parent_rotation}, "rotation", (0.0, 0.0, 0.0))
            if min(_vec3({"scale": group.parent_scale}, "scale", (1.0, 1.0, 1.0))) <= 0:
                raise ValueError("父实体 scale 三轴必须 > 0")
    elif resolved_wrapper_mode == WRAPPER_MODE_SHRINK_HIDE:
        hidden_scale = float(wrapper_hidden_scale)
        if not math.isfinite(hidden_scale) or not 0 < hidden_scale <= 1:
            raise ValueError("wrapper_hidden_scale 必须位于 (0, 1]")
        groups = group_objects_for_decoration(
            objects, max_per_parent, fixed_parent_scale=hidden_scale
        )
    else:
        groups = group_objects_for_decoration(
            objects,
            max_per_parent,
            parent_position=parent_position,
            parent_scale=parent_scale,
            fixed_parent_scale=fixed_parent_scale,
        )
    if resolved_wrapper_mode == WRAPPER_MODE_RANDOM_GROUP_OBJECT:
        selector = random.Random(random_seed)
        groups = [
            DecorationGroup(
                parent_position=_vec3(group.objects[selected_index], "position", (0.0, 0.0, 0.0)),
                parent_scale=_vec3(group.objects[selected_index], "scale", (1.0, 1.0, 1.0)),
                parent_rotation=_vec3(group.objects[selected_index], "rotation", (0.0, 0.0, 0.0)),
                parent_object_index=selected_index,
                objects=group.objects,
            )
            for group in groups
            for selected_index in (selector.randrange(len(group.objects)),)
        ]
    header, footer, original_payload, root = _load_template(Path(decoration_template_path))
    if rebuild_message(root) != original_payload:
        raise ValueError("装饰物包装模板无法 lossless roundtrip")
    parent_fields = [field for field in root if field.number == 1 and field.wire_type == 2]
    resource_fields = [field for field in root if field.number == 2 and field.wire_type == 2]
    if not parent_fields or not resource_fields:
        raise ValueError("装饰物包装模板必须至少包含一个主元件和一个装饰物资源")
    parent_template = bytes(parent_fields[0].value)
    decoration_template = bytes(resource_fields[0].value)
    # Named groups may reorder the input; source IDs must follow each original object.
    source_ids = {
        id(item): int(item.get("entity_id", item.get("object_id", item.get("id", entity_id_start + i))))
        for i, item in enumerate(objects)
    }
    decoration_count = len(objects) - sum(
        group.parent_object_index is not None for group in groups
    )
    decoration_ids = [int(decoration_id_start) + index for index in range(decoration_count)]
    if decoration_ids and not 1 <= decoration_ids[0] <= decoration_ids[-1] <= 0xFFFFFFFF:
        raise ValueError("装饰物 ID 超出 uint32 范围")

    reserved_entity_ids: set[int] = set()
    for asset_blob in standalone_entity_assets:
        asset_fields = parse_fields(bytes(asset_blob), context="standalone entity asset")
        meta_blob = first_bytes(asset_fields, 1)
        if meta_blob is None:
            raise ValueError("独立静态元件缺少 Asset.meta")
        asset_id = first_varint(parse_fields(meta_blob, context="standalone entity meta"), 4)
        if asset_id is None:
            raise ValueError("独立静态元件缺少 asset_id")
        if asset_id in reserved_entity_ids:
            raise ValueError(f"独立静态元件 ID 重复：{asset_id}")
        reserved_entity_ids.add(asset_id)
    if parent_ids is None:
        resolved_parent_ids: list[int] = []
        candidate_id = int(entity_id_start)
        while len(resolved_parent_ids) < len(groups):
            if candidate_id > 0xFFFFFFFF:
                raise ValueError("生成的主元件 ID 超出 uint32 范围")
            if candidate_id not in reserved_entity_ids:
                resolved_parent_ids.append(candidate_id)
            candidate_id += 1
    else:
        resolved_parent_ids = [int(value) for value in parent_ids]
        if len(resolved_parent_ids) != len(groups):
            raise ValueError("显式 parent_ids 数量必须与装饰物分组数量一致")
        if len(set(resolved_parent_ids)) != len(resolved_parent_ids):
            raise ValueError("显式 parent_ids 不得重复")
        if any(not 1 <= value <= 0xFFFFFFFF for value in resolved_parent_ids):
            raise ValueError("显式 parent_ids 必须位于 uint32 正整数范围")
        if reserved_entity_ids.intersection(resolved_parent_ids):
            raise ValueError("显式 parent_ids 与独立实体 ID 冲突")
    if set(resolved_parent_ids).intersection(decoration_ids) or reserved_entity_ids.intersection(decoration_ids):
        raise ValueError("主元件 ID 区间与装饰物 ID 区间重叠")

    standalone_fields = [len_field(1, bytes(asset)) for asset in standalone_entity_assets]
    standalone_records = [dict(record) for record in standalone_entity_records]

    generated_parents: list[WireField] = []
    generated_resources: list[WireField] = []
    parent_records: list[dict[str, Any]] = []
    decoration_records: list[dict[str, Any]] = []
    decoration_index = 0
    total = decoration_count
    for group_index, group in enumerate(groups):
        parent_id = resolved_parent_ids[group_index]
        metas: list[bytes] = []
        group_resources: list[WireField] = []
        ids: list[int] = []
        for object_index, item in enumerate(group.objects):
            if object_index == group.parent_object_index:
                continue
            source_id = source_ids[id(item)]
            decoration_id = decoration_ids[decoration_index]
            decoration_index += 1
            ids.append(decoration_id)
            position = _vec3(item, "position", (0.0, 0.0, 0.0))
            world_scale = _vec3(item, "scale", (1.0, 1.0, 1.0))
            # 装饰物的变换是父空模型下的局部 TRS。父模型缩放到 AABB 后，
            # 局部位移和局部缩放都必须除以父缩放，否则导入时会被二次放大。
            parent_delta = tuple(position[axis] - group.parent_position[axis] for axis in range(3))
            unrotated_delta = _inverse_rotate(parent_delta, group.parent_rotation)
            local_position = tuple(
                unrotated_delta[axis] / group.parent_scale[axis]
                for axis in range(3)
            )
            local_scale = tuple(
                world_scale[axis] / group.parent_scale[axis] for axis in range(3)
            )
            local_item = dict(item)
            if group.parent_rotation != (0.0, 0.0, 0.0):
                local_item["rotation"] = _local_rotation(
                    _vec3(item, "rotation", (0.0, 0.0, 0.0)), group.parent_rotation
                )
            resource, meta, record = _patch_decoration_asset(
                decoration_template,
                decoration_id=decoration_id,
                owner_id=parent_id,
                item=local_item,
                local_position=local_position,
                local_scale=local_scale,
                no_transparency=no_transparency_export,
            )
            record["source_entity_id"] = source_id
            metas.append(meta)
            group_resources.append(len_field(2, resource))
            decoration_records.append(record)
            completed = len(decoration_records)
            if progress_callback is not None and total and (completed == total or completed % max(1, total // 100) == 0):
                progress_callback(10 + round(75 * completed / total), f"正在写入装饰物：{completed:,}/{total:,}")

        prefix = str(parent_name_prefix).strip() or "DecorationGroup"
        digits = 4 if prefix == "DecorationGroup" else 3
        parent_item = (
            group.objects[group.parent_object_index]
            if group.parent_object_index is not None
            else None
        )
        parent_name = group.parent_name or (
            str(parent_item.get("name") or f"{prefix}_{group_index + 1:0{digits}d}")
            if parent_item is not None
            else f"{prefix}_{group_index + 1:0{digits}d}"
        )
        parent = _patch_parent_asset(
            parent_template,
            parent_id=parent_id,
            name=parent_name,
            position=group.parent_position,
            rotation=group.parent_rotation,
            decoration_metas=metas,
            decoration_ids=ids,
            wrapper_template_id=(
                int(parent_item["template_id"])
                if parent_item is not None
                else int(wrapper_template_id)
            ),
            wrapper_static=bool(wrapper_static),
            wrapper_collision=bool(wrapper_collision),
            wrapper_climb=bool(wrapper_climb),
            wrapper_enable_out_of_range_run=bool(wrapper_enable_out_of_range_run),
            wrapper_out_of_range_display_mode=int(wrapper_out_of_range_display_mode),
            scale=group.parent_scale,
            color=(
                _rgba(parent_item)
                if parent_item is not None and parent_item.get("custom_color_enabled", True)
                and parent_item.get("color", parent_item.get("rgb")) is not None
                else None
            ),
        )
        generated_parents.append(len_field(1, parent))
        generated_resources.extend(group_resources)
        parent_records.append(
            {
                "parent_id": parent_id,
                "name": parent_name,
                "template_id": (
                    int(parent_item["template_id"])
                    if parent_item is not None
                    else int(wrapper_template_id)
                ),
                "position": list(group.parent_position),
                "rotation": list(group.parent_rotation),
                "scale": list(group.parent_scale),
                "decoration_count": len(ids),
                "decoration_ids": list(ids),
                "static": bool(wrapper_static),
                "enable_native_collision": bool(wrapper_collision),
                "enable_climb": bool(wrapper_climb),
                "enable_out_of_range_run": bool(wrapper_enable_out_of_range_run),
                "out_of_range_display_mode": int(wrapper_out_of_range_display_mode),
                "source_object_name": None if parent_item is None else str(parent_item.get("name", "")),
            }
        )
        if group.parent_group is not None:
            parent_records[-1].update(
                parent_group=group.parent_group,
                anchor=list(group.parent_anchor) if group.parent_anchor is not None else None,
            )

    tail = [field for field in root if field.number not in (1, 2)]
    source_path = f"generated\\{output_path.name}".encode("utf-8")
    for index, field in enumerate(tail):
        if field.number == 3 and field.wire_type == 2:
            tail[index] = field.with_value(source_path)
            break
    else:
        tail.insert(0, len_field(3, source_path))
    payload = rebuild_message(standalone_fields + generated_parents + generated_resources + tail)
    total_size = HEADER_SIZE + len(payload) + len(footer)
    header[0:4] = (total_size - 4).to_bytes(4, "big")
    header[16:20] = len(payload).to_bytes(4, "big")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(header) + payload + footer)
    return {
        "template": str(decoration_template_path),
        "output": str(output_path),
        "asset_count": len(standalone_fields) + len(generated_parents),
        "resource_asset_count": len(generated_resources),
        "parent_count": len(generated_parents),
        "standalone_asset_count": len(standalone_fields),
        "decoration_count": len(generated_resources),
        "max_decorations_per_parent": int(max_per_parent),
        "wrapper_template_id": int(wrapper_template_id),
        "wrapper_mode": resolved_wrapper_mode,
        "wrapper_hidden_scale": float(wrapper_hidden_scale),
        "random_seed": random_seed,
        "decoration_id_start": int(decoration_id_start),
        "wrapper_static": bool(wrapper_static),
        "wrapper_collision": bool(wrapper_collision),
        "wrapper_climb": bool(wrapper_climb),
        "wrapper_enable_out_of_range_run": bool(wrapper_enable_out_of_range_run),
        "wrapper_out_of_range_display_mode": int(wrapper_out_of_range_display_mode),
        "file_size": output_path.stat().st_size,
        "parents": parent_records,
        "standalone_records": standalone_records,
        "records": decoration_records,
    }


__all__ = [
    "WRAPPER_MODE_BOUNDING_BOX",
    "WRAPPER_MODE_SHRINK_HIDE",
    "WRAPPER_MODE_RANDOM_GROUP_OBJECT",
    "DEFAULT_DECORATION_ID_START",
    "DEFAULT_WRAPPER_TEMPLATE_ID",
    "MIN_WRAPPER_SCALE",
    "MAX_DECORATIONS_PER_PARENT",
    "WRAPPER_SCALE_REDUCTION",
    "DecorationGroup",
    "GeometryBounds",
    "build_decorated_gia",
    "geometry_bounds",
    "geometry_center",
    "group_objects_for_decoration",
    "place_objects_on_backing",
    "reduce_wrapper_scale",
]
