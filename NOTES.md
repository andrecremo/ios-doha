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

## 2026-11-05: `dohaPkg` pronto para compilar

O dono rodou o UEFIReader no próprio terminal: 84 módulos, com 73 dos 74 do willow com o mesmo nome. Fica de fora do
repositório, em uma pasta privada do WSL.

`uefi/mkdohapkg.py` gera o `dohaPkg` a partir do `willowPkg` em um Mu-Silicium fixado (`6b3d90b7`). Testado em uma
cópia só com os fontes: passa, com 32 referências de binários conferidas. Compilação ainda não testada.

Escolhas para o primeiro boot:
- `SimpleFbDxe`, sobre o framebuffer que o ABL deixa ligado, sem `DisplayDxe`. A dependência dele do protocolo de hwid
  da Motorola não pesa aqui.
- Fora: USB, carregador, ADC, PIL e o app de armazenamento em massa. `Mot*` nem entram.
- `PcdEmuVariableNvModeEnable` vem ligado no `QcomPkg`: as variáveis ficam na RAM.
- `TzDxe`, `ScmDxe` e `SdccDxe` ficam, como no willow. O `ButtonsDxe` procura o protocolo de hwid; efeito desconhecido.
- ACPI continua a do willow, porque só um sistema operacional a lê.
- `uefi/DohaShim.S` é nosso e `uefi/mkdohaimg.py` empacota como header v2 com o dtb do aparelho.

Primeiro boot pela RAM, `doha-uefi.img` RELEASE, sha256 `5b89add3c86bc4cd`: 2 minutos parado no logo da Motorola, sem
mudança na tela. Inconclusivo: RELEASE não escreve nada. Próximo: DEBUG, com log na tela, e o shim pintando uma
faixa verde antes de saltar, para separar "o ABL não rodou o shim" de "a UEFI travou".

Boot DEBUG pela RAM, sha256 `b306386088aad613`: **a UEFI rodou no aparelho**, com o framebuffer funcionando. Parou com
um data abort: `ELR 0x5A2E6874`, `FAR 0x10AC000`, `ESR 0x96000046` (escrita, translation fault no nível 2). O stack tem o
texto `ASSERT BootFlagsLib.c +28: Status == 0 && mProtocol != (void *)`. Os módulos da Motorola têm um `BootFlagsLib`
que exige o protocolo do `MotBootFlagsDxe`. O salto para `0x10AC000` parece ser o tratamento desse assert; não confirmado.

Pela ordem original (arquivo APRIORI do FV): `... ArmTimerDxe MotBootFlagsDxe SmemDxe ...`. `MotBootFlagsDxe` entra:
guarda flags na memória, sem biblioteca de armazenamento. `MotHwIdDxe` fica fora, porque usa `UtagsLib` e pode gravar
("Failed to write programmable HWID"). Logo, `ButtonsDxe`, que exige o hwid, sai também.

Com o `MotBootFlagsDxe`, DEBUG sha256 `82807aeeb71f738c`: o assert sumiu, o log vai até o `ULogDxe`, a tela apaga e o
aparelho "reinicia". Para isolar, `uefi/DohaHaltDxe` para o boot depois do módulo em `DOHA_HALT_AFTER`, conta na tela e
pede `PSCI SYSTEM_RESET` aos 30 s, um sinal que funciona sem tela.

| Parada depois de | Resultado |
|---|---|
| `ULogDxe`, `NpaDxe` | Tela viva. `NpaDxe`: reboot PSCI aos 30 s (controle). `ULogDxe` ainda sem PSCI: contou sem reiniciar |
| `ClockDxe` | Tela apaga, reboot perto de 30 s no relato do usuário: CPU e timer vivos |
| `ScmDxeLA`, `SdccDxe`, `TzDxeLA`, `PmicDxeLa` | Reboot por volta de 30 s |

Imagem completa, cabo tirado com a tela preta: a impressão foi de que ficou desligado. Coerente com
`PlatformBootManagerUnableToBoot` (Mu-Silicium), que espera 10 s e pede `EfiResetShutdown`. Nesse caso a UEFI termina o
boot; falta confirmar. Com o cabo, o desligamento parecia um reboot.

