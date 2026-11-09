# iOS 16.5 off the doha's flash, willow-hackios's flash recipe with userdata in the place of willow's system:
#
#   1. the image for userdata (F:\doha-ios\ios-userdata.img, 8365539328 bytes): Apple's root volume (rootfs.dmg,
#      a UDIF image, unpacked by tools/apfs/dmg.py to the raw APFS container, 5628755968 bytes), then Apple's OS
#      cryptex (2726297600) and App cryptex (10485760) as they are -- containers 0, 1 and 2 of /dev/ufs_userdata,
#      which init mounts as the root and as ",c=1" and ",c=2" (src/init.c, flash_root)
#   2. the RAM part of the boot: root.apfs (the small image) and flashboot.apfs (the boot volume, ~20 MB),
#      FLASHBOOT=1 CRYPTEXES=flash; RC_JOBS=rc.jobs.unlock (nothing touches the screen yet); SHARE=1 (no secrets)
#   3. the UEFI image (C:\Users\andre\doha-uefi-DEBUG-xnu.img): loader, kernel, both images, and
#      the command line below (GL=1: the GPU). No ufs_write, no var_disk: nothing writes.
#
# userdata already holds the image (written 2026-11-09 from Lineage's recovery: Motorola's bootloader refuses
# `fastboot flash userdata`), and boot_a and boot_b hold this UEFI, so that Android never runs: its fstab has
# userdata "formattable" and it would format it. A new build: fastboot boot it, or flash it to boot_a and boot_b.
#
# Nothing goes to the phone here. Booting the image before userdata is written is safe: the mount of the iOS
# volume fails (userdata is still Android's f2fs) and everything before it runs. About 7.4 GB to download.
set -e
W=~/doha-xnu/willow-doha                        # willow-hackios with the doha patch (scripts/regen-patch.sh)
R=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
# DOHA_FILES: the phone's own files (vendor-firmware/, modem-image/) and the 8.4 GB image, kept out of the repository
# (F:\doha-ios on the machine this was made on)
F=${DOHA_FILES:-/mnt/f/doha-ios}
OUT=$F
K=$W/xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
cd $W
grep -q platform_doha xnuloader/loader.c || { echo "the doha patch is not in $W"; exit 1; }
strings $K | grep -q 'GPIO9 of the PM6125' || { echo "$K has no doha: run run-doha-kernel.sh"; exit 1; }
[ -f ios165/.done-rootfs ] && [ -f ios165/cryptex-app.dmg ] || { echo "run run-ios-fetch.sh first"; exit 1; }
[ -d "$(dirname "$F")" ] || { echo "$(dirname "$F") is not there (DOHA_FILES)"; exit 1; }
mkdir -p $OUT

echo "== 1. the image for userdata"
cd ios165
size() { stat -c %s "$1" 2>/dev/null || echo 0; }
if [ "$(size $OUT/ios-userdata.img)" != 8365539328 ]; then
	if [ "$(size rootfs.apfs)" != 5628755968 ]; then
		[ "$(size rootfs.dmg)" = 4728546953 ] || python3 fetch-from-ipsw.py 096-04088-077.dmg rootfs.dmg
		echo "unpacking rootfs.dmg (UDIF) to the raw APFS container: this takes a while"
		# its chunks are LZFSE: the python module lzfse, in a venv of its own (Ubuntu's python has no pip)
		[ -x ~/doha-xnu/venv/bin/python ] || python3 -m venv ~/doha-xnu/venv
		~/doha-xnu/venv/bin/python -c 'import lzfse' 2>/dev/null || ~/doha-xnu/venv/bin/pip install -q --only-binary=:all: lzfse
		~/doha-xnu/venv/bin/python ../tools/apfs/dmg.py extract rootfs.dmg rootfs.apfs.part --apfs
		mv rootfs.apfs.part rootfs.apfs
	fi
	[ "$(size rootfs.apfs)" = 5628755968 ] || { echo "rootfs.apfs is $(size rootfs.apfs) bytes, not 5628755968"; exit 1; }
	rm -f rootfs.dmg
	[ "$(size cryptex-os.dmg)" = 2726297600 ] || python3 fetch-from-ipsw.py 096-04666-078.dmg cryptex-os.dmg
	[ "$(size cryptex-os.dmg)" = 2726297600 ] || { echo "cryptex-os.dmg is not 2726297600 bytes"; exit 1; }
	[ "$(size cryptex-app.dmg)" = 10485760 ] || { echo "cryptex-app.dmg is not 10485760 bytes"; exit 1; }
	# the first block of each must be an APFS container superblock ("NXSB" at byte 32)
	for f in rootfs.apfs cryptex-os.dmg cryptex-app.dmg; do
		[ "$(dd if=$f bs=1 skip=32 count=4 2>/dev/null)" = NXSB ] || { echo "$f is not a raw APFS container"; exit 1; }
	done
	echo "writing $OUT/ios-userdata.img (8.4 GB)"
	cat rootfs.apfs cryptex-os.dmg cryptex-app.dmg > $OUT/ios-userdata.img.part
	mv $OUT/ios-userdata.img.part $OUT/ios-userdata.img
	sha256sum rootfs.apfs cryptex-os.dmg cryptex-app.dmg > $OUT/parts.sha256
	sha256sum $OUT/ios-userdata.img | sed "s|$OUT/||" > $OUT/ios-userdata.sha256
