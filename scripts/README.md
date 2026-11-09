# Building iOS for the doha

What was run to get iOS 16.5 to the home screen on the Moto G8 Plus, in WSL (Ubuntu 24.04), in this order. The
willow-hackios tree lives at `~/doha-xnu/willow-doha` (its `main` at `796e42b` plus `../willow/patches/0001-doha.patch`,
and its `userland` branch at `0ffde01` checked out into the same tree, as its `common/setup.sh` does). Nothing from Apple,
from the phone or from willow-hackios is in this repository: the scripts fetch or take it where it is.

| Script | What it does |
|---|---|
| `regen-patch.sh` | Resets `~/doha-xnu/willow-doha` to `796e42b` (**`git reset --hard`**: local changes there are lost), applies `doha_willow_edit.py` (the doha's changes, each checked to apply exactly once; it adds `redwood_focaltech.c`), commits and writes `../willow/patches/0001-doha.patch` |
| `run-doha-kernel.sh` | Builds the kernel (theos with `iPhoneOS16.5.sdk` in `~/theos`; `xnu-build.sh -k`) |
| `run-ios-fetch.sh` | Brings in willow-hackios's userland and fetches the parts of the iOS 16.5 IPSW it needs from Apple's CDN (7-Zip 23: `sudo apt install -y 7zip`) |
| `run-ios-flash.sh` | Makes the 8.4 GB image for `userdata`, the small images (with `GL=1`, Mesa too) and the UEFI image `doha-uefi-DEBUG-xnu.img` with the command line; `DOHA_FILES` is where the phone's own firmware and the image are kept |
| `doha_userland_edit.py` | Puts the FT8719's firmware into the small image and gives `var_store` doha's store (`../willow/patches/userland/`) |

`run-ios-flash.sh` options: `GL=1` (the GPU: `gpu=1 fb_gpu=1 glasync=1`, Mesa), `HUD=1` (the status panel), `VERBOSE=1`
(the kernel's console), `CPUMASK=` / `CPUS=` (default `cpumask=0x15`, the Silver cores), `OSM=0`, `TOUCH=0`, `MEMMAP=1`, `PERSIST=1` (keep `/private/var`: `ufs_write=1 var_store=1
var_save_every=120`, `SAVE_EVERY=` seconds).

The phone's files the build takes from `DOHA_FILES`: `vendor-firmware/` (`/vendor/firmware` of `vendor_a`, EROFS) and
`modem-image/` (`image/` of `modem_a`, ext4), both copied read-only from Lineage's recovery. Writing `userdata` and the
reasons `boot_a`/`boot_b` hold the UEFI: `../NOTES.md`.
