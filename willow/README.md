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
| `0001` | A platform of its own for doha in `xnuloader/loader.c`. The loader tells devices apart by the framebuffer base, which doha's UEFI shares with willow (`0x5C000000`), so it now also compares the height (2280 on doha, 2340 on willow). doha gets willow's SoC values (I/O window, GIC, clusters) and nothing of willow's board: no partition to write, no OSM, no RPM voltages, no touch panel. With no logdump and no USB link to the loader yet, its screen is the only log on doha, so the loader leaves it up 30 s before its final reset. In the kernel, `device=doha` uses the SM6125's timer interrupt like willow (`gic_v3_irq.c`), and has its own row of buttons (`redwood_buttons.c`: the PM6125's power-on block for power and volume down, GPIO9 of the PM6125 for volume up, read from doha's device tree). |

## Starting the loader from doha's UEFI

willow-hackios does it with `uefi/mu-silicium.patch` (boot shim and `BootManagerLib`). The doha does the same
without changing either tree:

- `uefi/DohaShim.S` copies an "XNUP" container that follows the UEFI image to `0xF0000000`;
  `uefi/mkdohaimg.py OUT ... PAYLOAD.bin` appends it and raises the Image's size;
- `uefi/mkdohapkg.py` adds the `QTEE`, `TZApps` and `XNU Payload` regions to the memory map, and with
  `DOHA_WILLOW=<willow-hackios tree>` makes `dohaPkg/Library/BootManagerLib` from willow-hackios's Mu-Silicium base
  with its patch and its `XnuLoader.c`: when BDS has nothing to boot, it starts `loader.efi` from the container;
- `uefi/build-doha.sh` takes `DOHA_WILLOW` and `DOHA_PAYLOAD` (the image is then `doha-uefi-DEBUG-xnu.img`).

Not to be used on doha: `gpu=1` (the redwood GPU driver decides by the SoC base, which doha shares with redwood),
`osm=`, `ufs_write=`, `touchscreen=1` (willow's Novatek panel; doha has a FocalTech FT8719), and anything from
`prebuilt/`.

Not done yet: the loader's log, which goes to a `logdump` partition doha does not have.
