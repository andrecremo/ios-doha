# ios-doha: diário de engenharia

Observações medidas ficam separadas de suposições. Cada boot ganha uma entrada.

## Aparelho

Moto G8 Plus XT2019-2 (LATAM, `retbr`), 4 GB, eMMC 58,2 GiB, A/B (slot `_a`), bootloader
`MBM-3.0-doha_retail-f9b10e522bd-210929` desbloqueado, LineageOS (boot header v2, os 15.0.0 /
2025-04). Backups locais, fora do git (persist, modemst1/2, fsg_a/b, fsc, boot, dtbo, vbmeta).

## 2026-11-02, boot 1: milestone 1 (shim de diagnóstico), SUCESSO

`fastboot boot doha-shim-boot.img` (shim/ desta data, MMU desligado). Tela verde, sem exceção.
Valores lidos da foto:

| Item | Valor | Leitura |
|---|---|---|
| MDP | pipe 0 (VIG0), addr `0x5c000000`, 1080×2280 (`0x438`×`0x8e8`) | splash do ABL continua em scanout |
| Formato | `SRC_FORMAT 0x000237ff`, `UNPACK 0x03020001`, `YSTRIDE0 0x10e0` (4320) | **a8r8g8b8, 4 bytes/pixel**, bytes B,G,R,A: o mesmo do sweet |
| DTB | `0x454fd000`, magic `d00dfeed` | ABL passa o FDT em x0 |
| EL | 1, CNTFRQ `0x124f800` (19,2 MHz) | |
| MIDR boot | `0x51af8014`: Qualcomm, part `0x801` (Kryo 260 Silver), r a p4 | |
| MPIDR boot | `0x80000000` → CPU 0 (Aff0 = 0) | |
| MMFR0 | `0x1122`: PARange 40 bits, ASID 16 bits, **TGran16 = 0 (sem 16K)**, 4K e 64K sim | igual ao Exynos do S7 |
| MMFR1 / MMFR2 | `0` / `0` | sem PAN, sem VHE, sem HAFDBS |
| ISAR0 | `0x11120`: AES+PMULL, SHA1, SHA2, CRC32, **atomic = 0 (sem LSE)** | |
| ISAR1 | `0` | sem PAC, sem LRCPC, sem DPB |
| PFR0 | `0x1002222`: EL0–3 AArch64+AArch32, FP/SIMD, **GIC sysreg = 1** | |
| CTR_EL0 | `0x84448004`: linha de cache I/D de 64 bytes | |
| PSCI | versão 1.0, SMCCC 1.1; `CPU_ON` suportado, `SYSTEM_RESET2` não | |
| SMP | CPU_ON ret 0 nos 7; CPUs 1–3 MIDR `0x51af8014` (Silver), CPUs 4–7 `0x51af8002` (Gold, part `0x800` r a p2) | MPIDR `0x1–0x3`, `0x100–0x103` |
| GICD_CTLR | era `0`, depois de escrever `0x13` lê `0x12` | igual a como o Linux deixa |
| GICR | `0x0f300000` (CPU 0), WAKER `0` depois do wake | |
| vtimer | 29 IRQs (`0x1d`) em ~300 ms com período de 10 ms, INTID 19 (`last=0x13`), nenhuma outra | Group 1 IRQ, como no sweet |
| SGI 1 | 10 de 10 | |

Conclusões:
1. **Sem 16K**: o XNU do doha precisa de páginas de hardware de 4K sob páginas de VM de 16K,
   como no herolte/a5xelte (`0082`, `0084`, `0093`, `0202`, `0257`).
2. **ARMv8.0 puro** nos dois clusters (sem LSE, PAN, PAC, LRCPC): série `0094`–`0096` do a5xelte.
3. **GICv3, PSCI, timer e framebuffer** se comportam como no sweet: o caminho Qualcomm do sweet
   serve com outros endereços. O framebuffer tem o mesmo formato do sweet (`0003`/`0010` com
   base `0x5c000000` e 1080×2280).
4. Os 8 núcleos ligam via PSCI. A topologia é a do herolte (`0203`: Aff1 = cluster).

Correção: o padrão `FB_BPP` do console passou de 3 para 4 (só usado se a leitura do MDP falhar).

## 2026-11-02: milestone 2, kernel DOHA compila

