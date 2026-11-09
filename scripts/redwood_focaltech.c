/*
 * The touch screen of the Moto G8 Plus (doha): a FocalTech FT8719 -- the panel's own display driver,
 * which does the touch as well -- on the SPI bus of the SoC's serial engine 2 (QUP 0), the same engine,
 * the same four pins (GPIO 6 to 9) and the same interrupt line (GPIO 88) as willow's Novatek, whose driver
 * (bsd/dev/redwood_novatek.c) this one follows for the clocks, the pins and the engine. A source of touches
 * for /dev/redwood-touch (sys/redwood_input.h). Only with boot-arg touchscreen=1 and device=doha.
 *
 * The FT8719's touch half has no flash ("0flash"): whoever drives it gives it its firmware at every start,
 * into its program RAM, through the boot loader in its ROM. After the UEFI has started the panel nobody has,
 * and the ROM sits waiting. Its reset line (GPIO 87) is the panel's as well (the device tree's
 * focaltech,share_reset_gpio: "TP reset pin is shared with LCD"): pulled low it would reset the display the
 * UEFI set up, and nothing here could bring the picture back. So this driver never touches it. It does what
 * Motorola's driver does when it finds the chip in its ROM without a reset (focaltech_flash.c,
 * fts_fwupg_check_boot_recovery): the boot id (0x90: 0x87 0x19), the boot state (0xd0: 2), and the
 * firmware written into program RAM, checked and started (focaltech_flash_ft8719.c, fts_fw_write_start
 * with need_reset false). The firmware is the phone's own, from Android's /vendor/firmware, as
 * fw/focaltech_ts_fw.bin of the small image (FocalTech's, not this repository's). Without it, this stops
 * after saying what the chip is.
 *
 * The bus protocol (Motorola's focaltech_spi_v1_1.c, the FT8719's): SPI mode 1; every transfer's first
 * byte says what it is -- 0x05 a status poll, 0xc0 a command, 0x3f data -- and the chip wants 30 us
 * between that byte and the rest with the chip select held, and 150 us with it released after. A command is
 * 0xc0, a control byte (0x00 write, 0xa0 read with CRC) or'ed with its length, and its bytes (with two
 * bytes of the data's length after them once the firmware runs); between packages the status is polled
 * until the chip is idle. A read's data comes back with a CRC-16 (0x8408, reflected, from 0xffff), checked.
 *
 * The report: 0x90 or so, the number of fingers, then 6 bytes a finger (event and X high, X low, id and Y
 * high, Y low, pressure, area), read as a data package of its own once the firmware runs. A thread looks at
 * the interrupt line 100 times a second (touch_poll_us=N) and reads a report when the chip pulls it low.
 */
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/redwood_input.h>
#include <sys/systm.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t thread_terminate(thread_t thread);
extern const uint8_t *redwood_image_file(const char *dir, const char *name, uint64_t *size, int *disk_out);
extern void loader_log_putc(char c);

static int say(const char *format, ...) __printflike(1, 2);

static int
say(const char *format, ...)
{
	char line[400];
	va_list list;

	va_start(list, format);
	vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	for (const char *c = line; *c != 0; c++) {
		loader_log_putc(*c);
	}
	return printf("%s", line);
}
#define printf say

static vm_offset_t tlmm, gcc, se;

static inline uint32_t
rd(vm_offset_t address)
{
	return *(volatile uint32_t *)address;
}

static inline void
wr(vm_offset_t address, uint32_t value)
{
	*(volatile uint32_t *)address = value;
}

static void
sleep_us(uint32_t us)
{
	delay_for_interval(us, NSEC_PER_USEC);
}

static void
sleep_ms(uint32_t ms)
{
	delay_for_interval(ms, NSEC_PER_MSEC);
}

/* ---- pins (TLMM): doha's device tree, qupv3_se2_spi_active and pmx_ts_* -------------------------------- */

#define TLMM_PHYS               0x00500000UL
#define TLMM_SIZE               0x100000UL
#define GPIO_CFG(n)             (tlmm + 0x1000UL * (n))         /* [1:0] pull, [5:2] function, [8:6] drive, [9] output */
#define GPIO_IO(n)              (tlmm + 0x1000UL * (n) + 4)     /* bit 0 in, bit 1 out */
#define PULL_NONE               0
#define PULL_UP                 3

#define PIN_SPI_FIRST           6       /* 6 to 9, "qup02" */
#define PIN_RESET               87      /* the panel's reset as well: looked at, never driven */
#define PIN_INT                 88      /* low: a report is waiting */
#define PIN_FUNCTION_SPI        1

static void
gpio_configure(unsigned pin, unsigned function, unsigned pull, unsigned ma, bool output)
{
	wr(GPIO_CFG(pin), pull | function << 2 | (ma / 2 - 1) << 6 | (output ? 1u << 9 : 0));
}

static bool
gpio_get(unsigned pin)
{
	return rd(GPIO_IO(pin)) & 1;
}

