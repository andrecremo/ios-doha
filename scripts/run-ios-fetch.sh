# iOS 16.5 for the doha: willow-hackios's userland in the doha tree, and the parts of the iOS 16.5 IPSW it needs,
# fetched from Apple's CDN and extracted on this machine (ios165/fetch.sh). Nothing goes to the phone, nothing to git.
# Needs once: sudo apt install -y 7zip      (7-Zip 23 or newer: it reads APFS)
# About 7.4 GB downloaded, 8 GB of disk while it runs, 5.3 GB afterwards. Run it again after a failure: it goes on.
set -e
W=~/doha-xnu/willow-doha
cd $W
grep -q platform_doha xnuloader/loader.c || { echo "the doha patch is not in $W"; exit 1; }
command -v 7z >/dev/null || { echo "missing: 7z (sudo apt install -y 7zip)"; exit 1; }
v=$(7z 2>&1 | grep -m1 -oE '[0-9]+\.[0-9]+' || true)
[ "${v%%.*}" -ge 23 ] 2>/dev/null || { echo "7z $v is too old: 23 or newer reads APFS (sudo apt install -y 7zip)"; exit 1; }
[ -d xnu-deps/build/lzbitmap ] || { echo "missing: xnu-deps/build/lzbitmap (run run-doha-kernel.sh first)"; exit 1; }

echo "== willow-hackios's userland, into this tree (its own git dir, .userland.git), at 0ffde01"
if [ ! -d .userland.git ]; then
	USERLAND_URL=$HOME/doha-xnu/refs/willow USERLAND_REF=userland bash common/setup.sh | grep -E '^setup: (cloning|hackios)'
fi
U=$(git --git-dir=.userland.git --work-tree=. log -1 --format=%h)
[ "$U" = 0ffde01 ] || { echo "the userland is at $U, not 0ffde01"; exit 1; }
[ -f ios165/fetch.sh ] && [ -f userland/build.sh ] || { echo "the userland files are not in $W"; exit 1; }

echo "== iOS 16.5 (20F66) from updates.cdn-apple.com"
cd ios165
bash fetch.sh
du -sh rootfs cryptex cryptex-app 20F66__iPhone10,3_6
echo "fetch=ok"
