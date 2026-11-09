"""The doha's changes to willow-hackios's userland (branch userland, 0ffde01), each made once, idempotent.

  doha_userland_edit.py TREE
"""
import sys
from pathlib import Path

tree = Path(sys.argv[1])
p = tree / 'userland/build.sh'
t = p.open(encoding='utf-8', newline='').read()
old = """if [ -f ../fw-touch/novatek_ts_fw.bin ]; then
	mkdir -p root/fw
	install -m 0644 ../fw-touch/novatek_ts_fw.bin root/fw/
fi
"""
new = old + """# ... and doha's (Moto G8 Plus): the FocalTech FT8719 has no flash either, and its firmware is the phone's
# /vendor/firmware/focaltech-ft8719-a0-0000-doha.bin, into ../fw-touch as focaltech_ts_fw.bin
# (bsd/dev/redwood_focaltech.c; 64 KB, FocalTech's and not in the repository)
if [ -f ../fw-touch/focaltech_ts_fw.bin ]; then
	mkdir -p root/fw
	install -m 0644 ../fw-touch/focaltech_ts_fw.bin root/fw/
fi
"""
# the store of /private/var on doha: userdata past the iOS volume (src/var_store.c), after willow's, which have
# no userdata of that kind (/dev/rufs_system does not exist on doha, whose system is system_a and system_b)
vs = tree / 'userland/src/var_store.c'
v = vs.open(encoding='utf-8', newline='').read()
vold = """	{ "darwin", 0x80000000LL },
	{ "system", 0x40000000LL },
};"""
vnew = """	{ "darwin", 0x80000000LL },
	{ "system", 0x40000000LL },
	/* doha (Moto G8 Plus): userdata, 50 GiB, with the same image in its first 8365539328 bytes */
	{ "userdata", 0x80000000LL },
};"""
if '"userdata", 0x80000000LL' in v:
    print("userland/src/var_store.c: has doha's store already")
elif v.count(vold) != 1:
    raise SystemExit(f'userland/src/var_store.c: expected 1x the STORES table, found {v.count(vold)}')
else:
    vs.open('w', encoding='utf-8', newline='').write(v.replace(vold, vnew))
    print("ok userland/src/var_store.c: doha's store, userdata")

if 'focaltech_ts_fw.bin' in t:
    print('userland/build.sh: has the FT8719 firmware already')
elif t.count(old) != 1:
    raise SystemExit(f'userland/build.sh: expected 1x the Novatek firmware block, found {t.count(old)}')
else:
    p.open('w', encoding='utf-8', newline='').write(t.replace(old, new))
    print('ok userland/build.sh: the FT8719 firmware into fw/')