static void
gpio_describe(const char *name, unsigned pin)
{
	uint32_t cfg = rd(GPIO_CFG(pin)), io = rd(GPIO_IO(pin));

	printf("focaltech: %s (GPIO %u): function %u, pull %u, %u mA, %s; reads %u%s\n", name, pin, cfg >> 2 & 0xf,
	    cfg & 3, ((cfg >> 6 & 7) + 1) * 2, (cfg & (1u << 9)) ? "output" : "input", io & 1,
	    (cfg & (1u << 9)) ? ((io & 2) ? ", driven high" : ", driven low") : "");
}

/* ---- clocks (GCC), as bsd/dev/redwood_novatek.c ------------------------------------------------------- */

#define GCC_PHYS                0x01400000UL
#define GCC_SIZE                0x80000UL
#define GCC_VOTE                (gcc + 0x7900c)
#define VOTE_QUP0_M_AHB         (1u << 6)
#define VOTE_QUP0_S_AHB         (1u << 7)
#define VOTE_QUP0_CORE          (1u << 8)
#define VOTE_QUP0_CORE_2X       (1u << 9)
#define VOTE_QUP0_SE2           (1u << 12)
#define GCC_QUP0_M_AHB_CBCR     (gcc + 0x1f004)
#define GCC_QUP0_S_AHB_CBCR     (gcc + 0x1f008)
#define GCC_QUP0_SE2_CBCR       (gcc + 0x1f3a4)
#define GCC_QUP0_SE2_CMD        (gcc + 0x1f3a8)
#define GCC_QUP0_SE2_CFG        (gcc + 0x1f3ac)
#define GCC_QUP0_SE2_DFSR       (gcc + 0x1f3bc)
#define GCC_QUP0_SE2_PERF_CFG(l) (gcc + 0x1f3c4 + 4 * (l))
#define GCC_QUP0_SE2_PERF_M(l)  (gcc + 0x1f404 + 4 * (l))
#define GCC_QUP0_SE2_PERF_N(l)  (gcc + 0x1f444 + 4 * (l))
#define CLOCK_OFF               (1u << 31)
#define XO_HZ                   19200000

static uint32_t se_source_hz, se_clock_select;

static uint32_t
rcg_rate(uint32_t cfg, uint32_t m, uint32_t not_n_minus_m)
{
	static const uint32_t parent[8] = { XO_HZ, 600000000, 300000000, 0, 384000000, 0, 0, 0 };
	uint64_t hz = parent[cfg >> 8 & 7];
	uint32_t divider = cfg & 0x1f, mode = cfg >> 12 & 3;

	if (divider) {
		hz = hz * 2 / (divider + 1);
	}
	if (mode) {
		uint32_t n = (~not_n_minus_m & 0xffff) + (m & 0xffff);

		if (n) {
			hz = hz * (m & 0xffff) / n;
		}
	}
	return (uint32_t)hz;
}

static bool
clocks_on(void)
{
	printf("focaltech: clocks before: votes %#x, m-ahb %#x, s-ahb %#x, engine %#x, its source %#x (preset rates %s)\n",
	    rd(GCC_VOTE), rd(GCC_QUP0_M_AHB_CBCR), rd(GCC_QUP0_S_AHB_CBCR), rd(GCC_QUP0_SE2_CBCR), rd(GCC_QUP0_SE2_CFG),
	    (rd(GCC_QUP0_SE2_DFSR) & 1) ? "on" : "off");
	wr(GCC_VOTE, rd(GCC_VOTE) | VOTE_QUP0_CORE_2X | VOTE_QUP0_CORE | VOTE_QUP0_M_AHB | VOTE_QUP0_S_AHB);
	if (rd(GCC_QUP0_SE2_DFSR) & 1) {
		for (uint32_t level = 0; level < 8; level++) {
			uint32_t hz = rcg_rate(rd(GCC_QUP0_SE2_PERF_CFG(level)), rd(GCC_QUP0_SE2_PERF_M(level)),
			    rd(GCC_QUP0_SE2_PERF_N(level)));

			if (hz >= 4000000 && (se_source_hz == 0 || hz < se_source_hz)) {
				se_source_hz = hz;
				se_clock_select = level;
			}
		}
		if (se_source_hz == 0) {
			printf("focaltech: no usable preset clock rate\n");
			return false;
		}
	} else {
		wr(GCC_QUP0_SE2_CFG, (rd(GCC_QUP0_SE2_CFG) & ~0x371fu) | 1);
		wr(GCC_QUP0_SE2_CMD, rd(GCC_QUP0_SE2_CMD) | 1);
		for (int i = 0; i < 500 && (rd(GCC_QUP0_SE2_CMD) & 1); i++) {
			sleep_us(10);
		}
		if (rd(GCC_QUP0_SE2_CMD) & 1) {
			printf("focaltech: the serial engine's clock does not take its configuration (%#x)\n",
			    rd(GCC_QUP0_SE2_CMD));
			return false;
		}
		se_source_hz = XO_HZ;
		se_clock_select = 0;
	}
	wr(GCC_VOTE, rd(GCC_VOTE) | VOTE_QUP0_SE2);
	for (int i = 0; i < 1000; i++) {
		if (!((rd(GCC_QUP0_M_AHB_CBCR) | rd(GCC_QUP0_S_AHB_CBCR) | rd(GCC_QUP0_SE2_CBCR)) & CLOCK_OFF)) {
			printf("focaltech: clocks on; the engine's source runs at %u kHz (preset %u)\n", se_source_hz / 1000,
			    se_clock_select);
			return true;
		}
		sleep_us(10);
	}
	printf("focaltech: clocks stay off: %#x %#x %#x\n", rd(GCC_QUP0_M_AHB_CBCR), rd(GCC_QUP0_S_AHB_CBCR),
	    rd(GCC_QUP0_SE2_CBCR));
	return false;
}

