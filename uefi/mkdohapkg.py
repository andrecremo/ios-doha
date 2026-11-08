#!/usr/bin/env python3
"""Make Platforms/Motorola/dohaPkg in a Mu-Silicium tree, from its willowPkg (same SoC).

  mkdohapkg.py MU_TREE EXTRACTED_FIRMWARE

EXTRACTED_FIRMWARE is what UEFIReader made of the phone's own xbl. It is copied to Binaries/doha and
never goes into a repository.

For a first boot the package keeps what it takes to reach the boot menu on the framebuffer ABL left on,
and leaves out what could act on the hardware for no use here: charging, USB (mass storage above all),
loading peripherals, the buttons, and every Motorola module but one (BOOT_FLAGS below).
"""
import os
import re
import shutil
import sys
from pathlib import Path

FD_BASE, FD_SIZE = '0x5FC00000', '0x300000'
FB_WIDTH, FB_HEIGHT = 1080, 2280
PLATFORM_GUID = '6F0B7B2E-3C52-4C0E-9A41-5B1C7D2E9F10'
SECURITY_FLAG = '0x81CC'     # uefiplat.cfg of the doha xbl; willow's is 0xC4

# Module lines dropped from APRIORI.inc and DXE.inc.
LEFT_OUT = (
    'UsbMsdDxe', 'UsbDeviceDxe', 'UsbConfigDxe', 'UsbfnDwc3Dxe', 'UsbPwrCtrlDxe', 'XhciDxe',
    'XhciPciEmulationDxe', 'UsbBusDxe', 'UsbKbDxe', 'UsbMassStorageDxe',
    'QcomChargerDxeLA', 'ChargerExDxe', 'AdcDxe', 'PILDxe',
    # Asks for the protocol of MotHwIdDxe, which stays out: that one uses UtagsLib and can write.
    'ButtonsDxe',
)
# The one Motorola module in the package. EnvDxe, SmemDxe and PmicDxe assert without its protocol. It keeps
# flags in memory: no storage library, no dependencies. In the stock order it loads right before SmemDxe.
BOOT_FLAGS = 'Binaries/doha/MbmPkg/Core/Drivers/MotBootFlagsDxe/MotBootFlagsDxe.inf'
# Lines dropped from the .fdf: the USB power enabler, and the application that offers the storage over USB.
FDF_LEFT_OUT = ('NicobarPkg/Drivers/UsbPwrEnablerDxe', 'QcomPkg/Extra.fdf.inc')


def sub1(text, old, new, what):
    if text.count(old) != 1:
        raise SystemExit(f'{what}: expected 1x {old!r}, found {text.count(old)}')
    return text.replace(old, new)


def drop_lines(text, names, what):
    out, dropped = [], set()
    for line in text.splitlines(keepends=True):
        hit = next((n for n in names if n in line), None)
        if hit:
            dropped.add(hit)
        else:
            out.append(line)
    return ''.join(out), dropped


def add_halt(dst, after, drivers, what='diagnostic build'):
    """Diagnostic build: drivers of ours (DOHA_HALT_DRIVER, comma separated, in load order) right after
    DOHA_HALT_AFTER. The last one usually never returns."""
    for spec in drivers.split(','):
        # DIR/INF for a directory with more than one module (DohaRegsDxe/DohaRegsBefore), else the name of both.
        folder, driver = spec.split('/') if '/' in spec else (spec, spec)
        if not (dst / 'Drivers' / folder).exists():
            shutil.copytree(Path(__file__).parent / folder, dst / 'Drivers' / folder)
        inf = f'dohaPkg/Drivers/{folder}/{driver}.inf'
        dsc = dst / 'doha.dsc'
        dsc.write_text(sub1(dsc.read_text(), '[Components]\n', f'[Components]\n  {inf}\n', 'dsc'))
        apriori = dst / 'Include/APRIORI.inc'
        t, n = re.subn(rf'^(\s*INF \S*/{re.escape(after)}\.inf\n)', rf'\g<1>  INF {inf}\n', apriori.read_text(), flags=re.M)
        if n != 1:
            raise SystemExit(f'APRIORI.inc: expected one {after}, found {n}')
        apriori.write_text(t)
        dxe = dst / 'Include/DXE.inc'
        dxe.write_text(dxe.read_text().rstrip('\n') + f'\n  INF {inf}\n')
        if driver == 'DohaSaveDxe':
            once = 1 if os.environ.get('DOHA_SAVE_ONCE') else 0
            (dst / 'Drivers' / driver / 'DohaSaveConfig.h').write_text(f'#define SAVE_ONCE  {once}\n')
        print(f'{what}: {driver} after {after}')
        after = driver


