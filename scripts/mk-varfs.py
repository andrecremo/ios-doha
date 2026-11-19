#!/usr/bin/env python3
"""The pack the init makes doha's data volume from (run-ios-flash.sh VARDISK=1).

  mk-varfs.py OUT.pack [WORKDIR]

/private/var on the flash lives in userdata from byte 12 GiB to its end (the kernel's /dev/ufs_var: past the iOS
volume, the cryptexes and var_store's two slots). This makes a new, empty HFS+ volume of exactly that size -- case
sensitive, journaled, as iOS's data volume is -- as a sparse file (mkfs.hfsplus, from hfsprogs), and packs what the
init has to write for it: every run mkfs wrote, as zeros where it wrote zeros (the flash there still holds what Android
left, which a new volume must not read as its catalog) and as data where it wrote data -- some 150 MB of zeros and
50 KB of data for 37.7 GiB. The init writes the pack once, when there is no HFS+ signature at the volume's byte 1024.

Pack, little endian: "DOHAVAR1", u64 volume bytes, u32 records, u32 0; then per record u64 offset (in the volume),
u32 length, u32 kind (0 zeros, 1 data, followed by its bytes). Offsets and lengths are multiples of 512.
"""
import os
import struct
import subprocess
import sys

USERDATA = 104218591 * 512              # doha's userdata, mmcblk0p80 (bsd/dev/redwood_ufs.c, ufs_stores)
VAR_AT = 12 << 30                       # UFS_VAR_AT there, VAR_DISK_AT in the init
VOLUME = USERDATA - VAR_AT              # 40475016704
DATA_MAX = 1 << 16                      # the init reads a data record into a buffer of this size

out = sys.argv[1]
work = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(out))
image = os.path.join(work, 'var.hfs')
os.makedirs(work, exist_ok=True)
if os.path.exists(image):
    os.unlink(image)
with open(image, 'wb') as f:
    f.truncate(VOLUME)
subprocess.run(['mkfs.hfsplus', '-s', '-J', '-v', 'Data', image], check=True)

fd = os.open(image, os.O_RDONLY)
runs, pos = [], 0
while pos < VOLUME:
    try:
        start = os.lseek(fd, pos, os.SEEK_DATA)
    except OSError:
        break
    end = os.lseek(fd, start, os.SEEK_HOLE)
    start -= start % 512
    end += (-end) % 512
    runs.append((start, min(end, VOLUME)))
    pos = end

records = []
for start, end in runs:
    at = start
    while at < end:
        # 4096 at a time where the run allows (the last run, the alternate header, is 512-aligned only)
        step = 4096 if at % 4096 == 0 and end - at >= 4096 else 512
        block = os.pread(fd, step, at)
        kind = 1 if block.strip(b'\0') else 0
        if records and records[-1][2] == kind and records[-1][0] + records[-1][1] == at and \
                (kind == 0 or records[-1][1] + step <= DATA_MAX):
            records[-1][1] += step
        else:
            records.append([at, step, kind])
        at += step

with open(out, 'wb') as f:
    f.write(b'DOHAVAR1' + struct.pack('<QII', VOLUME, len(records), 0))
    for offset, length, kind in records:
        f.write(struct.pack('<QII', offset, length, kind))
        if kind == 1:
            f.write(os.pread(fd, length, offset))
header = os.pread(fd, 512, 1024)
zeros = sum(r[1] for r in records if r[2] == 0)
data = sum(r[1] for r in records if r[2] == 1)
print('mk-varfs: %s: volume %d bytes (signature %r, block size %d), %d records: %d MB of zeros, %d KB of data; pack %d bytes'
      % (out, VOLUME, header[:2], int.from_bytes(header[40:44], 'big'), len(records), zeros >> 20, data >> 10,
         os.path.getsize(out)))
