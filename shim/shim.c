/*
 * doha boot shim for the Moto G8 Plus (SM6125 "trinket"), derived from
 * ios-sweet's milestone 2 and 4 shims; addresses come from the live FDT
 * (dtb/doha-live.dts.txt).
 *
 * Milestone 2: with an XNU payload (tools/mkpayload.py) in the ramdisk,
 * loader.c places kernel + ADT + boot_args and jumps to XNU.
 *
 * Milestone 1 (no payload): one boot answers the questions that decide the
 * XNU port; the answers are in NOTES.md.
 *   - splash framebuffer format, read back from the MDP source pipe
 *   - CPU feature registers (16K granule, LSE, PAN, GIC sysreg interface)
 *   - PSCI/SMCCC version and which PSCI calls the Qualcomm TZ offers
 *   - SMP: PSCI CPU_ON for the 7 secondaries, each reports MPIDR and MIDR
 *   - GICv3 Group 1 IRQ from the virtual timer (INTID 19) and an SGI
 * The MMU stays off. Normal screen is green; any unexpected exception
 * paints the panic screen red. Afterwards it reboots into fastboot.
 */
#include <stdint.h>
#include "console.h"
#include "loader.h"

#define IMEM_RESTART_REASON	0x0c12565cUL	/* qcom,msm-imem@c125000 restart_reason@65c */
#define RESTART_BOOTLOADER	0x77665500U
#define PSHOLD			0x0440b000UL	/* restart@440b000 pshold-base */

#define GICD_BASE		0x0f200000UL
#define GICR_BASE		0x0f300000UL
#define GICR_SIZE		0x100000UL
#define GICR_PE_SIZE		0x20000UL
#define GICR_TYPER		0x08
#define GICR_WAKER		0x14
#define GICR_SGI		0x10000
#define GICR_IGROUPR0		(GICR_SGI + 0x080)
#define GICR_ISENABLER0		(GICR_SGI + 0x100)
#define GICR_ICENABLER0		(GICR_SGI + 0x180)
#define GICR_IPRIORITYR		(GICR_SGI + 0x400)
#define GICR_ISPENDR0		(GICR_SGI + 0x200)
#define GICR_ISACTIVER0		(GICR_SGI + 0x300)
#define VTIMER_INTID		19	/* DT timer: <GIC_PPI 3 ...> */
#define PTIMER_INTID		18	/* DT timer: <GIC_PPI 2 ...> */
#define SGI_INTID		1

/* MDP source pipes (qcom,sde-sspp-off from mdss_mdp@5e00000: vig, dma, dma) */
#define MDP_BASE		0x05e00000UL
#define SSPP_SRC_SIZE		0x00
#define SSPP_SRC0_ADDR		0x14
#define SSPP_SRC_YSTRIDE0	0x24
#define SSPP_SRC_FORMAT		0x30
#define SSPP_SRC_UNPACK		0x34

#define PSCI_VERSION		0x84000000UL
#define PSCI_CPU_SUSPEND	0xc4000001UL
#define PSCI_CPU_OFF		0x84000002UL
#define PSCI_CPU_ON		0xc4000003UL
#define PSCI_SYSTEM_RESET	0x84000009UL
#define PSCI_FEATURES		0x8400000aUL
#define PSCI_SYSTEM_SUSPEND	0xc400000eUL
#define PSCI_SYSTEM_RESET2	0xc4000012UL
#define SMCCC_VERSION		0x80000000UL

