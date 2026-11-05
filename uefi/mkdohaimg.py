#!/usr/bin/env python3
"""Pack DohaShim + the UEFI image into a boot image for `fastboot boot`, like the phone's own: header v2.

  mkdohaimg.py SHIM.bin SILICIUM_UEFI.fd DTB OUT.img
"""
import gzip
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

FD_SIZE = 0x300000
SHIM_SIZE = 0x1000


def main():
    shim, fd = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes()
    dtb, out = sys.argv[3], sys.argv[4]
    if len(shim) != SHIM_SIZE or shim[0x38:0x3c] != b'ARM\x64':
        raise SystemExit(f'{sys.argv[1]}: not the shim ({len(shim):#x} bytes)')
    if len(fd) != FD_SIZE or fd[40:44] != b'_FVH':
        raise SystemExit(f'{sys.argv[2]}: not a {FD_SIZE:#x} byte UEFI image')
    for needle in (b'SWEETXNU', b'XNUP'):
        if needle in shim:
            raise SystemExit(f'unexpected {needle} in the shim')
    tool = Path(__file__).resolve().parent.parent / 'tools/mkbootimg_v2.py'
    with tempfile.TemporaryDirectory() as tmp:
        kernel = Path(tmp) / 'kernel'
        kernel.write_bytes(gzip.compress(shim + fd, 6))
        subprocess.run([sys.executable, '-I', str(tool), '--kernel', str(kernel), '--dtb', dtb, '-o', out], check=True)
    data = Path(out).read_bytes()
    print(f'{out}: {len(data)} bytes, {data[:8]}, sha256 {hashlib.sha256(data).hexdigest()[:16]}')


if __name__ == '__main__':
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    main()
