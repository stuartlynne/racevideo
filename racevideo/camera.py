"""Linux V4L2 control discovery and verified writes, without shell utilities.

Uses the Linux UAPI from linux/videodev2.h. The recorder owns this handle;
neither Tk nor the review reader talks directly to camera hardware.
"""
from __future__ import annotations

import ctypes as C
import errno
import fcntl
import os
import sys
from pathlib import Path


class Query(C.Structure):
    _fields_ = [("id", C.c_uint32), ("type", C.c_uint32), ("name", C.c_char * 32),
                ("minimum", C.c_int32), ("maximum", C.c_int32), ("step", C.c_int32),
                ("default_value", C.c_int32), ("flags", C.c_uint32),
                ("reserved", C.c_uint32 * 2)]


class Menu(C.Structure):
    _pack_ = 1
    _fields_ = [("id", C.c_uint32), ("index", C.c_uint32), ("data", C.c_ubyte * 32),
                ("reserved", C.c_uint32)]


class Value(C.Structure):
    _fields_ = [("id", C.c_uint32), ("value", C.c_int32)]


class Capability(C.Structure):
    _fields_=[('driver',C.c_char*16),('card',C.c_char*32),('bus',C.c_char*32),
              ('version',C.c_uint32),('capabilities',C.c_uint32),('device_caps',C.c_uint32),('reserved',C.c_uint32*3)]


def request(number, structure):
    # _IOWR on Linux x86/ARM (the supported deployment architectures).
    return (3 << 30) | (C.sizeof(structure) << 16) | (ord("V") << 8) | number


QUERY = request(36, Query)
QUERY_MENU = request(37, Menu)
GET = request(27, Value)
SET = request(28, Value)
NEXT = 0x80000000
EXPOSURE = 0x009A0902


def call(fd, operation, value):
    data = bytearray(bytes(value))
    fcntl.ioctl(fd, operation, data, True)
    C.memmove(C.addressof(value), bytes(data), len(data))
    return value


def format_value(control_id, value):
    if value is None:
        return "not readable"
    if control_id == EXPOSURE and value > 0:
        return f"{value / 10:g} ms · 1/{10000 / value:.0f}s"
    return str(value)


def list_devices():
    aliases=list(Path('/dev/v4l/by-id').glob('*'))
    result=[]
    for path in sorted(Path('/dev').glob('video[0-9]*')):
        item=dict(device=str(path),aliases=[str(a) for a in aliases if a.resolve()==path.resolve()])
        fd=None
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
            cap=call(fd,(2<<30)|(C.sizeof(Capability)<<16)|(ord('V')<<8),Capability())
            flags=cap.device_caps if cap.capabilities & 0x80000000 else cap.capabilities
            item.update(driver=bytes(cap.driver).decode(errors='replace'),name=bytes(cap.card).decode(errors='replace'),
                        bus=bytes(cap.bus).decode(errors='replace'),capture=bool(flags & (1|0x1000)))
        except OSError as exc:item['error']=str(exc)
        finally:
            if fd is not None:os.close(fd)
        result.append(item)
    return result


class CameraControls:
    def __init__(self, device):
        self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)

    def close(self):
        os.close(self.fd)

    def describe(self, control_id):
        q = call(self.fd, QUERY, Query(id=control_id))
        control = dict(id=q.id, type=q.type, name=bytes(q.name).decode(errors="replace"),
                       minimum=q.minimum, maximum=q.maximum, step=max(1, q.step),
                       default=q.default_value, flags=q.flags, value=None, choices=[])
        reasons = []
        for flag, message in ((1, "disabled by driver"), (2, "busy"), (4, "read only"),
                              (16, "inactive — change automatic mode first")):
            if q.flags & flag:
                reasons.append(message)
        if q.type not in (1, 2, 3, 4, 9):
            reasons.append("control type not supported by this panel")
        control["writable"] = not reasons
        control["disabled_reason"] = "; ".join(reasons)
        if q.type in (3, 9):
            # Drivers may leave holes in a menu. Only show valid entries.
            for index in range(q.minimum, min(q.maximum, q.minimum + 1023) + 1):
                try:
                    m = call(self.fd, QUERY_MENU, Menu(id=q.id, index=index))
                except OSError as exc:
                    if exc.errno == errno.EINVAL:
                        continue
                    raise
                data = bytes(m.data)
                label = (str(int.from_bytes(data[:8], sys.byteorder, signed=True)) if q.type == 9
                         else data.split(b"\0", 1)[0].decode(errors="replace"))
                control["choices"].append(dict(value=index, label=label))
        if q.type in (1, 2, 3, 9) and not q.flags & 0x40:
            try:
                control["value"] = call(self.fd, GET, Value(id=q.id)).value
            except OSError as exc:
                control["read_error"] = str(exc)
        control["display_value"] = format_value(q.id, control["value"])
        return control

    def enumerate(self):
        controls, previous = [], 0
        for _ in range(512):
            try:
                q = call(self.fd, QUERY, Query(id=previous | NEXT))
            except OSError as exc:
                if exc.errno == errno.EINVAL:
                    break
                raise
            if q.id <= previous:
                raise RuntimeError("Camera returned a non-increasing control ID")
            previous = q.id
            if q.type != 6:  # Class headings are not adjustable controls.
                controls.append(self.describe(q.id))
        return controls

    def set(self, control_id, value):
        control = self.describe(control_id)
        if not control["writable"]:
            raise ValueError(control["disabled_reason"])
        if not isinstance(value, int):
            raise ValueError("Camera values must be integers")
        if control["type"] in (3, 9):
            if value not in {c["value"] for c in control["choices"]}:
                raise ValueError("Unsupported menu choice")
        elif control["type"] != 4:
            if not control["minimum"] <= value <= control["maximum"]:
                raise ValueError("Value outside camera's supported range")
            if (value - control["minimum"]) % control["step"]:
                raise ValueError("Value does not match camera's supported step")
        call(self.fd, SET, Value(id=control_id, value=value))
        return self.describe(control_id)["value"]