fi
ls -l $OUT/ios-userdata.img; cat $OUT/ios-userdata.sha256
cd $W

echo "== 2. the RAM part of the boot"
# the touch screen's firmware (the phone's /vendor/firmware, copied to F:\doha-ios\vendor-firmware), into fw/ of the
# small image, where bsd/dev/redwood_focaltech.c reads it
FTFW=$F/vendor-firmware/focaltech-ft8719-a0-0000-doha.bin
python3 $R/scripts/doha_userland_edit.py $W
# ... and the GPU's (redwood_a610.c): the zap shader from the phone's modem partition (F:\doha-ios\modem-image) and the
# command processor's microcode from its /vendor/firmware, into fw-a610/, which userland/build.sh puts in fw/
if [ -f $F/modem-image/a610_zap.mdt ] && [ -f $F/vendor-firmware/a630_sqe.fw ]; then
	mkdir -p $W/fw-a610
	cp $F/modem-image/a610_zap.mdt $F/modem-image/a610_zap.b0[0-9] \
		$F/vendor-firmware/a630_sqe.fw $W/fw-a610/
	echo "GPU firmware: $(ls $W/fw-a610 | tr '\n' ' ')"
fi
if [ -f $FTFW ]; then
	mkdir -p $W/fw-touch
	cp $FTFW $W/fw-touch/focaltech_ts_fw.bin
	echo "touch firmware: $(sha256sum $W/fw-touch/focaltech_ts_fw.bin | cut -c1-16) ($(stat -c %s $FTFW) bytes)"
fi
# GL=1: Mesa's build wants meson 1.4 or newer (Ubuntu 24.04 has 1.3) and ninja: both from pip in ~/doha-xnu/venv
if [ "${GL:-0}" = 1 ]; then
	[ -x ~/doha-xnu/venv/bin/meson ] || ~/doha-xnu/venv/bin/pip install -q "meson==1.6.1" ninja
	export PATH=$HOME/doha-xnu/venv/bin:$PATH GL=1
	echo "GL=1: Mesa with meson $(meson --version); its first build takes a while (log: ~/doha-xnu/ios-flash-build.log)"
fi
FLASHBOOT=1 CRYPTEXES=flash REST=1 RC_JOBS=rc.jobs.unlock SHARE=1 bash userland/build.sh > ~/doha-xnu/ios-flash-build.log 2>&1 ||
	{ tail -n 20 ~/doha-xnu/ios-flash-build.log; echo "build.sh failed: see ~/doha-xnu/ios-flash-build.log"; exit 1; }
grep -E 'flashboot.apfs|root.apfs:' ~/doha-xnu/ios-flash-build.log | tail -3
ls -l userland/root.apfs userland/flashboot.apfs