/* ---- SPI through the serial engine (GENI), as bsd/dev/redwood_novatek.c, in mode 1 -------------------- */

#define SE_PHYS                 0x04a88000UL
#define SE_SIZE                 0x4000UL
#define GENI_FORCE_DEFAULT      (se + 0x020)
#define GENI_OUTPUT_CTRL        (se + 0x024)
#define GENI_CGC_CTRL           (se + 0x028)
#define GENI_STATUS             (se + 0x040)
#define GENI_SER_M_CLK_CFG      (se + 0x048)
#define GENI_IF_DISABLE_RO      (se + 0x064)
#define GENI_FW_REVISION_RO     (se + 0x068)
#define GENI_CLK_SEL            (se + 0x07c)
#define SPI_CPHA                (se + 0x224)
#define SPI_LOOPBACK            (se + 0x22c)
#define SPI_CPOL                (se + 0x230)
#define SPI_DEMUX_OUTPUT_INV    (se + 0x24c)
#define SPI_DEMUX_SEL           (se + 0x250)
#define GENI_BYTE_GRAN          (se + 0x254)
#define GENI_DMA_MODE_EN        (se + 0x258)
#define SPI_TRANS_CFG           (se + 0x25c)
#define GENI_TX_PACKING_CFG0    (se + 0x260)
#define GENI_TX_PACKING_CFG1    (se + 0x264)
#define SPI_WORD_LEN            (se + 0x268)
#define SPI_TX_TRANS_LEN        (se + 0x26c)
#define SPI_RX_TRANS_LEN        (se + 0x270)
#define SPI_DELAY_COUNTERS      (se + 0x278)
#define GENI_RX_PACKING_CFG0    (se + 0x284)
#define GENI_RX_PACKING_CFG1    (se + 0x288)
#define GENI_M_CMD0             (se + 0x600)
#define GENI_M_CMD_CTRL         (se + 0x604)
#define GENI_M_IRQ_STATUS       (se + 0x610)
#define GENI_M_IRQ_EN           (se + 0x614)
#define GENI_M_IRQ_CLEAR        (se + 0x618)
#define GENI_S_IRQ_CLEAR        (se + 0x648)
#define GENI_TX_FIFO            (se + 0x700)
#define GENI_RX_FIFO            (se + 0x780)
#define GENI_TX_FIFO_STATUS     (se + 0x800)
#define GENI_RX_FIFO_STATUS     (se + 0x804)
#define GENI_TX_WATERMARK       (se + 0x80c)
#define GENI_RX_WATERMARK       (se + 0x810)
#define GENI_RX_RFR_WATERMARK   (se + 0x814)
#define SE_DMA_TX_IRQ_CLR       (se + 0xc44)
#define SE_DMA_RX_IRQ_CLR       (se + 0xd44)
#define SE_GSI_EVENT_EN         (se + 0xe18)
#define SE_IRQ_EN               (se + 0xe1c)
#define SE_HW_PARAM_0           (se + 0xe24)
#define SE_DMA_GENERAL_CFG      (se + 0xe30)

#define M_CMD_DONE              (1u << 0)
#define M_CMD_CANCEL            (1u << 4)
#define M_CMD_ABORT             (1u << 5)
#define M_ERRORS                ((1u << 1) | (1u << 2) | (1u << 3) | (1u << 24) | (1u << 25) | (1u << 28) | (1u << 29))
#define SPI_FULL_DUPLEX         (3u << 27)
#define SPI_FRAGMENTATION       (1u << 2)       /* the chip select stays asserted after this command (spi-geni-qcom) */

static uint32_t fifo_depth;