`xnu/patches/0400-doha-board-target.patch` sobre a série herolte de ios-a5xelte
(`1fc7467e`). DOHA = `ARM64_BOARD_CONFIG_A5XELTE` + `ARM64_BOARD_CONFIG_DOHA`:
- 4K hw/16K VM, `-mcpu=cortex-a53`, sem PAN, commpage LL/SC (herdado de A5XELTE)
- `HAS_GIC_V3 1` e as definições GICv3 de SWEET.h; os caminhos GICv2 de sleh.c e SweetCPU.cpp
  passaram a `A5XELTE && !HAS_GIC_V3`; `ICC_SRE_EL2` liberado no caminho EL2 de start.s
- framebuffer `0x5c000000` 1080×2280 stride 4320 (5 blocos de 2 MiB), marcador inicial em
  `0xaf000100` (região ramoops), boot MPIDR `0x0`, `SWEET_SMP_MAX_CPUS 1`
- teclas/touch/eMMC/UFS/GPU do Exynos desligados em IOKitBSDInit
- correção de commpage 16K do HEROLTE também para DOHA

CI: run 41497994045 falhou só em `sleh.c` (`sweet_vtimer_intid` declarado apenas para
`ARM64_BOARD_CONFIG_SWEET` em protos.h). Corrigido; run 41500864255 OK em 17 min, sem LSE.
`kernel.development.doha` sha256 `eafabe05…b81492d`.

Payload: virt_base `0xfffffff006000000` → phys `0xc0000000`, entry `0xfffffff007424488`,
kernel_end `0xfffffff0084a4000` (~36 MiB a partir da base). ADT: 1 GiB em `0xc0000000` menos
1 MiB de `/pram` (`0xfff00000`). Sem `/product` (falta o d22ap.adt), o que não importa até o
userland. boot.img com payload: 17,9 MB.

Não testado em QEMU (sem qemu no WSL): foi direto para o aparelho.

## 2026-11-03, boot 2: XNU no aparelho, milestone 2 atingido

`fastboot boot doha-xnu-boot.img` (kernel sha256 `eafabe05…`, 1 GiB, `cpus=1`). O console do XNU
aparece no painel, em 1080×2280 e legível. Lido da foto (a tela é circular: a parte de baixo é
mais antiga):
- VM e zonas sobem (`zone_init`, `kmem_large_ranges`, `vm_compressor_mode` 4, "VM bootstrap done")
- `iBoot version: doha-shim`, ou seja, o ADT foi lido
- PRNG, libpthread 514.100.2, AMFI embutido e vnguard registrados; trust caches indisponíveis (esperado)
- `A5XELTE: platform expert registered`; AppleKeyStore, IOWatchdog, IOCoreSurfaceRoot e HID registrados
- `SWEET FB: AppleCLCD 1080x2280 stride 4320 at 0x5c000000`
- `ml_processor_register` no cluster 0; `A5XELTE CPU: requested=1 selected=1`
- última linha: `cpu=0 entered initCPU mpidr=0x0 EL1 IRQs=1`

Sem panic na foto. Observações:
- Não há driver de armazenamento nem RAM disk, então nenhuma raiz é possível. Falta saber se o
  kernel segue vivo esperando a raiz ou se travou depois de `initCPU`: a foto é um instante só.
- A faixa verde no pé da tela é resto do shim, abaixo da última linha de texto do console.
- As mensagens ainda dizem `A5XELTE`/`SWEET` porque o DOHA reaproveita esses caminhos.

## 2026-11-03, boot 3: timer sem interrupção, kernel com diagnóstico (0401)

A tela parou de vez depois do `initCPU`, sem `came alive` e sem o panic de 5 s. Com o 0401, a
última linha é `DOHA pre: IOSleep(1)`, antes de `processor_start`. Valores lidos da foto:

| | pre1 | pre2 (1 s depois) |
|---|---|---|
| irq | t=0 s=0 o=0 sp=0, IE=1 | igual |
| ICC | pmr=f0 rpr=ff grp1=1 hppi=3ff isr=0 daif=200 | igual |
| CNTV | ctl=1 cval=`1a4e034b` vct=`1a4b373d` | ctl=**5** cval igual vct=`1b7058ea` |
| GIC | ctlr=12 waker=0 **en=0** pend=`8200000` act=0 | igual |