#define NR_CPUS			8
#define HOLD_SECONDS		90	/* time to photograph the screen */

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))
#define isb() __asm__ volatile("isb" ::: "memory")

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline uint64_t rd64(uintptr_t a) { return *(volatile uint64_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static inline void wr8(uintptr_t a, uint8_t v) { *(volatile uint8_t *)a = v; }

extern char secondary_entry[];

static const char *stage;	/* set at runtime: no absolute pointers in data */
static volatile uint64_t sec_mpidr[NR_CPUS], sec_midr[NR_CPUS];
static volatile uint32_t irq_count, irq_other, irq_last;
static volatile int irq_src;

/* ICC_SGI1R_EL1 value targeting the calling core only. */
static uint64_t sgi_self(unsigned id)
{
	uint64_t m = rsr("mpidr_el1");
	return ((m >> 16) & 0xff) << 32 |	/* Aff2 */
	       ((m >> 8) & 0xff) << 16 |	/* Aff1 */
	       (uint64_t)id << 24 |
	       (1U << (m & 0xf));		/* target list: Aff0 */
}

static uint64_t smc(uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3)
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = a1;
	register uint64_t x2 __asm__("x2") = a2;
	register uint64_t x3 __asm__("x3") = a3;
	__asm__ volatile("smc #0"
			 : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
			 :
			 : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
			   "x12", "x13", "x14", "x15", "x16", "x17", "memory");
	return x0;
}

static uint64_t now(void)
{
	isb();
	return rsr("cntpct_el0");
}

static void delay_ms(unsigned ms)
{
	uint64_t end = now() + rsr("cntfrq_el0") / 1000 * ms;
	while (now() < end)
		;
}

static void __attribute__((noreturn)) reset(unsigned after_s)
{
	con_skip();
	con_str("RESET", after_s > 60 ? "fastboot in 90s" : "fastboot in 40s");
	delay_ms(after_s * 1000);
	wr32(IMEM_RESTART_REASON, RESTART_BOOTLOADER);
	__asm__ volatile("dsb sy" ::: "memory");
	smc(PSCI_SYSTEM_RESET, 0, 0, 0);
	wr32(PSHOLD, 0);
	for (;;)
		__asm__ volatile("wfe");
}

/* ---- exceptions ---- */

static void irq_handler(void)
{
	uint64_t iar = rsr("icc_iar1_el1");
	uint32_t id = iar & 0xffffff;

	if (id >= 1020 && id <= 1023)
		return;	/* spurious */
	irq_last = id;
	if (id == (uint32_t)irq_src)
		irq_count++;
	else
		irq_other++;
	if (id == VTIMER_INTID)
		wsr("cntv_tval_el0", rsr("cntfrq_el0") / 100);	/* 10 ms */
	else if (id == PTIMER_INTID)
		wsr("cntp_tval_el0", rsr("cntfrq_el0") / 100);
	wsr("icc_eoir1_el1", iar);
	isb();
}

void exc_handler(uint64_t slot, uint64_t *regs)
{
	if (slot == 5) {	/* IRQ from current EL, SPx */
		irq_handler();
		return;
	}
	con_clear(RED);
	switch (slot & 3) {
	case 0: con_str("PANIC", "SYNC"); break;
	case 1: con_str("PANIC", "IRQ"); break;
	case 2: con_str("PANIC", "FIQ"); break;
	default: con_str("PANIC", "SERROR"); break;
	}
	con_hex2("SLOT", "n=", slot, "cpu=", rsr("mpidr_el1"));
	con_str("STAGE", stage);
	con_hex("ESR", rsr("esr_el1"));
	con_hex("ELR", rsr("elr_el1"));
	con_hex("FAR", rsr("far_el1"));
	con_hex("SPSR", rsr("spsr_el1"));
	con_hex("X0", regs[0]);
	con_hex("X1", regs[1]);
	con_hex("X30", regs[29]);	/* stashed lr is just above the frame */
	reset(40);
}

/* ---- framebuffer: what did ABL program into the MDP? ---- */

static void setup_fb(void)
{
	static const uint32_t sspp_off[] = { 0x5000, 0x25000, 0x27000 };
	uint32_t size = 0, addr = 0, ystride = 0, fmt = 0, unpack = 0;
	int pipe = -1;

	stage = "mdp";
	con_setup(FB_BASE, FB_W, FB_H, FB_W * FB_BPP, FB_BPP);	/* for a panic during the probe */
	for (int i = 0; i < 3; i++) {
		uintptr_t p = MDP_BASE + sspp_off[i];
		uint32_t a = rd32(p + SSPP_SRC0_ADDR);
		if (a >= 0x40000000U && (rd32(p + SSPP_SRC_YSTRIDE0) & 0xffff)) {
			pipe = i;
			addr = a;
			size = rd32(p + SSPP_SRC_SIZE);
			ystride = rd32(p + SSPP_SRC_YSTRIDE0);
			fmt = rd32(p + SSPP_SRC_FORMAT);
			unpack = rd32(p + SSPP_SRC_UNPACK);
			break;
		}
	}

	int w = size & 0xffff, h = size >> 16, stride = ystride & 0xffff;
	int bpp = ((fmt >> 9) & 3) + 1;		/* SRC_FORMAT[10:9] = bytes per pixel - 1 */
	if (pipe < 0 || w < 720 || w > 1440 || h < 1280 || h > 2400) {
		w = FB_W;
		h = FB_H;
		bpp = FB_BPP;
		stride = FB_W * FB_BPP;
		addr = FB_BASE;
	} else if (bpp != 3 && bpp != 4) {
		bpp = stride / w;
	}
	con_setup(addr, w, h, stride, bpp);
	con_clear(GREEN);
	con_str("SHIM", "doha milestone 2");
	con_skip();
	con_hex2("MDP", "pipe=", (uint32_t)pipe, "addr=", addr);
	con_hex2(" size", "w=", w, "h=", h);
	con_hex2(" fmt", "fmt=", fmt, "unpk=", unpack);
	con_hex2(" stride", "ys0=", ystride, "bpp=", bpp);
	con_skip();
}

/* ---- CPU features ---- */

static void test_cpu(uint64_t dtb)
{
	stage = "cpu";
	uint64_t mmfr0 = rsr("id_aa64mmfr0_el1");
	uint64_t isar0 = rsr("id_aa64isar0_el1");
	uint64_t mmfr1 = rsr("id_aa64mmfr1_el1");

	con_hex2("DTB", "at=", dtb, "magic=", dtb ? __builtin_bswap32(rd32(dtb)) : 0);
	con_hex2("EL", "cur=", rsr("currentel") >> 2, "frq=", rsr("cntfrq_el0"));
	con_hex2("MIDR", "boot=", rsr("midr_el1"), "rev=", rsr("revidr_el1"));
	con_hex("MPIDR", rsr("mpidr_el1"));
	/* Full milestone 1 register dump (MMFR2, ISAR1, CTR, SCTLR) is in NOTES.md. */
	con_hex("MMFR0", mmfr0);
	con_hex("MMFR1", mmfr1);
	con_hex("ISAR0", isar0);
	con_hex("PFR0", rsr("id_aa64pfr0_el1"));
	/* TGran16 [23:20]: 1 = supported. TGran4 [31:28]: 0 = supported. */
	con_str("16K", ((mmfr0 >> 20) & 0xf) ? "YES" : "NO -> 4K hw pages");
	con_str("4K", ((mmfr0 >> 28) & 0xf) == 0 ? "YES" : "NO");
	/* ISAR0 atomic [23:20]: 2 = LSE. MMFR1 PAN [23:20]: != 0 = PAN. */
	con_str("LSE", ((isar0 >> 20) & 0xf) >= 2 ? "YES" : "NO");
	con_str("PAN", ((mmfr1 >> 20) & 0xf) ? "YES" : "NO");
	con_skip();
}

/* ---- SMP ---- */

void secondary_main(uint64_t idx)
{
	sec_midr[idx] = rsr("midr_el1");
	sec_mpidr[idx] = rsr("mpidr_el1") | (1ULL << 63);
	__asm__ volatile("dsb sy" ::: "memory");
	smc(PSCI_CPU_OFF, 0, 0, 0);
}

static void test_smp(void)
{
	/* doha: Aff0 = core, Aff1 = cluster (cpu@0..3 Silver, cpu@100..103 Gold) */
	static const uint32_t mpidr[NR_CPUS] = { 0x0, 0x1, 0x2, 0x3, 0x100, 0x101, 0x102, 0x103 };
	uint64_t self = rsr("mpidr_el1") & 0xffffff;
	int64_t ret[NR_CPUS];

	stage = "smp";
	for (int i = 0; i < NR_CPUS; i++)
		ret[i] = mpidr[i] == self ? 0 :
			 (int64_t)smc(PSCI_CPU_ON, mpidr[i], (uintptr_t)secondary_entry, i);
	delay_ms(500);
	for (int i = 0; i < NR_CPUS; i++) {
		char label[] = "CPU0";
		label[3] = '0' + i;
		if (mpidr[i] == self)
			con_str(label, "is boot cpu");
		else
			con_hex2(label, "ret=", (uint32_t)ret[i], "midr=",
				 sec_mpidr[i] ? (uint32_t)sec_midr[i] : 0xdead0000);
	}
	con_skip();
}

/* ---- GIC + timer ---- */

static uintptr_t find_gicr(void)
{
	uint64_t aff = rsr("mpidr_el1");
	uint32_t want = (aff & 0xffffff) | ((aff >> 8) & 0xff000000);

	for (uintptr_t off = 0; off < GICR_SIZE; off += GICR_PE_SIZE) {
		uint64_t typer = rd64(GICR_BASE + off + GICR_TYPER);
		if ((uint32_t)(typer >> 32) == want)
			return GICR_BASE + off;
		if (typer & (1 << 4))	/* Last */
			break;
	}
	return 0;
}

static void gicd_wait_rwp(void)
{
	for (int i = 0; i < 1000000 && (rd32(GICD_BASE) & (1U << 31)); i++)
		;
}

/* Run one interrupt source for ~300 ms and report what the GIC saw. */
static void irq_window(const char *label, uintptr_t r, int src)
{
	uint64_t f = rsr("cntfrq_el0");

	irq_count = irq_other = 0;
	irq_last = 0x3ff;
	irq_src = src;
	if (src == VTIMER_INTID) {
		wsr("cntv_tval_el0", f / 100);
		wsr("cntv_ctl_el0", 1);
	}
	isb();
	if (src == SGI_INTID)
		wsr("icc_sgi1r_el1", sgi_self(SGI_INTID));
	isb();
	uint32_t pend = rd32(r + GICR_ISPENDR0);

	__asm__ volatile("msr daifclr, #2" ::: "memory");
	uint64_t t = now() + f * 3 / 10;
	/* SGI: one already sent above, send 9 more 10 ms apart -> expect 10 */
	uint64_t next = now() + f / 100;
	for (int sent = 1; now() < t;)
		if (src == SGI_INTID && sent < 10 && now() >= next) {
			wsr("icc_sgi1r_el1", sgi_self(SGI_INTID));
			isb();
			sent++;
			next += f / 100;
		}
	__asm__ volatile("msr daifset, #2" ::: "memory");
	wsr("cntv_ctl_el0", 0);
	isb();

	con_hex2(label, "irqs=", irq_count, "other=", irq_other);
	con_hex2(" pre", "pend=", pend, "last=", irq_last);
}

static void test_gic(void)
{
	stage = "gic sre";
	uint64_t sre = rsr("icc_sre_el1");
	if (!(sre & 1)) {
		wsr("icc_sre_el1", sre | 1);
		isb();
	}
	if (!(rsr("icc_sre_el1") & 1)) {
		con_str("GIC", "no sysreg iface, skip");
		return;
	}

	stage = "gic dist";
	uint32_t dctlr = rd32(GICD_BASE);
	/* Non-secure view (DS=0): bit0 EnableGrp1, bit1 EnableGrp1A, bit4 ARE_NS; Linux writes 0x13 */
	wr32(GICD_BASE, dctlr | 0x13);
	gicd_wait_rwp();
	con_hex2("GICD", "was=", dctlr, "now=", rd32(GICD_BASE));

	stage = "gic redist";
	uintptr_t r = find_gicr();
	if (!r) {
		con_str("GICR", "not found");
		return;
	}
	uint32_t waker = rd32(r + GICR_WAKER);
	if (waker & 2) {
		wr32(r + GICR_WAKER, waker & ~2U);
		for (int i = 0; i < 100000 && (rd32(r + GICR_WAKER) & 4); i++)
			;
	}
	con_hex2("GICR", "base=", r, "waker=", rd32(r + GICR_WAKER));

	stage = "gic config";
	wr32(r + GICR_IGROUPR0, 0xffffffff);	/* NS view: secure bits are WI */
	for (int id = 0; id < 32; id++)
		wr8(r + GICR_IPRIORITYR + id, 0xa0);
	wr32(r + GICR_ISENABLER0, (1U << VTIMER_INTID) | (1U << SGI_INTID));

	uint64_t ctlr = rsr("icc_ctlr_el1");
	wsr("icc_ctlr_el1", ctlr & ~2ULL);	/* EOImode 0: EOIR also deactivates */
	wsr("icc_pmr_el1", 0xf0);
	wsr("icc_bpr1_el1", 0);
	wsr("icc_igrpen1_el1", 1);
	isb();

	stage = "gic vtimer";
	irq_window("VTIMER", r, VTIMER_INTID);
	stage = "gic sgi";
	irq_window("SGI1", r, SGI_INTID);
	wr32(r + GICR_ICENABLER0, 0xffffffff);
	isb();
}

/* ---- main ---- */

void shim_main(uint64_t dtb)
{
	setup_fb();

	/* An xnu payload in the ramdisk means: boot it (MMU stays off). */
	stage = "loader";
	const char *why = loader_boot(dtb);
	con_str("LOADER", why);
	con_skip();

	test_cpu(dtb);

	stage = "psci";
	con_hex2("PSCI", "ver=", smc(PSCI_VERSION, 0, 0, 0), "smccc=", smc(SMCCC_VERSION, 0, 0, 0));
	con_hex2(" feat", "on=", smc(PSCI_FEATURES, PSCI_CPU_ON, 0, 0),
		 "rst2=", smc(PSCI_FEATURES, PSCI_SYSTEM_RESET2, 0, 0));
	con_skip();

	test_smp();
	test_gic();

	stage = "done";
	con_skip();
	con_str("DONE", "photograph this screen");
	reset(HOLD_SECONDS);
}