static const char *
geni_spi_init(uint32_t hz)
{
	uint32_t divider;

	if ((rd(GENI_FW_REVISION_RO) >> 8 & 0xff) != 1) {
		return "the serial engine has no SPI firmware";
	}
	if (rd(GENI_IF_DISABLE_RO) & 1) {
		return "the serial engine's FIFO interface is disabled";
	}
	fifo_depth = rd(SE_HW_PARAM_0) >> 16 & 0x3f;
	if (fifo_depth < 4) {
		return "the serial engine reports no FIFO";
	}
	wr(SE_GSI_EVENT_EN, 0);
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
	wr(GENI_S_IRQ_CLEAR, 0xffffffff);
	wr(SE_DMA_TX_IRQ_CLR, 0xffffffff);
	wr(SE_DMA_RX_IRQ_CLR, 0xffffffff);
	wr(GENI_CGC_CTRL, rd(GENI_CGC_CTRL) | 0x7f);
	wr(SE_DMA_GENERAL_CFG, rd(SE_DMA_GENERAL_CFG) | 0xf);
	wr(GENI_OUTPUT_CTRL, 0x7f);
	wr(GENI_FORCE_DEFAULT, 1);
	wr(GENI_DMA_MODE_EN, rd(GENI_DMA_MODE_EN) & ~1u);
	wr(GENI_RX_WATERMARK, fifo_depth - 3);
	wr(GENI_RX_RFR_WATERMARK, fifo_depth - 2);
	wr(GENI_TX_WATERMARK, 0);
	wr(SE_IRQ_EN, rd(SE_IRQ_EN) | 0xf);
	wr(GENI_M_IRQ_EN, rd(GENI_M_IRQ_EN) | 0x7fc0007f);

	/* SPI mode 1 (fts_ts_probe sets SPI_MODE_1 for the FT8719): CPHA 1, CPOL 0; chip select 0, 8 bits, MSB first */
	wr(SPI_LOOPBACK, 0);
	wr(SPI_DEMUX_SEL, 0);
	wr(SPI_CPHA, 1);
	wr(SPI_CPOL, 0);
	wr(SPI_DEMUX_OUTPUT_INV, 0);
	wr(SPI_TRANS_CFG, rd(SPI_TRANS_CFG) & ~2u);
	wr(SPI_DELAY_COUNTERS, 0);
	wr(GENI_TX_PACKING_CFG0, 0x0007f8fe);
	wr(GENI_TX_PACKING_CFG1, 0x000ffefe);
	wr(GENI_RX_PACKING_CFG0, 0x0007f8fe);
	wr(GENI_RX_PACKING_CFG1, 0x000ffefe);
	wr(GENI_BYTE_GRAN, 0);
	wr(SPI_WORD_LEN, 8 - 4);

	divider = (se_source_hz + hz - 1) / hz;
	wr(GENI_CLK_SEL, se_clock_select & 7);
	wr(GENI_SER_M_CLK_CFG, (divider ? divider : 1) << 4 | 1);
	printf("focaltech: SPI mode 1 at %u kHz (divider %u), FIFO of %u words\n",
	    se_source_hz / (divider ? divider : 1) / 1000, divider, fifo_depth);
	return NULL;
}

static void
geni_drain(uint8_t *rx, uint32_t length, uint32_t *received)
{
	uint32_t status = rd(GENI_RX_FIFO_STATUS), words = status & 0x01ffffff, bytes = words * 4;

	if (status & 0x80000000u) {
		uint32_t valid = status >> 28 & 7;

		if (valid && valid < 4) {
			bytes -= 4 - valid;
		}
	}
	for (uint32_t i = 0; i < words; i++) {
		uint32_t word = rd(GENI_RX_FIFO);

		for (int j = 0; j < 4 && bytes; j++, bytes--) {
			if (*received < length) {
				if (rx) {
					rx[*received] = (uint8_t)(word >> (8 * j));
				}
				(*received)++;
			}
		}
	}
}

static void
geni_recover(void)
{
	wr(GENI_M_CMD_CTRL, 1u << 2);
	for (int i = 0; i < 2000 && !(rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL); i++) {
		sleep_us(100);
	}
	if (!(rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL)) {
		wr(GENI_M_CMD_CTRL, 1u << 1);
		for (int i = 0; i < 2000 && !(rd(GENI_M_IRQ_STATUS) & M_CMD_ABORT); i++) {
			sleep_us(100);
		}
	}
	for (int i = 0; i < 64 && (rd(GENI_RX_FIFO_STATUS) & 0x01ffffff); i++) {
		(void)rd(GENI_RX_FIFO);
	}
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
}

/* One command of the engine: `length` bytes out and as many in; `hold`: the chip select stays asserted after. */
static bool
geni_transfer(const uint8_t *tx, uint8_t *rx, uint32_t length, bool hold)
{
	static unsigned complaints;
	uint32_t sent = 0, received = 0, status = 0;
	uint64_t deadline;

	for (int i = 0; rd(GENI_STATUS) & 1; i++) {
		if (i > 2000) {
			geni_recover();
			break;
		}
		sleep_us(100);
	}
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
	wr(SPI_TX_TRANS_LEN, length);
	wr(SPI_RX_TRANS_LEN, length);
	wr(GENI_M_CMD0, SPI_FULL_DUPLEX | (hold ? SPI_FRAGMENTATION : 0));
	/* 64 KB at 4 MHz is 131 ms: room for the biggest of the firmware's packets */
	clock_interval_to_deadline(200 + length / 256, NSEC_PER_MSEC, &deadline);
	while (mach_absolute_time() < deadline) {
		while (sent < length && (rd(GENI_TX_FIFO_STATUS) & 0x0fffffff) + 1 < fifo_depth) {
			uint32_t word = 0;

			for (int j = 0; j < 4 && sent < length; j++, sent++) {
				word |= (uint32_t)tx[sent] << (8 * j);
			}
			wr(GENI_TX_FIFO, word);
		}
		status = rd(GENI_M_IRQ_STATUS);
		geni_drain(rx, length, &received);
		if (status & M_ERRORS) {
			break;
		}
		if (status & M_CMD_DONE) {
			geni_drain(rx, length, &received);
			wr(GENI_M_IRQ_CLEAR, status);
			if (received == length) {
				return true;
			}
			break;
		}
	}
	if (complaints++ < 8) {
		printf("focaltech: SPI transfer of %u bytes failed: status %#x, sent %u, received %u\n", length, status,
		    sent, received);
	}
	geni_recover();
	return false;
}

