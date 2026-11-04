/*
 * doha milestone 3: read the eMMC through the SDHCI host ABL leaves running
 * (sdhci@4744000, qcom,sdhci-msm-v5). Standard SDHCI registers, PIO only, so
 * no DMA and no SMMU. No clock, reset-all or card init: ABL's setup is kept.
 *
 * READ ONLY by construction: the only commands sent are CMD13 (status),
 * CMD8 (read EXT_CSD) and CMD17 (read one block).
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
#define HC_CLOCK		0x2c	/* clock (16), timeout (8), software reset (8) */
#define HC_RESET		0x2f
#define HC_INT			0x30	/* normal (16), error (16); write 1 to clear */
#define HC_INT_EN		0x34
#define HC_SIG_EN		0x38
#define HC_CTRL2		0x3c
#define HC_CAPS			0x40
#define HC_VERSION		0xfe

#define PRESENT_INHIBIT		0x3	/* command and data lines */
#define CLOCK_SD_ON		(1U << 2)
#define RESET_CMD_DAT		0x6
#define INT_CMD			(1U << 0)
#define INT_XFER		(1U << 1)
#define INT_BUF_RD		(1U << 5)
#define INT_ERR			(1U << 15)

/* Command register: index << 8 | data present | index check | CRC check | 48-bit response */
#define CMD_R1			0x1a
#define CMD_R1_DATA		0x3a
#define XFER_READ_ONE		((1U << 4) | (1U << 1))	/* card to host, count enable, no DMA */

#define MMC_READ_EXT_CSD	8
#define MMC_STATUS		13
#define MMC_READ_BLOCK		17
#define MMC_STATE_TRAN		4

#define SECTOR			512
#define GPT_ENTRY_SIZE		128

#define isb() __asm__ volatile("isb" ::: "memory")

static inline uint32_t rd32(unsigned r) { return *(volatile uint32_t *)(HC + r); }
static inline uint16_t rd16(unsigned r) { return *(volatile uint16_t *)(HC + r); }
static inline uint8_t rd8(unsigned r) { return *(volatile uint8_t *)(HC + r); }
static inline void wr32(unsigned r, uint32_t v) { *(volatile uint32_t *)(HC + r) = v; }
static inline void wr8(unsigned r, uint8_t v) { *(volatile uint8_t *)(HC + r) = v; }

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
	con_hex2(" ent", "size=", size, 0, 0);
	if (size != GPT_ENTRY_SIZE || count > 128) {
		con_str("GPT", "unexpected entry layout");
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
			uint32_t first = sec[(entry + 32) / 4], last = sec[(entry + 40) / 4];
			con_str(" part", want[w]);
			con_hex2("  p", "n=", i + 1, "hi=", sec[(entry + 36) / 4]);
			con_hex2("  lba", "1st=", first, "end=", last);
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
	con_hex2(" head", "w0=", sec[0], "w1=", sec[1]);
}

void test_sdhci(void)
{
	uint32_t clock = rd32(HC_CLOCK);

	con_str("SDHCI", "doha milestone 3, read only");
	con_hex2(" ver", "ver=", rd16(HC_VERSION), "caps=", rd32(HC_CAPS));
	con_hex2(" state", "pres=", rd32(HC_PRESENT), "ctl1=", rd32(HC_CTRL1));
	con_hex2(" clk", "clk=", clock, "ctl2=", rd32(HC_CTRL2));
	con_hex2(" int", "st=", rd32(HC_INT), "en=", rd32(HC_INT_EN));
	if (!(clock & CLOCK_SD_ON) || rd32(HC_CAPS) == 0xffffffff) {
		con_str("SDHCI", "host not running, stop");
		return;
	}

	/* Status bits must be enabled to latch; the signal lines stay off (no IRQs). */
	wr32(HC_SIG_EN, 0);
	wr32(HC_INT_EN, 0xffffffff);

	/* Linux names the card mmc0:0001; firmware may have given another RCA. */
	uint32_t state = 0xff;
	for (uint32_t rca = 1; rca <= 2 && state == 0xff; rca++) {
		int rc = send(MMC_STATUS, rca << 16, CMD_R1, 0);
		if (rc) {
			con_hex2(" cmd13", "rca=", rca, "int=", last_int);
			continue;
		}
		uint32_t r1 = rd32(HC_RESP0);
		state = (r1 >> 9) & 0xf;
		con_hex2(" cmd13", "rca=", rca, "r1=", r1);
	}
	if (state != MMC_STATE_TRAN) {
		con_hex2("CARD", "state=", state, 0, 0);
		con_str("CARD", "not in tran state, stop");
		return;
	}

	int rc = read_data(MMC_READ_EXT_CSD, 0);
	if (rc) {
		report_fail("EXTCSD", rc);
		return;
	}
	/* Bytes 212..215 SEC_COUNT, 179 PARTITION_CONFIG (low bits 0 = user area),
	 * 185 HS_TIMING, 15 CMDQ_MODE_EN. */
	con_hex2("EXTCSD", "sectors=", sec[212 / 4], "part=", byte_at(179));
	con_hex2(" mode", "hs=", byte_at(185), "cmdq=", byte_at(15));
	if (byte_at(179) & 7) {
		con_str("CARD", "not on the user area, stop");
		return;
	}
	test_gpt();
}
