#!/usr/bin/env python3
"""Write an Android boot image header v2, laid out like doha's stock boot_a
(base 0, kernel 0x8000, ramdisk 0x1000000, tags 0x100, dtb 0x1f00000, page 4096).
Stand-in for AOSP mkbootimg so the build needs no extra packages.

Usage: mkbootimg_v2.py --kernel IMAGE --dtb DTB [--ramdisk FILE] -o OUT
Without --ramdisk an empty gzipped newc cpio is used (ABL dislikes size 0).
"""
import argparse, gzip, hashlib, struct

PAGE = 4096
KERNEL_ADDR, RAMDISK_ADDR, TAGS_ADDR, DTB_ADDR = 0x8000, 0x1000000, 0x100, 0x1f00000
HEADER_SIZE_V2 = 1660


def os_version(ver, patch):
    """AOSP packing: a.b.c in bits 31..11, (year-2000, month) in bits 10..0."""
    a, b, c = (int(x) for x in ver.split('.'))
    y, m = (int(x) for x in patch.split('-')[:2])
    return (a << 25 | b << 18 | c << 11) | ((y - 2000) << 4 | m)


def empty_cpio_gz():
    name = b'TRAILER!!!\0'
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0]
    hdr = b'070701' + b''.join(b'%08x' % f for f in fields) + name
    hdr += b'\0' * (-len(hdr) % 4)
    hdr += b'\0' * (-len(hdr) % 512)
    return gzip.compress(hdr, 9, mtime=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kernel', required=True)
    ap.add_argument('--dtb', required=True)
    ap.add_argument('--ramdisk')
    ap.add_argument('--cmdline', default='console=null')
    # Mirror the running LineageOS boot_a (os_version 0x1e000194)
    ap.add_argument('--os-version', default='15.0.0')
    ap.add_argument('--os-patch-level', default='2025-04')
    ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args()

    kernel = open(a.kernel, 'rb').read()
    dtb = open(a.dtb, 'rb').read()
    ramdisk = open(a.ramdisk, 'rb').read() if a.ramdisk else empty_cpio_gz()
    cmdline = a.cmdline.encode()
    assert len(cmdline) < 512

    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, b'', b'', dtb):	# kernel, ramdisk, second, recovery_dtbo, dtb
        sha.update(blob)
        sha.update(struct.pack('<I', len(blob)))

    hdr = b'ANDROID!'
    hdr += struct.pack('<10I', len(kernel), KERNEL_ADDR, len(ramdisk), RAMDISK_ADDR,
                       0, 0, TAGS_ADDR, PAGE, 2, os_version(a.os_version, a.os_patch_level))
    hdr += b'\0' * 16					# name
    hdr += cmdline.ljust(512, b'\0')
    hdr += sha.digest().ljust(32, b'\0')		# id
    hdr += b'\0' * 1024					# extra_cmdline
    hdr += struct.pack('<IQI', 0, 0, HEADER_SIZE_V2)	# recovery_dtbo size/offset, header_size
    hdr += struct.pack('<IQ', len(dtb), DTB_ADDR)
    assert len(hdr) == HEADER_SIZE_V2

    pad = lambda b: b + b'\0' * (-len(b) % PAGE)
    with open(a.output, 'wb') as f:
        for blob in (hdr, kernel, ramdisk, dtb):
            f.write(pad(blob))
    print(f'{a.output}: kernel {len(kernel)}, ramdisk {len(ramdisk)}, dtb {len(dtb)} bytes')


if __name__ == '__main__':
    main()
