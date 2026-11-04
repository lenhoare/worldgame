"""Minimal Mapbox Vector Tile (MVT) decoder with no third-party dependencies.

Only what the generator needs: layers, features, tags and decoded geometry.
Spec: https://github.com/mapbox/vector-tile-spec/tree/master/2.1
"""

import gzip
import struct

POINT, LINESTRING, POLYGON = 1, 2, 3


def _varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7


def _fields(buf):
    """Yield (field_number, wire_type, value) for a protobuf message."""
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value = buf[pos:pos + 8]
            pos += 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value = buf[pos:pos + length]
            pos += length
        elif wire == 5:
            value = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield field, wire, value


def _packed(buf):
    out = []
    pos = 0
    end = len(buf)
    while pos < end:
        v, pos = _varint(buf, pos)
        out.append(v)
    return out


def _zigzag(n):
    return (n >> 1) ^ -(n & 1)


def _value(buf):
    for field, _wire, v in _fields(buf):
        if field == 1:
            return bytes(v).decode("utf-8", "replace")
        if field == 2:
            return struct.unpack("<f", v)[0]
        if field == 3:
            return struct.unpack("<d", v)[0]
        if field in (4, 5):
            return v
        if field == 6:
            return _zigzag(v)
        if field == 7:
            return bool(v)
    return None


def _geometry(cmds):
    """Decode command stream into a list of parts (lists of (x, y))."""
    parts = []
    current = None
    x = y = 0
    i = 0
    n = len(cmds)
    while i < n:
        cmd = cmds[i] & 7
        count = cmds[i] >> 3
        i += 1
        if cmd == 1:  # MoveTo
            for _ in range(count):
                x += _zigzag(cmds[i])
                y += _zigzag(cmds[i + 1])
                i += 2
                current = [(x, y)]
                parts.append(current)
        elif cmd == 2:  # LineTo
            for _ in range(count):
                x += _zigzag(cmds[i])
                y += _zigzag(cmds[i + 1])
                i += 2
                current.append((x, y))
        elif cmd == 7:  # ClosePath
            if current and current[0] != current[-1]:
                current.append(current[0])
        else:
            raise ValueError(f"bad geometry command {cmd}")
    return parts


def ring_area(ring):
    """Signed area (shoelace). Positive = exterior ring in MVT (y-down) space."""
    a = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        a += x0 * y1 - x1 * y0
    return a / 2.0


def polygons(parts):
    """Group rings into [exterior, hole, hole...] polygons."""
    out = []
    for ring in parts:
        if len(ring) < 4:
            continue
        a = ring_area(ring)
        if a > 0:
            out.append([ring])
        elif a < 0 and out:
            out[-1].append(ring)
    return out


class Feature:
    __slots__ = ("id", "type", "tags", "parts")

    def __init__(self, fid, ftype, tags, parts):
        self.id = fid
        self.type = ftype
        self.tags = tags
        self.parts = parts


class Layer:
    __slots__ = ("name", "extent", "features")

    def __init__(self, name, extent, features):
        self.name = name
        self.extent = extent
        self.features = features


def decode(data, layers=None):
    """Decode a (possibly gzipped) tile into {layer_name: Layer}."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    data = memoryview(data)
    out = {}
    for field, _w, layer_buf in _fields(data):
        if field != 3:
            continue
        name = None
        extent = 4096
        keys, values, raw_features = [], [], []
        for f, _w2, v in _fields(layer_buf):
            if f == 1:
                name = bytes(v).decode()
            elif f == 2:
                raw_features.append(v)
            elif f == 3:
                keys.append(bytes(v).decode())
            elif f == 4:
                values.append(_value(v))
            elif f == 5:
                extent = v
        if layers is not None and name not in layers:
            continue
        features = []
        for fb in raw_features:
            fid, ftype, tags, geom = None, 0, {}, []
            for f, _w3, v in _fields(fb):
                if f == 1:
                    fid = v
                elif f == 2:
                    t = _packed(v)
                    for k in range(0, len(t) - 1, 2):
                        tags[keys[t[k]]] = values[t[k + 1]]
                elif f == 3:
                    ftype = v
                elif f == 4:
                    geom = _packed(v)
            features.append(Feature(fid, ftype, tags, _geometry(geom)))
        out[name] = Layer(name, extent, features)
    return out
