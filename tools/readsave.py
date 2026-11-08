#!/usr/bin/env python3
"""Read back what uefi/DohaSaveDxe wrote to system_b, 128 MiB into it, and make a PNG of the screen.

  readsave.py OUT_DIR [ADB]            from Android, over adb (root)
  readsave.py OUT_DIR --file PATH      from a copy of that area

Reads only. Prints the header and the last text lines of the log buffer; writes OUT_DIR/screen.png and OUT_DIR/save.bin.
"""
import struct
import subprocess
import sys
import zlib
from pathlib import Path

MAGIC = 0x314B534441484F44    # "DOHADSK1"
SAVE_SECTOR = 262144          # 128 MiB into system_b
SAVE_SECTORS = 19303          # header, framebuffer padded to a sector, log buffer
READ = f'dd if=/dev/block/by-name/system_b bs=512 skip={SAVE_SECTOR} count={SAVE_SECTORS} 2>/dev/null'


def png(path, width, height, stride, data):
    rows = bytearray()
    for y in range(height):
        row = data[y * stride:y * stride + width * 4]
        rows.append(0)
        for x in range(0, len(row), 4):        # a8r8g8b8 little-endian: B G R A in memory
            rows += bytes((row[x + 2], row[x + 1], row[x]))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(bytes(rows), 6)) + chunk(b'IEND', b''))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 3 and sys.argv[2] == '--file':
        blob = Path(sys.argv[3]).read_bytes()
    else:
        adb = sys.argv[2] if len(sys.argv) > 2 else 'adb'
        blob = subprocess.run([adb, 'exec-out', READ], capture_output=True, timeout=300).stdout
    if len(blob) < 512:
        raise SystemExit(f'nothing read ({len(blob)} bytes): is adb root on?')
    magic, seconds, count, fb_size, log_size, width, height, stride, stamp = struct.unpack_from('<9Q', blob)
    if magic != MAGIC:
        raise SystemExit(f'not a save (magic {magic:#x})')
    print(f'seconds {seconds}  writes {count}  screen {width}x{height} stride {stride}  stamp {stamp:#x}  size {len(blob)}')
    fb_padded = (fb_size + 511) // 512 * 512
    if len(blob) < 512 + fb_padded + log_size:
        raise SystemExit('the file is shorter than its header says')
    (out / 'save.bin').write_bytes(blob)
    png(out / 'screen.png', width, height, stride, blob[512:512 + fb_size])
    log = blob[512 + fb_padded:512 + fb_padded + log_size]
    text = [l.decode('latin1') for l in log.replace(b'\r', b'\n').split(b'\n') if len(l) >= 4 and all(32 <= c < 127 for c in l)]
    print(f'log buffer: {len(text)} lines, last ones:')
    for line in text[-12:]:
        print('  ', line)
    print('wrote', out / 'screen.png')


if __name__ == '__main__':
    main()