echo "== 3. the UEFI image"
# the payload at 0x78000000, where doha's UEFI (uefi/DohaShim.S) puts it: the RAM above 0x80000000 is the kernel's whole
PAYLOAD_BASE=0x78000000 LOADER_BASE=0x61000000 bash xnuloader/build.sh
# VERBOSE=1: the kernel's console on the screen (-v), over iOS's own picture. epoch=: the clock, from this
# machine at build time (as willow's iosimg.sh), or iOS starts on 31 December 1969
# CPUS=N: how many cores the kernel takes (8: all, as willow's iosimg.sh; 1: the first doha runs). The kernel
# starts on core 3 (Silver) in either case, and core 0 stays the loader's, which serves the storage
# OSM=1 (default): osm=1, the Silver cluster at 1804 MHz, a row of the table doha's firmware wrote (the loader
# checks the cluster's OSM is on and the row sane); without it Silver runs at ~650 MHz. OSM=0: left out
OSMARG=; [ "${OSM:-1}" = 1 ] && OSMARG=" osm=1"
# TOUCH=1 (default): touchscreen=1, the FT8719 driver (bsd/dev/redwood_focaltech.c, device=doha); TOUCH=0: left out
TOUCHARG=; [ "${TOUCH:-1}" = 1 ] && TOUCHARG=" touchscreen=1"
# HUD=1: fb_hud=1, a line for each part of the phone (the drivers' redwood_status()) drawn over the picture
# GPU=1: gpu=1, the Adreno 610 started and kept for the system (redwood_a610.c; the RPM's buses first, the zap shader,
# 745 MHz); FBGPU=1 too: fb_gpu=1, frames onto the panel by the GPU's 2D engine (with a GL=1 small image)
GPUARG=; [ "${GPU:-0}" = 1 ] && GPUARG=" gpu=1"; [ "${FBGPU:-0}" = 1 ] && GPUARG="$GPUARG fb_gpu=1"
# GL=1: the small image with Mesa (userland/build.sh builds it with tools/mk-mesa.sh the first time, a long while),
# and the system drawing on the GPU: gpu=1 fb_gpu=1, frames of the panel's own size (willow's iosimg.sh line)
# glasync=1 (the GL flush without waiting for the frame, willow's) too, GLASYNC=0 leaves it out: the App Library went
# from up to 1231 ms a frame to 37 ms with it (willow's SIGBUS with it was with /var on the disk; here /var is in RAM)
[ "${GL:-0}" = 1 ] && GPUARG=" gpu=1 fb_gpu=1 fbwidth=1080 fbheight=2280 sb_statusbar=1"
[ "${GL:-0}" = 1 ] && [ "${GLASYNC:-1}" = 1 ] && GPUARG="$GPUARG glasync=1"
# CPUMASK=M: the cores by mask instead of cpus=. The bits are positions in the loader's list, the boot core first
# (bit 0, which must be set: the kernel panics without it), then by distance from it: 3, 4, 2, 5, 1, 6, 7 (core 0 is
# the loader's). 0x15: the Silver cores 3, 2, 1 alone, without the Gold ones the firmware leaves at 300 MHz.
# MEMMAP=1: memmap=1, the loader shows the UEFI's memory map for 20 s before the kernel
# The default is 0x15: smoother than all 8 cores with the Gold ones at 300 MHz (2026-11-09). CPUS=N: cpus=N instead.
if [ -n "$CPUS" ]; then CPUARG="cpus=$CPUS"; else CPUARG="cpumask=${CPUMASK:-0x15}"; fi
[ "${MEMMAP:-0}" = 1 ] && GPUARG="$GPUARG memmap=1"
# PERSIST=1: /private/var kept between boots (userland/src/var_store.c): ufs_write=1 lets the store, userdata past
# the iOS volume (the kernel's ufs_stores and the loader's doha_store), take writes; var_store=1 loads the last
# save at boot and runs the saver; var_save_every=SAVE_EVERY (120 s) saves by itself, as doha has no orderly end of a run
[ "${PERSIST:-0}" = 1 ] && GPUARG="$GPUARG ufs_write=1 var_store=1 var_save_every=${SAVE_EVERY:-120}"
CMD="${VERBOSE:+-v }${HUD:+fb_hud=1 }${GPUARG:+${GPUARG# } }bootcpu=3 $CPUARG ufs=2 root_apfs=ufs_userdata${OSMARG}${TOUCHARG} epoch=$(date +%s)"
echo "cmdline: $CMD"
python3 xnuloader/mkpayload.py -o ~/doha-xnu/uefi/payload-ios.bin \
	--cmdline "$CMD" \
	loader.efi=xnuloader/loader.efi kernel=$K ramdisk=userland/root.apfs resident=userland/flashboot.apfs
ls -l ~/doha-xnu/uefi/payload-ios.bin
P=$(stat -c %s ~/doha-xnu/uefi/payload-ios.bin)
[ $P -lt 67108864 ] || { echo "the payload ($P bytes) is more than the 64 MiB the shim reserves"; exit 1; }
set +e
DOHA_WILLOW=$W DOHA_PAYLOAD=~/doha-xnu/uefi/payload-ios.bin bash "$R/uefi/build-doha.sh" DEBUG 2>&1 | tee ~/doha-xnu/uefi/build.log | tail -n 6
echo "exit=${PIPESTATUS[0]}"
