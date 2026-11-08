#!/bin/bash
# Build the doha UEFI from source in WSL, in ~/doha-xnu/uefi. Touches neither the phone nor Windows, but
# for the finished image in C:\Users\andre. Needs, once, from the system's packages:
#   sudo apt install -y build-essential clang lld llvm uuid-dev nasm mono-devel python3-venv gcc-aarch64-linux-gnu
set -euo pipefail

MU_COMMIT=6b3d90b79e191e08171bfedd3980234a7e49d340
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=~/doha-xnu/uefi
FIRMWARE=$WORK/private/doha
MODE=${1:-DEBUG}        # DEBUG writes its log on the screen; RELEASE is silent
# DOHA_HALT_AFTER=<module> makes a diagnostic image: DOHA_HALT_DRIVER (default DohaHaltDxe) runs right after
# that module and the boot goes no further.
# DOHA_STOCK_DISPLAY=1 uses the firmware's own DisplayDxe instead of the framebuffer ABL left on.
# DOHA_LOG=1 keeps the logs in RAM and reboots at 25 s, for the shim to show them.
# DOHA_INSERT (see mkdohapkg.py) puts diagnostic drivers at several places; the image is named -insert.
OUT=/mnt/c/Users/andre/doha-uefi-$MODE${DOHA_STOCK_DISPLAY:+-display}${DOHA_LOG:+-log}${DOHA_INSERT:+-insert}${DOHA_HALT_AFTER:+-${DOHA_HALT_DRIVER:-halt}-$DOHA_HALT_AFTER}.img

[ -d "$FIRMWARE" ] || { echo "no $FIRMWARE: run UEFIReader on the xbl first"; exit 1; }
for tool in clang lld llvm-objcopy nasm mono make python3; do
	command -v "$tool" >/dev/null || { echo "missing: $tool (see the apt line at the top)"; exit 1; }
done

cd "$WORK"
if [ ! -d Mu-Silicium/.git ]; then
	git clone --filter=blob:none --no-checkout https://github.com/Project-Silicium/Mu-Silicium
fi
git -C Mu-Silicium fetch -q origin "$MU_COMMIT" || true
git -C Mu-Silicium checkout -q "$MU_COMMIT"
[ "$(git -C Mu-Silicium rev-parse HEAD)" = "$MU_COMMIT" ]
git -C Mu-Silicium submodule update --init --depth 1 Common/Mu Common/Mu_OEM_Sample Mu_Basecore Silicium-ACPI \
	Silicon/Silicium/OpensslPkg/Library/OpensslLib/openssl Binaries

python3 "$HERE/mkdohapkg.py" Mu-Silicium "$FIRMWARE"

[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q -r Mu-Silicium/pip-requirements.txt

(cd Mu-Silicium && source ../venv/bin/activate && python3 build_uefi.py -d doha -r "$MODE")
FD=Mu-Silicium/Build/dohaPkg/${MODE}_CLANGPDB/FV/SILICIUM_UEFI.fd
[ -f "$FD" ] || { echo "no $FD"; exit 1; }

clang --target=aarch64-linux-gnu -c "$HERE/DohaShim.S" -o DohaShim.o
aarch64-linux-gnu-objcopy -O binary DohaShim.o DohaShim.bin
truncate -s 4096 DohaShim.bin

python3 "$HERE/mkdohaimg.py" DohaShim.bin "$FD" "$HERE/../dtb/boot_a_unpacked/dtb" "$OUT"
echo "done: $OUT"
