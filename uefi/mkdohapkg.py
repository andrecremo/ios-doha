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
import subprocess
import sys
import tempfile
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


def show_xnu_loader_log(path):
    """willow-hackios's XnuLoader.c keeps its log for a "logdump" partition, which the doha does not have, and resets
    at once: the doha's copy also prints what it does and the whole log on the screen, and waits 30 s first."""
    raw = path.read_bytes()
    crlf = b'\r\n' in raw
    t = raw.decode().replace('\r\n', '\n')
    t = sub1(t, '#include <Library/PrintLib.h>\n', '#include <Library/PrintLib.h>\n#include <Library/DebugLib.h>\n', 'XnuLoader.c')
    t = sub1(t, '  if (Header->Magic != XNU_PAYLOAD_MAGIC || Header->Size > XNU_PAYLOAD_MAX_SIZE) {\n    return;\n  }\n',
             '  DEBUG ((DEBUG_ERROR, "XnuLoader: payload at %lx: magic %08x size %x\\n", (UINT64)XNU_PAYLOAD_BASE,\n'
             '          Header->Magic, Header->Size));\n'
             '  if (Header->Magic != XNU_PAYLOAD_MAGIC || Header->Size > XNU_PAYLOAD_MAX_SIZE) {\n    return;\n  }\n',
             'XnuLoader.c')
    t = sub1(t, '      if (!EFI_ERROR (gBS->LoadImage (FALSE, gImageHandle, NULL, Entry + 1, Entry->Size, &Handle))) {\n'
                '        gBS->StartImage (Handle, NULL, NULL);\n      }\n',
             '      EFI_STATUS  Status = gBS->LoadImage (FALSE, gImageHandle, NULL, Entry + 1, Entry->Size, &Handle);\n\n'
             '      DEBUG ((DEBUG_ERROR, "XnuLoader: loader.efi, %u bytes: LoadImage %r\\n", Entry->Size, Status));\n'
             '      if (!EFI_ERROR (Status)) {\n'
             '        Status = gBS->StartImage (Handle, NULL, NULL);\n'
             '        DEBUG ((DEBUG_ERROR, "XnuLoader: StartImage returned %r\\n", Status));\n'
             '      }\n', 'XnuLoader.c')
    t = sub1(t, '  // The phone is unattended: always come back to Android.\n',
             '  // The doha has no logdump: the log goes on the screen, line by line, with time to read it.\n'
             '  if (mLog != NULL) {\n'
             '    CHAR8 *Line = mLog;\n\n'
             '    while (*Line != 0) {\n'
             '      CHAR8  *End = Line;\n'
             '      CHAR8  Keep;\n\n'
             '      while (*End != 0 && *End != \'\\n\' && End - Line < 120) {\n'
             '        End++;\n'
             '      }\n\n'
             '      Keep = *End;\n'
             '      *End = 0;\n'
             '      DEBUG ((DEBUG_ERROR, "%a\\n", Line));\n'
             '      *End = Keep;\n'
             '      Line = (Keep == \'\\n\') ? End + 1 : End;\n'
             '    }\n'
             '  }\n\n'
             '  DEBUG ((DEBUG_ERROR, "XnuLoader: reset in 30 s\\n"));\n'
             '  gBS->Stall (30000000);\n\n'
             '  // The phone is unattended: always come back to Android.\n', 'XnuLoader.c')
    path.write_bytes(t.replace('\n', '\r\n').encode() if crlf else t.encode())


