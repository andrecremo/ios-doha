/*
 * doha milestone 3: read the eMMC through sdhci@4744000 (qcom,sdhci-msm-v5).
 * Standard SDHCI registers, PIO only, so no DMA and no SMMU.
 *
 * Measured (boot 5): ABL leaves the host reset: SD clock off, bus power off,
 * 1-bit, nothing enabled. So bring it up from scratch, slowly:
 *   - MSM hosts do not use the SDHCI divider: the card clock is the GCC RCG
 *     (register values as in Linux gcc-sm6125.c, 400 kHz from TCXO)
 *   - power and IO level writes raise a request the driver must acknowledge
 *     (Linux sdhci-msm.c); the regulators are left on: vdd-io is always on
 *   - VCCQ is 1.8 V (live FDT qcom,vdd-io-voltage-level), so set the pads for it
 *   - standard eMMC identification: 1-bit at 400 kHz, the power-on default
 *
 * Then raise the speed: 8-bit bus and HS timing at 50 MHz, single data rate.
 * No DLL or tuning, which Linux only uses above 100 MHz.
 *
 * No data is ever written. The only commands sent are CMD0, CMD1, CMD2, CMD3
 * and CMD7 (reset and select the card), CMD13 (status), CMD8 (read EXT_CSD),
 * CMD17 and CMD18 (read blocks) and CMD6, only for the two mode fields BUS_WIDTH
 * and HS_TIMING of EXT_CSD, which return to their defaults on reset. No CMD24, CMD25.
 *
 * The DMA test uses ADMA2 into free RAM, card to memory only. The live FDT binds
 * no iommus to this host; the stream's real SMMU state is printed first.
 */
#include <stdint.h>
#include "console.h"
#include "sdhci.h"

#define HC			0x04744000UL
#define HC_BLOCK		0x04	/* size (16), count (16) */
#define HC_ARG			0x08
#define HC_XFER_CMD		0x0c	/* transfer mode (16), command (16) */
#define HC_RESP0		0x10
#define HC_DATA			0x20
#define HC_PRESENT		0x24
#define HC_CTRL1		0x28
#define HC_POWER		0x29
#define HC_CLOCK		0x2c	/* clock (16), timeout (8), software reset (8) */
#define HC_TIMEOUT		0x2e
#define HC_RESET		0x2f
#define HC_INT			0x30	/* normal (16), error (16); write 1 to clear */
#define HC_INT_EN		0x34
#define HC_SIG_EN		0x38
#define HC_CTRL2		0x3c
#define HC_CTRL2_HI		0x3e
#define HC_CAPS			0x40
#define HC_ADMA_ERR		0x54
#define HC_ADMA_ADDR		0x58
#define HC_ADMA_ADDR_HI		0x5c
#define HC_VERSION		0xfe

/* sdhci_msm_v5_offset */
#define MSM_DLL_CONFIG		0x200
#define DLL_PDN			(1U << 29)
#define DLL_RST			(1U << 30)
#define MSM_VENDOR_SPEC		0x20c
#define MSM_VENDOR_CAPS0	0x21c
#define MSM_PWRCTL_STATUS	0x240
#define MSM_PWRCTL_CLEAR	0x248
#define MSM_PWRCTL_CTL		0x24c
#define PWRCTL_BUS_SUCCESS	(1U << 0)
#define PWRCTL_IO_SUCCESS	(1U << 2)
#define VENDOR_IO_PAD_EN	(1U << 15)
#define VENDOR_IO_PAD_1V8	(1U << 16)

#define GCC			0x01400000UL
#define GCC_SDCC1_APPS_CBCR	0x38004
#define GCC_SDCC1_AHB_CBCR	0x38008
#define GCC_SDCC1_RCG_CMD	0x38028
#define GCC_SDCC1_RCG_CFG	0x3802c
#define GCC_SDCC1_RCG_M		0x38030
#define GCC_SDCC1_RCG_N		0x38034
#define GCC_SDCC1_RCG_D		0x38038
#define CBCR_OFF		(1U << 31)
#define RCG_UPDATE		(1U << 0)
#define RCG_CFG_400K		((23U << 0) | (0U << 8) | (2U << 12))	/* TCXO / 12, M/N 1/4 */
#define RCG_CFG_50M		((11U << 0) | (2U << 8))		/* GPLL0_OUT_AUX2 / 6, no M/N */

