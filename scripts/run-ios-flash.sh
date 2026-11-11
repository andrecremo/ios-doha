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
# BATTERY=1 (default): battery=1, the battery's level for the status bar: the loader asks Qualcomm's ChargerEx in
# doha's UEFI (read-only: present, charger plugged, voltage; the level estimated from the voltage); BATTERY=0: left out
[ "${BATTERY:-1}" = 1 ] && TOUCHARG="$TOUCHARG battery=1"
# CHARGE=1: charge=1, the charger's watchdog petted every 5 s while a cable is in (MISC 0x43), without which the
# PMI632 stops charging a few minutes into the run; the panel's Wi-Fi line then starts "chg+" ("chg!": a write refused)
[ "${CHARGE:-0}" = 1 ] && TOUCHARG="$TOUCHARG charge=1"
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
# GPUMHZ=N (default 900): a610_mhz=N, the 3D core at a speed of gpucc-trinket.c's table (320 465 600 745 820 900 950;
# the CX rail at that speed's level through the RPM). 900 over the driver's 745 (2026-11-10): scrolling Settings, the
# longest gap between frames from 465 ms to 75-141 ms, the GPU still 80-92% busy
GPUARG="$GPUARG a610_mhz=${GPUMHZ:-900}"
# BIMC=kHz (default 1804000): rpm_bimc=kHz, the memory bus asked of the RPM (the kernel's own 400000 without it).
# doha's kernel votes 1353000 with the GPU at 745 MHz and 1804000 at 900 (trinket-gpu.dtsi); at 1804000 a frame's
# copy onto the panel took the GPU 5.0 ms against 6.7 (2026-11-10)
GPUARG="$GPUARG rpm_bimc=${BIMC:-1804000}"
# MDSSDUMP=1: mdssdump=1, the loader shows the display controller's source pipes, CTL0, LM0 and the DSI interface as
# the UEFI keeps them (read only) for 30 s before the kernel
[ "${MDSSDUMP:-0}" = 1 ] && GPUARG="$GPUARG mdssdump=1"
# FLIPTEST=1: fliptest=1, the loader shows eight coloured bands for 5 s by pointing the display's pipe (VIG0) at them,
# then puts it back: whether a picture anywhere in RAM can be shown without the GPU's copy
[ "${FLIPTEST:-0}" = 1 ] && GPUARG="$GPUARG fliptest=1"
# LASTPANIC=1: lastpanic=1, the loader shows the text left in the panic log region by the run before (30 s)
[ "${LASTPANIC:-0}" = 1 ] && GPUARG="$GPUARG lastpanic=1"
# FLIP=1 (default; FLIP=0 copies every frame as before): fb_flip=1, a frame of one layer shown where the GPU drew it
# (the display's pipe pointed at it) instead of copied onto the panel's memory by the GPU. 2026-11-10: Settings'
# scroll 29-59 fps against 21-30, the longest gap 17-57 ms against 150-470, and no SpringBoard restart (the black
# screen with the spinner) in any run; the HUD's Screen line says "flip, N late" while it is
[ "${FLIP:-1}" = 1 ] && GPUARG="$GPUARG fb_flip=1"
# GOV=1: cpu_gov=1, the cores' clocks follow the load (bsd/dev/redwood_osm.c): the top row only while a core is busy,
# down to 300 MHz at rest; the HUD's CPU line says the clock, the load and how much of the time was at the top.
# GOVMIN=N: cpu_gov_min=N, the lowest row (0: 300 MHz, 1: 614, 2: 864 ...)
# GOV=2: cpu_gov=2, the load measured and shown on the CPU line, no clock changed
# GOV=1 is the default (2026-11-11: at rest on the home screen, unplugged, 442 mA against 527 without it; GOV=0 leaves
# the cores at the top all the time)
[ "${GOV:-1}" != 0 ] && GPUARG="$GPUARG cpu_gov=${GOV:-1}"
[ -n "$GOVMIN" ] && GPUARG="$GPUARG cpu_gov_min=$GOVMIN"
# WALLFREEZE=1: wallpaper_freeze=1, SpringBoard shows the wallpaper as one still picture read off the panel (20 s
# in, at the home screen; the icons blink once) instead of drawing its layers every frame; 2: the wallpaper hidden
[ -n "$WALLFREEZE" ] && GPUARG="$GPUARG wallpaper_freeze=$WALLFREEZE"
# CPUMASK=M: the cores by mask instead of cpus=. The bits are positions in the loader's list, the boot core first
# (bit 0, which must be set: the kernel panics without it), then by distance from it: 3, 4, 2, 5, 1, 6, 7 (core 0 is
# the loader's). 0x15: the Silver cores 3, 2, 1 alone, without the Gold ones the firmware leaves at 300 MHz.
# MEMMAP=1: memmap=1, the loader shows the UEFI's memory map for 20 s before the kernel
# The default is cpus=8, all the cores, the Gold ones at 1804 MHz (OSMGOLD=6 below, 2026-11-10); before Gold could be
# clocked, 0x15 was smoother than the 8 with Gold at 300 MHz. CPUS=N: cpus=N instead.
if [ -n "$CPUS" ]; then CPUARG="cpus=$CPUS"; elif [ -n "$CPUMASK" ]; then CPUARG="cpumask=$CPUMASK"; else CPUARG="cpus=8"; fi
[ "${MEMMAP:-0}" = 1 ] && GPUARG="$GPUARG memmap=1"
# UEFILOG=1: uefilog=1, the loader shows the lines of the UEFI's own log about the charger for 25 s before the kernel
[ "${UEFILOG:-0}" = 1 ] && GPUARG="$GPUARG uefilog=1"
# OSMDUMP=1: osmdump=1, the loader shows both clusters' OSM (enable, the words that differ, the tables' first rows)
# for 30 s before the kernel
[ "${OSMDUMP:-0}" = 1 ] && GPUARG="$GPUARG osmdump=1"
# OSMREPORT=1: osm_dump=1, the kernel reads both clusters' OSM 70 s in (with CPUS=8 the Gold cores are up by then)
# and puts a summary on the panel's CPU line: Gold's enable, its configuration words set, each core's speed
[ "${OSMREPORT:-0}" = 1 ] && GPUARG="$GPUARG osm_dump=1"
# UEFICPU=1: uefi_cpu=probe, the loader shows what Qualcomm's ClockDxe says of each core's performance levels
# (read only) for 25 s before the kernel
[ "${UEFICPU:-0}" = 1 ] && GPUARG="$GPUARG uefi_cpu=probe"
# OSMGOLD=ROW (default 6, 1804 MHz; OSMGOLD=0 leaves it out, Gold at 300 MHz): each Gold core asks for row ROW of Gold's OSM table as it comes up (osmc=f523000:ROW, the
# request doha's own clk-cpu-osm.c writes; enable and configuration left alone), cpuprobe=1 measures each core; the panel's
# CPU line: "G<enable before>><after> r<row read back> <MHz of cores 0-3>|<4-7>". Rows: 3 1056, 5 1536, 6 1804, 7 2016 MHz
# (7 not used: nothing in this port watches the temperature; the SoC's own limits hardware still does). The firmware
# turns Gold's OSM on (enable 3) as PSCI powers a Gold core: the loader, before that, reads 2
[ "${OSMGOLD:-6}" != 0 ] && GPUARG="$GPUARG osmc=f523000:${OSMGOLD:-6} cpuprobe=1"
# PERSIST=1 (default; PERSIST=0 leaves it out, a boot with an empty /var that writes nothing): /private/var kept between boots (userland/src/var_store.c): ufs_write=1 lets the store, userdata past
# the iOS volume (the kernel's ufs_stores and the loader's doha_store), take writes; var_store=1 loads the last
# save at boot and runs the saver; var_save_every=SAVE_EVERY (120 s) saves by itself, as doha has no orderly end of a run
[ "${PERSIST:-1}" = 1 ] && GPUARG="$GPUARG ufs_write=1 var_store=1 var_save_every=${SAVE_EVERY:-120}"
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