Leitura:
- O decrementer está armado certo: `cval` fica ~9,5 ms à frente em pre1, e em pre2 o timer disparou.
- `en=0` e o bit 19 não pendente: o GIC não recebeu a configuração do timer. Nenhuma interrupção
  de timer chegou desde o boot.
- `ctlr=12` e `grp1=1` mostram que `pe_init_fiq` rodou até o fim, então a escrita em
  `GICR_ISENABLER0` foi executada e não ficou.
- O shim leu `GICD_CTLR` = 0 na entrada (boot 1) e escreve o GICD *antes* do GICR: lá funcionou.
  O XNU escreve o GICR primeiro e o GICD no fim. O comentário de pe_fiq.c diz que no sweet o ABL
  deixa `ARE_NS` ligado, o que não acontece no doha.

Hipótese (fortemente sugerida, ainda não confirmada): sem `ARE_NS`, os registradores SGI_base do
redistribuidor ignoram escritas. Correção em `0402-doha-gicd-are-before-gicr.patch`: ligar
`ARE_NS` + Grp1 antes de configurar o GICR.

## 2026-11-03, boot 4: milestone 2 concluído, XNU espera a raiz

`fastboot boot doha-xnu-are.img` (kernel sha256 `11052f00…`, com 0401 + 0402). A hipótese do
`ARE_NS` se confirmou. Lido da foto:
- `en=80002` (vtimer + SGI1), `post2 irq t=386 s=1 o=0 sp=0 last=19`, IE=1, grp1=1
- `DOHA post: IOSleep returned`, `cpu=0 mpidr=0x0 came alive; SGI1 OK`, `1/1 CPUs initialized`
- AMFI e Sandbox substitutos e `hfs-627.100.6` registrados; `mcache: 1 CPU(s), 64 bytes`
- `mbinit` (64 MB), `dlil_init`, self-tests do Skywalk `PASSED`, `lo0`/`gif0`/`stf0` anexados
- `bsd_autoconf: calling kminit`
- fim: `Waiting on <dict>...IOProviderClass IOMedia...Content Apple_HFS...` e
  `Failed to write boot-picker-bringup-reason to NVRAM.` (não há NVRAM)

Sem panic. A parada é a esperada: não há dispositivo de raiz. Nesta foto, o console ainda mostra
os dumps do 0401.

Próximo: raiz. Um RAM disk não comporta o shared cache do iOS (GBs) em 1 GiB de RAM; serviria só
para testar um init mínimo. O caminho real é o driver SDHCI do eMMC, só leitura primeiro: listar
a GPT sem gravar nada. Gravar a raiz em `userdata` apaga o Android e exige confirmação antes.
O 0401 pode sair quando o próximo kernel for compilado (custa ~4 s de espera a cada boot).

## 2026-11-03, boots 5 e 6: eMMC lido no shim (milestone 3, primeira etapa)

Boot 5 (só leitura de registradores): `ver=7202`, `caps=742dc8b2`, `pres=01f800f0`, `ctl1=0`,
`ctl2=0`, `clk=3`, `en=0`. O ABL deixa o host resetado: clock interno ligado, clock do cartão e
energia do barramento desligados.

Boot 6 (`shim/sdhci.c`, inicialização completa, sem comando de escrita):
- GCC antes: `apps=4221`, `ahb=1`, RCG `cfg=401` (GPLL6 / 1 = 384 MHz, a taxa de HS400).
  `spec=00300a0c`. A escrita do RCG para 400 kHz foi aceita, sem reset do hipervisor.
- Pedidos de energia confirmados: `st=2` (bus on) e `st=4` (IO low).
- `clk=000e0005`, `pres=03f800f0`, `OCR=c0ff8080` (pronto, setores), `r1=900`, estado 4 (tran).
- `EXT_CSD`: `sectors=0747c000` = 58,24 GiB, partição de usuário. Bate com os 58,2 GiB do Linux.
- GPT: `my=1`, `alt=0747bfff` (último setor), entradas em LBA 2, `n=80`, `used=77`.
  Os 3 vazios são p69, p70 e p71, justamente os que faltam no `/dev/block/by-name`.
- Partições, batendo com o Linux: `persist` p46 LBA `104200`, `boot_a` p53 LBA `12c700`,
  `userdata` p80 LBA `1118000`.