/* ---- the FT8719's SPI protocol (focaltech_spi_v1_1.c) ---------------------------------------------------- */

#define PKG_STATUS              0x05
#define PKG_COMMAND             0xc0
#define PKG_DATA                0x3f
#define CTRL_WRITE              0x00
#define CTRL_READ               0xa0            /* 0x80 read | 0x20 data CRC */
#define FTS_BUF                 (64 * 1024 + 8)

static uint8_t fts_tx[FTS_BUF], fts_rx[FTS_BUF];
static bool fw_running;                         /* the firmware runs: commands carry the data's length, idle is 1 */

/* A package: its first byte, 30 us with the chip selected, the rest, and 150 us with it released. */
static bool
fts_package(uint8_t *tx, uint8_t *rx, uint32_t length)
{
	bool ok;

	if (length > 1) {
		ok = geni_transfer(tx, rx, 1, true);
		sleep_us(30);
		ok = ok && geni_transfer(tx + 1, rx + 1, length - 1, false);
	} else {
		ok = geni_transfer(tx, rx, 1, false);
	}
	sleep_us(150);
	return ok;
}

/* Poll the status until the chip is idle: (status & 0x81) == 0 in its ROM, 1 once its firmware runs. */
static bool
fts_wait_idle(void)
{
	uint8_t tx[2] = { PKG_STATUS, 0 }, rx[2] = { 0, 0 };
	uint8_t idle = fw_running ? 1 : 0;

	for (int i = 0; i < 100; i++) {
		sleep_us(150);
		if (fts_package(tx, rx, 2) && (rx[1] & 0x81) == idle) {
			return true;
		}
	}
	printf("focaltech: the chip stays busy (status %#x)\n", rx[1]);
	return false;
}

static bool
fts_command(uint8_t ctrl, const uint8_t *cmd, uint32_t cmdlen)
{
	uint8_t tx[20], rx[20];

	if (cmdlen == 0 || cmdlen > 15) {
		return false;
	}
	tx[0] = PKG_COMMAND;
	tx[1] = ctrl | (uint8_t)(cmdlen & 0x0f);
	memcpy(tx + 2, cmd, cmdlen);
	return fts_package(tx, rx, cmdlen + 2);
}

static uint16_t
crc_kermit(const uint8_t *data, uint32_t length)
{
	uint16_t crc = 0xffff;

	for (uint32_t i = 0; i < length; i++) {
		crc ^= data[i];
		for (int j = 0; j < 8; j++) {
			crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0x8408) : (uint16_t)(crc >> 1);
		}
	}
	return crc;
}

/* fts_boot_write: a command of `cmdlen` bytes, then (if any) its data in a data package. */
static bool
fts_write_cmd(const uint8_t *cmd, uint32_t cmdlen, const uint8_t *data, uint32_t datalen)
{
	uint8_t c[16];

	if (cmdlen > 13 || datalen > FTS_BUF - 8 || !fts_wait_idle()) {
		return false;
	}
	memcpy(c, cmd, cmdlen);
	if (fw_running && datalen) {
		c[cmdlen++] = (uint8_t)(datalen >> 8);
		c[cmdlen++] = (uint8_t)datalen;
	}
	if (!fts_command(CTRL_WRITE, c, cmdlen)) {
		return false;
	}
	if (datalen == 0) {
		return true;
	}
	if (!fts_wait_idle()) {
		return false;
	}
	fts_tx[0] = PKG_DATA;
	memcpy(fts_tx + 1, data, datalen);
	return fts_package(fts_tx, fts_rx, datalen + 1);
}

/* fts_read: a read command (none if cmd is NULL), then `datalen` bytes and their CRC in a data package. */
static bool
fts_read(const uint8_t *cmd, uint32_t cmdlen, uint8_t *data, uint32_t datalen)
{
	static unsigned crc_complaints;
	uint8_t c[16];
	uint16_t crc;

	if (datalen == 0 || datalen > FTS_BUF - 8 || cmdlen > 13) {
		return false;
	}
	if (cmd != NULL && cmdlen) {
		if (!fts_wait_idle()) {
			return false;
		}
		memcpy(c, cmd, cmdlen);
		if (fw_running) {
			c[cmdlen++] = (uint8_t)(datalen >> 8);
			c[cmdlen++] = (uint8_t)datalen;
		}
		if (!fts_command(CTRL_READ, c, cmdlen) || !fts_wait_idle()) {
			return false;
		}
	}
	memset(fts_tx, 0, datalen + 3);
	fts_tx[0] = PKG_DATA;
	if (!fts_package(fts_tx, fts_rx, datalen + 3)) {
		return false;
	}
	memcpy(data, fts_rx + 1, datalen);
	crc = crc_kermit(fts_rx + 1, datalen);
	if (crc != (uint16_t)(fts_rx[datalen + 1] | fts_rx[datalen + 2] << 8)) {
		if (crc_complaints++ < 8) {
			printf("focaltech: read of %u bytes (command %#x): CRC %#x, the chip's %#x\n", datalen,
			    cmd ? cmd[0] : 0, crc, fts_rx[datalen + 1] | fts_rx[datalen + 2] << 8);
		}
		return false;
	}
	return true;
}

