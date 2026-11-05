#!/usr/bin/env python3
"""Make Platforms/Motorola/dohaPkg in a Mu-Silicium tree, from its willowPkg (same SoC).

  mkdohapkg.py MU_TREE EXTRACTED_FIRMWARE

EXTRACTED_FIRMWARE is what UEFIReader made of the phone's own xbl. It is copied to Binaries/doha and
never goes into a repository.

For a first boot the package keeps what it takes to reach the boot menu on the framebuffer ABL left on,
and leaves out what could act on the hardware for no use here: charging, USB (mass storage above all),
loading peripherals, and every Motorola module, which are not in willow's lists to begin with.
"""
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
)
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
        path.write_text(t)
    if seen != set(LEFT_OUT):
        raise SystemExit(f'module lists: did not find {set(LEFT_OUT) - seen}')

    # willow's panels, only there for its own display driver, which this package does not build.
    raw = dst / 'Include/RAW.inc'
    t, n = re.subn(r'!if \$\(USE_CUSTOM_DISPLAY_DRIVER\) == 1\n.*?!endif\n', '', raw.read_text(), flags=re.S)
    if n != 1:
        raise SystemExit(f'RAW.inc: expected one display block, found {n}')
    raw.write_text(t)

    cfg = dst / 'Library/ConfigurationMapLib/ConfigurationMapLib.c'
    cfg.write_text(sub1(cfg.read_text(), '{"SecurityFlag", 0xC4}', '{"SecurityFlag", %s}' % SECURITY_FLAG, 'config map'))

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
    bad = [n for n in names if re.search(r'/Mot[A-Z]|MbmPkg|/MiToken', n)]
    if bad:
        raise SystemExit(f'not for this boot: {bad}')
    print(f'{dst}: {len(set(names))} binary references checked, {len(LEFT_OUT)} modules left out')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main()