#define PRESENT_INHIBIT		0x3	/* command and data lines */
#define CLOCK_SD_ON		(1U << 2)
#define POWER_ON_3V0		0x0d	/* bus on, 3.0 V: vdd is 2.95 V */
#define CTRL2_1V8		(1U << 3)
#define CTRL1_HS		(1U << 2)
#define CTRL1_8BIT		(1U << 5)
#define RESET_CMD_DAT		0x6
#define INT_CMD			(1U << 0)
#define INT_XFER		(1U << 1)
#define INT_BUF_RD		(1U << 5)
#define INT_ERR			(1U << 15)

/* Command register: index << 8 | data present | index check | CRC check | response */
#define CMD_NONE		0x00
#define CMD_R1			0x1a
#define CMD_R1B			0x1b
#define CMD_R1_DATA		0x3a
#define CMD_R2			0x09
#define CMD_R3			0x02
#define XFER_READ_ONE		((1U << 4) | (1U << 1))	/* card to host, count enable, no DMA */

#define MMC_GO_IDLE		0
#define MMC_SEND_OP_COND	1
#define MMC_ALL_SEND_CID	2
#define MMC_SET_RCA		3
#define MMC_SWITCH		6
#define MMC_SELECT		7
#define MMC_READ_EXT_CSD	8
#define MMC_STATUS		13
#define MMC_READ_BLOCK		17
#define MMC_STATE_TRAN		4
#define OCR_SECTOR_DUAL		0x40ff8080	/* sector addressing, 1.8 V and 2.7-3.6 V */
#define OCR_READY		(1U << 31)
#define CARD_RCA		1
#define R1_SWITCH_ERROR		(1U << 7)
#define EXT_CSD_BUS_WIDTH	183
#define EXT_CSD_HS_TIMING	185
#define EXT_CSD_DEVICE_TYPE	196
#define BUS_WIDTH_8		2
#define HS_TIMING_HS		1
#define DEVICE_TYPE_HS_52	(1U << 1)
#define MMC_READ_MULTIPLE	18
#define CTRL1_DMA_MASK		(3U << 3)
#define CTRL1_ADMA2_32		(2U << 3)
/* DMA on, count enable, auto CMD12 (Linux MULTIBLOCK_READ_ACMD12), read, multi-block */
#define XFER_READ_DMA		((1U << 0) | (1U << 1) | (1U << 2) | (1U << 4) | (1U << 5))
#define ADMA_VALID_TRAN		0x21
#define ADMA_END		0x02
#define ADMA_CHUNK		0x8000U
/* The shim runs low in RAM and a boot without a payload leaves this range unused. */
#define DMA_DESC_PA		0xc0000000UL
#define DMA_BUF_PA		0xc0100000UL
#define DMA_TEST_SECTORS	32768U	/* 16 MiB, the largest SDHCI block count */
/* Sum of the first 16 MiB of the boot_a.img backup, as little-endian 32-bit words. */
#define BOOT_A_SUM_16M		0x4ddcf87cU
#define BOOT_A_SUM_64K		0xa5528332U

#define SMMU			0x0c600000UL
#define SMMU_CR0		0x000
#define SMMU_IDR0		0x020
#define SMMU_SMR(n)		(0x800 + 4 * (n))
#define SMMU_S2CR(n)		(0xc00 + 4 * (n))
#define EMMC_SID		0x160U	/* mainline sm6125.dtsi sdhc_1 */

#define SPEED_TEST_SECTORS	2048	/* 1 MiB */
/* Sum of the first 1 MiB of the boot_a.img backup, as little-endian 32-bit words. */
#define BOOT_A_SUM		0xfa62bcb9U

