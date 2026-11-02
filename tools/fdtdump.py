"""Minimal FDT -> dts-like text dumper (no dtc on this machine). Usage: fdtdump.py IN.dtb OUT.txt"""
import struct, sys

def dump(blob):
    magic, total, off_struct, off_strings, _, ver, _, _, sz_strings, sz_struct = struct.unpack_from('>10I', blob, 0)
    assert magic == 0xd00dfeed, hex(magic)
    strs = blob[off_strings:off_strings + sz_strings]
    out, depth, p, path = [], 0, off_struct, []
    def fmt(name, val):
        if not val:
            return ''
        printable = all(32 <= b < 127 or b == 0 for b in val) and val[-1] == 0 and val[0] != 0 \
            and b'\0\0' not in val
        if printable:
            return ' = ' + ', '.join('"%s"' % s.decode() for s in val[:-1].split(b'\0'))
        if len(val) % 4 == 0:
            return ' = <' + ' '.join('0x%x' % x for x in struct.unpack('>%dI' % (len(val) // 4), val)) + '>'
        return ' = [' + val.hex() + ']'
    while True:
        tok, = struct.unpack_from('>I', blob, p); p += 4
        if tok == 1:
            e = blob.index(b'\0', p); name = blob[p:e].decode(); p = (e + 4) & ~3
            path.append(name)
            out.append('  ' * depth + (name or '/') + ' {   // /' + '/'.join(path[1:]))
            depth += 1
        elif tok == 2:
            depth -= 1; path.pop(); out.append('  ' * depth + '};')
        elif tok == 3:
            ln, no = struct.unpack_from('>II', blob, p); p += 8
            val = blob[p:p + ln]; p = (p + ln + 3) & ~3
            name = strs[no:strs.index(b'\0', no)].decode()
            out.append('  ' * depth + name + fmt(name, val) + ';')
        elif tok == 4:
            continue
        elif tok == 9:
            break
    return out

blob = open(sys.argv[1], 'rb').read()
lines = dump(blob)
open(sys.argv[2], 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print(len(lines), 'lines')