`BOOT_A magic MISMATCH` no boot 6 veio de um erro na constante de `OID!`, não da leitura.

Boot 7 confirma, com a constante corrigida: `ANDROID! magic OK`, `w0=52444e41`, `w1=2144494f`,
`w2=00d7e5f1`. São os mesmos 3 primeiros valores do backup `boot_a.img`, incluindo o tamanho do
kernel, então a leitura de dados pelo eMMC está certa. Só o início de um setor foi comparado.

## 2026-11-03, boot 8: eMMC em 8 bits e HS a 50 MHz

`CMD6` em `BUS_WIDTH`=2 e `HS_TIMING`=1, ambos com `r1=900` (sem erro de switch). RCG
`cfg=20b`. Depois de cada etapa, o EXT_CSD relido mostra os valores novos e `sec=0747c000`.

1 MiB do início do `boot_a`, um `CMD17` por setor, em PIO e com MMU desligado: `ms=1f0` (496 ms,
~2 MiB/s). Soma de 32 bits `fa62bcb9`, igual à do `boot_a.img`.

## 2026-11-04, boot 9: XNU lê o eMMC (0403)

`fastboot boot doha-xnu-emmc.img` (kernel sha256 `91399a70…`, `emmcprobe=1`, sem o 0401). Lido
da foto, sem panic, antes de `Waiting on ... IOMedia ... Apple_HFS`:
- `probe, no writes; ver=0x7202 clk=0x3`, `OCR 0xc0ff8080`, `122142720 sectors`
- `8-bit HS 50 MHz, width=2 hs=1`
- `GPT entries at LBA 2, 80 of 128 bytes`, `77 partitions`
- `p46 persist LBA 1065472..1131007` (32 MiB, o tamanho do backup)
- `p53 boot_a LBA 1230592..1361663` (64 MiB, o tamanho do backup)
- `p80 userdata LBA 17924096..122142686` (~49,7 GiB)
- `1 MiB of boot_a in 438 ms, sum32 0xfa62bcb9`, igual ao backup

O driver roda sob o MMU, com os mesmos registradores do shim, e o hipervisor não reclamou. Ele
ainda é só uma sonda: não há dispositivo de bloco.

## 2026-11-04, boot 10: ADMA2 e CMD18 no shim

`shim/sdhci.c`: 16 MiB de uma vez, ADMA2 de 32 bits, chunks de 32 KiB, auto CMD12, da LBA do
`boot_a` para `0xc0100000`, com MMU desligado.
- `DMA ms=169` (361 ms, ~44 MiB/s). Soma `4ddcf87c`, igual aos 16 MiB iniciais do backup.
- SMMU: `cr0=00270406`, `smrs=0x36` (54). Stream do eMMC: `smr=80000160`, `s2cr=00000000`.

Atenção: `s2cr` tipo 0 é **tradução, pelo context bank 0**, e não bypass como o device tree
sugeria. O DMA chegou aos endereços certos, então o bank 0 deve estar desligado ou ser identidade
nessa faixa, mas isso não foi lido, e `cr0` tem `USFCFG` ligado (stream sem SMR gera falha). Só a
faixa `0xc0000000..0xc1100000` foi comprovada. Conferir o SCTLR do bank 0 se o DMA falhar em
outro endereço, especialmente acima de 4 GiB.

## 2026-11-04, boot 11: disco `emmcroot0` reinicia o aparelho antes do driver

Kernel `82eadf1f…`, `emmcprobe=1 rd=emmcroot0 emmcroot=boot_a`. O aparelho reinicia. Última linha
fotografada: `A5XELTE CPU: 1/1 CPUs initialized, SGI1 verified`. Nenhuma linha `DOHA EMMC`,
que no boot 9 só vinham muito depois (MAC, mbinit, dlil, Skywalk). A foto é um instante, então o
reset pode ter vindo um pouco depois da última linha, mas não há sinal de que o driver tenha rodado.

Bug achado na revisão (no fonte local, ainda não compilado): `HC_ADMA_ADDR` era programado uma vez
só, e o host o avança a cada transferência. Agora é programado em cada leitura.

## 2026-11-04, boot 12: varredura de DMA no shim, DMA descartado como causa