#define SECTOR			512
#define GPT_ENTRY_SIZE		128

#define isb() __asm__ volatile("isb" ::: "memory")

static inline uint32_t rd32(unsigned r) { return *(volatile uint32_t *)(HC + r); }
static inline uint16_t rd16(unsigned r) { return *(volatile uint16_t *)(HC + r); }
static inline uint8_t rd8(unsigned r) { return *(volatile uint8_t *)(HC + r); }
static inline void wr32(unsigned r, uint32_t v) { *(volatile uint32_t *)(HC + r) = v; }
static inline void wr16(unsigned r, uint16_t v) { *(volatile uint16_t *)(HC + r) = v; }
static inline void wr8(unsigned r, uint8_t v) { *(volatile uint8_t *)(HC + r) = v; }
static inline uint32_t gcc_rd(unsigned r) { return *(volatile uint32_t *)(GCC + r); }
static inline void gcc_wr(unsigned r, uint32_t v) { *(volatile uint32_t *)(GCC + r) = v; }

static uint32_t sec[SECTOR / 4];
static uint32_t last_int;

static uint64_t now(void)
{
	uint64_t v;
	isb();
	__asm__ volatile("mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

static uint64_t ticks_per_s(void)
{
	uint64_t v;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v));
	return v;
}

static void delay_ms(unsigned ms)
{
	uint64_t end = now() + ticks_per_s() / 1000 * ms;
	while (now() < end)
		;
}

/* MMU off: all memory is Device, so build the bytes out of aligned words. */
static uint8_t byte_at(unsigned off)
{
	return sec[off / 4] >> ((off & 3) * 8);
}

static void reset_lines(void)
{
	uint64_t end = now() + ticks_per_s();

	wr8(HC_RESET, RESET_CMD_DAT);
	while ((rd8(HC_RESET) & RESET_CMD_DAT) && now() < end)
		;
	wr32(HC_INT, 0xffffffff);
}

/* 0 when a bit of mask latched (and acked); -1 on a controller error, -2 on timeout. */
static int wait_int_s(uint32_t mask, unsigned seconds)
{
	uint64_t end = now() + ticks_per_s() * seconds;

	for (;;) {
		uint32_t st = rd32(HC_INT);
		if (st & INT_ERR) {
			last_int = st;
			reset_lines();
			return -1;
		}
		if (st & mask) {
			wr32(HC_INT, st & mask);
			return 0;
		}
		if (now() > end) {
			last_int = st;
			reset_lines();
			return -2;
		}
	}
}

static int wait_int(uint32_t mask)
{
	return wait_int_s(mask, 1);
}

static int send(unsigned index, uint32_t arg, unsigned flags, uint32_t xfer)
{
	uint64_t end = now() + ticks_per_s();

	while (rd32(HC_PRESENT) & PRESENT_INHIBIT) {
		if (now() > end) {
			last_int = rd32(HC_PRESENT);
			reset_lines();
			return -3;
		}
	}
	wr32(HC_INT, 0xffffffff);
	if (xfer)
		wr32(HC_BLOCK, (1U << 16) | SECTOR);
	wr32(HC_ARG, arg);
	wr32(HC_XFER_CMD, ((index << 8 | flags) << 16) | xfer);
	return wait_int(INT_CMD);
}

/* One 512-byte block into sec[]. CMD17 takes a sector address on this card. */
static int read_data(unsigned index, uint32_t arg)
{
	int rc = send(index, arg, CMD_R1_DATA, XFER_READ_ONE);

	if (rc)
		return rc;
	rc = wait_int(INT_BUF_RD);
	if (rc)
		return rc;
	for (unsigned i = 0; i < SECTOR / 4; i++)
		sec[i] = rd32(HC_DATA);
	return wait_int(INT_XFER);
}

static int report_fail(const char *what, int rc)
{
	con_hex2(what, "rc=", (uint32_t)rc, "int=", last_int);
	return rc;
}