def add_xnu_boot(mu, dst, willow):
    """BDS starts willow-hackios's XNU loader ("loader.efi" in the XNUP payload at 0x78000000) instead of giving up.

    willow-hackios patches Mu-Silicium's BootManagerLib in place (uefi/mu-silicium.patch, on its uefi/BASE commit);
    here the patched library is made in dohaPkg from that same base, so that neither tree is changed and nothing of
    willow-hackios is copied into this repository.
    """
    base = (willow / 'uefi/BASE').read_text().strip()
    rel = 'Silicon/Silicium/SiliciumPkg/Library/BootManagerLib'
    lib = dst / 'Library/BootManagerLib'
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / rel
        work.mkdir(parents=True)
        names = subprocess.run(['git', '-C', str(mu), 'ls-tree', '--name-only', f'{base}:{rel}'],
                               capture_output=True, check=True, text=True).stdout.split()
        for name in names:
            text = subprocess.run(['git', '-C', str(mu), 'show', f'{base}:{rel}/{name}'],
                                  capture_output=True, check=True).stdout
            (work / name).write_bytes(text)
        # As bytes: the patched files have CRLF line ends, which reading as text would turn into LF.
        patch = (willow / 'uefi/mu-silicium.patch').read_bytes()
        hunk = patch[patch.index(f'diff --git a/{rel}/BootManager.c'.encode()):]
        subprocess.run(['patch', '-s', '-p1', '-d', tmp], input=hunk, check=True)
        for name in ('XnuLoader.c', 'XnuLoader.h'):
            shutil.copy(willow / 'uefi/files' / rel / name, work / name)
        show_xnu_loader_log(work / 'XnuLoader.c')
        # the payload where DohaShim.S puts it (0x78000000: XNU keeps the RAM above 0x80000000 in one piece)
        h = work / 'XnuLoader.h'
        h.write_text(sub1(h.read_text(), '#define XNU_PAYLOAD_BASE      0xF0000000ULL',
                          '#define XNU_PAYLOAD_BASE      0x78000000ULL', 'XnuLoader.h'))
        shutil.copytree(work, lib)
    if 'XnuLoaderMain ()' not in (lib / 'BootManager.c').read_text() or 'XnuLoader.c' not in (lib / 'BootManagerLib.inf').read_text():
        raise SystemExit('BootManagerLib: willow-hackios patch did not give the XNU loader hook')
    dsc = dst / 'doha.dsc'
    t = dsc.read_text()
    # The [LibraryClasses] of doha.dsc come after the SiliciumPkg include, so this mapping is the one used.
    t = sub1(t, '  MemoryMapLib|dohaPkg/Library/MemoryMapLib/MemoryMapLib.inf\n',
             '  MemoryMapLib|dohaPkg/Library/MemoryMapLib/MemoryMapLib.inf\n'
             '  PlatformBootManagerLib|dohaPkg/Library/BootManagerLib/BootManagerLib.inf\n', 'dsc')
    dsc.write_text(t)
    print(f'BDS starts the XNU loader: BootManagerLib from willow-hackios {base[:8]} + its patch')


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

    # Kept out of the UEFI's memory: TrustZone's regions (the doha xbl's TzAppsRegnAddr = 0x46D00000; Android's
    # removed_region covers 0x46200000 to 0x48F00000), and the 64 MiB where the shim puts an XNUP payload.
    mm = dst / 'Library/MemoryMapLib/MemoryMapLib.c'
    t = mm.read_text()
    t = sub1(t, '  {"SMEM",              0x46000000, 0x00200000, AddMem, MEM_RES, WRITE_COMBINEABLE, Reserv, UNCACHED_UNBUFFERED_XN},\n',
             '  {"SMEM",              0x46000000, 0x00200000, AddMem, MEM_RES, WRITE_COMBINEABLE, Reserv, UNCACHED_UNBUFFERED_XN},\n'
             '  {"QTEE",              0x46200000, 0x00B00000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},\n'
             '  {"TZApps",            0x46D00000, 0x02200000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},\n', 'memory map')
    t = sub1(t, '  {"Info Blk",          0x5FFFF000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP, RtData, WRITE_BACK_XN},\n',
             '  {"Info Blk",          0x5FFFF000, 0x00001000, AddMem, SYS_MEM, SYS_MEM_CAP, RtData, WRITE_BACK_XN},\n'
             '  {"XNU Payload",       0x78000000, 0x04000000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, WRITE_BACK_XN},\n', 'memory map')
    mm.write_text(t)

    # DOHA_WILLOW=path to a willow-hackios tree: BDS starts its XNU loader from the payload (see add_xnu_boot).
    if os.environ.get('DOHA_WILLOW'):
        add_xnu_boot(mu, dst, Path(os.environ['DOHA_WILLOW']))

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
