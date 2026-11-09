# doha on willow-hackios

The doha's next base is [willow-hackios](https://github.com/Floppikrob/willow-hackios) (Redmi Note 8T, the same
SM6125 SoC): Mu-Silicium UEFI, its XNU loader and its XNU 8796. This directory holds only our changes to it, as
patches on top of its commit `796e42b`; the upstream code stays upstream. Those files are under the Apple Public
Source License 2.0 (willow-hackios's LICENSE), and so are the changes to them.

```sh
git clone https://github.com/Floppikrob/willow-hackios
cd willow-hackios && git checkout 796e42b && git am path/to/ios-doha/willow/patches/*.patch
```

| Patch | What it does |
|---|---|
| `0001` | A platform of its own for doha in `xnuloader/loader.c`. The loader tells devices apart by the framebuffer base, which doha's UEFI shares with willow (`0x5C000000`), so it now also compares the height (2280 on doha, 2340 on willow). doha gets willow's SoC values (I/O window, GIC, clusters) and nothing of willow's board: no partition to write, no RPM voltages, no touch panel. `osm=1` works on doha too, asking for a row of the OSM table doha's own firmware wrote, and only for a cluster whose OSM the firmware has on (Silver; Gold is left at 300 MHz) and a row between 300 and 2100 MHz. With no logdump and no USB link to the loader yet, its screen is the only log on doha, so the loader leaves it up 30 s before its final reset. In the kernel, `device=doha` uses the SM6125's timer interrupt like willow (`gic_v3_irq.c`), and has its own row of buttons (`redwood_buttons.c`: the PM6125's power-on block for power and volume down, GPIO9 of the PM6125 for volume up, read from doha's device tree). |

## Starting the loader from doha's UEFI

willow-hackios does it with `uefi/mu-silicium.patch` (boot shim and `BootManagerLib`). The doha does the same
without changing either tree:

- `uefi/DohaShim.S` copies an "XNUP" container that follows the UEFI image to `0xF0000000`;
  `uefi/mkdohaimg.py OUT ... PAYLOAD.bin` appends it and raises the Image's size;
- `uefi/mkdohapkg.py` adds the `QTEE`, `TZApps` and `XNU Payload` regions to the memory map, and with
  `DOHA_WILLOW=<willow-hackios tree>` makes `dohaPkg/Library/BootManagerLib` from willow-hackios's Mu-Silicium base
  with its patch and its `XnuLoader.c`: when BDS has nothing to boot, it starts `loader.efi` from the container;
- `uefi/build-doha.sh` takes `DOHA_WILLOW` and `DOHA_PAYLOAD` (the image is then `doha-uefi-DEBUG-xnu.img`).

Not to be used on doha: `ufs_write=`, and anything from
`prebuilt/`.

The patch also adds doha's touch screen, `bsd/dev/redwood_focaltech.c` (`touchscreen=1` with `device=doha`): a
FocalTech FT8719 on the same SPI engine and pins as willow's Novatek, its protocol from Motorola's GPL driver
(`focaltech_0flash_mmi`). It has no flash; the driver loads the phone's own firmware
(`/vendor/firmware/focaltech-ft8719-a0-0000-doha.bin`, not in this repository) into its RAM without touching its reset
line, which is the panel's too. `patches/userland/0001-doha-ft8719-firmware.patch` (on willow-hackios's `userland`
branch, `0ffde01`) puts that file into the small image as `fw/focaltech_ts_fw.bin` from `fw-touch/`.

`gpu=1` works on doha too: the patch lets `redwood_a610.c`, `redwood_rpm.c` and `redwood_osm.c` take `device=doha`,
keeps `redwood_adreno.c` (redwood's Adreno 642L) off as on willow, and puts the zap shader where doha's device tree has
its `gpu_region` (`0x57115000`; willow's is `0x57515000`). The firmware is the phone's (`a610_zap.*` from its `modem`
partition, `a630_sqe.fw` from `/vendor/firmware`), in `fw-a610/`. With a `GL=1` small image and `gpu=1 fb_gpu=1
fbwidth=1080 fbheight=2280` the home screen draws in 35-99 ms a frame instead of 1749.

Not done yet: the loader's log, which goes to a `logdump` partition doha does not have.