static int name_is(unsigned entry, const char *want)
{
	for (unsigned i = 0; i < 36; i++) {
		char c = byte_at(entry + 56 + 2 * i);
		if (c != want[i])
			return 0;
		if (!c)
			return 1;
	}
	return 0;
}

static uint32_t boot_lba;

static void test_gpt(void)
{
	/* Names only: string tables of pointers would be absolute relocations. */
	static const char want[3][10] = { "boot_a", "persist", "userdata" };
	unsigned used = 0;
	int rc;

	rc = read_data(MMC_READ_BLOCK, 1);
	if (rc) {
		report_fail("LBA1", rc);
		return;
	}
	if (sec[0] != 0x20494645 || sec[1] != 0x54524150) {	/* "EFI PART" */
		con_hex2("GPT", "bad sig=", sec[0], "next=", sec[1]);
		return;
	}
	uint32_t entries_lba = sec[72 / 4], count = sec[80 / 4], size = sec[84 / 4];
	con_hex2("GPT", "my=", sec[24 / 4], "alt=", sec[32 / 4]);
	if (size != GPT_ENTRY_SIZE || count > 128) {
		con_hex2("GPT", "bad size=", size, 0, 0);
		return;
	}
	for (uint32_t i = 0; i < count; i++) {
		unsigned entry = (i % (SECTOR / GPT_ENTRY_SIZE)) * GPT_ENTRY_SIZE;

		if (entry == 0) {
			rc = read_data(MMC_READ_BLOCK, entries_lba + i / (SECTOR / GPT_ENTRY_SIZE));
			if (rc) {
				report_fail("ENTRIES", rc);
				return;
			}
		}
		if (sec[entry / 4] || sec[entry / 4 + 1])	/* type GUID in use */
			used++;
		for (unsigned w = 0; w < 3; w++) {
			if (!name_is(entry, want[w]))
				continue;
			uint32_t first = sec[(entry + 32) / 4];
			con_hex2(want[w], "n=", i + 1, "lba=", first);
			if (w == 0)
				boot_lba = first;
		}
	}
	con_hex2("GPT", "used=", used, 0, 0);

	if (!boot_lba)
		return;
	rc = read_data(MMC_READ_BLOCK, boot_lba);
	if (rc) {
		report_fail("BOOT_A", rc);
		return;
	}
	/* End-to-end check: the same bytes as the boot_a.img backup. */
	con_str("BOOT_A", sec[0] == 0x52444e41 && sec[1] == 0x2144494f ?
		"ANDROID! magic OK" : "magic MISMATCH");
}

/* CMD6, write-byte access to one EXT_CSD mode field; R1b, so wait out the busy. */
static int mmc_switch(unsigned index, unsigned value)
{
	uint64_t end;
	int rc = send(MMC_SWITCH, (3U << 24) | (index << 16) | (value << 8), CMD_R1B, 0);

	if (rc)
		return report_fail("CMD6", rc);
	for (end = now() + ticks_per_s(); rd32(HC_PRESENT) & PRESENT_INHIBIT;) {
		if (now() > end) {
			last_int = rd32(HC_PRESENT);
			reset_lines();
			return report_fail("CMD6 busy", -3);
		}
	}
	rc = send(MMC_STATUS, CARD_RCA << 16, CMD_R1, 0);
	if (rc)
		return report_fail("CMD6 st", rc);
	uint32_t r1 = rd32(HC_RESP0);
	con_hex2(" cmd6", "idx=", index, "r1=", r1);
	return (r1 & R1_SWITCH_ERROR) ? -1 : 0;
}

