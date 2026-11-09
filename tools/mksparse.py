"""Raw image -> Android sparse image (format 1.0, blocks of 4096): runs of zero blocks become FILL chunks of
zeros (written as zeros on the phone, so nothing of the partition's old contents is left in the image's range),
everything else RAW chunks of at most 16 MiB. Then reads the sparse file back and checks that it expands to
the raw image's exact bytes (sha256).

usage: mksparse.py RAW OUT
"""
import hashlib
import struct
import sys

BS = 4096
MAX_RAW = 4096          # blocks per RAW chunk (16 MiB)
ZERO = bytes(BS)

src, dst = sys.argv[1], sys.argv[2]
chunks = []             # (type, blocks, offset in raw)


def scan():
    blk = 0
    run_type, run_start, run_len = None, 0, 0
    with open(src, 'rb') as f:
        while True:
            buf = f.read(BS * 1024)
            if not buf:
                break
            if len(buf) % BS:
                raise SystemExit('the raw image is not a whole number of 4096-byte blocks')
            for i in range(0, len(buf), BS):
                t = 'fill' if buf[i:i + BS] == ZERO else 'raw'
                if t == run_type and not (t == 'raw' and run_len == MAX_RAW):
                    run_len += 1
                else:
                    if run_type:
                        chunks.append((run_type, run_len, run_start))
                    run_type, run_start, run_len = t, blk, 1
                blk += 1
    chunks.append((run_type, run_len, run_start))
    return blk


total = scan()
with open(src, 'rb') as f, open(dst, 'wb') as out:
    out.write(struct.pack('<IHHHHIIII', 0xED26FF3A, 1, 0, 28, 12, BS, total, len(chunks), 0))
    for t, n, start in chunks:
        if t == 'fill':
            out.write(struct.pack('<HHII', 0xCAC2, 0, n, 12 + 4))
            out.write(b'\0\0\0\0')
        else:
            out.write(struct.pack('<HHII', 0xCAC1, 0, n, 12 + n * BS))
            f.seek(start * BS)
            out.write(f.read(n * BS))

# check: expand the sparse file and compare with the raw image
h_raw, h_sp = hashlib.sha256(), hashlib.sha256()
with open(src, 'rb') as f:
    while b := f.read(1 << 24):
        h_raw.update(b)
with open(dst, 'rb') as s:
    magic, _, _, fh, ch, bs, tb, tc, _ = struct.unpack('<IHHHHIIII', s.read(28))
    assert magic == 0xED26FF3A and bs == BS and tb == total and tc == len(chunks)
    for _ in range(tc):
        ctype, _, n, size = struct.unpack('<HHII', s.read(12))
        if ctype == 0xCAC1:
            left = n * BS
            while left:
                b = s.read(min(left, 1 << 24))
                h_sp.update(b)
                left -= len(b)
        elif ctype == 0xCAC2:
            fill = s.read(4) * (BS // 4)
            for _ in range(n):
                h_sp.update(fill)
        else:
            raise SystemExit(f'unexpected chunk type {ctype:x}')
fills = sum(n for t, n, _ in chunks if t == 'fill')
print(f'{total} blocks, {len(chunks)} chunks, {fills} zero blocks as FILL')
print('raw   ', h_raw.hexdigest())
print('sparse', h_sp.hexdigest())
print('check=' + ('ok' if h_raw.digest() == h_sp.digest() else 'MISMATCH'))
