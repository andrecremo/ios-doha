# ios-doha

Experimento: XNU + userland do iOS no Moto G8 Plus (`doha`, SM6125 "trinket"), a partir de
[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) (MIT) e da série ARMv8.0 de
[wardevsa/ios-a5xelte](https://github.com/wardevsa/ios-a5xelte/tree/herolte). Plano completo em
[`docs/PLANO.md`](docs/PLANO.md).

## Milestone 1: shim de diagnóstico

`shim/` roda direto no lugar do kernel, com o MMU desligado, e mostra na tela:

- o formato do framebuffer que o ABL deixou (lido do pipe do MDP)
- registradores de CPU: granule de 16K, LSE, PAN, MIDR/MPIDR
- versão do PSCI e `CPU_ON` dos 7 núcleos secundários (MIDR de cada um)
- interrupções GICv3: timer virtual (INTID 19) e SGI

Depois de 90 s grava "bootloader" no restart_reason e reinicia no fastboot. Não grava nada no
eMMC. Fundo **verde** = rodando; **vermelho** = exceção (a tela mostra ESR/ELR/FAR).

### Build (WSL/Linux, precisa de `aarch64-linux-gnu-gcc` e `python3`)

```sh
python3 tools/unpack_bootv2.py /mnt/c/Users/andre/backup/boot_a.img dtb/boot_a_unpacked
bash shim/build.sh          # -> shim/out/shim-boot.img
```

`tools/mkbootimg_v2.py` substitui o mkbootimg do AOSP. Testado: refazendo o `boot_a` com ele, só
o campo `id` (hash SHA-1) difere.

### Boot

```sh
adb reboot bootloader
fastboot boot shim-boot.img
```

`fastboot boot` só carrega na RAM. Se travar: segure Power + Volume para baixo ~10 s.

## Fora do git

`dtb/` (o `/chosen` do DTB ao vivo tem serial e MACs), backups de partições, imagens da Apple.