/* The SD clock must be off while the root clock changes. */
static int set_50mhz(void)
{
	wr16(HC_CLOCK, rd16(HC_CLOCK) & ~CLOCK_SD_ON);
	/* DLL off below 100 MHz (Linux sdhci_msm_set_uhs_signaling). */
	wr32(MSM_DLL_CONFIG, rd32(MSM_DLL_CONFIG) | DLL_RST);
	wr32(MSM_DLL_CONFIG, rd32(MSM_DLL_CONFIG) | DLL_PDN);
	gcc_wr(GCC_SDCC1_RCG_CFG, RCG_CFG_50M);
	gcc_wr(GCC_SDCC1_RCG_CMD, gcc_rd(GCC_SDCC1_RCG_CMD) | RCG_UPDATE);
	for (uint64_t end = now() + ticks_per_s() / 10; gcc_rd(GCC_SDCC1_RCG_CMD) & RCG_UPDATE;) {
		if (now() > end) {
			con_hex2("RCG", "stuck=", gcc_rd(GCC_SDCC1_RCG_CMD), 0, 0);
			return -1;
		}
	}
	wr16(HC_CLOCK, rd16(HC_CLOCK) | CLOCK_SD_ON);
	delay_ms(1);
	con_hex2("RCG", "50M cfg=", gcc_rd(GCC_SDCC1_RCG_CFG), "apps=", gcc_rd(GCC_SDCC1_APPS_CBCR));
	return 0;
}

static void speed_test(void)
{
	uint64_t start = now();
	uint32_t sum = 0;

	for (uint32_t s = 0; s < SPEED_TEST_SECTORS; s++) {
		int rc = read_data(MMC_READ_BLOCK, boot_lba + s);
		if (rc) {
			con_hex2("SPEED", "fail at=", s, "int=", last_int);
			return;
		}
		for (unsigned i = 0; i < SECTOR / 4; i++)
			sum += sec[i];
	}
	uint64_t ticks = now() - start;
	/* Reports the whole loop: PIO through Device memory, one command per block. */
	con_hex2("SPEED", "ms=", (uint32_t)(ticks * 1000 / ticks_per_s()), "kib=", SPEED_TEST_SECTORS / 2);
	con_hex2(" sum", "got=", sum, "want=", BOOT_A_SUM);
	con_str(" sum", sum == BOOT_A_SUM ? "1 MiB MATCHES backup" : "MISMATCH");
}

static inline uint32_t smmu_rd(unsigned r)
{
	return *(volatile uint32_t *)(SMMU + r);
}

/* How does the SMMU treat the eMMC stream? S2CR type: 0 translate, 1 bypass, 2 fault. */
static void smmu_report(void)
{
	uint32_t cr0 = smmu_rd(SMMU_CR0), smrs = smmu_rd(SMMU_IDR0) & 0xff;

	con_hex2("SMMU", "cr0=", cr0, "smrs=", smrs);
	for (uint32_t n = 0; n < smrs; n++) {
		uint32_t smr = smmu_rd(SMMU_SMR(n));
		uint32_t id = smr & 0x7fff, mask = (smr >> 16) & 0x7fff;

		if ((smr >> 31) && !((id ^ EMMC_SID) & ~mask)) {
			con_hex2(" sid", "smr=", smr, "s2cr=", smmu_rd(SMMU_S2CR(n)));
			return;
		}
	}
	con_str(" sid", "no SMR matches 0x160");
}

/*
 * Boot 11: the kernel driver reset the phone. Where can DMA go? Stream 0x160 is
 * "translate" through bank 0, so show that bank, then read 64 KiB of boot_a to a
 * few places in the kernel's RAM. The last TRY on screen is the one that reset.
 */