Tela preta: o `ClockDxe` do doha é quase o mesmo do willow (mesmo tamanho, textos quase iguais; não comparei o código). Ele
traz nós NPA de PMIC (`/pmic/client/disp_prim`, `ldo7`, `ldo10`, `ldo15`, `ldo18`, `smps5`), uma pista ainda sem prova. O
willow usa o framebuffer da UEFI no iOS, então a queda não é inerente a esse módulo. Falta saber se a luz de fundo fica acesa.

Consumidores lidos no Lineage: painel `mipi_mot_vid_tianma_1080p_630` (`dsi_ft8719_tm_vid_display`, modo vídeo). `pm6125_l18`
alimenta `mdss_dsi_ctrl0-vdda-1p2`, `pm6125_s5_level` alimenta `mdss_dsi_phy0-vdda-0p9`, `pm6125_l9` é `dsi-display-vddio`,
`lcdb_ldo` e `lcdb_ncp` são `lab` e `ibb`. `l7`, `l10` e `l15` alimentam o `qusb`, não o display. Dos reguladores citados no
`ClockDxe`, `l18` e `s5` são os candidatos. Depois de um boot de teste, com religamento pelo Power: `POWERUPREASON 0x80`,
`Last boot reason: power_key_press`, ou seja, o aparelho estava mesmo desligado.

Imagem `halt-ClockDxe`, sem cabo: luz de fundo acesa, sem imagem, reboot aos 30 s. Logo, o desligamento em 15 s veio da imagem
completa, que chega à BDS. `uefi/DohaDispProbeDxe` (sha256 `6c69a60a7875ceda`) ligou, pela `EFI_CLOCK_PROTOCOL`, o
`mdss_core_gdsc` e 12 clocks do display: a imagem não voltou, reboot perto de 60 s, ou seja, algum clock lido estava desligado.
Não sei qual, porque esse log ficou invisível.

Caminho original: o `DisplayDxe` do doha tem `Panel_tm_ft8719_fhd_vid.xml`, nosso painel, e o arquivo está no firmware. Ele
exige o protocolo de hwid `6634b0ee-0d71-40f4-5944-487ad029619e`, do `MotHwIdDxe`, com assert se faltar. Na desmontagem, o
`DisplayDxe` só chama duas funções dele, nos deslocamentos `0x18` e `0x28`. A primeira tem o retorno testado contra NULL. O que
cada uma faz ainda não está confirmado. Ideia: um driver nosso, só em memória, com esse protocolo, sem `MotHwIdDxe`,
`MotUtagsDxe` e `MotStorageDxe`.

Imagem com `DisplayDxe` e `DohaHwIdDxe`: tela preta, sem mudança em 2 minutos. Para ler sem tela, `uefi/DohaLogDxe` põe o
núcleo `0x103` como vigia (PSCI CPU_ON, MMU desligada): copia o framebuffer e o buffer de log para a região `DBI Dump` a cada
segundo e pede reboot aos 45 s. Ao reiniciar segurando Volume para baixo, `doha-logreader.img` (sem payload, `show_saved` em
`shim.c`) mostra as cópias. A RAM sobrevive ao `PSCI SYSTEM_RESET`. Um primeiro vigia por timer parou cedo; o abort abaixo
explica isso, porque o tratador nunca retorna. O buffer `0x5FFF7000` só tinha o log antigo do XBL, 116 linhas.

Tela salva, `SECONDS` 0x2F: data abort, `ESR 0x96000046`, `FAR 0x10AC000`, `ELR 0x59B7EF14`, com a pilha trazendo
`ASSERT UtagsLib.c +26: !(((INTN)(RETURN_STATUS)(Status)) < 0) && mProtoc...`. É o mesmo `FAR` do assert do `BootFlagsLib`. Dos
módulos mantidos, só o `DisplayDxe` tem `UtagsLib`. Ele usa o protocolo `feb30e8d-06ed-4c9a-8d35-a8e52a346f3f` por quatro entradas:
`0x10`, `0x18`, `0x20` (tamanho por parâmetro de saída) e `0xA8` (a tag existe?), para `BootCycleCount`, `logfs` e `bare_board`.
O `DohaHwIdDxe` agora responde `EFI_NOT_FOUND` a todas, sem gravar nada.