`SWEEP all addresses OK`: 64 KiB com a soma certa em `c8000000`, `d0000000`, `e0000000`,
`f0000000` e `ffe00000`, com a tabela de ADMA no mesmo lugar.
- SMMU: `cr0=002f0406` (no boot 10 era `00270406`: o bit 19 muda entre boots, sem explicação),
  `smr=80000160`, `s2cr=0`.
- **Bank 0: `sctlr=000000e0`, bit M = 0, desligado**; `tcr=0`, `ttbr=0`. Então não há tradução de
  estágio 1 para o eMMC, ao menos neste estado.

## 2026-11-04, boots 13 e 14: causa do boot 11

Mesmo kernel `82eadf1f…`, só mudando boot-args:
- Sem `emmcprobe` e sem `rd`: para em `Waiting on`, sem reset.
- Só `emmcprobe=1`: `DMA at 0xc3e64000`, `8-bit HS 50 MHz`, e então
  `read lba 2 n 20 failed: 5 int=0x2008100 adma=0x0`, `probe failed: 5`. Para em `Waiting on`,
  sem reset. A leitura da LBA 1, a primeira por DMA sob o MMU, passou na checagem do GPT.

`int` tem o bit 25 (erro de ADMA) e `lba 2` é a segunda transferência: é o bug do `HC_ADMA_ADDR`.

Causa provável do boot 11 (dedução, a confirmar): com `rd=emmcroot0` o mesmo erro faz
`doha_emmc_rootdev` falhar, e o `panic` em `IOFindBSDRoot` reinicia o aparelho. Era errado concluir
pela foto do boot 11 que o reset vinha antes do driver: a foto era só um instante do boot.

Correções no 0403: `HC_ADMA_ADDR` em cada leitura, e 30 s na tela antes desse panic.

## 2026-11-04, boot 15: disco `emmcroot0` lido pelo HFS (0403 corrigido)

`doha-xnu-disk2.img`, `emmcprobe=1 rd=emmcroot0 emmcroot=boot_a`. Sem reset. Lido da foto:
- `p53 boot_a LBA 1230592..1361663`
- `16 MiB of boot_a: 363 ms in reads, sum32 0x4ddcf87c`, igual ao backup; `with the sum, 371 ms`.
  Sob o MMU, com cache e a manutenção de cache: ~44 MiB/s, o mesmo do shim.
- `BSD root: emmcroot0, major 1, minor 0`
- `hfs_ValidateHFSPlusVolumeHeader: unknown Volume Signature : 0`,
  `hfs_mount returned error=22`, `cannot mount root, errno = 19`, `mount(N) failed`

O HFS leu pelo disco e recusou o conteúdo, como esperado: o `boot_a` não é HFS, e os bytes 1024 e
1025 do backup, onde fica a assinatura, são zero. O loop é a repetição de montagem do próprio
XNU, que reexecuta o `emmcprobe` a cada tentativa. O reset do boot 11 não se repetiu com a correção do ADMA, o que combina
com a dedução anterior, sem prová-la.

Milestone 3 cumprido para leitura. Ainda não testados: montar um volume HFS de verdade e um
caminho de escrita, que o iOS vai precisar (raiz read/write).

Depois:
1. Imagem HFS de teste em `system_b`, o slot inativo, o que mantém o LineageOS no `_a` (grava no
   eMMC: confirmar antes; conferir o tamanho e o uso de `system_b` pelo LineageOS).
2. Caminho de escrita limitado à partição escolhida (`CMD25`).
3. Raiz em `userdata`: apaga o LineageOS; confirmar antes.

## 2026-11-04, boot 16: raiz HFS real montada; o kernel procura o launchd

`system_b` (p79) não é espaço livre: é a cópia do sistema do slot `_b`, com hash igual ao de
`system_a` (prefixo `4ab9d8d9f0be0245`) e sem dynamic partitions. Restaurável a partir do `system_a`.

`fastboot flash system_b` recusou: `(bootloader) Preflash validation failed`. Causa não
identificada. A imagem de teste (64 MiB, HFSX vazio, `mkfs.hfsplus -s -v DOHATEST`, sha256
`631c24576920aac7…`) foi gravada com `dd` pelo LineageOS, com `adb root`.