static void dma_sweep(void)
{
	static const uint32_t pa[] = { 0xc8000000, 0xd0000000, 0xe0000000, 0xf0000000, 0xffe00000 };
	uint32_t idr1 = smmu_rd(0x024);
	unsigned page = (idr1 >> 31) ? 0x10000 : 0x1000, pages = 1U << (((idr1 >> 28) & 7) + 1);
	unsigned cb0 = page * pages;

	smmu_report();
	con_hex2(" cb0", "sctlr=", smmu_rd(cb0), "tcr=", smmu_rd(cb0 + 0x30));
	con_hex2(" cb0", "ttbr=", smmu_rd(cb0 + 0x20), "hi=", smmu_rd(cb0 + 0x24));
	delay_ms(5000);

	for (unsigned t = 0; t < sizeof(pa) / sizeof(pa[0]); t++) {
		volatile uint32_t *desc = (volatile uint32_t *)(uintptr_t)pa[t];
		volatile uint32_t *buf = (volatile uint32_t *)(uintptr_t)(pa[t] + 0x1000);

		con_hex2("TRY", "pa=", pa[t], 0, 0);
		delay_ms(3000);
		desc[0] = (ADMA_CHUNK << 16) | ADMA_VALID_TRAN;
		desc[1] = pa[t] + 0x1000;
		desc[2] = (ADMA_CHUNK << 16) | ADMA_VALID_TRAN | ADMA_END;
		desc[3] = pa[t] + 0x1000 + ADMA_CHUNK;
		__asm__ volatile("dsb sy" ::: "memory");

		wr8(HC_CTRL1, (rd8(HC_CTRL1) & ~CTRL1_DMA_MASK) | CTRL1_ADMA2_32);
		wr32(HC_ADMA_ADDR, pa[t]);
		wr32(HC_ADMA_ADDR_HI, 0);
		while (rd32(HC_PRESENT) & PRESENT_INHIBIT)
			;
		wr32(HC_INT, 0xffffffff);
		wr32(HC_BLOCK, (128U << 16) | SECTOR);
		wr32(HC_ARG, boot_lba);
		wr32(HC_XFER_CMD, ((MMC_READ_MULTIPLE << 8 | CMD_R1_DATA) << 16) | XFER_READ_DMA);
		int rc = wait_int(INT_CMD);
		if (!rc)
			rc = wait_int_s(INT_XFER, 5);
		if (rc) {
			con_hex2(" fail", "rc=", (uint32_t)rc, "int=", last_int);
			return;
		}
		__asm__ volatile("dsb sy" ::: "memory");
		uint32_t sum = 0;
		for (uint32_t i = 0; i < (2 * ADMA_CHUNK) / 4; i++)
			sum += buf[i];
		if (sum != BOOT_A_SUM_64K) {
			con_hex2(" bad", "got=", sum, "want=", BOOT_A_SUM_64K);
			return;
		}
	}
	con_str("SWEEP", "all addresses OK");
}

static void __attribute__((unused)) test_dma(void)
{
	volatile uint32_t *desc = (volatile uint32_t *)DMA_DESC_PA;
	uint32_t bytes = DMA_TEST_SECTORS * SECTOR, chunks = bytes / ADMA_CHUNK;

	smmu_report();
	/* A bad DMA can reset the phone at once: leave time to photograph the above. */
	con_str("DMA", "16 MiB read in 8 s");
	delay_ms(8000);

	for (uint32_t i = 0; i < chunks; i++) {
		desc[2 * i] = (ADMA_CHUNK << 16) | ADMA_VALID_TRAN | (i == chunks - 1 ? ADMA_END : 0);
		desc[2 * i + 1] = DMA_BUF_PA + i * ADMA_CHUNK;
	}
	__asm__ volatile("dsb sy" ::: "memory");

	wr8(HC_CTRL1, (rd8(HC_CTRL1) & ~CTRL1_DMA_MASK) | CTRL1_ADMA2_32);
	wr32(HC_ADMA_ADDR, DMA_DESC_PA);
	wr32(HC_ADMA_ADDR_HI, 0);
	while (rd32(HC_PRESENT) & PRESENT_INHIBIT)
		;
	wr32(HC_INT, 0xffffffff);
	wr32(HC_BLOCK, (DMA_TEST_SECTORS << 16) | SECTOR);
	wr32(HC_ARG, boot_lba);

	uint64_t start = now();
	wr32(HC_XFER_CMD, ((MMC_READ_MULTIPLE << 8 | CMD_R1_DATA) << 16) | XFER_READ_DMA);
	int rc = wait_int(INT_CMD);
	if (!rc)
		rc = wait_int_s(INT_XFER, 20);
	uint64_t ticks = now() - start;
	if (rc) {
		con_hex2("DMA", "rc=", (uint32_t)rc, "int=", last_int);
		con_hex2(" adma", "err=", rd32(HC_ADMA_ERR), "addr=", rd32(HC_ADMA_ADDR));
		return;
	}
	con_hex2("DMA", "ms=", (uint32_t)(ticks * 1000 / ticks_per_s()), "kib=", bytes / 1024);
	__asm__ volatile("dsb sy" ::: "memory");

	uint32_t sum = 0;
	for (uint32_t i = 0; i < bytes / 4; i++)
		sum += ((volatile uint32_t *)DMA_BUF_PA)[i];
	con_hex2(" sum", "got=", sum, "want=", BOOT_A_SUM_16M);
	con_str(" sum", sum == BOOT_A_SUM_16M ? "16 MiB MATCHES backup" : "MISMATCH");
}

