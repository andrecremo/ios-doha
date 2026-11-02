# ios-doha: plano de port do iOS para o Moto G8 Plus (doha, SM6125)

Atualizado em 2026-11-02. Clones de referência em `refs/` (clones locais, fora do repo):

| Repo | Aparelho | Para que serve aqui |
|---|---|---|
| [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) (MIT) | Redmi Note 10 Pro, SM7150 | Tudo o que é **Qualcomm**: GICv3, PSCI via `smc`, UFS, GENI I²C, SPMI, RPMh, `fastboot boot` |
| [wardevsa/ios-a5xelte](https://github.com/wardevsa/ios-a5xelte/tree/herolte), branch `herolte` | Galaxy S7 (Exynos 8890) e Galaxy A5 2016 (Exynos 7580) | Tudo o que é **ARMv8.0 / Cortex-A53**: páginas de 4K, sem LSE, sem PAN, driver eMMC |
| [ry-diffusion/Bergamota](https://github.com/ry-diffusion/Bergamota) | Poco F1, SD845 | iOS 18 sem PAC (Renegade), USB/SMMU, pesquisa de GPU Adreno |

Pelo levantamento de forks do Bergamota (`docs/FORKS_SURVEY.md` do Bergamota) e pelo que vimos até
agora, **ninguém publicou um port para SM6125**. O post do Redmi 5 Plus (Snapdragon 625, só
Cortex-A53) no r/hackios seria o parente mais próximo, mas não consegui abri-lo.

## 1. A descoberta que muda o plano: páginas de 4K já funcionam

O maior risco do plano anterior era o A53/A73 não ter o granule de 16K que o XNU do iOS usa. O
port do Galaxy S7 confirma o problema e mostra a solução:

- O probe dele leu `ID_AA64MMFR0_EL1 = 0x1122` ("sin 16 KiB"). O A53 não tem 16K.
- A solução foi **páginas de VM de 16K sobre páginas de hardware de 4K** (`PAGE_RATIO 4`). Com isso o
  S7 chegou à tela inicial do iOS 16.7.16 com GPU (Mali via Panfrost), touch, bateria e 8 núcleos.
- Patches que fazem isso (em `xnu/patches/` do ios-a5xelte):

| Patch | O que faz |
|---|---|
| `0082-a5xelte-4k-entry` | Desliga o mapeamento inicial específico de 16K do sweet |
| `0084-a5xelte-4k-user-va` | Limite do espaço de endereços do usuário compatível com 4K |
| `0093-a5xelte-39bit-kernel-va` | Kernel em VA de 39 bits (TTBR1 com 4K), sem `ARM_LARGE_MEMORY` |
| `0094-a5xelte-cortex-a53-codegen` | `-mcpu=cortex-a53 -march=armv8-a+crypto` |
| `0095-a5xelte-disable-pan` | PAN é ARMv8.1, o A53 não tem |
| `0096-a5xelte-commpage-llsc` | Troca `casa` (LSE, ARMv8.1) por `ldaxr`/`stxr` no commpage |
| `0202-herolte-4k-unsigned-dyld-cache` | Aceita assinaturas de código de 16K com páginas de 4K |
| `0257-commpage-text-16k-aligned` | Alinha o commpage a 16K dentro de páginas de 4K |
| `0242-pmap-sync-page-attributes-above-4g` | Corrige truncamento de endereço físico acima de 4 GiB |

O A73 também é ARMv8.0 (sem LSE, sem PAN, sem 16K), então a mesma série deve servir para os dois
clusters do doha. Isso ainda precisa ser confirmado no aparelho.

**Estratégia:** partir da branch `herolte` (que já contém a série do sweet + ARMv8.0) e trazer de
volta as partes Qualcomm do sweet (GICv3, PSCI, UFS) que o S7 trocou por Exynos.

## 1.1 Confirmado no aparelho (adb, 2026-11-02)

- `Hardware: Qualcomm Technologies, Inc TRINKET`
- CPUs 0–3: implementer `0x51` part `0x801` (Kryo 260 Silver, derivado do A53), rev 4.
  CPUs 4–7: part `0x800` (Kryo 260 Gold, derivado do A73), rev 2. Todos `CPU architecture: 8`.
- Features: `fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid`. **Sem `atomics`** (sem LSE), então
  é ARMv8.0 puro: a série ARMv8.0 do herolte (`0094`–`0096`) é necessária.
- MIDR com implementer Qualcomm (`0x51`), não ARM (`0x41`). O sweet também roda em Kryo da Qualcomm,
  mas a identificação de CPU (`0101-a5xelte-cpu-identity`, `SweetCPU.cpp`) precisa aceitar `0x800`/`0x801`.
- Armazenamento: `/dev/block/platform/soc/4744000.sdhci` → **eMMC** no SDHCI v5 da Qualcomm.
  O driver UFS do sweet não serve; é preciso um driver SDHCI novo (ver risco 1).
- Firmware: `motorola/doha_retail/doha:10/QPIS30.28-Q3-28-26-4-1-3/f0a9a:user/release-keys`
  (Android 10, retail).
- **Medido no shim (2026-11-02, milestone 1 OK):** `ID_AA64MMFR0_EL1 = 0x1122`, **sem 16K**; sem
  LSE, PAN ou PAC; 8 núcleos ligam via PSCI; GICv3 + vtimer INTID 19 funcionam; framebuffer
  a8r8g8b8 em `0x5c000000`, stride 4320. Detalhes em `NOTES.md`.

## 1.2 Do DTB ao vivo (`/sys/firmware/fdt`, LineageOS, 2026-11-02)

Decodificado em `dtb/doha-live.dts.txt` (local) (com `tools/fdtdump.py`). **Privado:** o `/chosen` tem
serial e MACs do aparelho.

| Item | Valor no doha | Comparação com o sweet |
|---|---|---|
| Modelo | XT2019-2, `bootloader=MBM-3.0-doha_retail-f9b10e522bd-210929`, A/B (slot `_a`) | – |
| RAM (4 GB) | `0x40000000`+`0x3dd00000`, `0x80000000`+1 GiB, `0xc0000000`+2 GiB | Faixa limpa `0xc0000000`–`0x140000000` (2 GiB); começar com 1 GiB em `0xc0000000`, toda abaixo de 4 GiB |
| Carve-outs fixos | todos abaixo de `0x5f000000`, mais `ramoops` `0xaf000000` (0xbf800) e `mmi_annotate` `0xaefa1800` | – |
| Framebuffer do ABL | `cont_splash_region` `0x5c000000`, 15 MiB; painel 1080×2280, 60 Hz, vídeo | sweet: `0x9c000000`, 1080×2400. Formato (RGB888 ou 32 bpp) a medir no shim |
| GICv3 | GICD `0xf200000` (64K), GICR `0xf300000` (1 MiB, stride `0x20000`) | – |
| Timer | PPIs 1/2/3/0 → **vtimer INTID 19**, ptimer 18, 19,2 MHz | igual ao sweet |
| PSCI | 1.0, `smc` | igual |
| MPIDR | `0x0`–`0x3` (Silver), `0x100`–`0x103` (Gold): **Aff0 = core, Aff1 = cluster** | sweet usa Aff1 como core; herolte tem o mesmo esquema do doha (`0203-herolte-boot-mpidr`) |
| PSHOLD | `0x440b000` | sweet `0xc264000` |
| IMEM restart_reason | `0xc125000 + 0x65c` = `0xc12565c` | sweet `0x146aa65c` |
| eMMC | `qcom,sdhci-msm-v5` em `0x4744000` (+ CQE `0x4745000`, ICE `0x4748000`), 8 bits; Linux: HS400 ES, CMDQ, 58,2 GiB, `userdata` = `mmcblk0p80` | – |
| Touch | FocalTech **FT8719** (TDDI, touch e display no mesmo chip) em **SPI**, QUP0 SE2 `0x4a88000`, IRQ GPIO 88, reset GPIO 87 **compartilhado com o display** | sweet: Goodix em I²C. Existe variante Himax do doha |
| Painel | `tm_ft8719_fhd_vid` (Tianma, `mipi_mot_vid_tianma_1080p_630`) | – |
| Botões | Power: PM6125 PON (SPMI SID 0, `0x800`); volume: `gpio-keys` | sweet: PM6150 |

### boot.img (`boot_a`)
Header **v2**, page 4096, kernel `0x8000`, ramdisk `0x1000000`, tags `0x100`, **dtb `0x1f00000`**.
É o mesmo layout do `shim/build.sh` do sweet; basta trocar o DTB.

### Ideia de log: ramoops
O Lineage reserva `ramoops` em `0xaf000000`. Se o shim/XNU escrever o console nesse formato
(`persistent_ram_buffer`, assinatura `DBGC`), depois de um reboot para o Lineage o log aparece em
`/sys/fs/pstore/`. É um canal de debug sem cabo serial e sem recovery.

## 2. O que muda para o doha (SM6125)

Fonte: `sm6125.dtsi` do Linux mainline. ⚠ = confirmar no DTB do próprio aparelho.

| Item | sweet (SM7150) | herolte (Exynos 8890) | doha (SM6125) |
|---|---|---|---|
| CPUs | A55 + A76, ARMv8.2 | A53 + Mongoose, ARMv8.0 | Kryo 260: A53 + A73, **ARMv8.0** |
| Páginas | 16K | 4K hw / 16K VM | 4K hw / 16K VM (esperado) |
| GIC | v3 `0x17a00000` / `0x17a60000` | v2 | v3: GICD `0x0f200000`, GICR `0x0f300000` |
| Boot | `fastboot boot` | S-Boot carrega da partição BOOT | `fastboot boot` (esperado) ⚠ |
| RAM base | `0x80000000` + banco alto | 2º banco DRAM | `0x40000000` (tamanho vem do ABL) |
| Framebuffer | `0x9c000000` | DECON | `cont_splash_mem` `0x5c000000`, 15 MiB ⚠ |
| Armazenamento | UFS Qualcomm `0x1d84000` | UFS Exynos | **eMMC**, SDHCI v5 `0x4744000` (confirmado) |
| USB DWC3 | `0xa600000` | – | `0x4e00000`, PHY QUSB2 `0x1613000` |
| SMMU | `0x15000000` | – | `0x0c600000` (MMU-500) |
| I²C (GENI) | SE7 `0xa84000` | HSI2C Exynos | QUP0 `0x4a80000`–`0x4a90000`, QUP1 `0x4c80000`–`0x4c90000` |
| SPMI | sim | – | `0x1c40000` (core), `0x1e00000` (chnls) |
| Display | DSC video, splash | DECON/DSIM | MDP `0x5e01000`, DSI0 `0x5e94000` |
| Touch | Goodix GT9896 | Samsung sec_ts | desconhecido ⚠ |
| PSHOLD / IMEM | `0xc264000` / `0x146aa65c` | – | não está no mainline ⚠ |

## 3. Riscos que sobram

1. **eMMC (confirmado).** Precisa de um driver SDHCI v5 novo, no shim e no XNU. O driver do A5 2016
   (`0104-a5xelte-emmc-gpt-probe`, `bsd/dev/a5xelte_emmc.c`) é para o DesignWare da Samsung, mas a
   estratégia vale igual: o ABL deixa o eMMC inicializado (clocks, pads, user area selecionada),
   então começamos só lendo a GPT, sem reset e sem escrita, e a escrita vem depois (como no `0108`).
   O lado bom: SDHCI é um padrão aberto (SD Host Controller Spec 3.0/4.0). Os registradores são
   documentados, e o `sdhci-msm.c` do Linux mostra as particularidades da Qualcomm. Começar com PIO
   (sem DMA, então sem SMMU) e só depois passar para ADMA2.
2. **Hipervisor da Qualcomm (QHEE).** MMIO proibido ou DMA fora do SMMU reinicia o aparelho sem log.
   Por isso o console no framebuffer e o log persistente vêm primeiro.
3. **Memória.** O doha tem 4 GB. O S7 teve pânico com 2 GiB no 2º banco e usou 1–1,5 GiB. Começar
   com 1 GiB.
4. **Touch, botões e PMIC.** Drivers novos para o controlador do doha e para o PMIC dele.
5. **Desempenho.** Sem GPU no começo. A GPU (Adreno 610) é trabalho de longo prazo, como no Poco F1.

## 4. Fases

### Fase 0: coletar dados do aparelho (sem desbloquear nada)
- Pelo `adb` (sem root):
  - `adb shell cat /proc/cpuinfo`: "CPU part" `0xd03` = A53, `0xd09` = A73.
  - `adb shell ls /dev/block/platform/soc/`: `4804000.ufshc` = UFS, `4744000.sdhci` = eMMC.
  - `adb shell getprop ro.build.fingerprint`: versão exata do firmware.
- `boot.img` de fábrica da mesma versão: extrair com `tools/unpack_bootv2.py` para obter o DTB, o
  header version e os offsets. Decompilar com `dtc -I dtb -O dts` e anotar: memória,
  reserved-memory, cont_splash, touch (nó i2c com `compatible`), painel, PMIC, PSHOLD,
  `restart_reason` na IMEM.
- Backup **antes** de qualquer outra coisa: `persist`, `modemst1/2`, `fsg`, `fsc`, `boot`, `dtbo`,
  `vbmeta`.

### Fase 1: shim de diagnóstico no doha
- Desbloquear o bootloader (site oficial da Motorola; **apaga os dados**).
- Shim do sweet com os endereços do doha e o MMU em 4K (ver `shim/` do ios-a5xelte para o
  `mmu.c` com 4K). Imprimir no framebuffer: `ID_AA64MMFR0_EL1`, `ID_AA64ISAR0_EL1` (LSE), MIDR de
  cada núcleo, versão do PSCI, `CPU_ON` dos 7 secundários, IRQ do vtimer.
- `fastboot boot shim-boot.img`. Sucesso = texto na tela.

### Fase 2: XNU até o console
- Config de máquina `DOHA` = `A5XELTE`/`HEROLTE` (4K, ARMv8.0) + `HAS_GIC_V3 1` e PSCI do sweet.
- `mkadt.py` com os endereços do doha. Testar primeiro em QEMU (`-cpu cortex-a53`).
- Meta: log do XNU no framebuffer até a raiz em RAM-disk.

### Fase 3: armazenamento
- Driver SDHCI v5 para o eMMC, só leitura primeiro (no shim, depois no XNU no lugar de `sweet_ufs.c`).
- Raiz HFS+ em `userdata`.

### Fase 4: userland
- iOS 16.7.16 do iPhone X, igual aos três projetos (`mkiosroot.sh` + `sweet-root-tweaks.py`).
- Meta: SpringBoard na tela.

### Fase 5: entrada e extras
- Botões via SPMI, touch via GENI I²C, bateria, 8 núcleos.
- USB CDC-ECM para SSH (DWC3 + SMMU, `FORKS_SURVEY.md` seção A).
- Depois: cpufreq, GPU Adreno 610, iOS 18 via Renegade.

## 5. Do que precisamos agora

1. ~~As saídas dos três comandos `adb` da Fase 0.~~ Feito.
1b. ~~Firmware de fábrica~~ Não precisa mais: DTB ao vivo e `boot_a` puxados do LineageOS.
1c. Backup feito em `C:\Users\andre\backup`, faltando `fsg_a`/`fsg_b`.
2. O texto do post do Redmi 5 Plus (ou o link do código dele), se você conseguir copiar.
3. Um PC Linux (ou WSL2) para `aarch64-linux-gnu-gcc`, `mkbootimg` e `dtc`, e uma conta no GitHub
   para o build do XNU no CI macOS.
