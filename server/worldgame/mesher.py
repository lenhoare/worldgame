"""Turn voxels into face instances for the viewer.

The heavy lifting is done here with numpy so the Godot client needs no
per-voxel loops: for every chunk the server sends a float32 buffer that is
handed straight to a MultiMesh of unit quads (12 floats of transform plus an
RGBA colour per face). Faces are emitted only where a voxel meets air, and
runs of identical faces are merged into one long quad.

Units are voxels: x east, y = layer (up), z south. Colour alpha carries the
voxel material id / 255 so the shader can add per-material detail.
"""

import gzip
import struct

import numpy as np

from . import materials as M
from .world import CHUNK

# (dx, dk, dz), run axis ("x" or "z")
_DIRS = [((1, 0, 0), "z"), ((-1, 0, 0), "z"), ((0, 1, 0), "x"), ((0, -1, 0), "x"),
         ((0, 0, 1), "x"), ((0, 0, -1), "x")]
_LINEAR = None


def _palette():
    global _LINEAR
    if _LINEAR is None:
        t = M.numpy_tables()["colour"].astype(np.float32) / 255.0
        # Godot converts instance colours from sRGB itself, so send them as they are.
        _LINEAR = np.concatenate([t, (np.arange(len(M.VOXELS), dtype=np.float32) / 255.0)[:, None]], axis=1)
    return _LINEAR


def chunk_faces(w, cx, cz):
    """float32 array (n, 16) of face instances for one chunk."""
    x0, z0 = cx * CHUNK, cz * CHUNK
    x1, z1 = min(w.X, x0 + CHUNK), min(w.Z, z0 + CHUNK)
    nx, nz, Y = x1 - x0, z1 - z0, w.Y
    pad = np.zeros((nx + 2, nz + 2, Y + 2), np.uint8)
    pad[:, :, 0] = 255                                         # nothing is drawn underneath the world
    xa, xb = max(0, x0 - 1), min(w.X, x1 + 1)
    za, zb = max(0, z0 - 1), min(w.Z, z1 + 1)
    pad[xa - x0 + 1:xb - x0 + 1, za - z0 + 1:zb - z0 + 1, 1:-1] = w.vox[xa:xb, za:zb, :]
    occ = pad != 0
    core = pad[1:-1, 1:-1, 1:-1]
    solid = occ[1:-1, 1:-1, 1:-1]
    pal = _palette()
    out = []
    for (dx, dk, dz), axis in _DIRS:
        nb = occ[1 + dx:nx + 1 + dx, 1 + dz:nz + 1 + dz, 1 + dk:Y + 1 + dk]
        xi, zi, ki = np.nonzero(solid & ~nb)
        if xi.size == 0:
            continue
        mat = core[xi, zi, ki]
        if axis == "x":
            order = np.lexsort((xi, zi, ki))
            run, a, b = xi[order], zi[order], ki[order]
        else:
            order = np.lexsort((zi, xi, ki))
            run, a, b = zi[order], xi[order], ki[order]
        mat = mat[order]
        start = np.ones(run.size, bool)
        start[1:] = (run[1:] != run[:-1] + 1) | (a[1:] != a[:-1]) | (b[1:] != b[:-1]) | (mat[1:] != mat[:-1])
        idx = np.flatnonzero(start)
        length = np.diff(np.append(idx, run.size)).astype(np.float32)
        r0 = run[idx].astype(np.float32)
        a0 = a[idx].astype(np.float32)
        k = b[idx].astype(np.float32)
        m = mat[idx]
        n = idx.size
        buf = np.zeros((n, 16), np.float32)
        mid = r0 + length / 2.0
        if axis == "x":
            x, z = mid + x0, a0 + z0
        else:
            x, z = a0 + x0, mid + z0
        # rows: [right.x, up.x, normal.x, origin.x, right.y, up.y, normal.y, origin.y, right.z, up.z, normal.z, origin.z]
        if dk == 1:
            buf[:, 0], buf[:, 9], buf[:, 6] = length, -1, 1
            buf[:, 3], buf[:, 7], buf[:, 11] = x, k + 1, z + 0.5
        elif dk == -1:
            buf[:, 0], buf[:, 9], buf[:, 6] = length, 1, -1
            buf[:, 3], buf[:, 7], buf[:, 11] = x, k, z + 0.5
        elif dx == 1:
            buf[:, 8], buf[:, 5], buf[:, 2] = -length, 1, 1
            buf[:, 3], buf[:, 7], buf[:, 11] = x + 1, k + 0.5, z
        elif dx == -1:
            buf[:, 8], buf[:, 5], buf[:, 2] = length, 1, -1
            buf[:, 3], buf[:, 7], buf[:, 11] = x, k + 0.5, z
        elif dz == 1:
            buf[:, 0], buf[:, 5], buf[:, 10] = length, 1, 1
            buf[:, 3], buf[:, 7], buf[:, 11] = x, k + 0.5, z + 1
        else:
            buf[:, 0], buf[:, 5], buf[:, 10] = -length, 1, -1
            buf[:, 3], buf[:, 7], buf[:, 11] = x, k + 0.5, z
        buf[:, 12:16] = pal[m]
        out.append(buf)
    if not out:
        return np.zeros((0, 16), np.float32)
    return np.concatenate(out)


class MeshCache:
    def __init__(self, w):
        self.w = w
        self.cache = {}                 # (cx, cz) -> (rev, bytes)

    def chunk(self, cx, cz):
        rev = int(self.w.chunk_rev[cx, cz])
        hit = self.cache.get((cx, cz))
        if hit and hit[0] == rev:
            return hit[1]
        faces = chunk_faces(self.w, cx, cz)
        data = struct.pack("<HHI", cx, cz, faces.shape[0]) + faces.tobytes()
        self.cache[(cx, cz)] = (rev, data)
        return data

    def since(self, rev, limit=None):
        """gzip blob of every chunk changed after `rev`: count, then records."""
        cxs, czs = np.nonzero(self.w.chunk_rev > rev)
        todo = list(zip(cxs.tolist(), czs.tolist()))
        if limit:
            todo = todo[:limit]
        body = struct.pack("<I", len(todo)) + b"".join(self.chunk(cx, cz) for cx, cz in todo)
        return gzip.compress(body, compresslevel=3)
