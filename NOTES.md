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

## Próximo: milestone 2

Kernel XNU com config de máquina `DOHA` até o console no framebuffer:
- base: série do branch `herolte` (sweet 0001–0081 + ARMv8.0/4K), separando o que é Exynos
  (GICv2, DECON, UFS Exynos, Mali, PMIC Samsung) do que é genérico
- trazer de volta do sweet: GICv3 (`HAS_GIC_V3 1`), PSCI, timer, console no framebuffer
- `tools/mkadt.py` para o doha: RAM `0xc0000000` + 1 GiB, GIC, FB, timer
- testar primeiro em QEMU (`-cpu cortex-a53`, `gic-version=3`)