static bool
fts_read_reg(uint8_t reg, uint8_t *value)
{
	return fts_read(&reg, 1, value, 1);
}

static void
hex_line(const char *what, const uint8_t *bytes, uint32_t length)
{
	char text[3 * 64 + 1];
	uint32_t n = 0;

	for (uint32_t i = 0; i < length && i < 64; i++) {
		n += (uint32_t)snprintf(text + n, sizeof(text) - n, " %02x", bytes[i]);
	}
	printf("focaltech: %s:%s\n", what, text);
}

/* ---- the firmware into program RAM (focaltech_flash_ft8719.c) ------------------------------------------- */

#define FW_APP_INFO             0x100           /* the code's length and its complement, big-endian */
#define FW_MIN                  0x120
#define FW_MAX                  (64 * 1024)
#define CMD_START1              0x55
#define CMD_READ_ID             0x90
#define CMD_PRAM_WRITE          0xae            /* 3 bytes of address, 2 of length, then the data */
#define CMD_ECC                 0xcc            /* 3 bytes of address, 3 of length */
#define CMD_ECC_FINISH          0xce
#define CMD_ECC_READ            0xcd
#define CMD_START_APP           0x08
#define REG_BOOT_STATE          0xd0            /* 2: the ROM waits for a firmware */
#define REG_CHIP_ID             0xa3
#define REG_FW_VERSION          0xa6

static uint16_t
ecc_host(const uint8_t *data, uint32_t length)
{
	uint16_t ecc = 0;

	for (uint32_t i = 0; i + 1 < length; i += 2) {
		ecc ^= (uint16_t)(data[i] << 8 | data[i + 1]);
		for (int j = 0; j < 16; j++) {
			ecc = (ecc & 1) ? (uint16_t)((ecc >> 1) ^ 0x8408) : (uint16_t)(ecc >> 1);
		}
	}
	return ecc;
}

static bool
fts_download(const uint8_t *fw, uint64_t fw_size)
{
	uint8_t cmd[7], v[2], dbval = 0;
	static const uint8_t f2[6] = { 0xf2, 0x00, 0x78, 0x0a, 0x00, 0x02 };
	uint32_t length, packet, ecc_chip = 0;
	uint16_t code, code_n, ecc;

	if (fw_size < FW_APP_INFO + 4) {
		printf("focaltech: the firmware file is too short (%llu bytes)\n", fw_size);
		return false;
	}
	code = (uint16_t)(fw[FW_APP_INFO] << 8 | fw[FW_APP_INFO + 1]);
	code_n = (uint16_t)(fw[FW_APP_INFO + 2] << 8 | fw[FW_APP_INFO + 3]);
	length = code;
	if ((uint16_t)(code + code_n) != 0xffff || length < FW_MIN || length > FW_MAX || length > fw_size) {
		printf("focaltech: the firmware file's length is not one (%#x %#x, file %llu bytes)\n", code, code_n, fw_size);
		return false;
	}
	ecc = ecc_host(fw, length);
	/* fast download (64 KB packets) where the ROM says it has it, else 4092 bytes a packet and 3 ms after each */
	packet = 4 * 1024 - 4;
	if (fts_read_reg(0xdb, &dbval) && fts_read(f2, 6, v, 2) && dbval >= 0x18 && v[0] == 0x55) {
		packet = 64 * 1024;
	}
	printf("focaltech: the firmware: %u bytes of code, ecc %#06x; packets of %u bytes (0xdb %#x)\n", length, ecc,
	    packet, dbval);
	for (uint32_t offset = 0; offset < length; offset += packet) {
		uint32_t n = length - offset < packet ? length - offset : packet;

		cmd[0] = CMD_PRAM_WRITE;
		cmd[1] = (uint8_t)(offset >> 16), cmd[2] = (uint8_t)(offset >> 8), cmd[3] = (uint8_t)offset;
		cmd[4] = (uint8_t)(n >> 8), cmd[5] = (uint8_t)n;
		if (!fts_write_cmd(cmd, 6, fw + offset, n)) {
			printf("focaltech: writing the firmware failed at %#x\n", offset);
			return false;
		}
		if (packet < 64 * 1024) {
			sleep_ms(3);
		}
	}
	cmd[0] = CMD_ECC;
	cmd[1] = 0, cmd[2] = 0, cmd[3] = 0;
	cmd[4] = (uint8_t)(length >> 16), cmd[5] = (uint8_t)(length >> 8), cmd[6] = (uint8_t)length;
	if (!fts_write_cmd(cmd, 7, NULL, 0)) {
		return false;
	}
	sleep_ms(3);
	cmd[0] = CMD_ECC_FINISH;
	for (int i = 0;; i++) {
		if (!fts_read(cmd, 1, v, 1)) {
			return false;
		}
		if (v[0] == 0) {
			break;
		}
		if (i >= 100) {
			printf("focaltech: the chip's ecc does not finish\n");
			return false;
		}
		sleep_ms(1);
	}
	cmd[0] = CMD_ECC_READ;
	if (!fts_read(cmd, 1, v, 2)) {
		return false;
	}
	ecc_chip = (uint32_t)(v[0] << 8 | v[1]);
	printf("focaltech: ecc: the chip's %#06x, ours %#06x\n", ecc_chip, ecc);
	if (ecc_chip != ecc) {
		return false;
	}
	cmd[0] = CMD_START_APP;
	if (!fts_write_cmd(cmd, 1, NULL, 0)) {
		return false;
	}
	fw_running = true;
	return true;
}

