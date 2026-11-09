#!/usr/bin/env python3
"""Pack DohaShim + the UEFI image (+ an "XNUP" payload) into a boot image for `fastboot boot`, like the phone's
own: header v2.

  mkdohaimg.py SHIM.bin SILICIUM_UEFI.fd DTB OUT.img [PAYLOAD.bin]

The payload is a complete "XNUP" container (willow-hackios's xnuloader/mkpayload.py); the shim copies it to
0x78000000 (DohaShim.S), where the UEFI's BootManagerLib finds the XNU loader in it.
"""
import gzip
import hashlib
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

FD_SIZE = 0x300000
SHIM_SIZE = 0x1000
PAYLOAD_MAX = 0x04000000        # "XNU Payload" in the memory map
IMAGE_SIZE_AT = 16              # the arm64 Image header's image_size


def main():
    shim, fd = bytearray(Path(sys.argv[1]).read_bytes()), Path(sys.argv[2]).read_bytes()
    dtb, out = sys.argv[3], sys.argv[4]
    payload = Path(sys.argv[5]).read_bytes() if len(sys.argv) == 6 else b''
    if len(shim) != SHIM_SIZE or shim[0x38:0x3c] != b'ARM\x64':
        raise SystemExit(f'{sys.argv[1]}: not the shim ({len(shim):#x} bytes)')
    if len(fd) != FD_SIZE or fd[40:44] != b'_FVH':
        raise SystemExit(f'{sys.argv[2]}: not a {FD_SIZE:#x} byte UEFI image')
    for needle in (b'SWEETXNU', b'XNUP'):
        if needle in shim:
            raise SystemExit(f'unexpected {needle} in the shim')
    if payload:
        size = struct.unpack_from('<I', payload, 4)[0] if len(payload) >= 8 else -1
        if payload[:4] != b'XNUP' or size + 8 > len(payload) or len(payload) > PAYLOAD_MAX - 0x1000:
            raise SystemExit(f'{sys.argv[5]}: not an XNUP container that fits in {PAYLOAD_MAX:#x}')
        # The Image's memory footprint, in 2 MiB units: the shim, the FD and the payload.
        image_size = (SHIM_SIZE + FD_SIZE + len(payload) + 0x1FFFFF) & ~0x1FFFFF
        struct.pack_into('<Q', shim, IMAGE_SIZE_AT, image_size)
        print(f'payload: {len(payload)} bytes, image size {image_size:#x}')
    tool = Path(__file__).resolve().parent.parent / 'tools/mkbootimg_v2.py'
    with tempfile.TemporaryDirectory() as tmp:
        kernel = Path(tmp) / 'kernel'
        kernel.write_bytes(gzip.compress(bytes(shim) + fd + payload, 6))
        subprocess.run([sys.executable, '-I', str(tool), '--kernel', str(kernel), '--dtb', dtb, '-o', out], check=True)
    data = Path(out).read_bytes()
    print(f'{out}: {len(data)} bytes, {data[:8]}, sha256 {hashlib.sha256(data).hexdigest()[:16]}')


if __name__ == '__main__':
    if len(sys.argv) not in (5, 6):
        raise SystemExit(__doc__)
    main()
