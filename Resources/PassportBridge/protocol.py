"""Bounded PCM/control framing shared with main/dots_protocol.h."""
import struct

HEADER = struct.Struct('!2sBBHH')
MAX_PAYLOAD = 640
MIC, SPEAKER, AUTH, READY, CALL, STATE, PING = range(1, 8)
IDLE, DIALING, ACTIVE, ERROR = range(4)


def encode(kind, payload=b'', sequence=0):
    if not 1 <= kind <= 7 or len(payload) > MAX_PAYLOAD:
        raise ValueError('invalid frame')
    return HEADER.pack(b'DP', 1, kind, len(payload), sequence & 65535) + payload


class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= HEADER.size:
            magic, version, kind, size, seq = HEADER.unpack_from(self.buffer)
            if magic != b'DP' or version != 1 or not 1 <= kind <= 7 or size > MAX_PAYLOAD:
                raise ValueError('invalid frame header')
            end = HEADER.size + size
            if len(self.buffer) < end:
                break
            payload = bytes(self.buffer[HEADER.size:end])
            del self.buffer[:end]
            if kind in (MIC, SPEAKER) and len(payload) != 640:
                raise ValueError('PCM must be 20 ms / 640 bytes')
            result.append((kind, payload, seq))
        return result