def add_hwid(dst):
    """The firmware's DisplayDxe needs a hwid protocol: DohaHwIdDxe, in memory, loads right before it."""
    shutil.copytree(Path(__file__).parent / 'DohaHwIdDxe', dst / 'Drivers/DohaHwIdDxe')
    inf = 'dohaPkg/Drivers/DohaHwIdDxe/DohaHwIdDxe.inf'
    dsc = dst / 'doha.dsc'
    dsc.write_text(sub1(dsc.read_text(), '[Components]\n', f'[Components]\n  {inf}\n', 'dsc'))
    apriori = dst / 'Include/APRIORI.inc'
    display = '  INF Binaries/doha/QcomPkg/Drivers/DisplayDxe/DisplayDxe.inf\n'
    apriori.write_text(sub1(apriori.read_text(), display, f'  INF {inf}\n{display}', 'APRIORI.inc'))
    dxe = dst / 'Include/DXE.inc'
    dxe.write_text(dxe.read_text().rstrip('\n') + f'\n  INF {inf}\n')


def add_log(dst):
    """Diagnostic build: DohaLogDxe keeps the logs in RAM, from as soon as there is a timer."""
    shutil.copytree(Path(__file__).parent / 'DohaLogDxe', dst / 'Drivers/DohaLogDxe')
    inf = 'dohaPkg/Drivers/DohaLogDxe/DohaLogDxe.inf'
    dsc = dst / 'doha.dsc'
    dsc.write_text(sub1(dsc.read_text(), '[Components]\n', f'[Components]\n  {inf}\n', 'dsc'))
    apriori = dst / 'Include/APRIORI.inc'
    apriori.write_text(sub1(apriori.read_text(), f'  INF {BOOT_FLAGS}\n', f'  INF {inf}\n  INF {BOOT_FLAGS}\n', 'APRIORI.inc'))
    dxe = dst / 'Include/DXE.inc'
    dxe.write_text(dxe.read_text().rstrip('\n') + f'\n  INF {inf}\n')


def stock_panels(firmware):
    """The panel files of the firmware, under the names and GUIDs it has them, for DisplayDxe to pick from."""
    found = re.findall(r'FILE FREEFORM = ([0-9A-Fa-f-]+) \{\s*SECTION UI = "((?:Panel_|mipi_)[^"]+\.xml)"\s*SECTION RAW = RawFiles/\2\s*\}',
                       (firmware / 'DXE.inc').read_text())
    if not any(name == 'Panel_tm_ft8719_fhd_vid.xml' for _, name in found):
        raise SystemExit('the firmware does not list the panel of this phone')
    return ''.join(f'  FILE FREEFORM = {guid} {{\n    SECTION UI = "{name}"\n    SECTION RAW = Binaries/doha/RawFiles/{name}\n  }}\n\n'
                   for guid, name in found)


