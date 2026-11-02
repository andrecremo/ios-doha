#!/bin/bash
# Build the doha shim and wrap it in a boot.img v2 that mirrors the stock boot_a header.
# Needs aarch64-linux-gnu-gcc and python3. The DTB comes from the phone's own boot_a:
#   python3 ../tools/unpack_bootv2.py ../../backup/boot_a.img ../dtb/boot_a_unpacked
set -euo pipefail
cd "$(dirname "$0")"
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
DTB=${DTB:-../dtb/boot_a_unpacked/dtb}
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"
SRCS="start.S shim.c console.c"
mkdir -p out
objs=""
for f in $SRCS; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
	objs="$objs out/${f%.*}.o"
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$(aarch64-linux-gnu-readelf -r out/shim.o out/console.o | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	$objs -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print strtonum("0x"$1)}')
truncate -s "$size" out/Image
[ -f "$DTB" ] || { echo "error: $DTB missing (see the unpack_bootv2.py line above)" >&2; exit 1; }
python3 ../tools/mkbootimg_v2.py --kernel out/Image --dtb "$DTB" -o out/shim-boot.img
ls -l out/Image out/shim-boot.img