/* ---- the reports --------------------------------------------------------------------------------------- */

#define FTS_FINGERS             10
#define FTS_REPORT_BYTES        (FTS_FINGERS * 6 + 3 + 6 * 4 + 4 - 1)   /* fts_read_touchdata: pnt_buf_size - 1 */

static uint32_t max_x = 1080, max_y = 2280;     /* the device tree's focaltech,display-coords */

static struct finger {
	bool     down;
	uint32_t x, y;
} fingers[FTS_FINGERS];

static uint64_t reports, posted, failures;

static uint32_t
scale(uint32_t value, uint32_t range)
{
	if (value >= range) {
		value = range - 1;
	}
	return (uint32_t)((uint64_t)value * 65535 / (range - 1));
}

static void
fts_poll(void)
{
	uint8_t r[FTS_REPORT_BYTES];
	bool seen[FTS_FINGERS] = { false };
	unsigned count;

	if (!fts_read(NULL, 0, r, sizeof(r))) {
		failures++;
		return;
	}
	reports++;
	if (reports <= 3) {
		hex_line("report", r, 20);
	}
	if (r[1] == 0xef && r[2] == 0xef && r[3] == 0xef) {
		/* the firmware is gone (Motorola's driver downloads it again here) */
		failures++;
		return;
	}
	if ((r[0] & 0xf0) != 0x90) {
		failures++;
		return;
	}
	count = r[1] & 0x0f;
	if (count > FTS_FINGERS) {
		return;
	}
	for (unsigned i = 0; i < FTS_FINGERS; i++) {
		const uint8_t *p = r + 2 + 6 * i;
		unsigned id = p[2] >> 4, flag = p[0] >> 6;
		uint32_t x, y;

		if (id >= FTS_FINGERS) {
			break;
		}
		if (flag == 1) {        /* up */
			continue;
		}
		x = (uint32_t)(p[0] & 0x0f) << 8 | p[1];
		y = (uint32_t)(p[2] & 0x0f) << 8 | p[3];
		if (x > max_x || y > max_y) {
			continue;
		}
		seen[id] = true;
		x = scale(x, max_x);
		y = scale(y, max_y);
		if (!fingers[id].down) {
			fingers[id] = (struct finger){ .down = true, .x = x, .y = y };
			redwood_touch_post(REDWOOD_TOUCH_DOWN, id, x, y);
			posted++;
			redwood_status(REDWOOD_STATUS_TOUCH, "ok, finger %u at %u,%u; %llu events", id, x * max_x / 65535,
			    y * max_y / 65535, posted);
			if (posted <= 20) {
				printf("focaltech: finger %u down at %u, %u (of 65535)\n", id, x, y);
			}
		} else if (fingers[id].x != x || fingers[id].y != y) {
			fingers[id].x = x;
			fingers[id].y = y;
			redwood_touch_post(REDWOOD_TOUCH_MOVE, id, x, y);
			posted++;
		}
	}
	for (unsigned id = 0; id < FTS_FINGERS; id++) {
		if (fingers[id].down && !seen[id]) {
			fingers[id].down = false;
			redwood_touch_post(REDWOOD_TOUCH_UP, id, fingers[id].x, fingers[id].y);
			posted++;
		}
	}
}

/* ---- bringing it up ------------------------------------------------------------------------------------ */