def main():
    mu, firmware = Path(sys.argv[1]), Path(sys.argv[2])
    src = mu / 'Platforms/Xiaomi/willowPkg'
    dst = mu / 'Platforms/Motorola/dohaPkg'
    if not src.is_dir():
        raise SystemExit(f'no {src}')
    roots = [p for p in firmware.iterdir() if p.is_dir()]
    if len(roots) != 1 or not (roots[0] / 'QcomPkg').is_dir():
        raise SystemExit(f'{firmware}: expected one firmware directory with QcomPkg in it')
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for old in ('willow.dec', 'willow.dsc', 'willow.fdf'):
        (dst / old).rename(dst / old.replace('willow', 'doha'))

    binaries = mu / 'Binaries/doha'
    if binaries.exists():
        shutil.rmtree(binaries)
    binaries.parent.mkdir(exist_ok=True)
    shutil.copytree(roots[0], binaries)

    # Everything but the ACPI tables, which stay willow's: only an operating system reads them.
    for path in dst.rglob('*'):
        if not path.is_file() or path.suffix not in ('.dec', '.dsc', '.fdf', '.inc', '.inf', '.c', '.py'):
            continue
        t = path.read_text()
        t = t.replace('Binaries/willow', 'Binaries/doha').replace('willowPkg', 'dohaPkg')
        path.write_text(t)

    dsc = dst / 'doha.dsc'
    t = dsc.read_text()
    t = sub1(t, 'PLATFORM_NAME                  = willow', 'PLATFORM_NAME                  = doha', 'dsc')
    t = re.sub(r'(PLATFORM_GUID\s*=\s*)[0-9A-Fa-f-]+', r'\g<1>' + PLATFORM_GUID, t, count=1)
    t = sub1(t, 'FLASH_DEFINITION               = dohaPkg/willow.fdf', 'FLASH_DEFINITION               = dohaPkg/doha.fdf', 'dsc')
    t = sub1(t, 'PcdSmbiosSystemManufacturer|"Xiaomi"', 'PcdSmbiosSystemManufacturer|"Motorola"', 'dsc')
    t = sub1(t, 'PcdSmbiosSystemModel|"Redmi Note 8T"', 'PcdSmbiosSystemModel|"Moto G8 Plus"', 'dsc')
    t = sub1(t, 'PcdSmbiosSystemRetailModel|"willow"', 'PcdSmbiosSystemRetailModel|"doha"', 'dsc')
    t = sub1(t, 'PcdSmbiosSystemRetailSku|"Redmi_Note_8T_willow"', 'PcdSmbiosSystemRetailSku|"Moto_G8_Plus_doha"', 'dsc')
    t = sub1(t, 'PcdSmbiosSystemBoardModel|"Redmi Note 8T"', 'PcdSmbiosSystemBoardModel|"Moto G8 Plus"', 'dsc')
    t = sub1(t, 'PcdFrameBufferWidth|1080', f'PcdFrameBufferWidth|{FB_WIDTH}', 'dsc')
    t = sub1(t, 'PcdFrameBufferHeight|2340', f'PcdFrameBufferHeight|{FB_HEIGHT}', 'dsc')
    if not re.search(r'USE_CUSTOM_DISPLAY_DRIVER\s*=\s*0', t):
        raise SystemExit('dsc: the first boot needs SimpleFbDxe (USE_CUSTOM_DISPLAY_DRIVER = 0)')
    stock_display = bool(os.environ.get('DOHA_STOCK_DISPLAY'))
    if stock_display:
        t = re.sub(r'(USE_CUSTOM_DISPLAY_DRIVER\s*=\s*)0', r'\g<1>1', t, count=1)
    dsc.write_text(t)

    fdf = dst / 'doha.fdf'
    t, dropped = drop_lines(fdf.read_text(), FDF_LEFT_OUT, 'fdf')
    if dropped != set(FDF_LEFT_OUT):
        raise SystemExit(f'fdf: did not find {set(FDF_LEFT_OUT) - dropped}')
    fdf.write_text(t)

    seen = set()
    for inc in ('Include/APRIORI.inc', 'Include/DXE.inc'):
        path = dst / inc
        t, dropped = drop_lines(path.read_text(), LEFT_OUT, inc)
        seen |= dropped
        smem = '  INF Binaries/doha/QcomPkg/Drivers/SmemDxe/SmemDxe.inf\n'
        path.write_text(sub1(t, smem, f'  INF {BOOT_FLAGS}\n{smem}', inc))
    if seen != set(LEFT_OUT):
        raise SystemExit(f'module lists: did not find {set(LEFT_OUT) - seen}')

    # Always: right after ClockDxe, ask for the bus the display reads the framebuffer through (/clk/mmrt), or the
    # RPM turns it off and the screen ABL left on goes black. Diagnostic drivers placed after ClockDxe come after it.
    add_halt(dst, 'ClockDxe', 'DohaMmrtDxe', 'part of the package')
    halt_after = os.environ.get('DOHA_HALT_AFTER')
    if halt_after:
        add_halt(dst, halt_after, os.environ.get('DOHA_HALT_DRIVER', 'DohaHaltDxe'))
    # DOHA_INSERT=MODULE=DRIVERS;MODULE=DRIVERS: diagnostic drivers at more than one place in the load order.
    for group in filter(None, os.environ.get('DOHA_INSERT', '').split(';')):
        module, drivers = group.split('=')
        add_halt(dst, module, drivers)

    if stock_display:
        add_hwid(dst)
    if os.environ.get('DOHA_LOG'):
        add_log(dst)

    # willow's panels, only there for its own display driver: either none, or the ones of the doha firmware.
    panels = stock_panels(roots[0]) if stock_display else ''
    raw = dst / 'Include/RAW.inc'
    t, n = re.subn(r'!if \$\(USE_CUSTOM_DISPLAY_DRIVER\) == 1\n.*?!endif\n', lambda _: panels, raw.read_text(), flags=re.S)
    if n != 1:
        raise SystemExit(f'RAW.inc: expected one display block, found {n}')
    raw.write_text(t)

    cfg = dst / 'Library/ConfigurationMapLib/ConfigurationMapLib.c'
    t = sub1(cfg.read_text(), '{"SecurityFlag", 0xC4}', '{"SecurityFlag", %s}' % SECURITY_FLAG, 'config map')
    if stock_display:
        # The firmware's DisplayDxe runs its work on a thread when this is 1, through Qualcomm's scheduler, which
        # Mu-Silicium does not have. With 1 it never returned on the doha.
        t = sub1(t, '{"EnableDisplayThread", 1}', '{"EnableDisplayThread", 0}', 'config map')
    cfg.write_text(t)

    build = dst / 'DeviceBuild.py'
    t = build.read_text()
    t = sub1(t, '"Platforms/Xiaomi",\n', '"Platforms/Motorola",\n', 'build')
    t = t.replace("('willow', 'gcc_aarch64_linux'", "('doha', 'gcc_aarch64_linux'")
    t = t.replace('dohaPkg/willow.dsc', 'dohaPkg/doha.dsc')
    t = t.replace('return "willow"', 'return "doha"')
    t = t.replace('"PRODUCT_NAME", "willow"', '"PRODUCT_NAME", "doha"')
    if 'willow' in t.replace('Silicium-ACPI', ''):
        raise SystemExit('build: willow is still named: ' + re.search(r'.*willow.*', t).group(0))
    build.write_text(t)

    # The image comes from mkdohaimg.py; build_uefi.py only needs a config to run.
    configs = mu / 'Resources/Configs'
    t = (configs / 'willow.toml').read_text()
    t = sub1(t, 'append_dtb         = true', 'append_dtb         = false', 'toml')
    if f'base = {FD_BASE}' not in t or f'size = {FD_SIZE}' not in t:
        raise SystemExit('toml: the FD is not where the doha xbl has it')
    (configs / 'doha.toml').write_text(t)

    # Every binary module and file the package names has to exist.
    missing = []
    names = []
    for path in [dst / 'Include/APRIORI.inc', dst / 'Include/DXE.inc', dst / 'Include/RAW.inc', fdf]:
        for m in re.finditer(r'Binaries/[A-Za-z0-9_./-]+', path.read_text()):
            names.append(m.group(0))
            if not (mu / m.group(0)).exists() and not m.group(0).startswith('Binaries/generic'):
                missing.append(m.group(0))
    if missing:
        raise SystemExit('missing from the firmware:\n  ' + '\n  '.join(sorted(set(missing))))
    bad = [n for n in names if n != BOOT_FLAGS and re.search(r'/Mot[A-Z]|MbmPkg|/MiToken', n)]
    if bad:
        raise SystemExit(f'not for this boot: {bad}')
    print(f'{dst}: {len(set(names))} binary references checked, {len(LEFT_OUT)} modules left out')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main()