Enquanto o teste estiver gravado, o slot `_b` não inicia. Para restaurar, no LineageOS:
`dd if=/dev/block/by-name/system_a of=/dev/block/by-name/system_b bs=4M`, e conferir o hash.

`doha-xnu-hfs.img`, kernel `b8d99f33c55c0e39…`, `rd=emmcroot0 emmcroot=system_b`. Lido da foto:

    panic(cpu 0 ...): Process 1 exec of /sbin/launchd failed, errno 2 @kern_exec.c:6973

com a tarefa `pid 1: init`. `errno 2` é `ENOENT`, o resultado esperado para um volume vazio: não há
`/sbin/launchd`. Isso indica que a montagem passou, pois o XNU só tenta o processo 1 depois dela e
o loop `mount(N) failed` do boot 15 não apareceu. A foto mostra só a tela do panic, sem as linhas
de montagem. `handshake structure not initialized`, na mesma tela, não foi investigado.

Milestone 3: leitura e montagem de raiz HFS read-only cumpridas. Escrita ainda não testada.

O boot 17 confirmou a montagem com a linha `hfs: mounted DOHATEST on device b(1, 0)`.

## 2026-11-04, boot 17: primeiro processo de usuário

`userland/init.S` como `/sbin/launchd` em um volume HFSX de 64 MiB sem journal, gerado pelo CI
(`rootfs.yml`; sha256 `bcdaf42cd28a0d26…`) e gravado em `system_b` com `dd`.
`doha-xnu-init.img`: mesmo kernel `b8d99f33c55c0e39…`, mais `cs_enforcement_disable=1`. O CI ficou
sem máquina `macos-15-intel` duas vezes, então este workflow usa `macos-15`.

Lido das fotos:

    hfs: mounted DOHATEST on device b(1, 0)
    A5XELTE: root volume is not authenticated (error 25); continuing unsealed
    load_init_program: attempting to load /sbin/launchd
    *** DOHA userspace: init running, PID 01 ***
    DOHA init: tick 01 ... tick 10
    panic: initproc failed to start -- no exit reason available -- (signal 0, exit status 42)

Funcionaram no aparelho: exec de um Mach-O lido do eMMC, entrada em EL0, syscalls, devfs,
`/dev/console` e `select` com timer. `exit status 42` só existe depois do último tick. O relógio do
panic dá `Calendar - Boot` = 0x5a - 0x1e = 60 s, igual aos 12 ticks de 5 s. As fotos mostram até o
tick 10; os ticks 11 e 12 são dedução do status.

`initproc failed to start` não indica erro aqui: o XNU usa esse texto enquanto `kern.initproc_spawned`
é 0, e quem liga esse sysctl é o launchd de verdade.

`EXIT init[1] xstat 0` vem do printf do patch 0261 em `proc_exit`. O exec encerra a tarefa antiga
(`kern_exec.c`, `task_terminate_internal(old_task)`), então é o `init` do kernel sendo trocado pelo
launchd. Combina com o código, mas a linha aparece duas vezes e não sei por quê.

Não testado: assinatura de código ligada (o boot usa `cs_enforcement_disable=1`), `fork`/`spawn`,
dyld, e qualquer escrita.

O `system_b` continua com o volume de teste e o slot `_b` não inicia até a restauração.

Depois:
1. Caminho de escrita limitado à partição escolhida (`CMD25`), testado em `system_b`. Comando novo
   no eMMC: confirmar antes.
2. Raiz em `userdata`, porque o `system_b` tem só 3 GiB: apaga o LineageOS; confirmar antes.

## 2026-11-04: `system_b` zerado além do volume; caminho de escrita pronto, sem teste no aparelho

Antes de testar a escrita, comparei as partições pelo LineageOS:
- `system_a` inteira: `4ab9d8d9f0be0245`, igual à leitura anterior. Intacta.
- `system_b`, primeiros 64 MiB: `bcdaf42cd28a0d26`, o volume de teste.
- `system_b`, de 64 MiB ao fim: `1c5607e28eca13cd`, igual a 3024 MiB de zeros. Antes tinha os dados
  do sistema (o hash inteiro batia com o de `system_a`).
- `boot_a/b`, `dtbo_a/b` e `vbmeta_a/b` batem com o backup. Primeiro 1 MiB do eMMC (GPT):
  `bdd742db82c608c7`.