Partições depois desses boots, contra `backup/2026-11-05`: 66 iguais e as duas GPT iguais. Mudaram `utags` e `utagsBackup`
(só `BootCycleCount`), `prodpersist` (na primeira comparação, 8 bytes no superbloco ext4), `logfs` (os `LOGxx.TXT`, cerca de
um por boot normal, pelas datas), e `persist`, `metadata`, `modemst1` e `modemst2`, sem comparação byte a byte.

Com o `DohaHwIdDxe` também como protocolo de UTAG, a imagem com `DisplayDxe` não trava mais no assert, mas a tela fica
preta. O vigia num segundo núcleo morreu cedo nessa imagem: o reboot veio da parada aos 30 s, e não dele aos 25 s, e a RAM
voltou sem a marca. Não sei por que ele morreu. A parada depois do `DisplayDxe` (`DohaHaltDxe`, salvando a tela pelo núcleo
principal ao carregar e a cada 5 s) também deixou a RAM sem marca. Já o controle, com a parada logo depois do `TsensDxe` e
antes do `DohaHwIdDxe` e do `DisplayDxe` (sha256 `59bce0cff8840bc2`), salvou a tela: `SECONDS` 0x1E, log até
`DohaHalt: 30 s`. Logo, o núcleo principal salva a RAM, e é o `DisplayDxe` que não retorna. A tela salva também mostra que
os módulos da Qualcomm escrevem no framebuffer: o `PmicDxe` imprime os motivos de PON do último reset (PM0: `HARD_RESET`,
`PS_HOLD`; PM1: `CBLPWR_N`, `SOFT`). O reboot por PSCI preserva a RAM.

Próximo: `uefi/DohaSaveDxe`, carregado antes do `DohaHwIdDxe`, salva a tela por timer a cada segundo e deixa o boot seguir,
para guardar a última tela do `DisplayDxe` enquanto ele não retorna.

O microSD não serve: com `DohaSaveDxe` listando os dispositivos de bloco, o firmware expõe só o eMMC (área de usuário de
122142720 setores e duas partições de boot de 8192), 80 dispositivos com as partições. `DohaSaveDxe` passou a gravar a tela
e o buffer de log na `system_b`, a 128 MiB (LBA 11862016 a 11881318), só se o disco tiver exatamente 122142720 setores e a
GPT trouxer `system_b` de 11599872 a 17924095. `tools/readsave.py` lê pelo adb e gera um PNG. Depois de cada uso, o trecho de
1 MiB antes e depois da área continuou zerado, e as 66 partições e as duas GPT seguiram iguais ao backup.

Com o `DisplayDxe`, só a escrita inicial acontecia: nenhum timer rodava depois, nem um de `TPL_NOTIFY` que copia para a RAM
(`SECONDS` 0 no leitor; a RAM sobrevive a esse reset). Motivo do reset, lido na rodada seguinte: `HARD_RESET`, `PS_HOLD`.
`EnableDisplayThread` em 0 não mudou nada. O `DisplayDxe` traz a própria `ArmMmuLib` e a usa pela
`UncachedMemoryAllocationLib`, desligando interrupções e MMU para trocar entradas de tabela de páginas (`0x7104`).

Rodada com um vigia no núcleo `0x103`, ligado pelo `DohaSaveDxe` logo antes do `DisplayDxe` (sha256 `966bb8eadbb85f28`):
o `DisplayDxe` retornou e o boot chegou à BDS. A tela salva tem `No Operating System Found!` desenhado pelo console gráfico, e
a `system_b` tem 4 escritas (0, 5, 10 e 15 s). Ainda não sei se o painel acendeu nem se o resultado se repete.

Resultados com o vigia: a tela acendeu em 3 de 4 boots (`No Operating System Found!` no painel, desenhado pelo console gráfico).
Um núcleo só parado em `wfe` (`uefi/DohaParkDxe`) não fez a tela acender em nenhum de 3. Um vigia leve (`uefi/DohaSnapDxe`)
ligou (`CPU_ON` 0) mas não deixou nada na RAM. O `DisplayDxe` tem uma corrida que o tráfego de memória do vigia costuma evitar.
Não a investiguei mais: os outros projetos reaproveitam o framebuffer do bootloader, e o willow usa o `SimpleFbDxe`.