static void go_fast(void)
{
	int rc = read_data(MMC_READ_EXT_CSD, 0);

	if (rc) {
		report_fail("EXTCSD", rc);
		return;
	}
	if (!(byte_at(EXT_CSD_DEVICE_TYPE) & DEVICE_TYPE_HS_52)) {
		con_hex2("CARD", "no HS52 type=", byte_at(EXT_CSD_DEVICE_TYPE), 0, 0);
		return;
	}

	/* 8-bit first, still at 400 kHz, so a wiring or pad problem shows up slowly. */
	if (mmc_switch(EXT_CSD_BUS_WIDTH, BUS_WIDTH_8))
		return;
	wr8(HC_CTRL1, rd8(HC_CTRL1) | CTRL1_8BIT);
	rc = read_data(MMC_READ_EXT_CSD, 0);
	if (rc) {
		report_fail("8BIT", rc);
		return;
	}
	con_hex2(" 8bit", "width=", byte_at(EXT_CSD_BUS_WIDTH), "sec=", sec[212 / 4]);

	if (mmc_switch(EXT_CSD_HS_TIMING, HS_TIMING_HS))
		return;
	wr8(HC_CTRL1, rd8(HC_CTRL1) | CTRL1_HS);
	if (set_50mhz())
		return;
	rc = read_data(MMC_READ_EXT_CSD, 0);
	if (rc) {
		report_fail("HS50", rc);
		return;
	}
	con_hex2(" hs50", "hs=", byte_at(EXT_CSD_HS_TIMING), "sec=", sec[212 / 4]);
	speed_test();
	dma_sweep();
}

/* Linux sdhci_msm_handle_pwr_irq, polled: clear the request and report success. */
static void ack_power(uint32_t ack)
{
	uint64_t end = now() + ticks_per_s() / 10;
	uint32_t st;

	while (!(st = rd32(MSM_PWRCTL_STATUS)) && now() < end)
		;
	if (st) {
		wr32(MSM_PWRCTL_CLEAR, st);
		wr32(MSM_PWRCTL_CTL, ack);
	}
}