static void
focaltech_thread(__unused void *parameter, __unused wait_result_t result)
{
	uint32_t poll_us = 10000;
	uint8_t id[2] = { 0, 0 }, state = 0, cmd;
	const char *problem;

	PE_parse_boot_argn("touch_poll_us", &poll_us, sizeof(poll_us));
	if (poll_us < 1000) {
		poll_us = 1000;
	}
	tlmm = ml_io_map(TLMM_PHYS, TLMM_SIZE);
	gcc = ml_io_map(GCC_PHYS, GCC_SIZE);
	se = ml_io_map(SE_PHYS, SE_SIZE);

	redwood_status(REDWOOD_STATUS_TOUCH, "starting");
	printf("focaltech: the pins as the firmware left them\n");
	for (unsigned pin = PIN_SPI_FIRST; pin < PIN_SPI_FIRST + 4; pin++) {
		gpio_describe("SPI", pin);
	}
	gpio_describe("reset (the panel's too: not touched)", PIN_RESET);
	gpio_describe("interrupt", PIN_INT);

	if (!clocks_on()) {
		redwood_status(REDWOOD_STATUS_TOUCH, "FAILED: SPI clocks stay off");
		goto out;
	}
	for (unsigned pin = PIN_SPI_FIRST; pin < PIN_SPI_FIRST + 4; pin++) {
		gpio_configure(pin, PIN_FUNCTION_SPI, PULL_NONE, 6, false);
	}
	gpio_configure(PIN_INT, 0, PULL_UP, 8, false);
	problem = geni_spi_init(4000000);
	if (problem != NULL) {
		printf("focaltech: %s: no touch screen\n", problem);
		redwood_status(REDWOOD_STATUS_TOUCH, "FAILED: %s", problem);
		goto out;
	}

	/* the ROM: boot id (0x87 0x19) and boot state (2: waiting for a firmware); 0x55 once if it does not answer */
	fw_running = false;
	cmd = CMD_READ_ID;
	redwood_status(REDWOOD_STATUS_TOUCH, "SPI up; asking the FT8719's ROM");
	for (int attempt = 0; attempt < 3; attempt++) {
		bool read = fts_read(&cmd, 1, id, 2);

		printf("focaltech: boot id %s: %02x %02x\n", read ? "read" : "not read", id[0], id[1]);
		if (read && id[0] == 0x87 && id[1] == 0x19) {
			break;
		}
		cmd = CMD_START1;
		fts_write_cmd(&cmd, 1, NULL, 0);
		sleep_ms(8);
		cmd = CMD_READ_ID;
	}
	if (id[0] != 0x87 || id[1] != 0x19) {
		/* maybe its firmware runs after all: its chip id register then */
		fw_running = true;
		if (fts_read_reg(REG_CHIP_ID, id)) {
			printf("focaltech: not in its ROM; with its firmware running, chip id %#x\n", id[0]);
		}
		redwood_status(REDWOOD_STATUS_TOUCH, "FAILED: no FT8719 boot id (%02x %02x)", id[0], id[1]);
		goto out;
	}
	if (fts_read_reg(REG_BOOT_STATE, &state)) {
		printf("focaltech: an FT8719 in its ROM, boot state %u%s\n", state, state == 2 ? " (waiting for a firmware)" : "");
	}
	{
		uint64_t size = 0;
		const uint8_t *fw = redwood_image_file("fw", "focaltech_ts_fw.bin", &size, NULL);

		if (fw == NULL) {
			printf("focaltech: no fw/focaltech_ts_fw.bin in the small image: the phone's FT8719 firmware from "
			    "Android's /vendor/firmware goes there\n");
			redwood_status(REDWOOD_STATUS_TOUCH, "FT8719 id 87 19, boot state %u; no fw file", state);
			goto out;
		}
		redwood_status(REDWOOD_STATUS_TOUCH, "FT8719 boot state %u; loading %llu bytes", state, size);
		if (!fts_download(fw, size)) {
			redwood_status(REDWOOD_STATUS_TOUCH, "FAILED: firmware did not start (state %u)", state);
			goto out;
		}
	}
	sleep_ms(50);
	{
		uint8_t chip = 0, version = 0;

		fts_read_reg(REG_CHIP_ID, &chip);
		fts_read_reg(REG_FW_VERSION, &version);
		printf("focaltech: the firmware runs: chip id %#x, firmware version %#x\n", chip, version);
	}

	printf("focaltech: watching the interrupt line every %u us\n", poll_us);
	redwood_status(REDWOOD_STATUS_TOUCH, "ok, FT8719, %u Hz", 1000000 / poll_us);
	for (unsigned tick = 1;; tick++) {
		if (!gpio_get(PIN_INT)) {
			fts_poll();
		}
		if (tick % (60 * 1000000 / poll_us) == 0) {
			printf("focaltech: %llu reports read, %llu failed, %llu records posted; interrupt line %s\n", reports,
			    failures, posted, gpio_get(PIN_INT) ? "high" : "low");
		}
		if (failures >= 1000 && failures * 2 > reports) {
			printf("focaltech: more than half of the reads have failed: giving up\n");
			redwood_status(REDWOOD_STATUS_TOUCH, "FAILED: reads fail, gave up");
			break;
		}
		delay_for_interval(poll_us, NSEC_PER_USEC);
	}
out:
	thread_terminate(current_thread());
}

void
redwood_focaltech_init(void)
{
	uint32_t enabled = 0;
	char device[16] = "";
	thread_t thread;

	if (!PE_parse_boot_argn("touchscreen", &enabled, sizeof(enabled)) || !enabled ||
	    !PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "doha") != 0) {
		return;
	}
	if (kernel_thread_start(focaltech_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