Caminho do framebuffer, resolvido. `uefi/DohaRegsDxe` (antes do `ClockDxe` e depois do `SdccDxe`, endereços de
`dispcc-sm6125.c` e `gcc-sm6125.c` do Linux) mostrou que o `ClockDxe` faz `gcc_disp_hf_axi_cbcr` ir de `00004221` a
`80004221`: o clock AXI do display, habilitado, para. Também `gcc_disp_throttle`, de `00000000` a `80000000`. A origem é o
barramento de multimídia em tempo real, o recurso do RPM `/clk/mmrt`, que o `ClockDxe` cria e ninguém pede. O `DisplayDxe`
original cria um cliente obrigatório (`0x40`, `UEFI_DISPLAY_DRIVER`) e pede 240000 kHz, pelo protocolo NPA do `NpaDxe`
(`79d6c870-725e-489e-a0a1-27e7a5d0cb35`, criar em `0x10`, pedir em `0x28`). `uefi/DohaMmrtDxe` faz o mesmo logo depois do
`ClockDxe`: com ele, a tela que o ABL deixou continua acesa até o fim do boot, com o `SimpleFbDxe` (sha256 `22237cabbb53289f`).
Antes e depois ficam iguais: AXI `00004221`, `mdss_gdscr` `F822F000` (ligado), pipe `VIG0` em `0x5C000000`, 1080 x 2280.
`mkdohapkg.py` agora põe o `DohaMmrtDxe` sempre depois do `ClockDxe`. As 66 partições e as duas GPT seguem iguais ao backup.

## Base willow-hackios: o loader no doha

`willow/patches/0001` (sobre willow-hackios `796e42b`): o `xnuloader` escolhe o aparelho pelo endereço do framebuffer, que
o doha divide com o willow (`0x5C000000`), e agora também pela altura (2280 contra 2340). `platform_doha` tem os valores
do SoC do willow e nada da placa dele (sem partição, OSM, RPM ou touch). No kernel, `device=doha` usa o timer da Qualcomm
como o willow (`gic_v3_irq.c`) e tem a sua linha nos botões (`redwood_buttons.c`: power e volume para baixo no PON do PM6125,
volume para cima no GPIO9 do PM6125, lidos do device tree do doha). Sem kernel, o loader espera 30 s antes do reset no doha.
Cuidados: sem `gpu=1` (o driver do redwood decide pelo SoC base, igual ao do doha), `touchscreen=1`, `osm=`, `ufs_write=`.

UEFI: `DohaShim.S` copia um contêiner XNUP que segue o FD para `0xF0000000`; `mkdohaimg.py` o acrescenta e aumenta o
`image_size`; `mkdohapkg.py` reserva `QTEE`, `TZApps` e `XNU Payload` no mapa de memória e, com `DOHA_WILLOW`, monta em
`dohaPkg/Library/BootManagerLib` a biblioteca da base do willow (`e51cd877`) com o patch dele e o `XnuLoader.c`, que no
doha também escreve na tela o que faz. Primeiro boot com só o loader no pacote (sha256 `3ac1a7260f45de12`):

    == XNULOADER v3 ==
    CurrentEL=1 MIDR=51af8014 MMFR0=1122 CNTFRQ=19200000 image=a1000000
    display 1080 x 2280 at 5c000000
    platform doha
    payload entry 'loader.efi' size 11e00
    no kernel in payload

Kernel: willow-hackios + o patch, `xnu-8796.121.2`, compilado no WSL (theos com `iPhoneOS16.5.sdk`, `xnu-deps/setup.sh`,
`xnu/apply.sh`, `./xnu-build.sh -j6 -k`; o `-k` é obrigatório, a checagem de exportações falha depois do link). Resultado:
`mach.development.bcm2837`, 15760312 bytes, `Darwin Kernel Version 22.5.0`, com a linha de botões do doha. O loader passa a
ser ligado em `0x61000000` (`LOADER_BASE`), fora de `0x80000000`-`0xF0000000`, o maior bloco livre da UEFI, que o XNU usa.

