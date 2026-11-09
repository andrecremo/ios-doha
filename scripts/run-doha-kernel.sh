# willow-hackios's XNU 8796.121.2 with the doha patch, built in WSL. Run it again at any time: what is there is kept.
# Needs once: theos in ~/theos with its Linux toolchain and sdks/iPhoneOS16.5.sdk (https://theos.dev/docs/installation-linux),
# and: sudo apt install -y autoconf automake
set -e
W=~/doha-xnu/willow-doha
cd $W
grep -q platform_doha xnuloader/loader.c || { echo "the doha patch is not in $W"; exit 1; }
for t in git curl make clang lld-link flex bison m4 perl autoconf automake; do
	command -v $t >/dev/null || { echo "missing: $t (see the apt line at the top)"; exit 1; }
done
THEOS=${THEOS:-$HOME/theos}
[ -d $THEOS/toolchain/linux/iphone/bin ] || { echo "missing: theos's Linux toolchain in $THEOS/toolchain/linux/iphone"; exit 1; }
[ -d $THEOS/sdks/iPhoneOS16.5.sdk/usr/include ] || { echo "missing: $THEOS/sdks/iPhoneOS16.5.sdk"; exit 1; }
echo "== stage 1: sources, host tools, the SDK"
bash xnu-deps/setup.sh --stage1
echo "== the kernel tree: Apple's xnu-8796.121.2 + willow-hackios + doha"
[ -d xnu-src/xnu-8796.121.2 ] || bash xnu/apply.sh
# apply.sh copies xnu/files/ only when it makes the tree: later changes to those files (the doha patch) go over by hand
cp -a xnu/files/. xnu-src/xnu-8796.121.2/
grep -q 'Spurious GIC interrupt: 0x13' xnu-src/xnu-8796.121.2/osfmk/arm64/gic_v3_irq.c || { echo "the kernel tree lacks the timer fix"; exit 1; }
grep -q '"doha"' xnu-src/xnu-8796.121.2/bsd/dev/redwood_buttons.c || { echo "the kernel tree has no doha: it was made before the patch"; exit 1; }
# a file the doha patch adds (the FT8719 touch screen) goes into the build's list too, which apply.sh wrote once
T=xnu-src/xnu-8796.121.2
grep -q '^bsd/dev/redwood_focaltech.c' $T/bsd/conf/files ||
	sed -i 's|^bsd/dev/redwood_novatek.c\tstandard$|&\nbsd/dev/redwood_focaltech.c\tstandard|' $T/bsd/conf/files
grep -q '^bsd/dev/redwood_focaltech.c' $T/bsd/conf/files || { echo "bsd/conf/files has no redwood_focaltech.c"; exit 1; }
echo "== stage 2: the libraries built against the kernel's headers"
bash xnu-deps/setup.sh --stage2
echo "== the kernel"
# -k is required (xnu/README.md): the export check fails after the kernel is linked, and make exits with 2 anyway.
# What counts is the kernel file and its date, not make's status.
set +e
START=$(date +%s)
WIFI_ATH11K=0 bash ./xnu-build.sh -j$(nproc) -k > ~/doha-xnu/kernel-build.log 2>&1
echo "make exit=$? (2 is normal)"
grep -E ' error:' ~/doha-xnu/kernel-build.log | head -5
K=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
# make relinks only what changed: the kernel has to be newer than every source it is made of, not than this run.
NEWER=$(find xnu-src/xnu-8796.121.2/bsd xnu-src/xnu-8796.121.2/osfmk xnu-src/xnu-8796.121.2/iokit -newer $K -name '*.[ch]' 2>/dev/null | head -3)
ls -l --time-style=long-iso $K 2>&1
if [ -f $K ] && [ -z "$NEWER" ]; then
	echo "kernel=ok (newer than its sources)"
else
	echo "kernel=STALE or missing; sources newer than it: $NEWER"
fi
