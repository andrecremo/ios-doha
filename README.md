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

## Milestone 2: XNU até esperar a raiz (concluído em 2026-11-03)

No aparelho, o kernel sobe VM, IOKit, BSD e rede e para em `Waiting on ... IOMedia ... Apple_HFS`,
porque ainda não há armazenamento. Ainda não há userland do iOS. Detalhes em [`NOTES.md`](NOTES.md).

Kernel `DOHA` = a porta ARMv8.0/4K do ios-a5xelte (config `A5XELTE`) com o caminho Qualcomm do
ios-sweet: GICv3, vtimer INTID 19, framebuffer do ABL em `0x5c000000`, só a CPU 0, sem drivers
Exynos. O patch é [`xnu/patches/0400-doha-board-target.patch`](xnu/patches/0400-doha-board-target.patch);
o [`0402`](xnu/patches/0402-doha-gicd-are-before-gicr.patch) liga `ARE_NS` antes de configurar o
redistribuidor, porque o ABL do doha deixa o `GICD_CTLR` zerado.

### Kernel (GitHub Actions)

O workflow [`xnu`](.github/workflows/xnu.yml) roda a cada push em `xnu/patches/`, ou à mão:

```sh
gh workflow run xnu.yml
gh run download -n xnu-kernel-doha -D xnu/out
```

Ele baixa o darwin-xnu-build e a série de patches do ios-sweet/ios-a5xelte em commits fixos (a
branch `herolte` não tem licença, então não fica copiada aqui) e aplica os `04xx-doha-*` por cima.

### ADT, payload e boot.img

```sh
python3 tools/mkadt_doha.py out/doha.adt          # 1 GiB em 0xc0000000, GICv3, fbcon
python3 tools/mkpayload.py xnu/out/kernel.development.doha out/doha.adt out/payload.bin \
    --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress wdt=-1'
bash shim/build.sh ../out/payload.bin             # payload vira o ramdisk do boot.img
```

O shim acha o payload no ramdisk, copia kernel + ADT + boot_args para `0xc0000000` e pula para o
XNU com o MMU desligado. A meta deste milestone é o log do XNU aparecer na tela.

## Fora do git

`dtb/` (o `/chosen` do DTB ao vivo tem serial e MACs), backups de partições, imagens da Apple.