Primeiro boot do kernel (pacote: `loader.efi`, `kernel`, `cmdline` `-v cpus=1`; imagem de 8 MB): o XNU sobe e escreve na
tela. `GICv3 ... virtual timer on interrupt 19`, mapas de VM e zonas sem erro, `GenericARMPE: platform "D22AP"`,
`GenericARMCPU: cpu 0 ... registered`, AMFI e Sandbox substitutos, `mbinit`, `dlil_init`, e por último
`MiniIOMobileFramebuffer: display 1125x2436 on a panel of 1080x2280 (4320 bytes per row)`. Sem disco raiz no pacote.

Na volta ao loader, o kernel deixava ligada a interrupção do seu timer (19) com o timer armado; a UEFI não a trata e escrevia
`Spurious GIC interrupt: 0x13` sem fim (`ArmGicV3Dxe`). O patch agora a desliga em `gic_v3_irq_quiesce`. `run-doha-kernel.sh`
copia `xnu/files/` para a árvore já criada, porque `xnu/apply.sh` só o faz ao criá-la.

Segundo boot do kernel (compilado 2026-11-09 07:31): depois do framebuffer, `GenericARMPE: the slower cores started too:
1 processors running`, `BSD`, `Waiting on <dict>... IOMedia ... Content Apple_HFS ...`, `Still waiting for root device`, e o
panic `Failed to mount root device` com `Boot args: debug=0x8 device=doha -v cpus=1`, `Stackshot Succeeded` e reboot. Sem o
loop do GIC. O XNU sobe inteiro no doha até montar a raiz.

O armazenamento pelo loader (`ufs=2`): o kernel não tem driver de eMMC nem de UFS; o loader fica no núcleo 0 e lê blocos com
o `BlockIo` da própria UEFI para o kernel, que roda no núcleo 3 (`bootcpu=3`), por uma página compartilhada
(`ufs_shared_pa=`). Nada nesse caminho é de UFS: as partições vêm da GPT pelo nome (`/dev/ufs_system_b` etc.). O driver do
kernel (`redwood_ufs_init`) só sobe depois que a raiz é montada (`bsd_init.c`, junto do `devfs`), então o teste leva o
`hello` do willow-userland como RAM disk (o mockfs o roda como processo 1).

Teste de leitura (cmdline `-v bootcpu=3 cpus=1 ufs=2 ufs_check=2`, `ramdisk=hello`; nada escreve): `BSD root: md0`,
`ufs: 77 partitions of the phone's storage as /dev/ufs_NAME ...`, `ufs: check: 80 partitions ... through the loader's page`,
444 pedidos, 460 MB em 2,6 s (~195 MB/s). Os hashes FNV-1a lidos pelo kernel são os mesmos calculados pelo adb no Lineage:

| Partição (a e b) | Bytes | FNV-1a 64 |
|---|---|---|
| `xbl` | 3706880 | `83629509a8eace72` |
| `tz` | 3710976 | `6d98f58b25c1e86b` |
| `abl` | 208896 | `c48ee2ef07fbe16d` |
| `bluetooth` | 503808 | `c621d721e28c546` |

`hyp`, `modem` e `dsp` falham com status 2: o teste usa os tamanhos do willow, maiores que essas partições no doha.

O volume do iOS: o do willow no flash (o volume inteiro da Apple e os cryptexes, ~8,4 GB) não cabe na `system_b`
(3238002688 bytes); a imagem reduzida (~2,5 GB) vai em RAM, mandada por USB ao loader, que o doha ainda não tem. Duas saídas:
a reduzida mais o cryptex refeito na `system_b` (apertado, com mudança no `init`), ou a receita do willow inteira na `userdata`
(sem o Lineage). Decidir na hora de gravar.

A receita de RAM não cabe: a maior RAM contínua do doha é `0x80000000`-`0x13FFFFFFF` (~3 GB, `/proc/iomem`), e o
`system.apfs` (2,5 GB) mais os 768 MB que o loader reserva ao kernel passam disso. Vale a do willow, pelo flash.

**iOS 16.5 na tela inicial (2026-11-09).** A receita do flash do willow, com a `userdata` no lugar da `system` dele:

