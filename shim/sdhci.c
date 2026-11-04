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
 * READ ONLY by construction. The only commands sent are CMD0, CMD1, CMD2, CMD3
 * and CMD7 (reset and select the card, nothing reaches the flash), CMD13
 * (status), CMD8 (read EXT_CSD) and CMD17 (read one block). No CMD6, CMD24, CMD25.
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
#define HC_VERSION		0xfe

/* sdhci_msm_v5_offset */
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

#define PRESENT_INHIBIT		0x3	/* command and data lines */
#define CLOCK_SD_ON		(1U << 2)
#define POWER_ON_3V0		0x0d	/* bus on, 3.0 V: vdd is 2.95 V */
#define CTRL2_1V8		(1U << 3)
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
#define MMC_SELECT		7
#define MMC_READ_EXT_CSD	8
#define MMC_STATUS		13
#define MMC_READ_BLOCK		17
#define MMC_STATE_TRAN		4
#define OCR_SECTOR_DUAL		0x40ff8080	/* sector addressing, 1.8 V and 2.7-3.6 V */
#define OCR_READY		(1U << 31)
#define CARD_RCA		1

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
static int wait_int(uint32_t mask)
{
	uint64_t end = now() + ticks_per_s();

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

static void test_gpt(void)
{
	/* Names only: string tables of pointers would be absolute relocations. */
	static const char want[3][10] = { "boot_a", "persist", "userdata" };
	uint32_t boot_lba = 0;
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
	con_hex2(" ent", "lba=", entries_lba, "n=", count);
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
	con_str("BOOT_A", sec[0] == 0x52444e41 && sec[1] == 0x21444f49 ?
		"ANDROID! magic OK" : "magic MISMATCH");
}

/* Linux sdhci_msm_handle_pwr_irq, polled: clear the request and report success. */
static void ack_power(uint32_t ack)
{
	uint64_t end = now() + ticks_per_s() / 10;
	uint32_t st;

	while (!(st = rd32(MSM_PWRCTL_STATUS)) && now() < end)
		;
	con_hex2(" pwrctl", "st=", st, "ack=", ack);
	if (st) {
		wr32(MSM_PWRCTL_CLEAR, st);
		wr32(MSM_PWRCTL_CTL, ack);
	}
}

static int host_init(void)
{
	con_hex2("GCC", "apps=", gcc_rd(GCC_SDCC1_APPS_CBCR), "ahb=", gcc_rd(GCC_SDCC1_AHB_CBCR));
	con_hex2(" rcg", "cmd=", gcc_rd(GCC_SDCC1_RCG_CMD), "cfg=", gcc_rd(GCC_SDCC1_RCG_CFG));
	con_hex2("VENDOR", "spec=", rd32(MSM_VENDOR_SPEC), "caps=", rd32(MSM_VENDOR_CAPS0));

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
	con_hex2("RCG", "cmd=", gcc_rd(GCC_SDCC1_RCG_CMD), "apps=", gcc_rd(GCC_SDCC1_APPS_CBCR));

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
	con_hex2(" host", "clk=", rd32(HC_CLOCK), "pres=", rd32(HC_PRESENT));
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
	con_hex2(" state", "pres=", rd32(HC_PRESENT), "ctl1=", rd32(HC_CTRL1));
	con_hex2(" clk", "clk=", rd32(HC_CLOCK), "ctl2=", rd32(HC_CTRL2));
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
}
