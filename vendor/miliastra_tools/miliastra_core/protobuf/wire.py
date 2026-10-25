from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import Iterable


class WireError(ValueError):
    pass


@dataclass(frozen=True)
class WireField:
    """Lossless Protobuf Wire 字段。

    未改字段的 raw 包含 key 与编码后的 value，rebuild_message 会原样写回。
    with_value 只重编码被修改的字段，因此未知字段和非规范 varint 仍可保真。
    """

    number: int
    wire_type: int
    value: int | bytes
    raw: bytes
    dirty: bool = False

    def with_value(self, value: int | bytes) -> "WireField":
        return replace(self, value=value, raw=b"", dirty=True)


def encode_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        raise WireError("此工具只接受非负 varint")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def decode_varint(data: bytes, offset: int = 0, *, context: str = "varint") -> tuple[int, int]:
    result = 0
    shift = 0
    start = offset
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
    if offset >= len(data):
        raise WireError(f"{context}: truncated varint at offset {start}")
    raise WireError(f"{context}: varint exceeds 10 bytes at offset {start}")


def parse_fields(data: bytes, *, context: str = "protobuf") -> list[WireField]:
    fields: list[WireField] = []
    offset = 0
    while offset < len(data):
        start = offset
        key, offset = decode_varint(data, offset, context=f"{context} key")
        number = key >> 3
        wire_type = key & 7
        if number <= 0:
            raise WireError(f"{context}: illegal field number {number} at offset {start}")
        if wire_type == 0:
            value, offset = decode_varint(data, offset, context=f"{context} field {number}")
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise WireError(f"{context}: truncated fixed64 field {number}")
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = decode_varint(data, offset, context=f"{context} length field {number}")
            end = offset + length
            if end > len(data):
                raise WireError(f"{context}: truncated length-delimited field {number}")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise WireError(f"{context}: truncated fixed32 field {number}")
            value = data[offset:end]
            offset = end
        else:
            raise WireError(f"{context}: unsupported wire type {wire_type} at offset {start}")
        fields.append(WireField(number, wire_type, value, data[start:offset], False))
    return fields


def _encode_field(field: WireField) -> bytes:
    key = encode_varint((field.number << 3) | field.wire_type)
    if field.wire_type == 0:
        return key + encode_varint(int(field.value))
    payload = bytes(field.value)
    if field.wire_type == 1:
        if len(payload) != 8:
            raise WireError("fixed64 必须恰好 8 字节")
        return key + payload
    if field.wire_type == 2:
        return key + encode_varint(len(payload)) + payload
    if field.wire_type == 5:
        if len(payload) != 4:
            raise WireError("fixed32 必须恰好 4 字节")
        return key + payload
    raise WireError(f"不支持的 wire type: {field.wire_type}")


def rebuild_message(fields: Iterable[WireField]) -> bytes:
    return b"".join(field.raw if not field.dirty and field.raw else _encode_field(field) for field in fields)


def varint_field(number: int, value: int) -> WireField:
    return WireField(number, 0, int(value), b"", True)


def len_field(number: int, value: bytes) -> WireField:
    return WireField(number, 2, bytes(value), b"", True)


def fixed32_field(number: int, value: float) -> WireField:
    return WireField(number, 5, struct.pack("<f", float(value)), b"", True)


def fixed64_field(number: int, value: bytes) -> WireField:
    if len(value) != 8:
        raise WireError("fixed64 必须恰好 8 字节")
    return WireField(number, 1, bytes(value), b"", True)


def first_index(fields: list[WireField], number: int, wire_type: int | None = None) -> int | None:
    for index, field in enumerate(fields):
        if field.number == number and (wire_type is None or field.wire_type == wire_type):
            return index
    return None


def first_field(fields: list[WireField], number: int, wire_type: int | None = None) -> WireField | None:
    index = first_index(fields, number, wire_type)
    return None if index is None else fields[index]


def first_varint(fields: list[WireField], number: int) -> int | None:
    field = first_field(fields, number, 0)
    return None if field is None else int(field.value)


def first_bytes(fields: list[WireField], number: int) -> bytes | None:
    field = first_field(fields, number, 2)
    return None if field is None else bytes(field.value)


def set_varint(fields: list[WireField], number: int, value: int) -> None:
    index = first_index(fields, number, 0)
    if index is None:
        fields.append(varint_field(number, value))
    else:
        fields[index] = fields[index].with_value(int(value))


def set_bytes(fields: list[WireField], number: int, value: bytes) -> None:
    index = first_index(fields, number, 2)
    if index is None:
        fields.append(len_field(number, value))
    else:
        fields[index] = fields[index].with_value(bytes(value))


def set_fixed32(fields: list[WireField], number: int, value: float) -> None:
    payload = struct.pack("<f", float(value))
    index = first_index(fields, number, 5)
    if index is None:
        fields.append(WireField(number, 5, payload, b"", True))
    else:
        fields[index] = fields[index].with_value(payload)


def unpack_fixed32(field: WireField | None) -> float | None:
    if field is None or field.wire_type != 5:
        return None
    return struct.unpack("<f", bytes(field.value))[0]


def encode_packed_varints(values: Iterable[int]) -> bytes:
    return b"".join(encode_varint(value) for value in values)


def decode_packed_varints(data: bytes) -> list[int]:
    values: list[int] = []
    offset = 0
    while offset < len(data):
        value, offset = decode_varint(data, offset, context="packed varint")
        values.append(value)
    return values