- `userdata` (`mmcblk0p80`, LBA 17924096, 53359918592 bytes): o volume raiz da Apple (`rootfs.dmg`, UDIF com LZFSE,
  aberto por `tools/apfs/dmg.py` no contêiner APFS bruto de 5628755968 bytes), o cryptex do sistema (2726297600) e o de
  apps (10485760), como a Apple os entrega, um atrás do outro: 8365539328 bytes, contêineres 0, 1 e 2 de
  `/dev/ufs_userdata` (o `init` monta `,c=1` e `,c=2`). sha256 da imagem `9efb156f...3735560`.
- O bootloader da Motorola recusa `fastboot flash userdata` (`flash permission denied`; antes, o fastboot 36.0.2 dava
  `bad_alloc` com a imagem bruta; `tools/mksparse.py` faz a versão sparse e confere que ela expande igual). A gravação foi pelo recovery do Lineage (Advanced >
  Enable ADB, `adb exec-in dd`, 6,8 MB/s) e conferida lendo de volta depois de `drop_caches`.
- A `fstab` do doha tem a `userdata` como `formattable`: um boot do Android a formataria. `boot_a` e `boot_b` levam a
  nossa UEFI (backup de boot, dtbo e vbmeta dos dois slots guardado fora do repositório). Para voltar ao Lineage: os
  `boot` do backup e "Format data" no recovery.
- Na RAM, só o `root.apfs` e o `flashboot.apfs` (4 MB cada; `FLASHBOOT=1 CRYPTEXES=flash`, `RC_JOBS=rc.jobs.unlock`).
  cmdline `bootcpu=3 cpus=1 ufs=2 root_apfs=ufs_userdata`. Nada escreve (`/private/var` em memória).

Resultado: launchd, SpringBoard e a tela inicial com o dock, desenhados pela CPU no framebuffer da UEFI. Com `-v` o
console do kernel corre por cima; sem `epoch=` o relógio começa em 31/12/1969.

Clock dos núcleos (`osm=1`): o firmware do doha deixa o OSM dos Silver ligado (`f521000`, enable 3) e o dos Gold
desligado (`f523000`, enable 2), como no willow. O loader passa a aceitar `osm=1` no doha, só onde o OSM está ligado e
para uma linha entre 300 e 2100 MHz da tabela do próprio firmware: Silver na linha 7, 1804 MHz (medido "982 MHz if one
add a cycle", ~2 ciclos por volta do laço); Gold fica em 300 MHz. Cmdline padrão agora `bootcpu=3 cpus=8 ufs=2
root_apfs=ufs_userdata osm=1 epoch=...`, sem `-v`: a tela inicial chega mais depressa, ainda devagar (a interface é
desenhada pela CPU).

**Touch (FocalTech FT8719) funciona (2026-11-09).** `bsd/dev/redwood_focaltech.c` (patch 0001), com `touchscreen=1` e
`device=doha`. O mesmo motor SPI do willow (`spi@4a88000`, QUP0 SE2, GPIO 6 a 9, interrupção no GPIO 88), em modo SPI 1;
o protocolo é o do driver GPL da Motorola (`motorola-kernel-modules`, tag `MMI-RPI31.Q2-42-25`,
`focaltech_0flash_mmi`: `focaltech_spi_v1_1.c`, `focaltech_flash_ft8719.c`). O FT8719 não tem flash: depois da UEFI ele
espera na ROM (boot id `87 19`, estado 2) e o firmware vai para a RAM dele a cada boot, pacotes `0xae`, ecc
conferida (`0xcc`/`0xce`/`0xcd`), `0x08` para rodar. O reset (GPIO 87) é o mesmo do painel (`share_reset_gpio`):
o driver nunca o toca e usa o caminho de recuperação sem reset da Motorola. O firmware é o do aparelho,
`/vendor/firmware/focaltech-ft8719-a0-0000-doha.bin` (64920 bytes; a `vendor_a` é EROFS), copiado pelo recovery do
Lineage, fora do repositório; o `userland/build.sh` o põe em `fw/` (`willow/patches/userland/`). O painel
`fb_hud=1` mostra "Touch ok, FT8719, 100 Hz", e o iOS reage ao dedo. A tela continua a ~1 quadro por segundo
(1749 ms por quadro desenhados pela CPU): o próximo passo é a GPU (Adreno 610).
