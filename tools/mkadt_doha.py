#!/usr/bin/env python3
"""Build the doha (Moto G8 Plus, Qualcomm SM6125) ADT for the DOHA XNU config.

Edits the ios-sweet base tree (mkadt.py, MIT) the way the herolte port of
ios-a5xelte edits it for its board (one CPU node, own GIC, a5xelte-fbcon). Addresses come from the phone's live FDT
(dtb/doha-live.dts.txt) and were checked on hardware by shim milestone 1:
GICv3 at 0x0f200000/0x0f300000, CNTV = INTID 19, boot CPU MPIDR 0x0, ABL
splash a8r8g8b8 at 0x5c000000 (1080x2280, stride 4320).

Milestone 2 describes the boot CPU only (DOHA sets SWEET_SMP_MAX_CPUS 1) and
no storage: the goal is the XNU console on the panel.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkadt  # noqa: E402

# 0xc0000000..0x140000000 (2 GiB) holds no reserved-memory node in the live
# FDT; use the first GiB, which keeps every physical address below 4 GiB.
DRAM_BASE, DRAM_SIZE = 0xc0000000, 0x40000000
SOC_BASE = 0x01000000       # arm-io ranges base; child regs are relative (must not be 0)
GICD, GICD_SIZE = 0x0f200000, 0x10000
GICR, GICR_SIZE = 0x0f300000, 0x100000
VTIMER_INTID = 19
TIMEBASE = 19200000
FB_BASE, FB_WIDTH, FB_HEIGHT, FB_STRIDE = 0x5c000000, 1080, 2280, 4320

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a53): its GIC and timer PPI.
QEMU_GICD, QEMU_GICR, QEMU_VTIMER_INTID, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 27, 62500000


def set_prop(node, name, value):
    for i, (key, flags, _) in enumerate(node.props):
        if key == name:
            node.props[i] = (key, flags, value)
            return
    node.props.append((name, 0, value))


def child(node, name):
    for candidate in node.children:
        if candidate.prop('name') == mkadt.cstr(name):
            return candidate
    raise ValueError(f'missing donor ADT node {name}')


def build(dram=(DRAM_BASE, DRAM_SIZE), qemu=False):
    # mkadt carves its 1 MiB panic log (/pram) off the top of this range and
    # sets /chosen dram-base/dram-size itself. qemu=True there gives the
    # single-CPU tree without sweet's UFS node; its GIC is replaced below.
    mkadt.PHYS_BASE, mkadt.MEM_SIZE = dram
    root = mkadt.build(seed=os.urandom(64), qemu=True)
    # The userland is the iPhone X IPSW (iPhone10,3 / D22AP), like the donors.
    # 'samsung,a5xelte' keeps the shared SweetPlatformExpert IONameMatch of
    # the A5XELTE port that DOHA builds on.
    set_prop(root, 'compatible', mkadt.cstr('D22AP') + mkadt.cstr('iPhone10,3') +
             mkadt.cstr('samsung,a5xelte') + mkadt.cstr('motorola,doha') +
             mkadt.cstr('qcom,sm6125') + mkadt.cstr('AppleARM'))
    chosen = child(root, 'chosen')
    set_prop(chosen, 'firmware-version', mkadt.cstr('doha-shim'))
    set_prop(chosen, 'system-firmware-version', mkadt.cstr('doha-shim'))
    # Synthetic, locally administered addresses, not the phone's (see mkadt_herolte.py).
    for name, last in (('wifi0', 1), ('bluetooth0', 2), ('ethernet0', 3)):
        set_prop(chosen, f'mac-address-{name}', bytes((0x02, 0x44, 0x4f, 0x48, 0x41, last)))

    timebase = QEMU_TIMEBASE if qemu else TIMEBASE
    cpu0 = child(child(root, 'cpus'), 'cpu0')
    # SweetCPU matches IONameMatch 'arm,cortex-a53' (KernelConfigTables).
    set_prop(cpu0, 'compatible', mkadt.cstr('qcom,kryo260') + mkadt.cstr('arm,cortex-a53') +
             mkadt.cstr('ARM,v8'))
    set_prop(cpu0, 'reg', mkadt.u32(0x0))
    set_prop(cpu0, 'timebase-frequency', mkadt.u32(timebase))
    set_prop(cpu0, 'peripheral-frequency', mkadt.u32(timebase))
    set_prop(cpu0, 'fixed-frequency', mkadt.u32(timebase))
    set_prop(cpu0, 'clock-frequency', mkadt.u32(1804800000))

    arm_io = child(root, 'arm-io')
    set_prop(arm_io, 'device_type', mkadt.cstr('doha-io'))
    set_prop(arm_io, 'compatible', mkadt.cstr('qcom,sm6125-io') + mkadt.cstr('arm-io'))
    set_prop(arm_io, 'ranges', mkadt.u64(0, SOC_BASE, 0x100000000 - SOC_BASE))
    arm_io.children = [n for n in arm_io.children if n.prop('name') == mkadt.cstr('wdt')]
    gicd, gicr = (QEMU_GICD, QEMU_GICR) if qemu else (GICD, GICR)
    arm_io.children.append(mkadt.node('gic', [
        ('compatible', mkadt.cstr('arm,gic-v3')),
        ('interrupt-controller', mkadt.cstr('master')),
        ('virtual-timer-intid', mkadt.u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', mkadt.u64(gicd - SOC_BASE, GICD_SIZE, gicr - SOC_BASE, GICR_SIZE)),
    ]))
    arm_io.children.append(mkadt.node('disp0', [
        ('device_type', mkadt.cstr('display-subsystem')),
        # AppleCLCD (SweetFramebuffer.cpp) matches 'samsung,a5xelte-display'.
        ('compatible', mkadt.cstr('samsung,a5xelte-display') + mkadt.cstr('motorola,doha-display')),
        ('canvas-width', mkadt.u32(FB_WIDTH)),
        ('canvas-height', mkadt.u32(FB_HEIGHT)),
    ]))
    root.children = [n for n in root.children if n.prop('name') not in
                     (mkadt.cstr('sweet-fbcon'), mkadt.cstr('sweet-ufs'))]
    # pe_serial.c looks this node up by name for the kprintf console.
    root.children.append(mkadt.node('a5xelte-fbcon', [
        ('reg', mkadt.u64(FB_BASE, FB_STRIDE * FB_HEIGHT)),
        ('width', mkadt.u32(FB_WIDTH)),
        ('height', mkadt.u32(FB_HEIGHT)),
        ('stride', mkadt.u32(FB_STRIDE)),
    ]))
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--mem-mb', type=int, default=DRAM_SIZE >> 20,
                        help='MiB of RAM from 0xc0000000 to give XNU (max 2048)')
    parser.add_argument('--qemu', action='store_true',
                        help='QEMU virt GIC/timer and RAM at 0x40000000 (tools/qemu-doha.sh)')
    parser.add_argument('--dump', action='store_true')
    args = parser.parse_args()
    if args.mem_mb > 2048:
        parser.error('only 0xc0000000..0x140000000 is free of carve-outs')
    dram = (0x40000000 if args.qemu else DRAM_BASE, args.mem_mb << 20)
    blob = mkadt.adt.serialize(build(dram, args.qemu))
    args.output.write_bytes(blob)
    if args.dump:
        mkadt.adt.dump(mkadt.adt.parse(blob)[0])
    print(f'{args.output}: {len(blob)} bytes')