Portanto, a frase "só os primeiros 64 MiB mudam" estava errada. Causa não identificada. Os kernels até
aqui não têm código de escrita nem de erase. Suspeitos, sem prova: o `fastboot flash` recusado ou o `dd`
sem `conv=notrunc`. Nada indica outra partição afetada. A restauração a partir de `system_a` continua valendo.

Patch 0403, kernel `4232c073de6db08a…`: `CMD25` só em `emmc_write`. Liga com `emmcwrite=` igual a
`emmcroot=`, partição em `writable_parts[]` e mesmo intervalo no GPT. `write_allowed` passou em 5,1
milhões de casos fora do aparelho, com sanitizadores. `emmcwritetest=1` faz a ida e volta a 128 MiB da
partição. Como essa área está zerada, depois do teste o hash do trecho final deve continuar
`1c5607e28eca13cd`, e qualquer byte perdido nele aparece.

Imagens: `doha-xnu-guard.img` (`emmcwrite=boot_a`, deve recusar) e `doha-xnu-write.img`
(`emmcwrite=system_b emmcwritetest=1`). O LineageOS pode ser apagado (decisão do dono), mas é por ele
que gravamos e conferimos partições, porque o `fastboot flash` recusou a nossa imagem.

## 2026-11-04, boot 19: primeira escrita do kernel no eMMC

`doha-xnu-write.img`, kernel `4232c073de6db08a…`, `emmcwrite=system_b emmcwritetest=1`. Lido da foto:

    "system_b" is emmcroot0, 3088 MiB, WRITES ON
    write test 1 sectors: 0 ms, pattern ok, sides ok, restored ok
    write test 8 sectors: 0 ms, pattern ok, sides ok, restored ok
    write test 2046 sectors: 23 ms, pattern ok, sides ok, restored ok
    write test passed (0), writes on

Depois disso, montagem, launchd e ticks normais. ~44 MiB/s, igual à leitura.

De volta ao LineageOS, todos os hashes batem com os de antes do teste: `system_a`, volume e trecho final
do `system_b`, `boot_a/b`, `dtbo_a/b`, `vbmeta_a/b`, primeiro 1 MiB do eMMC (GPT). O `userdata`, o
`persist` e o modem não entram na conta porque mudam sozinhos; o LineageOS iniciou normalmente.

Não prova:
- Persistência depois de reiniciar: a área voltou a zeros, então o hash seria o mesmo se o padrão nunca
  tivesse chegado à flash.
- O caminho de `doha_emmc_strategy` para escrita, que um sistema de arquivos usaria.
- A recusa de `doha-xnu-guard.img`, se esse boot não tiver sido feito (resultado não informado).

Depois:
1. Montar o volume com escrita, criar um arquivo a partir do programa de usuário e conferir depois de
   reiniciar. Cobre a persistência e o caminho do sistema de arquivos.
2. Raiz em `userdata`, que precisa de confirmação e de outro caminho de gravação sem o LineageOS.

## 2026-11-04: sistema de arquivos grava no eMMC e os dados sobrevivem ao reinício

`rootrw=1` não existe neste kernel: em 0031 o código é só para `ARM64_BOARD_CONFIG_SWEET`, e DOHA não
define isso. O caminho usado é `mount -uw /` a partir do processo 1, como o launchd faz. O `data` não
pode ser NULL (`hfs_assert`): caminho do dispositivo e `hfs_mount_args` com tudo em VNOVAL.

Mesmo kernel `4232c073de6db08a…`, `emmcwrite=system_b`, volume `382b00924e0ec625…`, gravado com
`dd conv=notrunc,fsync`. Lido das fotos:

    boot 1: root is read-write; previous count 00; wrote count 01; panic exit status 42
    boot 2: root is read-write; previous count 01; 2 MiB from the previous boot ok; wrote count 02;
            panic exit status 42

Status 42 também diz que `mount -ur /` passou. Entre os boots houve reinício por botões. `Calendar - Boot`
= 15 s, os 3 ticks. `vnode_create_internal: alias vnode ... state of change` aparece no `mount -uw`; não
investigado, sem efeito visível.