static int host_init(void)
{
	/* The SD clock is off while the root clock changes. */
	gcc_wr(GCC_SDCC1_RCG_M, (gcc_rd(GCC_SDCC1_RCG_M) & ~0xffU) | 1);
	gcc_wr(GCC_SDCC1_RCG_N, (gcc_rd(GCC_SDCC1_RCG_N) & ~0xffU) | (~(4U - 1) & 0xff));
	gcc_wr(GCC_SDCC1_RCG_D, (gcc_rd(GCC_SDCC1_RCG_D) & ~0xffU) | (~4U & 0xff));
	gcc_wr(GCC_SDCC1_RCG_CFG, RCG_CFG_400K);
	gcc_wr(GCC_SDCC1_RCG_CMD, gcc_rd(GCC_SDCC1_RCG_CMD) | RCG_UPDATE);
	for (uint64_t end = now() + ticks_per_s() / 10; gcc_rd(GCC_SDCC1_RCG_CMD) & RCG_UPDATE;) {
		if (now() > end) {
			con_hex2("RCG", "stuck=", gcc_rd(GCC_SDCC1_RCG_CMD), 0, 0);
			return -1;
		}
	}
	for (unsigned r = GCC_SDCC1_APPS_CBCR; r <= GCC_SDCC1_AHB_CBCR; r += 4)
		if (gcc_rd(r) & CBCR_OFF)
			gcc_wr(r, gcc_rd(r) | 1);
	delay_ms(1);

	/* Status bits must be enabled to latch; the signal lines stay off (no IRQs). */
	wr32(HC_SIG_EN, 0);
	wr32(HC_INT_EN, 0xffffffff);
	wr32(MSM_VENDOR_SPEC, rd32(MSM_VENDOR_SPEC) | VENDOR_IO_PAD_EN | VENDOR_IO_PAD_1V8);

	wr8(HC_POWER, POWER_ON_3V0);
	ack_power(PWRCTL_BUS_SUCCESS | PWRCTL_IO_SUCCESS);
	wr16(HC_CTRL2_HI, CTRL2_1V8);
	ack_power(PWRCTL_IO_SUCCESS);

	wr8(HC_TIMEOUT, 0xe);
	wr16(HC_CLOCK, rd16(HC_CLOCK) | CLOCK_SD_ON);
	delay_ms(2);	/* at least 74 clocks before the first command */
	return 0;
}

static int card_init(void)
{
	uint32_t ocr = 0;
	int rc;

	/* No response expected. Back to the power-on default: 1-bit, slow. */
	rc = send(MMC_GO_IDLE, 0, CMD_NONE, 0);
	if (rc)
		return report_fail("CMD0", rc);
	delay_ms(2);

	for (unsigned tries = 0; tries < 200 && !(ocr & OCR_READY); tries++) {
		rc = send(MMC_SEND_OP_COND, OCR_SECTOR_DUAL, CMD_R3, 0);
		if (rc)
			return report_fail("CMD1", rc);
		ocr = rd32(HC_RESP0);
		delay_ms(10);
	}
	con_hex2("OCR", "ocr=", ocr, 0, 0);
	if (!(ocr & OCR_READY))
		return -1;

	/* The CID carries the serial number: read it, do not print it. */
	rc = send(MMC_ALL_SEND_CID, 0, CMD_R2, 0);
	if (rc)
		return report_fail("CMD2", rc);
	rc = send(MMC_SET_RCA, CARD_RCA << 16, CMD_R1, 0);
	if (rc)
		return report_fail("CMD3", rc);
	rc = send(MMC_SELECT, CARD_RCA << 16, CMD_R1B, 0);
	if (rc)
		return report_fail("CMD7", rc);
	rc = send(MMC_STATUS, CARD_RCA << 16, CMD_R1, 0);
	if (rc)
		return report_fail("CMD13", rc);

	uint32_t r1 = rd32(HC_RESP0);
	con_hex2("CARD", "r1=", r1, "state=", (r1 >> 9) & 0xf);
	return ((r1 >> 9) & 0xf) == MMC_STATE_TRAN ? 0 : -1;
}

void test_sdhci(void)
{
	con_str("SDHCI", "doha milestone 3, read only");
	con_hex2(" ver", "ver=", rd16(HC_VERSION), "caps=", rd32(HC_CAPS));
	if (rd32(HC_CAPS) == 0xffffffff) {
		con_str("SDHCI", "host not responding, stop");
		return;
	}
	if (host_init() || card_init())
		return;

	int rc = read_data(MMC_READ_EXT_CSD, 0);
	if (rc) {
		report_fail("EXTCSD", rc);
		return;
	}
	/* Bytes 212..215 SEC_COUNT, 179 PARTITION_CONFIG (low bits 0 = user area). */
	con_hex2("EXTCSD", "sectors=", sec[212 / 4], "part=", byte_at(179));
	if (byte_at(179) & 7) {
		con_str("CARD", "not on the user area, stop");
		return;
	}
	test_gpt();
	if (boot_lba)
		go_fast();
}
