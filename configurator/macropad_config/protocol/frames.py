"""64-byte config protocol frames — pack/unpack + CRC32 (no hardware)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

CFG_MAGIC = 0x4D50
CFG_PROTO_VERSION = 1
CFG_REPORT_SIZE = 64
CFG_HEADER_SIZE = 8
CFG_PAYLOAD_MAX = 52
CFG_CRC_OFFSET = 60

CFG_FLAG_RESPONSE = 0x01

CFG_CMD_PING = 0x01
CFG_CMD_GET_INFO = 0x02
CFG_CMD_ECHO = 0x03
CFG_CMD_NAK = 0x7F

CFG_ERR_OK = 0
CFG_ERR_EINVAL = 1
CFG_ERR_EBADMSG = 2
CFG_ERR_ENOSYS = 3
CFG_ERR_EBUSY = 4

_HEADER = struct.Struct("<HBBBBH")  # magic, ver, flags, cmd, seq, length
_CRC = struct.Struct("<I")


class FrameError(ValueError):
    """Invalid frame (magic, CRC, length, version)."""


def crc32(data: bytes) -> int:
    """IEEE CRC32 (zlib/ethernet): init 0xFFFFFFFF, xorout 0xFFFFFFFF."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


@dataclass
class Frame:
    cmd: int
    seq: int
    payload: bytes = b""
    flags: int = 0
    version: int = CFG_PROTO_VERSION
    magic: int = CFG_MAGIC

    @property
    def is_response(self) -> bool:
        return bool(self.flags & CFG_FLAG_RESPONSE)

    def as_response(self) -> "Frame":
        return Frame(
            cmd=self.cmd,
            seq=self.seq,
            payload=self.payload,
            flags=self.flags | CFG_FLAG_RESPONSE,
            version=self.version,
            magic=self.magic,
        )


def pack_frame(
    cmd: int,
    seq: int,
    payload: bytes = b"",
    *,
    flags: int = 0,
    version: int = CFG_PROTO_VERSION,
) -> bytes:
    """Build a 64-byte report payload (no hidapi report-id prefix)."""
    if len(payload) > CFG_PAYLOAD_MAX:
        raise FrameError(f"payload too long: {len(payload)} > {CFG_PAYLOAD_MAX}")
    length = len(payload)
    padded = payload + bytes(CFG_PAYLOAD_MAX - length)
    head = _HEADER.pack(CFG_MAGIC, version, flags & 0xFF, cmd & 0xFF, seq & 0xFF, length)
    body = head + padded  # 60 bytes
    assert len(body) == CFG_CRC_OFFSET
    c = crc32(body)
    return body + _CRC.pack(c)


def unpack_frame(data: bytes) -> Frame:
    """Parse a 64-byte report; raises FrameError on bad magic/CRC/length."""
    if len(data) != CFG_REPORT_SIZE:
        raise FrameError(f"expected {CFG_REPORT_SIZE} bytes, got {len(data)}")
    magic, version, flags, cmd, seq, length = _HEADER.unpack_from(data, 0)
    if magic != CFG_MAGIC:
        raise FrameError(f"bad magic 0x{magic:04X}")
    if version != CFG_PROTO_VERSION:
        raise FrameError(f"bad version {version}")
    if length > CFG_PAYLOAD_MAX:
        raise FrameError(f"bad length {length}")
    expect = crc32(data[:CFG_CRC_OFFSET])
    got = _CRC.unpack_from(data, CFG_CRC_OFFSET)[0]
    if expect != got:
        raise FrameError(f"bad CRC: expect 0x{expect:08X} got 0x{got:08X}")
    payload = data[CFG_HEADER_SIZE : CFG_HEADER_SIZE + length]
    return Frame(cmd=cmd, seq=seq, payload=payload, flags=flags, version=version, magic=magic)


def parse_get_info(payload: bytes) -> dict:
    """Decode GET_INFO response payload."""
    if len(payload) < 6:
        raise FrameError("GET_INFO payload too short")
    tag = payload[6:14]
    if len(tag) < 8:
        tag = tag + bytes(8 - len(tag))
    return {
        "fw_major": payload[0],
        "fw_minor": payload[1],
        "proto_ver": payload[2],
        "active_slot": payload[3],
        "slot_count": payload[4],
        "flags": payload[5],
        "product_tag": tag.decode("ascii", errors="replace").rstrip("\x00"),
    }