Conferência pelo LineageOS, depois dos dois boots:
- Volume: `c13bc9ecc53a8218` (mudou, como esperado), assinatura `HX`, marcado limpo.
- `fsck_hfs -n -f` em uma cópia: "The volume DOHATEST appears to be OK".
- `DOHA-COUNT 02` e os 2 MiB do boot 2 estão no volume, lidos pelo Linux, fora do nosso driver.
- Iguais aos de antes: `system_a`, trecho final do `system_b` (zeros), `boot_a/b`, `dtbo_a/b`,
  `vbmeta_a/b`, primeiro 1 MiB do eMMC. `userdata`, `persist` e modem não são comparáveis por hash.

Milestone 3 cumprido: leitura e escrita pelo sistema de arquivos, limitadas a uma partição.

Em aberto: causa dos zeros no `system_b`; recusa de `doha-xnu-guard.img`, sem resultado informado; `fork`,
`spawn`, dyld; assinatura de código ligada; SMP.

Depois: raiz do iOS. Antes de apagar qualquer coisa, falta decidir como gravar o `userdata` sem ele estar
montado e onde montar o volume, porque o IPSW não pode passar pelo CI público.

## 2026-11-04: o que cada núcleo oferece

`doha-cores.img`, shim sem payload, sem acesso ao armazenamento. Lido da foto:

    CPU0-3 midr=51AF8014 mmfr0=00001122 isar0=00011120 isar1=00000000  16K NO   LSE NO  RCPC NO
    CPU4-6 midr=51AF8002 mmfr0=00101122 isar0=00011120 isar1=00000000  16K YES  LSE NO  RCPC NO
    CPU7   midr=51AF8002 mmfr0=00101122 isar0=00011120 isar1=00000000  (linhas seguintes fora da tela)

Os Gold têm 16K; o "sem 16K" de antes valia só para os Silver. Nenhum tem LSE ou `ldapr`, então o userland
precisa de emulação. Os 8 núcleos acordaram.

No fim, o aparelho reiniciou no LineageOS, não no fastboot como o shim anuncia. O motivo do reinício
gravado no IMEM não valeu desta vez; não investigado.

Outras leituras pelo LineageOS: `gpu_model` = `Adreno610v1`; toque `fts_ts_doha` (FocalTech);
`qpnp_pon` e `gpio-keys`; `board-id` `0x42 0xb200`.

## 2026-11-05: UEFI do doha comparada com a do willow, sem executar nada

Backup ampliado em `backup/2026-11-05` na pasta do usuário (privado): 74 partições, com hash igual ao do celular, e
as duas cópias do GPT. Sem `userdata`, `system_*` e RPMB. `xbl_a` e `xbl_b` são iguais.

O `xbl` traz um volume de firmware em `0x5FC00000`, 3 MiB, igual ao `willowPkg`. A parte principal é gzip
dentro de uma seção GUID. Lido com um parser próprio em Python:

- 113 módulos. Dos 74 do willow, 53 têm o mesmo nome. A maioria dos outros parece só nome diferente: `ChipInfo`,
  `DALSys`, `GlinkDxe`, `PmicDxe`, `ScmDxe`, `TzDxe`, `DxeCore`.
- Sem equivalente aparente: `MiToken` (Xiaomi).
- Só no doha: `MotBootFlagsDxe`, `MotCoreServicesDxe`, `MotHwIdDxe`, `MotSolDxe`, `MotStorageDxe`, `MotUtagsDxe`,
  `MotUtagsDictDxe`, `MbmModeDxe`, `AbDxe`, `BacklightDxe`. Um `.fdf` nosso só carrega o que listar; manter
  fora os `Mot*`, principalmente `MotStorageDxe` e `MotUtagsDxe`. Uma mensagem pede o "Motorola hwid protocol": pode
  haver dependência a resolver.
- `uefiplat.cfg`: 99 linhas nos dois; difere em uma região de log, `MemoryCaptureModeOffset`, `SecurityFlag`
  (`0xC4` x `0x81CC`), `DefaultBDSBootApp` e `EnableDisplayImageFv`.
- `SecParti.cfg` (RPMB/GPT) igual, ignorando comentários.
- Painéis da Motorola no firmware; falta saber qual é o do doha.

Parado aqui: o bloqueio automático de segurança não deixou compilar e executar o UEFIReader, por ser código externo.
A compilação do Mu-Silicium teria o mesmo problema. Falta autorização do dono. Os scripts ficam fora do repositório.
