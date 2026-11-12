"""Apply the doha changes to a willow-hackios tree, each replacement checked to happen exactly once.

  doha_willow_edit.py TREE
"""
import sys
from pathlib import Path

tree = Path(sys.argv[1])


def sub1(path, old, new):
    p = tree / path
    # newline='': a patch may carry CRLF lines of the files it changes, which must stay as they are
    t = p.open(encoding='utf-8', errors='surrogateescape', newline='').read()
    if t.count(old) != 1:
        raise SystemExit(f'{path}: expected 1x {old[:60]!r}, found {t.count(old)}')
    p.open('w', encoding='utf-8', errors='surrogateescape', newline='').write(t.replace(old, new))
    print('ok', path, old.splitlines()[0][:60])


L = 'xnuloader/loader.c'

sub1(L, """#define PAYLOAD_BASE        0xF0000000ULL
""", """#ifndef PAYLOAD_BASE                    /* build.sh: PAYLOAD_BASE=... (doha's UEFI puts it at 0x78000000) */
#define PAYLOAD_BASE        0xF0000000ULL
#endif
""")
sub1('xnuloader/build.sh', """  -mgeneral-regs-only -O1 -Wall -Wextra -Wno-unused-parameter -c loader.c -o loader.obj
""", """  -mgeneral-regs-only -O1 -Wall -Wextra -Wno-unused-parameter ${PAYLOAD_BASE:+-DPAYLOAD_BASE=${PAYLOAD_BASE}ULL} \\
  -c loader.c -o loader.obj
""")

sub1(L, """	uint64_t fb_base;                /* the framebuffer the firmware reports (GOP): it tells this device apart */
""", """	uint64_t fb_base;                /* the framebuffer the firmware reports (GOP): it tells this device apart */
	uint32_t fb_height;              /* ... with its height, when two devices share a base (willow, doha); 0: any */
""")

sub1(L, """	.fb_base = 0x5C000000,           /* Mu-Silicium willowPkg: "Display Reserved", 1080 x 2340 */
""", """	.fb_base = 0x5C000000,           /* Mu-Silicium willowPkg: "Display Reserved", 1080 x 2340 */
	.fb_height = 2340,
""")

sub1(L, """/* The slower cores of this run: the platform's, unless willow_osm() has raised the Gold cluster's clock. */
""", """/*
 * Moto G8 Plus (doha, SM6125, github.com/andrecremo/ios-doha): the same SoC as willow, so the same peripherals,
 * GIC and clusters, and its UEFI (dohaPkg) puts the framebuffer at the same 0x5C000000; the screen is 1080 x 2280,
 * which tells it from willow. Nothing of willow's board: not its RPM voltages, nor its touch panel (the kernel's
 * drivers check device=). osm=1 asks the clusters' OSM for a row of the table doha's own firmware wrote, as on willow
 * (and only where that OSM is on, see below).
 */
/*
 * userdata (mmcblk0p80), doha's 50 GiB that were Android's data: the iOS volume and both cryptexes fill its first
 * 8365539328 bytes, as they fill willow's system (written from Lineage's recovery, 2026-11-09), so a write goes from
 * the same block, and the data of iOS (userland/src/var_store.c) goes behind them. Its GUIDs as doha's GPT has them.
 */
static const struct store_part doha_store = {
	.name = "userdata",
	.type = { 0x1b81e7e6, 0xf50d, 0x419b, { 0xa7, 0x39, 0x2a, 0xee, 0xf8, 0xda, 0x33, 0x35 } },
	.uniq = { 0x6c51ad71, 0x9097, 0xc9ae, { 0x97, 0x69, 0xe8, 0x34, 0x0b, 0xf4, 0xf4, 0x68 } },
	.first_lba = 17924096, .last_lba = 122142686, .block_size = 512, .write_first = BLOCK_WRITE_FIRST,
};

static const struct platform platform_doha = {
	.name = "doha", .io_base = 0x00400000, .io_size = 0x3FC00000,
	.gic_dist = 0x0F200000, .gic_redist = 0x0F300000, .uart = 0, .log_other_cpu = 1,
	.cores = 8, .core_mpidr = willow_core_mpidr,
	.small_cores = 0xf0,             /* as on willow: Gold stays at its lowest clock with no OSM */
	.fb_base = 0x5C000000,           /* dohaPkg: "Display Reserved", what ABL scans out, 1080 x 2280 */
	.fb_height = 2280,
	.store = &doha_store,
};

/* The slower cores of this run: the platform's, unless willow_osm() has raised the Gold cluster's clock. */
""")

sub1(L, """	&platform_redwood,
	&platform_willow,
};""", """	&platform_redwood,
	&platform_willow,
	&platform_doha,
};""")

sub1(L, """			if (platforms[i]->fb_base == SCREEN.base)
				PLAT = platforms[i];""", """			if (platforms[i]->fb_base == SCREEN.base &&
			    (platforms[i]->fb_height == 0 || platforms[i]->fb_height == SCREEN.height))
				PLAT = platforms[i];""")

sub1(L, """	/* One-shot mode: run the kernel that came with the image, then reset. */
	if (have_payload) {
		run_kernel(0, 0);
	}
	reboot();""", """	/* One-shot mode: run the kernel that came with the image, then reset. */
	if (have_payload) {
		run_kernel(0, 0);
	}
	if (PLAT == &platform_doha) {
		/* doha has no logdump and no USB link to the loader yet: its screen is the only log, so leave time to read it */
		print("reset in 30 s\\n");
		BS->stall(30000000);
	}
	reboot();""")

sub1(L, """	if (PLAT == &platform_willow) {
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "osmdump=1") && (c == pi.cmdline || c[-1] == ' ')) {
				osm_dump();
				break;
			}
		}
	}""", """	if (PLAT == &platform_willow || PLAT == &platform_doha) {
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "osmdump=1") && (c == pi.cmdline || c[-1] == ' ')) {
				if (PLAT != &platform_doha) {
					osm_dump();
				}
				if (PLAT == &platform_doha) {
					/* the words that differ, four to a line so that all fit on the screen: offset silver/gold */
					volatile uint32_t *s = (volatile uint32_t *)(uintptr_t)0x0F521000ULL;
					volatile uint32_t *g = (volatile uint32_t *)(uintptr_t)0x0F523000ULL;
					unsigned on_line = 0, differ = 0;

					print("osm Silver/Gold, the words that differ (table 0x110..0x30f left out):\\n");
					for (uint32_t off = 0; off < 0x1400; off += 4) {
						if ((off >= 0x110 && off < 0x310) || s[off / 4] == g[off / 4]) {
							continue;
						}
						differ++;
						print("%x:%x/%x%s", (uint64_t)off, (uint64_t)s[off / 4], (uint64_t)g[off / 4],
						    ++on_line % 4 == 0 ? "\\n" : "  ");
					}
					print("%s%d differ; 20 s to read this, then the tables\\n", on_line % 4 ? "\\n" : "", (uint64_t)differ);
					BS->stall(20000000);
				}
				if (PLAT == &platform_doha) {
					/*
					 * doha: both clusters' enables and the first rows of their tables (Linux's clk_osm_read_lut:
					 * 0x110 + 32 * row, [31:30] source (0: the 300 MHz one), [7:0] L of 19.2 MHz; 0x114 + 32 * row,
					 * [21:16] virtual corner, [11:0] open loop mV) -- whether the firmware wrote Gold's -- 30 s on screen
					 */
					volatile uint32_t *osm[2] = { (volatile uint32_t *)(uintptr_t)0x0F521000ULL,
						                      (volatile uint32_t *)(uintptr_t)0x0F523000ULL };

					print("osm enable: Silver %x, Gold %x\\n", (uint64_t)osm[0][0], (uint64_t)osm[1][0]);
					{
						/*
						 * The copy uefi/DohaShim.S took of both blocks as ABL left them, before the UEFI ran (0x7BE00000
						 * Silver, +0x2000 Gold, "OSMS" at +0x4000): Gold's enable and configuration words then, and how
						 * much of Gold's block the UEFI has changed since
						 */
						volatile uint32_t *snap = (volatile uint32_t *)(uintptr_t)0x7BE00000ULL;

						if (snap[0x4000 / 4] == 0x534d534fu) {
							uint32_t then_set = 0, now_set = 0, changed = 0;

							for (uint32_t at = 0x1c; at <= 0xb8; at += 4) {
								then_set += snap[(0x2000 + at) / 4] != 0;
								now_set += osm[1][at / 4] != 0;
							}
							for (uint32_t at = 0; at < 0x1400; at += 4) {
								changed += snap[(0x2000 + at) / 4] != osm[1][at / 4];
							}
							print("osm as ABL left it: enable Silver %x Gold %x; Gold's config set then %d now %d of 40; "
							    "%d words of Gold's block changed since\\n", (uint64_t)snap[0], (uint64_t)snap[0x2000 / 4],
							    (uint64_t)then_set, (uint64_t)now_set, (uint64_t)changed);
							print("osm as ABL left it, Gold: 2c %x 54 %x 84 %x 700 %x 720 %x 920 %x row7 %x %x\\n",
							    (uint64_t)snap[(0x2000 + 0x2c) / 4], (uint64_t)snap[(0x2000 + 0x54) / 4],
							    (uint64_t)snap[(0x2000 + 0x84) / 4], (uint64_t)snap[(0x2000 + 0x700) / 4],
							    (uint64_t)snap[(0x2000 + 0x720) / 4], (uint64_t)snap[(0x2000 + 0x920) / 4],
							    (uint64_t)snap[(0x2000 + 0x110 + 32 * 7) / 4], (uint64_t)snap[(0x2000 + 0x114 + 32 * 7) / 4]);
						} else {
							print("osm as ABL left it: no copy from the shim (%x at 0x7BE04000)\\n", (uint64_t)snap[0x4000 / 4]);
						}
					}
					for (uint32_t row = 0; row < 16; row++) {
						uint32_t f[2], v[2];

						for (int k = 0; k < 2; k++) {
							f[k] = osm[k][(0x110 + 32 * row) / 4];
							v[k] = osm[k][(0x114 + 32 * row) / 4];
						}
						print("row %d: S %d MHz c%d %d mV | G %d MHz c%d %d mV (%x %x)\\n", (uint64_t)row,
						    (uint64_t)((f[0] >> 30) ? (f[0] & 0xff) * 192 / 10 : 300), (uint64_t)(v[0] >> 16 & 0x3f),
						    (uint64_t)(v[0] & 0xfff), (uint64_t)((f[1] >> 30) ? (f[1] & 0xff) * 192 / 10 : 300),
						    (uint64_t)(v[1] >> 16 & 0x3f), (uint64_t)(v[1] & 0xfff), (uint64_t)f[1], (uint64_t)v[1]);
					}
					print("osmdump=1: 20 s to read this\\n");
					BS->stall(20000000);
				}
				break;
			}
		}
	}""")

sub1(L, """	small_cores_now = PLAT->small_cores;
	if (PLAT == &platform_willow) {""", """	small_cores_now = PLAT->small_cores;
	if (PLAT == &platform_doha) {
		/*
		 * doha, "memmap=1": the UEFI's memory map on the screen, 20 s to read it -- where the RAM the kernel's
		 * window could grow into is (doha has no USB link for `oem memmap`)
		 */
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "memmap=1") && (c == pi.cmdline || c[-1] == ' ')) {
				print_memory_map();
				print("memmap=1: 20 s to read this\\n");
				BS->stall(20000000);
				break;
			}
		}
		/*
		 * doha, "uefilog=1": the lines of the UEFI's own log (dohaPkg's "Log Buffer", 32 KB at 0x5FFF7000, where
		 * DEBUG () goes) that say "harg" or "attery" -- why Qualcomm's charger drivers did not come up -- for 25 s
		 */
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "uefilog=1") && (c == pi.cmdline || c[-1] == ' ')) {
				const char *log = (const char *)(uintptr_t)0x5FFF7000ULL;
				char line[160];
				int shown = 0;

				print("uefilog=1: the UEFI log's lines about the charger:\\n");
				for (uint64_t i = 0, start = 0; i <= 0x8000 && shown < 40; i++) {
					if (i == 0x8000 || log[i] == '\\n' || log[i] == 0) {
						uint64_t len = i - start, k = 0;
						int match = 0;

						for (uint64_t j = start; j + 4 <= i; j++) {
							if ((log[j] == 'h' && log[j + 1] == 'a' && log[j + 2] == 'r' && log[j + 3] == 'g') ||
							    (log[j] == 'a' && log[j + 1] == 't' && log[j + 2] == 't' && log[j + 3] == 'e')) {
								match = 1;
							}
						}
						if (match && len > 0) {
							for (uint64_t j = start; j < i && k < sizeof(line) - 2; j++) {
								line[k++] = (log[j] >= 32 && log[j] < 127) ? log[j] : '.';
							}
							line[k++] = '\\n';
							line[k] = 0;
							print("%s", line);
							shown++;
						}
						start = i + 1;
					}
				}
				print("uefilog=1: %d lines; 25 s to read this\\n", (uint64_t)shown);
				BS->stall(25000000);
				break;
			}
		}
	}
	if (PLAT == &platform_willow || PLAT == &platform_doha) {""")

sub1(L, """				for (int k = 0; k < 2; k++) {
					volatile uint32_t *r = (volatile uint32_t *)(uintptr_t)osm[k];

					for (int core = 0; core < 4; core++) {""", """				for (int k = 0; k < 2; k++) {
					volatile uint32_t *r = (volatile uint32_t *)(uintptr_t)osm[k];

					/*
					 * doha: the same SoC and the same OSM, its table written by doha's own firmware, so a row
					 * of it is doha's own frequency and voltage. Still only a cluster whose OSM the firmware
					 * has on (enable 3), and a row of a frequency that makes sense for a Kryo 260.
					 */
					if (PLAT == &platform_doha) {
						uint64_t mhz = (uint64_t)(r[(0x110 + 32 * row[k]) / 4] & 0xff) * 192 / 10;

						print("osm %x: enable %x, row %d: %d MHz\\n", osm[k], (uint64_t)r[0], (uint64_t)row[k], mhz);
						if (r[0] != 3 || mhz < 300 || mhz > 2100) {
							print("osm %x: left as the firmware has it\\n", osm[k]);
							continue;
						}
					}
					for (int core = 0; core < 4; core++) {""")

sub1('xnu/files/osfmk/arm64/gic_v3_irq.c',
     """strcmp(device, "willow") == 0) {
				gic_vtimer = GIC_INTID_VTIMER_QCOM;""",
     """(strcmp(device, "willow") == 0 || strcmp(device, "doha") == 0)) {
				gic_vtimer = GIC_INTID_VTIMER_QCOM;     /* the SM6125's, both phones */""")

sub1('xnu/files/osfmk/arm64/gic_v3_irq.c', """	if (gic_active_iar[cpu] != 0) {
		__builtin_arm_wsr64("ICC_EOIR1_EL1", gic_active_iar[cpu] & ~GIC_IAR_TAKEN);
		__builtin_arm_isb(ISB_SY);
		gic_active_iar[cpu] = 0;
	}
}
""", """	if (gic_active_iar[cpu] != 0) {
		__builtin_arm_wsr64("ICC_EOIR1_EL1", gic_active_iar[cpu] & ~GIC_IAR_TAKEN);
		__builtin_arm_isb(ISB_SY);
		gic_active_iar[cpu] = 0;
	}
	/*
	 * The timer's interrupt is this kernel's too. Left enabled, with the virtual timer still armed, it reaches
	 * the loader's UEFI, which has no handler for it (19 on the SM6125: the UEFI's own timer is another one):
	 * doha's showed "Spurious GIC interrupt: 0x13" without end and never got to the loader.
	 */
	if (gicr_cpu_base[cpu] != 0) {
		gic_write32(gicr_cpu_base[cpu] + GICR_ICENABLER0, 1u << gic_vtimer);
	}
}
""")

# doha's touch screen: a FocalTech FT8719 (bsd/dev/redwood_focaltech.c), next to willow's Novatek
(tree / 'xnu/files/bsd/dev/redwood_focaltech.c').write_text((Path(__file__).parent / 'redwood_focaltech.c').read_text())
print('ok xnu/files/bsd/dev/redwood_focaltech.c (new)')

sub1('xnu/files/bsd/sys/redwood_input.h', """void redwood_novatek_init(void);        /* ... and with device=willow, the Redmi Note 8T's Novatek one instead */
""", """void redwood_novatek_init(void);        /* ... and with device=willow, the Redmi Note 8T's Novatek one instead */
void redwood_focaltech_init(void);      /* ... and with device=doha, the Moto G8 Plus's FocalTech FT8719 */
""")

sub1('xnu/files/bsd/dev/redwood_input.c', """	redwood_novatek_init();
""", """	redwood_novatek_init();
	redwood_focaltech_init();
""")

# the build's list of files: one line more in bsd/conf/files' first hunk, and the later hunks' new lines one further on
sub1('xnu/redwood.patch', """@@ -109,6 +109,83 @@ bsd/dev/munge.c""", """@@ -109,6 +109,84 @@ bsd/dev/munge.c""")
sub1('xnu/redwood.patch', """+bsd/dev/redwood_novatek.c	standard
""", """+bsd/dev/redwood_novatek.c	standard
+bsd/dev/redwood_focaltech.c	standard
""")
sub1('xnu/redwood.patch', """@@ -155,6 +232,14 @@ bsd/miscfs/devfs/devfs_vfsops.c""", """@@ -155,6 +233,14 @@ bsd/miscfs/devfs/devfs_vfsops.c""")
sub1('xnu/redwood.patch', """@@ -361,6 +446,7 @@ bsd/security/audit/audit_syscalls.c""", """@@ -361,6 +447,7 @@ bsd/security/audit/audit_syscalls.c""")
sub1('xnu/redwood.patch', """@@ -383,6 +469,7 @@ bsd/kern/kern_debug.c""", """@@ -383,6 +470,7 @@ bsd/kern/kern_debug.c""")

# doha's GPU: the same Adreno 610 (bsd/dev/redwood_a610.c), its zap shader's region where doha's device tree has it
A6 = 'xnu/files/bsd/dev/redwood_a610.c'
sub1(A6, """#define ZAP_REGION_PHYS         0x57515000UL
""", """/* willow's; doha's device tree has gpu_region@57115000 instead (redwood_a610_init() sets it) */
static unsigned long zap_region_phys = 0x57515000UL;
#define ZAP_REGION_PHYS         zap_region_phys
""")
sub1(A6, """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "willow") != 0) {
		return;
	}
	redwood_osm_report();""", """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) ||
	    (strcmp(device, "willow") != 0 && strcmp(device, "doha") != 0)) {
		return;
	}
	if (strcmp(device, "doha") == 0) {
		/*
		 * The Moto G8 Plus (doha): the same SM6125 and Adreno 610, everything above the SoC's; only the
		 * zap shader's region is the board's -- doha's device tree: gpu_region@57115000, 8 KB, "no-map",
		 * inside the UEFI's "PIL Reserved" (0x4ab00000-0x57d00000)
		 */
		zap_region_phys = 0x57115000UL;
	}
	redwood_osm_report();""")
# doha's battery (battery=1): Qualcomm's ChargerEx in doha's own UEFI, read-only queries alone -- the battery there,
# a charger plugged in, the cell's voltage -- and the state of charge estimated from that voltage; QcomCharger (the
# gauge's own figure) is left alone on doha: its initialize() is the charger driver's, and the layout of what it hands
# back was measured on redwood
sub1(L, """	if (charger_enabled || PLAT != &platform_redwood) {
		return;
	}
	ex_status = BS->locate_protocol(&charger_ex_guid, NULL, (void **)&CHARGER_EX);
	qcom_status = BS->locate_protocol(&qcom_charger_guid, NULL, (void **)&QCOM_CHARGER);
	if (!EFI_ERROR(qcom_status) && QCOM_CHARGER != NULL) {""", """	if (charger_enabled || (PLAT != &platform_redwood && PLAT != &platform_doha)) {
		return;
	}
	ex_status = BS->locate_protocol(&charger_ex_guid, NULL, (void **)&CHARGER_EX);
	qcom_status = BS->locate_protocol(&qcom_charger_guid, NULL, (void **)&QCOM_CHARGER);
	/*
	 * What the two locates said, for the kernel's line of the panel (bsd/dev/redwood_battery.c): 0x5a in the top
	 * byte, then bit 17 / 16 an error of QcomCharger / ChargerEx, and the low byte of each status (bits 15-8 / 7-0)
	 */
	charger_shared.reserved = 0x5a000000u | (EFI_ERROR(qcom_status) ? 0x20000u : 0) | (EFI_ERROR(ex_status) ? 0x10000u : 0) |
	    (uint32_t)(qcom_status & 0xff) << 8 | (uint32_t)(ex_status & 0xff);
	if (PLAT == &platform_doha) {
		/* doha: ChargerEx's read-only queries alone, the state of charge from the voltage (charger_poll) */
		QCOM_CHARGER = NULL;
		qcom_status = 1;
	}
	if (!EFI_ERROR(qcom_status) && QCOM_CHARGER != NULL) {""")

# doha's battery, from the PMI632 on the SPMI bus: reads only, by the buttons' reader and its lock
BTN = 'xnu/files/bsd/dev/redwood_buttons.c'
sub1(BTN, """static struct peripheral pon, pin;
""", """static struct peripheral pon, pin;
/*
 * doha, battery=1: the PMI632 (slave 2; doha's device tree, qcom,pmi632@2) -- its gauge (qgauge@4800), its USB input
 * and its charger (qcom,qpnp-smb5: usb@1300, chgr@1000) and the gauge's SDAM (qg-sdam@b100) -- read and never written
 */
static struct peripheral qg, usbin, chgr, qgsdam;
static bool battery_direct;
""")
sub1(BTN, """static void
buttons_thread(void *parameter, __unused wait_result_t result)
{""", """/*
 * doha: one look at the battery (Qualcomm's qg-reg.h, qg-defs.h, qg-sdam.c, smb5-reg.h of doha's kernel): the gauge's
 * last ADC reading of the cell (QG_LAST_ADC_V_DATA0, 2 bytes, 194.637 uV a step), a cable at USB in (its INT_RT_STS,
 * USBIN_PLUGIN bit 4), the charger's state (BATTERY_CHARGER_STATUS_1, bits 2:0: 1-4 charging, 5 done), and the level
 * Android's gauge driver last kept in the SDAM (offset 0x47, valid at 0x46). The level from the voltage, as the
 * loader's soc_from_voltage(): a cable lifts the voltage, so it reads high while charging.
 */
extern void redwood_battery_direct(int soc, int voltage_mv, int plugged, int charging, int android_soc);

static void
battery_look(void)
{
	static unsigned complaints;
	uint8_t v[2] = { 0, 0 }, usb = 0, state = 0, sdam[2] = { 0, 0 };
	const char *problem;
	int mv, soc, android = -1;

	if ((problem = spmi_read(&qg, 0xc0, v, 2)) != NULL || (problem = spmi_read(&usbin, 0x10, &usb, 1)) != NULL ||
	    (problem = spmi_read(&chgr, 0x06, &state, 1)) != NULL) {
		if (complaints++ < 5) {
			printf("battery: the PMI632 does not answer: %s\\n", problem);
		}
		return;
	}
	if (qgsdam.found && spmi_read(&qgsdam, 0x46, sdam, 2) == NULL && sdam[0] != 0 && sdam[1] <= 100) {
		android = sdam[1];
	}
	mv = (int)(((uint32_t)v[0] | (uint32_t)v[1] << 8) * 194637ULL / 1000000ULL);
	if (mv < 2800 || mv > 4600) {
		/* not a Li-ion cell's voltage: a reading to distrust, never a level to hand iOS (0% would mean empty) */
		redwood_status(REDWOOD_STATUS_BATTERY, "PMI632 gauge reads %d mV (raw %02x%02x): not used", mv, v[1], v[0]);
		return;
	}
	/*
	 * A cell's voltage sags while the cores draw (the Gold ones at 1804 MHz more so), and one low reading made the
	 * status bar show 16% when the panel said 44%. The level is taken from the highest of the last minute's readings
	 * (12, 5 s apart: the least loaded, the nearest the resting voltage), and it never rises without a cable nor
	 * falls with one; a cable in or out starts over.
	 */
	static int recent[12], filled, next, last_soc = -1, last_plugged = -1;
	int plugged_now = (usb & 0x10) != 0, high = 0;

	if (plugged_now != last_plugged) {
		filled = next = 0;
		last_soc = -1;
		last_plugged = plugged_now;
	}
	recent[next] = mv;
	next = (next + 1) % 12;
	if (filled < 12) {
		filled++;
	}
	for (int i = 0; i < filled; i++) {
		high = recent[i] > high ? recent[i] : high;
	}
	mv = high;
	if (mv <= 3300) {
		soc = 0;
	} else if (mv < 3700) {
		soc = (mv - 3300) * 10 / 400;
	} else if (mv < 3900) {
		soc = 10 + (mv - 3700) * 40 / 200;
	} else if (mv < 4200) {
		soc = 50 + (mv - 3900) * 40 / 300;
	} else if (mv < 4400) {
		soc = 90 + (mv - 4200) * 10 / 200;
	} else {
		soc = 100;
	}
	state &= 7;
	if (state == 5) {
		soc = 100;      /* the charger says it has finished: full */
	}
	if (last_soc >= 0 && (plugged_now ? soc < last_soc : soc > last_soc)) {
		soc = last_soc;
	}
	last_soc = soc;
	redwood_battery_direct(soc, mv, (usb & 0x10) != 0, state >= 1 && state <= 4, android);
}

static void
buttons_thread(void *parameter, __unused wait_result_t result)
{""")
sub1(BTN, """	find_channel(&pon, channels);
	find_channel(&pin, channels);
""", """	find_channel(&pon, channels);
	find_channel(&pin, channels);
	if (battery_direct) {
		find_channel(&qg, channels);
		find_channel(&usbin, channels);
		find_channel(&chgr, channels);
		find_channel(&qgsdam, channels);
		battery_direct = qg.found && usbin.found && chgr.found;
		if (battery_direct) {
			battery_look();
		}
	}
""")
sub1(BTN, """	for (unsigned tick = 1;; tick++) {
		buttons_poll();
""", """	for (unsigned tick = 1;; tick++) {
		buttons_poll();
		if (battery_direct && tick % (5000 / POLL_MS) == 0) {
			battery_look();
		}
""")
sub1(BTN, """	pon = (struct peripheral){ .name = board->pon_name, .id = board->pon_id };
""", """	pon = (struct peripheral){ .name = board->pon_name, .id = board->pon_id };
	if (strcmp(board->device, "doha") == 0) {
		uint32_t battery = 0;

		if (PE_parse_boot_argn("battery", &battery, sizeof(battery)) && battery) {
			battery_direct = true;
			qg = (struct peripheral){ .name = "the PMI632's gauge", .id = 0x248 };
			usbin = (struct peripheral){ .name = "the PMI632's USB input", .id = 0x213 };
			chgr = (struct peripheral){ .name = "the PMI632's charger", .id = 0x210 };
			qgsdam = (struct peripheral){ .name = "the PMI632's gauge SDAM", .id = 0x2b1 };
		}
	}
""")

# the battery's line of the panel (fb_hud=1): what the loader's cache says, and why nothing comes if nothing does
BAT = 'xnu/files/bsd/dev/redwood_battery.c'
# doha: read straight from the PMI632 by the buttons' SPMI reader (redwood_buttons.c), Qualcomm's UEFI charger drivers
# not coming up there; published here like the loader's
sub1(BAT, """static uint64_t battery_updates, battery_failures;
""", """static uint64_t battery_updates, battery_failures;
static int battery_android_soc = -1;    /* doha: the level Android's gauge driver last kept in the PMI632's SDAM */

/*
 * doha (bsd/dev/redwood_buttons.c, battery=1): what the PMI632 says, read on the SPMI bus -- the cell's voltage from
 * its gauge, the level estimated from it, a cable at USB in, the charger's state -- in place of the loader's cache.
 */
void redwood_battery_direct(int soc, int voltage_mv, int plugged, int charging, int android_soc);
void
redwood_battery_direct(int soc, int voltage_mv, int plugged, int charging, int android_soc)
{
	battery_soc_percent = soc;
	battery_voltage_mv = voltage_mv;
	battery_present = 1;
	battery_charger_present = plugged;
	battery_charging = charging;
	battery_soc_estimated = 1;
	battery_android_soc = android_soc;
	battery_updates++;
}
""")
sub1(BAT, """	for (unsigned tick = 0;; tick++) {
		battery_poll();
""", """	for (unsigned tick = 0;; tick++) {
		battery_poll();
		redwood_status(REDWOOD_STATUS_BATTERY, "%d%%%s %d mV, cable %d, chg %d; Android %d%%; L %#x",
		    battery_soc_percent, battery_soc_estimated ? "~" : "", battery_voltage_mv, battery_charger_present,
		    battery_charging, battery_android_soc, shared_battery->reserved);
""")
sub1(BAT, """		printf("battery: xnuloader did not provide battery_shared_pa\\n");
		return;""", """		printf("battery: xnuloader did not provide battery_shared_pa\\n");
		redwood_status(REDWOOD_STATUS_BATTERY, "FAILED: no battery_shared_pa from the loader");
		return;""")
sub1(BAT, """		    shared_battery->magic, shared_battery->version, shared_battery->size);
		return;""", """		    shared_battery->magic, shared_battery->version, shared_battery->size);
		redwood_status(REDWOOD_STATUS_BATTERY, "FAILED: bad loader cache (magic %#llx)", shared_battery->magic);
		return;""")

# doha's store: userdata past the iOS volume and the cryptexes (ufs_write=1), the same bounds as the loader's doha_store
sub1('xnu/files/bsd/dev/redwood_ufs.c', """	{ "userdata", 31031296, 91111391, 512, 0, true },
""", """	{ "userdata", 31031296, 91111391, 512, 0, true },
	/*
	 * doha: userdata, mmcblk0p80, its 50 GiB that were Android's data, with the iOS volume and both cryptexes in
	 * its first 8365539328 bytes: the store (ufs_write=1, not a filesystem), past them like willow's system.
	 */
	{ "userdata", 17924096, 104218591, 512, UFS_WRITE_FIRST, false },
""")

# doha: uefi_cpu=probe (what Qualcomm's ClockDxe says of each core's performance levels, read only) stays on screen:
# whether the UEFI's own clock driver can put the Gold cluster at a level, the OSM set up by the firmware itself
sub1(L, """					print("uefi clock: the clock protocol, version %x\\n", clock->version);
					uefi_cpu_probe(clock);
				}
				break;""", """					print("uefi clock: the clock protocol, version %x\\n", clock->version);
					uefi_cpu_probe(clock);
					if (PLAT == &platform_doha) {
						print("uefi_cpu=probe: 25 s to read this\\n");
						BS->stall(25000000);
					}
				}
				break;""")

# the OSM report (osm_dump=1) in short on the panel's CPU line: Gold's enable, how many of its configuration words
# (0x1c..0xb8, all set on Silver, all zero on Gold before its cores were up) are set now, and the cores' speed
OSMF = 'xnu/files/bsd/dev/redwood_osm.c'
sub1(OSMF, """	printf("osm: %u lines of the blocks not zero\\n", lines);
""", """	printf("osm: %u lines of the blocks not zero\\n", lines);
	static uint32_t gold_enable, gold_set;
	{
		uint32_t s_set = 0, g_set = 0;

		for (uint32_t at = 0x1c; at <= 0xb8; at += 4) {
			s_set += rd(osm + OSM_SILVER + at) != 0;
			g_set += rd(osm + OSM_GOLD + at) != 0;
		}
		redwood_status(REDWOOD_STATUS_CPU, "OSM %us: enable S %x G %x; config set S %u G %u of 40", after,
		    rd(osm + OSM_SILVER), rd(osm + OSM_GOLD), s_set, g_set);
		gold_enable = rd(osm + OSM_GOLD);
		gold_set = g_set;
	}
""")
sub1(OSMF, """		printf("osm: cpu %d (on cpu %d): 100M loops in %llu us: %llu million a second\\n", cpu, cpu_number(), ns / 1000,
		    ns ? 100000000000ull / ns : 0);""", """		printf("osm: cpu %d (on cpu %d): 100M loops in %llu us: %llu million a second\\n", cpu, cpu_number(), ns / 1000,
		    ns ? 100000000000ull / ns : 0);
		{
			static char speeds[48];
			size_t used = strlen(speeds);

			snprintf(speeds + used, sizeof(speeds) - used, "%s%llu", used ? " " : "", ns ? 100000000000ull / ns : 0);
			redwood_status(REDWOOD_STATUS_CPU, "G en %x cfg %u/40; Mloop/s: %s", gold_enable, gold_set, speeds);
		}""")

# osmc=f523000:ROW (each Gold core asks for a row as it comes up, as doha's own clk-cpu-osm.c does) on the panel's CPU
# line: Gold's OSM enable before and after the core asked, the row it reads back, and each core's speed (cpuprobe=1)
sub1(A6, """			printf("osm: core %d: enable %x then %x, desired %x, cycles %x then %x; %u MHz if one add a cycle\\n", core,
			    seen[0], seen[1], seen[2], seen[3], seen[4], redwood_cpu_mhz[core]);""",
     """			printf("osm: core %d: enable %x then %x, desired %x, cycles %x then %x; %u MHz if one add a cycle\\n", core,
			    seen[0], seen[1], seen[2], seen[3], seen[4], redwood_cpu_mhz[core]);
			if (core >= 4 && seen[5] != 0) {
				redwood_status(REDWOOD_STATUS_CPU, "G%x>%x r%x %u %u %u %u|%u %u %u %u", seen[0], seen[1], seen[2],
				    redwood_cpu_mhz[0], redwood_cpu_mhz[1], redwood_cpu_mhz[2], redwood_cpu_mhz[3], redwood_cpu_mhz[4],
				    redwood_cpu_mhz[5], redwood_cpu_mhz[6], redwood_cpu_mhz[7]);
			}""")

# the RPM (the SoC's buses for the GPU) and the OSM report: the SoC's, so doha's too
sub1('xnu/files/bsd/dev/redwood_rpm.c', """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "willow") != 0) {
		return;
	}
	if (!PE_parse_boot_argn("rpm", &steps, sizeof(steps))) {""", """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) ||
	    (strcmp(device, "willow") != 0 && strcmp(device, "doha") != 0)) {
		return;
	}
	if (!PE_parse_boot_argn("rpm", &steps, sizeof(steps))) {""")
sub1('xnu/files/bsd/dev/redwood_osm.c', """	    !PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "willow") != 0) {""",
     """	    !PE_parse_boot_arg_str("device", device, sizeof(device)) ||
	    (strcmp(device, "willow") != 0 && strcmp(device, "doha") != 0)) {""")
# redwood's GPU driver (Adreno 642L) stays off on doha, as on willow: gpu=1 there is redwood_a610.c's
sub1('xnu/files/bsd/dev/redwood_adreno.c', """	if (PE_parse_boot_arg_str("device", device, sizeof(device)) && strcmp(device, "willow") == 0) {
		return false;                   /* the willow's GPU is redwood_a610.c's (gpu=1 there too) */""",
     """	if (PE_parse_boot_arg_str("device", device, sizeof(device)) &&
	    (strcmp(device, "willow") == 0 || strcmp(device, "doha") == 0)) {
		return false;                   /* the willow's and doha's GPU is redwood_a610.c's (gpu=1 there too) */""")

sub1('xnu/files/bsd/dev/redwood_buttons.c',"""	{ "willow", 0x01c40000, 0x01c0a000, 0x03e00000, "the PM6125's power-on block", 0x008, 0x01, 0x05, 0x01, 0x02,
	  "GPIO5 of the PM6125", 0x0c4 },
""", """	{ "willow", 0x01c40000, 0x01c0a000, 0x03e00000, "the PM6125's power-on block", 0x008, 0x01, 0x05, 0x01, 0x02,
	  "GPIO5 of the PM6125", 0x0c4 },
	/* doha: the same PM6125 and SPMI; volume up is gpio_keys' GPIO9 of the PM6125 (pinctrl@c000, phandle 0x1e0) */
	{ "doha", 0x01c40000, 0x01c0a000, 0x03e00000, "the PM6125's power-on block", 0x008, 0x01, 0x05, 0x01, 0x02,
	  "GPIO9 of the PM6125", 0x0c8 },
""")

# The panel's GPU and Screen lines, for where a frame's time goes (2026-11-10): the GPU line, every 5 s window with
# submissions, how busy the GPU was and what the processor spent on it per second (pushing buffers out of the cache,
# waiting for the GPU in submissions and in programs' CPU_PREP); the Screen line, the longest gap between two frames
# of the last whole second in place of the last gap alone (gaps over half a second are the screen at rest, left out)
GPUF = 'xnu/files/iokit/Kernel/RedwoodGPU.cpp'
sub1(GPUF, """void redwood_osm_report(void);
""", """void redwood_osm_report(void);
void redwood_status(unsigned part, const char *format, ...) __printflike(2, 3);
uint64_t a610_fence_us(uint32_t fence);
""")
sub1(GPUF, """		absolutetime_to_nanoseconds(gGPUStat.prepWaiting, &prepWaiting);
""", """		absolutetime_to_nanoseconds(gGPUStat.prepWaiting, &prepWaiting);
		{
			uint64_t s = nanos / 1000000;   /* the window, in ms */

			if (s != 0) {
				uint64_t show, blit, app;

				absolutetime_to_nanoseconds(gWaitShow, &show);
				absolutetime_to_nanoseconds(gWaitBlit, &blit);
				absolutetime_to_nanoseconds(gWaitApp, &app);
				uint64_t copy = gBlitCount ? gBlitGpuUs / gBlitCount : 0;      /* us, one copy onto the panel */

				(void)app;
				redwood_status(3 /* REDWOOD_STATUS_GPU */, "busy %llu%% %llu/s; copy %llu.%llums; wait show %llu blit %llu",
				    worked / 10 / s, (uint64_t)gGPUStat.submissions * 1000 / s, copy / 1000, copy / 100 % 10,
				    show / 1000 / s, blit / 1000 / s);
				gWaitShow = gWaitBlit = gWaitApp = 0;
				gBlitGpuUs = 0;
				gBlitCount = 0;
			}
		}
""")
FBF = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
sub1(FBF, """	uint32_t        fHudFrames, fHudFps, fHudIntervalUs, fHudDriverUs;
""", """	uint32_t        fHudFrames, fHudFps, fHudIntervalUs, fHudDriverUs;
	uint32_t        fHudWorstUs, fHudWorstShownUs;  /* the longest gap of the second being counted, and of the last */
""")
sub1(FBF, """		fHudIntervalUs = (uint32_t) (ns / 1000);
	}""", """		fHudIntervalUs = (uint32_t) (ns / 1000);
		if (fHudIntervalUs < 500000 && fHudIntervalUs > fHudWorstUs) {
			fHudWorstUs = fHudIntervalUs;
		}
	}""")
sub1(FBF, """		fHudFps = fHudSecond == 0 ? 0 : (uint32_t) ((uint64_t) fHudFrames * NSEC_PER_SEC / ns);
		fHudFrames = 0;""", """		fHudFps = fHudSecond == 0 ? 0 : (uint32_t) ((uint64_t) fHudFrames * NSEC_PER_SEC / ns);
		fHudWorstShownUs = fHudWorstUs;
		fHudWorstUs = 0;
		fHudFrames = 0;""")
sub1(FBF, """	redwood_status(kStatusScreen, "%u fps; %u ms a frame, %u ms of it showing it", fHudFps, fHudIntervalUs / 1000,
	    fHudDriverUs / 1000);""", """	redwood_status(kStatusScreen, "%u fps; longest gap %u ms; %u ms showing it", fHudFps, fHudWorstShownUs / 1000,
	    fHudDriverUs / 1000);""")

# ... and the waits for the GPU by who waits: the display for a frame to be drawn before it shows it (show, with the
# wait for an announced frame's submission), a frame copied onto the panel by the GPU (blit), programs' MSM_WAIT_FENCE
# (app); all three were in one "wait"
sub1(GPUF, """} gGPUStat;
""", """} gGPUStat;
static uint64_t gWaitShow, gWaitBlit, gWaitApp;         /* the panel's GPU line: waits by who waited (processor clock) */
static uint64_t gBlitGpuUs;                             /* ... and the GPU's own time for the frames it copied onto the panel */
static uint32_t gBlitCount;
""")
sub1(GPUF, """		gAnnounced.waiting += mach_absolute_time() - began;
""", """		gAnnounced.waiting += mach_absolute_time() - began;
		gWaitShow += mach_absolute_time() - began;
""")
sub1(GPUF, """		done = !redwood_gpu_ready() || gpuWait(fence, milliseconds);
""", """		uint64_t showBegan = mach_absolute_time();

		done = !redwood_gpu_ready() || gpuWait(fence, milliseconds);
		gWaitShow += mach_absolute_time() - showBegan;
""")
sub1(GPUF, """	done = fence != 0 && gpuWait(fence, 200);
""", """	{
		uint64_t blitBegan = mach_absolute_time();

		done = fence != 0 && gpuWait(fence, 200);
		gWaitBlit += mach_absolute_time() - blitBegan;
		if (done) {
			gBlitGpuUs += a610_fence_us(fence);
			gBlitCount++;
		}
	}
""")
sub1(GPUF, """		slowWait("fence", waitBegan);
""", """		gWaitApp += mach_absolute_time() - waitBegan;
		slowWait("fence", waitBegan);
""")

# the GPU's own time for one submission (bsd/dev/redwood_a610.c's times, written by the core before and after it), for
# the panel's GPU line: what a frame's copy onto the panel costs the GPU (iokit/Kernel/RedwoodGPU.cpp)
sub1(A6, """/* Add up the times of the submissions the core has finished since this was last done (redwood_adreno.c's gpu_times). */
""", """/* How long the core worked on submission `fence`, in microseconds, if its times are still kept; 0 otherwise. */
uint64_t a610_fence_us(uint32_t fence);
uint64_t
a610_fence_us(uint32_t fence)
{
	volatile uint64_t *times = (volatile uint64_t *)(kept_scratch() + KEPT_TIMES_AT);
	uint32_t slot = fence % KEPT_TIMES;

	to_memory(kept_scratch(), 4096);
	return times[2 * slot + 1] > times[2 * slot] ? (times[2 * slot + 1] - times[2 * slot]) * 10 / 192 : 0;
}

/* Add up the times of the submissions the core has finished since this was last done (redwood_adreno.c's gpu_times). */
""")

# The memory bus (bimc) at what the GPU needs (2026-11-10): boot-arg rpm_bimc=kHz in place of the 400 MHz asked so far.
# doha's own kernel (trinket-gpu.dtsi, "grp3d", the 3D core to EBI) votes 10824000 KB/s with the GPU at 745 MHz and
# 14432000 at 900-950: bimc at 1353 and 1804 MHz. The RPM sets the rails for it itself
sub1('xnu/files/bsd/dev/redwood_rpm.c', """	if (!rpm_ask("the memory bus (bimc)", TYPE_MEM_CLK, 0, 400000)) {""",
     """	uint32_t bimc_khz = 400000;

	if (PE_parse_boot_argn("rpm_bimc", &bimc_khz, sizeof(bimc_khz)) && (bimc_khz < 100000 || bimc_khz > 1804000)) {
		printf("rpm: rpm_bimc=%u kHz is outside 100000-1804000: 400000\\n", bimc_khz);
		bimc_khz = 400000;
	}
	if (!rpm_ask("the memory bus (bimc)", TYPE_MEM_CLK, 0, bimc_khz)) {""")

# doha, "mdssdump=1" (2026-11-10): the display controller as the UEFI keeps it running, read only, for the way to show
# iOS's frame without the GPU's copy onto 0x5C000000: which source pipe scans out, from where, in what format
sub1(L, """				print("memmap=1: 20 s to read this\\n");
				BS->stall(20000000);
				break;
			}
		}
""", """				print("memmap=1: 20 s to read this\\n");
				BS->stall(20000000);
				break;
			}
		}
		/*
		 * doha, "mdssdump=1": the display controller (MDSS at 0x5E00000; its blocks where doha's own trinket-sde.dtsi
		 * has them) as the UEFI left it scanning out, read only: the three source pipes (VIG0 +0x5000, DMA0 +0x25000,
		 * DMA1 +0x27000: size 0x00, source xy 0x08, out size 0x0c, the picture's address 0x14, its stride 0x24, the
		 * format 0x30), CTL0 (+0x2000), the mixer LM0 (+0x45000) and the DSI interface (+0x6B800); 30 s to read
		 */
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "mdssdump=1") && (c == pi.cmdline || c[-1] == ' ')) {
				static const struct {
					const char *name;
					uint64_t at;
					uint32_t words;
				} blocks[] = {
					{ "VIG0", 0x05E05000ULL, 16 }, { "DMA0", 0x05E25000ULL, 16 }, { "DMA1", 0x05E27000ULL, 16 },
					{ "CTL0", 0x05E02000ULL, 16 }, { "LM0", 0x05E45000ULL, 16 }, { "INTF1", 0x05E6B800ULL, 28 },
				};

				print("mdssdump=1: the display controller, read only; 0x5E00000: %x\\n",
				    (uint64_t)*(volatile uint32_t *)(uintptr_t)0x05E00000ULL);
				for (int b = 0; b < 6; b++) {
					volatile uint32_t *r = (volatile uint32_t *)(uintptr_t)blocks[b].at;

					print("%s at %x:\\n", blocks[b].name, blocks[b].at);
					for (uint32_t i = 0; i < blocks[b].words; i += 4) {
						print("  +%x: %x %x %x %x\\n", (uint64_t)(4 * i), (uint64_t)r[i], (uint64_t)r[i + 1],
						    (uint64_t)r[i + 2], (uint64_t)r[i + 3]);
					}
				}
				print("mdssdump=1: 30 s to read this\\n");
				BS->stall(30000000);
				break;
			}
		}
""")

# doha, "fliptest=1" (2026-11-10): whether the display controller shows a picture from anywhere in RAM when VIG0's
# address is changed -- the way to show iOS's frames without the GPU's copy. Reversible: 5 s, then 0x5C000000 again
sub1(L, """				print("mdssdump=1: 30 s to read this\\n");
				BS->stall(30000000);
				break;
			}
		}
""", """				print("mdssdump=1: 30 s to read this\\n");
				BS->stall(30000000);
				break;
			}
		}
		/*
		 * doha, "fliptest=1": a picture of eight coloured bands in RAM of the loader's (below 4 GB: the pipe takes 32
		 * bits), shown for 5 s by pointing VIG0's picture address (0x5E05000 + 0x14, read by mdssdump=1 as 0x5c000000)
		 * at it and flushing VIG0 through CTL0 (+0x18, bit 0; the pipe takes it at the next frame), then put back. Same
		 * size, stride (4320) and format as the UEFI's picture. If the bands show, the controller reads physical memory
		 * wherever it is, and a frame of iOS's can be shown where it was drawn.
		 */
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "fliptest=1") && (c == pi.cmdline || c[-1] == ' ')) {
				const uint64_t bytes = 4320ULL * 2280, pages = (bytes + 0xFFF) >> 12;
				static const uint32_t colours[8] = { 0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffffff, 0xffffff00, 0xff00ffff,
				    0xffff00ff, 0xff808080 };
				volatile uint32_t *vig = (volatile uint32_t *)(uintptr_t)0x05E05000ULL;
				volatile uint32_t *ctl = (volatile uint32_t *)(uintptr_t)0x05E02000ULL;
				uint64_t buf = 0xFFFFFFFFULL;
				uint32_t old;

				if (EFI_ERROR(BS->allocate_pages(AllocateMaxAddress, EfiLoaderData, pages, &buf))) {
					print("fliptest=1: no %d pages below 4 GB\\n", pages);
					BS->stall(10000000);
					break;
				}
				for (uint64_t y = 0; y < 2280; y++) {
					uint32_t *row = (uint32_t *)(uintptr_t)(buf + y * 4320);

					for (uint64_t x = 0; x < 1080; x++) {
						row[x] = colours[y * 8 / 2280];
					}
				}
				flush_dcache(buf, buf + bytes);
				old = vig[0x14 / 4];
				print("fliptest=1: VIG0's picture from %x to %x for 5 s\\n", (uint64_t)old, buf);
				BS->stall(2000000);
				vig[0x14 / 4] = (uint32_t)buf;
				__asm__ volatile ("dsb sy" ::: "memory");
				ctl[0x18 / 4] = 1;
				__asm__ volatile ("dsb sy" ::: "memory");
				BS->stall(5000000);
				vig[0x14 / 4] = old;
				__asm__ volatile ("dsb sy" ::: "memory");
				ctl[0x18 / 4] = 1;
				__asm__ volatile ("dsb sy" ::: "memory");
				BS->stall(100000);
				print("fliptest=1: back; VIG0 +14 reads %x, CTL0 flush %x; 15 s to read this\\n", (uint64_t)vig[0x14 / 4],
				    (uint64_t)ctl[0x18 / 4]);
				BS->free_pages(buf, pages);
				BS->stall(15000000);
				break;
			}
		}
""")

# fb_flip=1, doha (2026-11-10): a frame of iOS's shown where the GPU drew it -- the display's pipe VIG0 pointed at the
# surface (fliptest=1 showed the controller reads physical memory below 4 GB) -- in place of the GPU's copy onto the
# panel's memory, which cost the GPU 5-7 ms a frame and kept the presenter waiting ~400 ms a second. Only a frame of one
# layer, the panel's size, unscaled, in a surface of memory in one piece below 4 GB (MiniIOSurface.cpp makes the big
# ones so with fb_flip=1); anything else is copied as before, the pipe pointed back at the panel's memory first.
FBF = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
sub1(FBF, """static TUNABLE(uint32_t, gFBGPU, "fb_gpu", 0);
""", """static TUNABLE(uint32_t, gFBGPU, "fb_gpu", 0);
/*
 * Boot-arg fb_flip=1 (doha): a frame of one layer, the panel's size and unscaled, shown where the GPU drew it, by
 * pointing the display controller's pipe at the surface (VIG0's picture address and stride, flushed through CTL0;
 * taken at the next refresh), not copied; the HUD is drawn into the surface first. Anything else as before.
 */
static TUNABLE(uint32_t, gFlip, "fb_flip", 0);
#define MDSS_PHYS               0x05E00000ull   /* doha's trinket-sde.dtsi, mdp_phys */
#define MDSS_SIZE               0x80000
#define VIG0_ADDR               ((0x5000 + 0x14) / 4)   /* SSPP_SRC0_ADDR */
#define VIG0_STRIDE             ((0x5000 + 0x24) / 4)   /* SSPP_SRC_YSTRIDE0 */
#define CTL0_FLUSH              ((0x2000 + 0x18) / 4)   /* bit 0: VIG0 */
extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" void flush_dcache(vm_offset_t addr, unsigned count, int phys);
""")
sub1(FBF, """	void drawHud(uint64_t began);
""", """	void drawHud(uint64_t began);
	bool flipTo(MiniIOSurface * s, const int32_t * src, const int32_t * dst, uint64_t began);
	void flipBack(void);
	bool flipLatched(void);
	MiniIOSurface * fFlipped;               /* fb_flip=1: the surface the pipe shows, held until the next is taken */
	volatile uint32_t * fMdss;
	uint32_t        fFlipHomeAddr, fFlipHomeStride, fFlipFrames, fFlipMisses;
	bool            fFlipTried;
""")
sub1(FBF, """/* A swap's surfaces onto the panel, once the GPU is done with them. */
void
IOMobileFramebuffer::show(""", """/* fb_flip=1: wait (40 ms at most) until the controller has taken the registers flushed (CTL0's flush bit back to 0) */
bool
IOMobileFramebuffer::flipLatched(void)
{
	uint64_t t0 = mach_absolute_time(), limit;

	nanoseconds_to_absolutetime(40 * NSEC_PER_MSEC, &limit);
	while (fMdss[CTL0_FLUSH] & 1) {
		if (mach_absolute_time() - t0 > limit) {
			return false;
		}
		delay(200);
	}
	return true;
}

/*
 * fb_flip=1: the pipe pointed at surface s, if s can be shown as it is; held until the next one is taken, the one
 * before let go once the controller has taken this. False: the frame is to be copied.
 */
bool
IOMobileFramebuffer::flipTo(MiniIOSurface * s, const int32_t * src, const int32_t * dst, uint64_t began)
{
	IOByteCount length = 0;
	uint64_t phys, bytes;
	MiniIOSurface * held;

	if (fMdss == NULL) {
		char device[16] = "";

		if (fFlipTried) {
			return false;
		}
		fFlipTried = true;
		if (!PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "doha") != 0 ||
		    (fMdss = (volatile uint32_t *) ml_io_map(MDSS_PHYS, MDSS_SIZE)) == NULL) {
			return false;
		}
		fFlipHomeAddr = fMdss[VIG0_ADDR];
		fFlipHomeStride = fMdss[VIG0_STRIDE];
		IOLog("MiniIOMobileFramebuffer: fb_flip=1: VIG0 shows %#x (stride %u); frames will be shown where drawn\\n",
		    fFlipHomeAddr, fFlipHomeStride);
	}
	if (s == NULL || s->client != NULL || s->memory == NULL || s->info.bytesPerElement != 4 || s->info.planeCount != 0 ||
	    s->info.width != fPanelWidth || s->info.height != fPanelHeight || fWidth != fPanelWidth || fHeight != fPanelHeight ||
	    !(src[2] <= 0 || src[3] <= 0 || (src[0] == 0 && src[1] == 0 && src[2] == (int32_t) fPanelWidth &&
	    src[3] == (int32_t) fPanelHeight)) ||
	    !(dst[2] <= 0 || dst[3] <= 0 || (dst[0] == 0 && dst[1] == 0 && dst[2] == (int32_t) fWidth && dst[3] == (int32_t) fHeight)) ||
	    (s->info.bytesPerRow & 63) != 0 || s->info.bytesPerRow > 0xffff) {
		return false;
	}
	bytes = (uint64_t) s->info.bytesPerRow * s->info.height;
	phys = s->memory->getPhysicalSegment((IOByteCount) (s->pixels() - s->kbase), &length, kIOMemoryMapperNone);
	if (phys == 0 || length < bytes || phys + bytes > 0x100000000ull) {
		fFlipMisses++;
		return false;
	}
	if (gHud) {
		uint8_t * base = fBase;
		uint32_t rowBytes = fRowBytes;

		fBase = s->pixels();
		fRowBytes = s->info.bytesPerRow;
		drawHud(began);
		fBase = base;
		fRowBytes = rowBytes;
		flush_dcache((vm_offset_t) s->pixels(), (unsigned) (s->info.bytesPerRow * 512), 0);
	}
	if ((held = MiniIOSurfaceCopy(s->sid)) == NULL) {
		return false;
	}
	flipLatched();
	fMdss[VIG0_STRIDE] = s->info.bytesPerRow;
	fMdss[VIG0_ADDR] = (uint32_t) phys;
	__asm__ volatile ("dsb sy" ::: "memory");
	fMdss[CTL0_FLUSH] = 1;
	__asm__ volatile ("dsb sy" ::: "memory");
	flipLatched();
	if (fFlipped != NULL) {
		MiniIOSurfaceDrop(fFlipped);
	}
	fFlipped = held;
	fFlipFrames++;
	return true;
}

/* fb_flip=1: the pipe back on the panel's memory (a frame has just been copied there) */
void
IOMobileFramebuffer::flipBack(void)
{
	if (fFlipped == NULL || fMdss == NULL) {
		return;
	}
	flipLatched();
	fMdss[VIG0_STRIDE] = fFlipHomeStride;
	fMdss[VIG0_ADDR] = fFlipHomeAddr;
	__asm__ volatile ("dsb sy" ::: "memory");
	fMdss[CTL0_FLUSH] = 1;
	__asm__ volatile ("dsb sy" ::: "memory");
	flipLatched();
	MiniIOSurfaceDrop(fFlipped);
	fFlipped = NULL;
}

/* A swap's surfaces onto the panel, once the GPU is done with them. */
void
IOMobileFramebuffer::show(""")
sub1(FBF, """	for (unsigned layer = 0; layer < SWAP_LAYERS; layer++) {
		uint32_t sid = swapWord(swap, SWAP_SURFACE(layer));
		int32_t src[4], dst[4];
		MiniIOSurface * s;
""", """	bool unflip = false;

	if (gFlip && fGraphics) {
		bool alone = surfaces[0] != NULL;

		for (unsigned layer = 1; layer < SWAP_LAYERS; layer++) {
			alone = alone && swapWord(swap, SWAP_SURFACE(layer)) == 0;
		}
		if (alone) {
			int32_t src[4], dst[4];

			memcpy(src, swap + SWAP_SOURCE(0), sizeof(src));
			memcpy(dst, swap + SWAP_DEST(0), sizeof(dst));
			if (flipTo(surfaces[0], src, dst, began)) {
				layers = 1;
				goto flipped;
			}
		}
		unflip = fFlipped != NULL;
	}
	for (unsigned layer = 0; layer < SWAP_LAYERS; layer++) {
		uint32_t sid = swapWord(swap, SWAP_SURFACE(layer));
		int32_t src[4], dst[4];
		MiniIOSurface * s;
""")
sub1(FBF, """	if (gHud && fGraphics) {
		drawHud(began);
	}
	drawn = mach_absolute_time();""", """	if (gHud && fGraphics) {
		drawHud(began);
	}
	if (unflip) {
		flipBack();
	}
flipped:
	drawn = mach_absolute_time();""")
sub1(FBF, """	redwood_status(kStatusScreen, "%u fps; longest gap %u ms; %u ms showing it", fHudFps, fHudWorstShownUs / 1000,
	    fHudDriverUs / 1000);""", """	redwood_status(kStatusScreen, "%u fps; longest gap %u ms; %u ms showing it%s", fHudFps, fHudWorstShownUs / 1000,
	    fHudDriverUs / 1000, fFlipped != NULL ? "; flip" : "");""")
SURF = 'xnu/files/iokit/Kernel/MiniIOSurface.cpp'
sub1(SURF, """	if (memory == NULL) {
		memory = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, kIODirectionInOut | kIOMemoryKernelUserShared, bytes,
		    PAGE_SIZE);
	}
	return memory;""", """	{
		/*
		 * fb_flip=1 (MiniIOMobileFramebuffer.cpp): a frame-sized surface in memory of one piece below 4 GB, which the
		 * display controller can be pointed at; as before if there is no such piece
		 */
		static int flip = -1;
		uint32_t value = 0;

		if (flip < 0) {
			flip = PE_parse_boot_argn("fb_flip", &value, sizeof(value)) && value != 0;
		}
		if (memory == NULL && flip && bytes >= (8u << 20)) {
			memory = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task, kIODirectionInOut |
			    kIOMemoryKernelUserShared | kIOMemoryPhysicallyContiguous, bytes, 0xfffff000ull);
		}
	}
	if (memory == NULL) {
		memory = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, kIODirectionInOut | kIOMemoryKernelUserShared, bytes,
		    PAGE_SIZE);
	}
	return memory;""")

# fb_flip=1, second run (2026-11-10): trails while scrolling -- CoreAnimation drew into the surface the panel was
# showing, nothing telling it the display had it. The display's use is now counted on the surface (its use count, the
# one IOSurfaceIsInUse reads), as Apple's display driver does, from the flip until the next surface is taken
SURF = 'xnu/files/iokit/Kernel/MiniIOSurface.cpp'
sub1(SURF, """MiniIOSurface *
MiniIOSurfaceCreateSimple(uint32_t width, uint32_t height, uint32_t pixelFormat)
{""", """/* The display shows the surface (delta 1) or has stopped (-1): its use count, which IOSurfaceIsInUse reads, says so */
void
MiniIOSurfaceDisplayUse(MiniIOSurface * s, int delta)
{
	if (s == NULL || gSurfaceLock == NULL) {
		return;
	}
	IOLockLock(gSurfaceLock);
	if (delta > 0 || s->useCount[0] != 0) {
		s->useCount[0] += delta;
		s->shared()->useCount = (uint64_t) s->useCount[1] << 32 | s->useCount[0];
	}
	IOLockUnlock(gSurfaceLock);
}

MiniIOSurface *
MiniIOSurfaceCreateSimple(uint32_t width, uint32_t height, uint32_t pixelFormat)
{""")
sub1('xnu/files/iokit/Kernel/MiniIOSurface.h', """void            MiniIOSurfaceDrop(MiniIOSurface * surface);
""", """void            MiniIOSurfaceDrop(MiniIOSurface * surface);
/* The display shows a surface where it is (delta 1), or has stopped (-1): counted as a use (IOSurfaceIsInUse) */
void            MiniIOSurfaceDisplayUse(MiniIOSurface * surface, int delta);
""")
FBF = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
sub1(FBF, """	if ((held = MiniIOSurfaceCopy(s->sid)) == NULL) {
		return false;
	}
""", """	if ((held = MiniIOSurfaceCopy(s->sid)) == NULL) {
		return false;
	}
	MiniIOSurfaceDisplayUse(held, 1);
""")
sub1(FBF, """	if (fFlipped != NULL) {
		MiniIOSurfaceDrop(fFlipped);
	}
	fFlipped = held;""", """	if (fFlipped != NULL) {
		MiniIOSurfaceDisplayUse(fFlipped, -1);
		MiniIOSurfaceDrop(fFlipped);
	}
	fFlipped = held;""")
sub1(FBF, """	flipLatched();
	MiniIOSurfaceDrop(fFlipped);
	fFlipped = NULL;""", """	flipLatched();
	MiniIOSurfaceDisplayUse(fFlipped, -1);
	MiniIOSurfaceDrop(fFlipped);
	fFlipped = NULL;""")

# doha, battery step 1 (2026-11-10, read only): why iOS does not charge -- the charger's state as the PMI632 has it,
# on the panel's Wi-Fi line (there is no Wi-Fi yet): status 1 and 2 (0x1006-7, bits 2:0 of 1: 0 inhibited, 1 trickle,
# 2 pre, 3 full-on, 4 taper, 5 done, 6 paused, 7 disabled), CHARGING_ENABLE_CMD (0x1042), CHGR_CFG2 (0x1051), USBIN_CMD_IL
# (0x1340), ICL_STATUS (0x1107), POWER_PATH_STATUS (0x110B), the charger's watchdog WD_CFG and SNARL_BARK_BITE_WD_CFG
# (0x1651, 0x1653), the gauge's subtype (0x4805) and its last current (0x48C2, 305.176 uA a step). Registers and their
# meaning: the doha's LineageOS 23 kernel, smb5-reg.h and qg-reg.h
sub1(BTN, """static struct peripheral qg, usbin, chgr, qgsdam;
""", """static struct peripheral qg, usbin, chgr, qgsdam;
static struct peripheral dcdc, misc;    /* the charger's DCDC (0x1100) and MISC (0x1600) blocks: read for the panel only */
""")
sub1(BTN, """		find_channel(&qgsdam, channels);
""", """		find_channel(&qgsdam, channels);
		find_channel(&dcdc, channels);
		find_channel(&misc, channels);
""")
sub1(BTN, """			qgsdam = (struct peripheral){ .name = "the PMI632's gauge SDAM", .id = 0x2b1 };
""", """			qgsdam = (struct peripheral){ .name = "the PMI632's gauge SDAM", .id = 0x2b1 };
			dcdc = (struct peripheral){ .name = "the PMI632's charger DCDC", .id = 0x211 };
			misc = (struct peripheral){ .name = "the PMI632's charger MISC", .id = 0x216 };
""")
sub1(BTN, """	redwood_battery_direct(soc, mv, (usb & 0x10) != 0, state >= 1 && state <= 4, android);
""", """	redwood_battery_direct(soc, mv, (usb & 0x10) != 0, state >= 1 && state <= 4, android);
	{
		uint8_t st[2] = { 0, 0 }, en = 0, cfg2 = 0, il = 0, icl = 0, pp = 0, wd[3] = { 0, 0, 0 }, sub = 0, ia[2] = { 0, 0 };
		int64_t ma;

		spmi_read(&chgr, 0x06, st, 2);
		spmi_read(&chgr, 0x42, &en, 1);
		spmi_read(&chgr, 0x51, &cfg2, 1);
		spmi_read(&usbin, 0x40, &il, 1);
		if (dcdc.found) {
			spmi_read(&dcdc, 0x07, &icl, 1);
			spmi_read(&dcdc, 0x0b, &pp, 1);
		}
		if (misc.found) {
			spmi_read(&misc, 0x51, wd, 3);
		}
		spmi_read(&qg, 0x05, &sub, 1);
		spmi_read(&qg, 0xc2, ia, 2);
		ma = (int64_t)(int16_t)((uint16_t)ia[0] | (uint16_t)ia[1] << 8) * 305176 / 1000000;
		redwood_status(REDWOOD_STATUS_WIFI, "chg S%02x/%02x E%02x C%02x U%02x L%02x P%02x W%02x/%02x T%02x I%lldmA",
		    st[0], st[1], en, cfg2, il, icl, pp, wd[0], wd[2], sub, ma);
	}
""")

# kern.redwood.fb_surface (upstream 348613f22): the IOSurface last put on the panel, for SpringBoard's
# wallpaper_freeze=1 (userland/src/inject_sb.c), which reads the wallpaper's picture from it
FBF = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
sub1(FBF, """#include <kern/thread_call.h>
""", """#include <kern/thread_call.h>
#include <sys/sysctl.h>
""")
sub1(FBF, """#define SWAP_QUEUE              2                       /* frames that may wait for the panel at most (fb_queue) */
""", """/* kern.redwood.fb_surface: the IOSurface on the panel, for a picture of what is there (SpringBoard's wallpaper_freeze=1) */
SYSCTL_DECL(_kern_redwood);
static uint32_t gShownSurface;
SYSCTL_UINT(_kern_redwood, OID_AUTO, fb_surface, CTLFLAG_RD | CTLFLAG_LOCKED, &gShownSurface, 0, "the IOSurface last put on the panel");
#define SWAP_QUEUE              2                       /* frames that may wait for the panel at most (fb_queue) */
""")
sub1(FBF, """				recorded = s;   /* (recorded once the frame is in the panel's memory: see below) */
""", """				recorded = s;   /* (recorded once the frame is in the panel's memory: see below) */
				gShownSurface = sid;
""")
sub1(FBF, """	fFlipped = held;
	fFlipFrames++;""", """	fFlipped = held;
	fFlipFrames++;
	gShownSurface = s->sid;""")

# fb_flip=1, third run (2026-11-10): 14-17 fps with the flip, as if each frame waited out flipLatched's 40 ms twice --
# CTL0's flush bit seems not to read back as 0 in time on doha. The wait is now for the DSI interface's frame counter
# (INTF1 + 0xac, INTF_FRAME_COUNT, which upstream's framebuffer reads too) to move on once: the scan that takes the new
# address has begun. And only after the write: before it nothing needs waiting for.
FBF = 'xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp'
sub1(FBF, """#define CTL0_FLUSH              ((0x2000 + 0x18) / 4)   /* bit 0: VIG0 */
""", """#define CTL0_FLUSH              ((0x2000 + 0x18) / 4)   /* bit 0: VIG0 */
#define INTF1_FRAMES            ((0x6B800 + 0xac) / 4)  /* the DSI interface's INTF_FRAME_COUNT */
""")
sub1(FBF, """/* fb_flip=1: wait (40 ms at most) until the controller has taken the registers flushed (CTL0's flush bit back to 0) */
bool
IOMobileFramebuffer::flipLatched(void)
{
	uint64_t t0 = mach_absolute_time(), limit;

	nanoseconds_to_absolutetime(40 * NSEC_PER_MSEC, &limit);
	while (fMdss[CTL0_FLUSH] & 1) {
		if (mach_absolute_time() - t0 > limit) {
			return false;
		}
		delay(200);
	}
	return true;
}""", """/*
 * fb_flip=1: wait (25 ms at most) until the scan after the flush has begun: the DSI interface's frame counter has moved
 * on from what it was when the flush was written. Registers flushed are taken at the start of a scan.
 */
bool
IOMobileFramebuffer::flipLatched(void)
{
	uint64_t t0 = mach_absolute_time(), limit;
	uint32_t frames = fMdss[INTF1_FRAMES];

	nanoseconds_to_absolutetime(25 * NSEC_PER_MSEC, &limit);
	while (fMdss[INTF1_FRAMES] == frames) {
		if (mach_absolute_time() - t0 > limit) {
			fFlipMisses++;
			return false;
		}
		delay(200);
	}
	return true;
}""")
sub1(FBF, """	MiniIOSurfaceDisplayUse(held, 1);
	flipLatched();
	fMdss[VIG0_STRIDE] = s->info.bytesPerRow;""", """	MiniIOSurfaceDisplayUse(held, 1);
	fMdss[VIG0_STRIDE] = s->info.bytesPerRow;""")
sub1(FBF, """	if (fFlipped == NULL || fMdss == NULL) {
		return;
	}
	flipLatched();
	fMdss[VIG0_STRIDE] = fFlipHomeStride;""", """	if (fFlipped == NULL || fMdss == NULL) {
		return;
	}
	fMdss[VIG0_STRIDE] = fFlipHomeStride;""")
sub1(FBF, """	redwood_status(kStatusScreen, "%u fps; longest gap %u ms; %u ms showing it%s", fHudFps, fHudWorstShownUs / 1000,
	    fHudDriverUs / 1000, fFlipped != NULL ? "; flip" : "");""", """	if (fFlipped != NULL) {
		redwood_status(kStatusScreen, "%u fps; longest gap %u ms; flip, %u late", fHudFps, fHudWorstShownUs / 1000,
		    fFlipMisses);
	} else {
		redwood_status(kStatusScreen, "%u fps; longest gap %u ms; %u ms showing it", fHudFps, fHudWorstShownUs / 1000,
		    fHudDriverUs / 1000);
	}""")

# cpu_gov=1, doha (2026-11-10): the cores' clocks follow the load. All eight ran at 1804 MHz all the time, the battery
# giving 1.2 to 1.9 A on the home screen (the PMI632 gauge's current on the HUD). Every 50 ms the busiest core's share of
# that time decides a row of the OSM tables for both clusters: 70% or more, the top (Silver row 7, Gold row 6), held for
# 250 ms at least; less, the lowest row fast enough for that load at 70%, at most two rows down a step. Only the rows
# asked for are written (0x920 + 4 * core, as doha's own clk-cpu-osm.c and osmc= do); the tables and the OSMs' set-up are
# the firmware's.
OSM = 'xnu/files/bsd/dev/redwood_osm.c'
sub1(OSM, """void
redwood_osm_init(void)
{""", """/* ---- cpu_gov=1 (doha): the rows of both clusters' OSM tables by the load ---- */
#include <mach/processor_info.h>
#include <mach/machine.h>
extern kern_return_t processor_info(processor_t processor, processor_flavor_t flavor, host_t *host, processor_info_t info,
    mach_msg_type_number_t *count);

#define GOV_PERIOD_MS           50
extern uint32_t redwood_osm_seen[8][6];         /* osfmk/arm/arm_init.c, osm_ask(): [core][5] set once a core came up */
#define GOV_UP_PERCENT          70              /* a core this busy: the top row */
#define GOV_HOLD_PERIODS        5               /* ... held so long at least */
static const uint32_t gov_silver_mhz[8] = { 300, 614, 864, 1017, 1305, 1420, 1612, 1804 };      /* doha's firmware's table */
#define GOV_TOP                 7
#define GOV_GOLD_TOP            6               /* Gold's row 6, 1804 MHz (7 is 2016: nothing here watches the heat) */

static void
gov_thread(void *parameter, __unused wait_result_t result)
{
	uint32_t mode = (uint32_t)(uintptr_t)parameter;        /* 1: the rows follow the load; 2: measured only */
	vm_offset_t osm = ml_io_map(OSM_PHYS, OSM_SIZE);
	natural_t last[8][CPU_STATE_MAX];
	bool seen[8] = { false };
	uint32_t row = GOV_TOP, written = ~0u, hold = 0, min_row = 0, periods = 0, at_top = 0, load_sum = 0, peak = 0;
	uint64_t since = mach_absolute_time();

	PE_parse_boot_argn("cpu_gov_min", &min_row, sizeof(min_row));
	min_row = min_row > GOV_TOP ? GOV_TOP : min_row;
	bzero(last, sizeof(last));
	/*
	 * Not before the system is up (the first run, starting at once, stopped the boot before the panel's HUD): 60 s,
	 * the Gold cores up by then (they come up ~57 s in), and Gold's rows written only once a Gold core has said so
	 * (osmc=, osfmk/arm/arm_init.c): its OSM is not written while that cluster is off
	 */
	delay_for_interval(60, NSEC_PER_SEC);
	/*
	 * The second run rebooted the phone as the governor began: Gold's OSM written from a Silver core. Linux's driver
	 * and osmc= (which worked) write a cluster's requests from that cluster's own cores; so does this now. Which
	 * processor is which cluster: each one's MPIDR (Aff1 1: Gold), read on it once.
	 */
	int gold_cpu = -1, silver_cpu = -1;

	/*
	 * cpu_gov=2 rebooted the phone too, about 15 s after it began, nothing written: so it is the measuring or the
	 * moving between processors. With cpu_gov=2 each step now says itself on the panel's CPU line first and waits:
	 * 20 s of measuring the load alone, then each processor in turn, 3 s before and 2 s after moving there.
	 */
	if (mode == 2) {
		for (int i = 0; i < 20; i++) {
			uint32_t got = 0;

			for (int cpu = 0; cpu < 8; cpu++) {
				processor_t processor = cpu_to_processor(cpu);
				struct processor_cpu_load_info info;
				mach_msg_type_number_t count = PROCESSOR_CPU_LOAD_INFO_COUNT;
				host_t host;

				if (processor != PROCESSOR_NULL &&
				    processor_info(processor, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)&info, &count) == KERN_SUCCESS) {
					got |= 1u << cpu;
				}
			}
			redwood_status(REDWOOD_STATUS_CPU, "gov test 1: measuring, %d s; processors %#x", i, got);
			delay_for_interval(1, NSEC_PER_SEC);
		}
	}
	for (int cpu = 0; cpu < 8; cpu++) {
		processor_t processor = cpu_to_processor(cpu);
		uint64_t cluster;

		if (processor == PROCESSOR_NULL) {
			continue;
		}
		if (mode == 2) {
			redwood_status(REDWOOD_STATUS_CPU, "gov test 2: moving to processor %d", cpu);
			delay_for_interval(3, NSEC_PER_SEC);
		}
		thread_bind(processor);
		thread_block(THREAD_CONTINUE_NULL);
		cluster = (__builtin_arm_rsr64("MPIDR_EL1") >> 8) & 0xff;
		if (mode == 2) {
			redwood_status(REDWOOD_STATUS_CPU, "gov test 2: on processor %d, MPIDR %#llx", cpu,
			    __builtin_arm_rsr64("MPIDR_EL1") & 0xffff);
			delay_for_interval(2, NSEC_PER_SEC);
		}
		if (cluster == 1 && gold_cpu < 0) {
			gold_cpu = cpu;
		} else if (cluster == 0 && silver_cpu < 0) {
			silver_cpu = cpu;
		}
	}
	/* the governor itself on a Silver core, where Silver's requests are written; Gold's from a Gold one */
	thread_bind(silver_cpu >= 0 ? cpu_to_processor(silver_cpu) : PROCESSOR_NULL);
	thread_block(THREAD_CONTINUE_NULL);
	printf("cpu_gov: on processor %d (Silver); Gold's requests from processor %d\\n", silver_cpu, gold_cpu);
	if (silver_cpu < 0) {
		thread_terminate(current_thread());
	}
	printf("cpu_gov: the cores' rows follow the load every %u ms (top at %u%% busy, lowest row %u)\\n", GOV_PERIOD_MS,
	    GOV_UP_PERCENT, min_row);
	for (;;) {
		uint32_t load = 0;

		delay_for_interval(GOV_PERIOD_MS, NSEC_PER_MSEC);
		for (int cpu = 0; cpu < 8; cpu++) {
			processor_t processor = cpu_to_processor(cpu);
			struct processor_cpu_load_info info;
			mach_msg_type_number_t count = PROCESSOR_CPU_LOAD_INFO_COUNT;
			host_t host;
			uint32_t busy, total;

			if (processor == PROCESSOR_NULL ||
			    processor_info(processor, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)&info, &count) != KERN_SUCCESS) {
				continue;
			}
			busy = (info.cpu_ticks[CPU_STATE_USER] - last[cpu][CPU_STATE_USER]) +
			    (info.cpu_ticks[CPU_STATE_SYSTEM] - last[cpu][CPU_STATE_SYSTEM]);
			total = busy + (info.cpu_ticks[CPU_STATE_IDLE] - last[cpu][CPU_STATE_IDLE]);
			memcpy(last[cpu], info.cpu_ticks, sizeof(last[cpu]));
			if (seen[cpu] && total != 0 && busy * 100 / total > load) {
				load = busy * 100 / total;
			}
			seen[cpu] = true;
		}
		if (load >= GOV_UP_PERCENT) {
			row = GOV_TOP;
			hold = GOV_HOLD_PERIODS;
		} else if (hold > 0) {
			hold--;
		} else {
			uint32_t want = gov_silver_mhz[GOV_TOP] * load / GOV_UP_PERCENT, target = min_row;

			while (target < GOV_TOP && gov_silver_mhz[target] < want) {
				target++;
			}
			row = target >= row ? target : (row - target > 2 ? row - 2 : target);
		}
		/* written when it changes, and every second besides (a Gold core powered off and on again forgets its row) */
		if (mode != 2 && (row != written || periods % (1000 / GOV_PERIOD_MS) == 0)) {
			uint32_t gold = row > GOV_GOLD_TOP ? GOV_GOLD_TOP : row;

			bool gold_up = false;
			static uint32_t gold_written = ~0u;

			for (int core = 4; core < 8; core++) {
				gold_up = gold_up || redwood_osm_seen[core][5] != 0;
			}
			for (int core = 0; core < 4; core++) {
				*(volatile uint32_t *)(osm + OSM_SILVER + 0x920 + 4 * core) = row;
			}
			if (gold_up && gold_cpu >= 0 && (gold != gold_written || periods % (1000 / GOV_PERIOD_MS) == 0)) {
				thread_bind(cpu_to_processor(gold_cpu));
				thread_block(THREAD_CONTINUE_NULL);
				if (((__builtin_arm_rsr64("MPIDR_EL1") >> 8) & 0xff) == 1) {
					for (int core = 0; core < 4; core++) {
						*(volatile uint32_t *)(osm + OSM_GOLD + 0x920 + 4 * core) = gold;
					}
					__asm__ volatile ("dsb sy" ::: "memory");
					gold_written = gold;
				}
				thread_bind(cpu_to_processor(silver_cpu));
				thread_block(THREAD_CONTINUE_NULL);
			}
			__asm__ volatile ("dsb sy" ::: "memory");
			written = row;
		}
		periods++;
		at_top += row == GOV_TOP;
		load_sum += load;
		peak = load > peak ? load : peak;
		{
			uint64_t ns;

			absolutetime_to_nanoseconds(mach_absolute_time() - since, &ns);
			if (ns >= NSEC_PER_SEC) {
				redwood_status(REDWOOD_STATUS_CPU, "gov %u MHz; load %u%% (peak %u%%); top %u%% of the time",
				    gov_silver_mhz[row], load_sum / periods, peak, at_top * 100 / periods);
				periods = at_top = load_sum = peak = 0;
				since = mach_absolute_time();
			}
		}
	}
}

void
redwood_osm_init(void)
{
	{
		uint32_t gov = 0;
		char where[16] = "";
		thread_t thread;

		if (PE_parse_boot_argn("cpu_gov", &gov, sizeof(gov)) && gov != 0 &&
		    PE_parse_boot_arg_str("device", where, sizeof(where)) && strcmp(where, "doha") == 0 &&
		    kernel_thread_start(gov_thread, (void *)(uintptr_t)gov, &thread) == KERN_SUCCESS) {
			thread_deallocate(thread);
		}
	}""")

# doha, "lastpanic=1" (2026-11-10): the kernel's panic log of the run before, if the RAM kept it through the reset --
# the loader zeroes that region (PANIC_LOG_BASE) for every run, so it is read before that: the printable text in it,
# 30 s on the screen. For reboots with no message (the governor's, cpu_gov=2)
sub1(L, """				print("mdssdump=1: 30 s to read this\\n");
				BS->stall(30000000);
				break;
			}
		}
""", """				print("mdssdump=1: 30 s to read this\\n");
				BS->stall(30000000);
				break;
			}
		}
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "lastpanic=1") && (c == pi.cmdline || c[-1] == ' ')) {
				const unsigned char *log = (const unsigned char *)(uintptr_t)PANIC_LOG_BASE;
				char line[120];
				uint64_t at = 0, shown = 0, lines = 0, nonzero = 0;

				for (uint64_t i = 0; i < PANIC_LOG_SIZE; i++) {
					nonzero += log[i] != 0;
				}
				print("lastpanic=1: the panic log region (%x, %x bytes): %d bytes not zero\\n", (uint64_t)PANIC_LOG_BASE,
				    (uint64_t)PANIC_LOG_SIZE, nonzero);
				/* runs of printable text 8 or more long, broken into lines, 40 lines at most */
				while (at < PANIC_LOG_SIZE && lines < 40) {
					uint64_t run = 0;

					while (at + run < PANIC_LOG_SIZE && ((log[at + run] >= 32 && log[at + run] < 127) || log[at + run] == 10)) {
						run++;
					}
					if (run >= 8) {
						uint64_t k = 0;

						for (uint64_t j = 0; j < run && lines < 40; j++) {
							char ch = (char)log[at + j];

							if (ch == 10 || k == sizeof(line) - 2) {
								line[k] = 0;
								print("%s\\n", line);
								lines++;
								k = 0;
								if (ch == 10) {
									continue;
								}
							}
							line[k++] = ch;
						}
						if (k > 0 && lines < 40) {
							line[k] = 0;
							print("%s\\n", line);
							lines++;
						}
						shown += run;
					}
					at += run + 1;
				}
				print("lastpanic=1: %d characters shown; 30 s to read this\\n", shown);
				BS->stall(30000000);
				break;
			}
		}
""")

# doha, battery step 2 (2026-11-11): charge=1, the charger's watchdog petted. The PMI632's SMB5 starts a watchdog
# whenever a cable is in (MISC 0x51 bit 1, read as W62 on the panel) whose bite stops the charging (MISC 0x53 bit 7, read
# as /8c); Android's driver pets it, under this kernel nobody did. As qdizax-w/hakios-sm7125 does for its SM7125
# (drivers/power/hakios.miatoll_battery.c, "charging under iOS"): BARK_BITE_WDOG_PET (MISC 0x43) bit 0 written 1 every
# 5 s while the cable is in, through the arbiter's write channel for MISC if it is ours (owner = this system), the
# only write; voltage, current and temperature limits stay the firmware's. Stops for good on a refused write.
sub1(BTN, """static struct peripheral dcdc, misc;    /* the charger's DCDC (0x1100) and MISC (0x1600) blocks: read for the panel only */
""", """static struct peripheral dcdc, misc;    /* the charger's DCDC (0x1100) and MISC (0x1600) blocks: read for the panel only */
/*
 * charge=1 (doha): the charger's watchdog petted (BARK_BITE_WDOG_PET, MISC 0x43 bit 0) while a cable is in, through
 * the arbiter's write channel for the PMI632's MISC block ("chnls" at 0x1E00000 in doha's spmi@1c40000, 0x10000 a
 * channel; command 0x00, status 0x08, write data 0x10; write opcode 0), if this system owns that channel
 */
#define DOHA_ARB_CHNLS          0x01E00000UL
#define CHANNEL_WDATA0          0x10
#define COMMAND_WRITE           (0u << 27)
static vm_offset_t pet_channel;
static uint16_t pet_channel_n;
static bool pet_stopped;
static uint32_t pets;

static void
pet_setup(uint32_t channels)
{
	for (uint32_t n = 0; n < channels; n++) {
		uint32_t map = rd(arb_core + ARB_CHANNEL(n));

		if (map != 0 && ((map >> 8) & 0xfff) == 0x216 && (rd(arb_cnfg + ARB_OWNER(n)) & 7) == ARB_SYSTEM) {
			pet_channel_n = (uint16_t)n;
			pet_channel = ml_io_map(DOHA_ARB_CHNLS + 0x10000UL * n, 0x1000);
			printf("battery: charge=1: the charger's watchdog will be petted (channel %u, MISC 0x43)\\n", n);
			return;
		}
	}
	printf("battery: charge=1, but no channel of the charger's MISC block is ours to write through: nothing petted\\n");
}

static void
pet(void)
{
	uint64_t start, interval;
	uint32_t status;

	if (pet_channel == 0 || pet_stopped) {
		return;
	}
	if (((rd(arb_core + ARB_CHANNEL(pet_channel_n)) >> 8) & 0xfff) != 0x216) {
		pet_stopped = true;
		printf("battery: the arbiter's channel %u is no longer the charger's MISC: not petted any more\\n", pet_channel_n);
		return;
	}
	nanoseconds_to_absolutetime(READ_TIMEOUT_US * (uint64_t)NSEC_PER_USEC, &interval);
	redwood_spmi_lock();
	wr(pet_channel + CHANNEL_WDATA0, 0x01);
	wr(pet_channel + OBSERVER_COMMAND, COMMAND_WRITE | 0x43u << 4);
	start = mach_absolute_time();
	do {
		status = rd(pet_channel + OBSERVER_STATUS);
	} while (!(status & STATUS_DONE) && mach_absolute_time() - start < interval);
	redwood_spmi_unlock();
	if (!(status & STATUS_DONE) || (status & (STATUS_DENIED | STATUS_FAILURE))) {
		pet_stopped = true;
		printf("battery: the charger's watchdog not petted any more: %s (status %#x)\\n",
		    !(status & STATUS_DONE) ? "no answer from the arbiter" : "the write was refused", status);
		return;
	}
	pets++;
}
""")
sub1(BTN, """		find_channel(&dcdc, channels);
		find_channel(&misc, channels);
""", """		find_channel(&dcdc, channels);
		find_channel(&misc, channels);
		{
			uint32_t charge = 0;

			if (PE_parse_boot_argn("charge", &charge, sizeof(charge)) && charge) {
				pet_setup(channels);
			}
		}
""")
sub1(BTN, """	redwood_battery_direct(soc, mv, (usb & 0x10) != 0, state >= 1 && state <= 4, android);
	{
""", """	if ((usb & 0x10) != 0) {
		pet();
	}
	redwood_battery_direct(soc, mv, (usb & 0x10) != 0, state >= 1 && state <= 4, android);
	{
""")
sub1(BTN, """		redwood_status(REDWOOD_STATUS_WIFI, "chg S%02x/%02x E%02x C%02x U%02x L%02x P%02x W%02x/%02x T%02x I%lldmA",
		    st[0], st[1], en, cfg2, il, icl, pp, wd[0], wd[2], sub, ma);""", """		redwood_status(REDWOOD_STATUS_WIFI, "chg%s S%02x/%02x E%02x C%02x U%02x L%02x P%02x W%02x/%02x T%02x I%lldmA",
		    pet_stopped ? "!" : pets != 0 ? "+" : "", st[0], st[1], en, cfg2, il, icl, pp, wd[0], wd[2], sub, ma);""")

# cpu_gov, second form (2026-11-11): processor_info() rebooted the phone (cpu_gov=2 never said its first step), so the
# rows follow what the phone does -- a frame handed to the panel or a touch -- instead of a measured load; cpu_gov=2 is a
# step-by-step test of the writes alone (bsd/dev/redwood_osm.c)
sub1(OSM, """static void
gov_thread(void *parameter, __unused wait_result_t result)
{
	uint32_t mode = (uint32_t)(uintptr_t)parameter;        /* 1: the rows follow the load; 2: measured only */
	vm_offset_t osm = ml_io_map(OSM_PHYS, OSM_SIZE);
	natural_t last[8][CPU_STATE_MAX];
	bool seen[8] = { false };
	uint32_t row = GOV_TOP, written = ~0u, hold = 0, min_row = 0, periods = 0, at_top = 0, load_sum = 0, peak = 0;
	uint64_t since = mach_absolute_time();

	PE_parse_boot_argn("cpu_gov_min", &min_row, sizeof(min_row));
	min_row = min_row > GOV_TOP ? GOV_TOP : min_row;
	bzero(last, sizeof(last));
	/*
	 * Not before the system is up (the first run, starting at once, stopped the boot before the panel's HUD): 60 s,
	 * the Gold cores up by then (they come up ~57 s in), and Gold's rows written only once a Gold core has said so
	 * (osmc=, osfmk/arm/arm_init.c): its OSM is not written while that cluster is off
	 */
	delay_for_interval(60, NSEC_PER_SEC);
	/*
	 * The second run rebooted the phone as the governor began: Gold's OSM written from a Silver core. Linux's driver
	 * and osmc= (which worked) write a cluster's requests from that cluster's own cores; so does this now. Which
	 * processor is which cluster: each one's MPIDR (Aff1 1: Gold), read on it once.
	 */
	int gold_cpu = -1, silver_cpu = -1;

	/*
	 * cpu_gov=2 rebooted the phone too, about 15 s after it began, nothing written: so it is the measuring or the
	 * moving between processors. With cpu_gov=2 each step now says itself on the panel's CPU line first and waits:
	 * 20 s of measuring the load alone, then each processor in turn, 3 s before and 2 s after moving there.
	 */
	if (mode == 2) {
		for (int i = 0; i < 20; i++) {
			uint32_t got = 0;

			for (int cpu = 0; cpu < 8; cpu++) {
				processor_t processor = cpu_to_processor(cpu);
				struct processor_cpu_load_info info;
				mach_msg_type_number_t count = PROCESSOR_CPU_LOAD_INFO_COUNT;
				host_t host;

				if (processor != PROCESSOR_NULL &&
				    processor_info(processor, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)&info, &count) == KERN_SUCCESS) {
					got |= 1u << cpu;
				}
			}
			redwood_status(REDWOOD_STATUS_CPU, "gov test 1: measuring, %d s; processors %#x", i, got);
			delay_for_interval(1, NSEC_PER_SEC);
		}
	}
	for (int cpu = 0; cpu < 8; cpu++) {
		processor_t processor = cpu_to_processor(cpu);
		uint64_t cluster;

		if (processor == PROCESSOR_NULL) {
			continue;
		}
		if (mode == 2) {
			redwood_status(REDWOOD_STATUS_CPU, "gov test 2: moving to processor %d", cpu);
			delay_for_interval(3, NSEC_PER_SEC);
		}
		thread_bind(processor);
		thread_block(THREAD_CONTINUE_NULL);
		cluster = (__builtin_arm_rsr64("MPIDR_EL1") >> 8) & 0xff;
		if (mode == 2) {
			redwood_status(REDWOOD_STATUS_CPU, "gov test 2: on processor %d, MPIDR %#llx", cpu,
			    __builtin_arm_rsr64("MPIDR_EL1") & 0xffff);
			delay_for_interval(2, NSEC_PER_SEC);
		}
		if (cluster == 1 && gold_cpu < 0) {
			gold_cpu = cpu;
		} else if (cluster == 0 && silver_cpu < 0) {
			silver_cpu = cpu;
		}
	}
	/* the governor itself on a Silver core, where Silver's requests are written; Gold's from a Gold one */
	thread_bind(silver_cpu >= 0 ? cpu_to_processor(silver_cpu) : PROCESSOR_NULL);
	thread_block(THREAD_CONTINUE_NULL);
	printf("cpu_gov: on processor %d (Silver); Gold's requests from processor %d\\n", silver_cpu, gold_cpu);
	if (silver_cpu < 0) {
		thread_terminate(current_thread());
	}
	printf("cpu_gov: the cores' rows follow the load every %u ms (top at %u%% busy, lowest row %u)\\n", GOV_PERIOD_MS,
	    GOV_UP_PERCENT, min_row);
	for (;;) {
		uint32_t load = 0;

		delay_for_interval(GOV_PERIOD_MS, NSEC_PER_MSEC);
		for (int cpu = 0; cpu < 8; cpu++) {
			processor_t processor = cpu_to_processor(cpu);
			struct processor_cpu_load_info info;
			mach_msg_type_number_t count = PROCESSOR_CPU_LOAD_INFO_COUNT;
			host_t host;
			uint32_t busy, total;

			if (processor == PROCESSOR_NULL ||
			    processor_info(processor, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)&info, &count) != KERN_SUCCESS) {
				continue;
			}
			busy = (info.cpu_ticks[CPU_STATE_USER] - last[cpu][CPU_STATE_USER]) +
			    (info.cpu_ticks[CPU_STATE_SYSTEM] - last[cpu][CPU_STATE_SYSTEM]);
			total = busy + (info.cpu_ticks[CPU_STATE_IDLE] - last[cpu][CPU_STATE_IDLE]);
			memcpy(last[cpu], info.cpu_ticks, sizeof(last[cpu]));
			if (seen[cpu] && total != 0 && busy * 100 / total > load) {
				load = busy * 100 / total;
			}
			seen[cpu] = true;
		}
		if (load >= GOV_UP_PERCENT) {
			row = GOV_TOP;
			hold = GOV_HOLD_PERIODS;
		} else if (hold > 0) {
			hold--;
		} else {
			uint32_t want = gov_silver_mhz[GOV_TOP] * load / GOV_UP_PERCENT, target = min_row;

			while (target < GOV_TOP && gov_silver_mhz[target] < want) {
				target++;
			}
			row = target >= row ? target : (row - target > 2 ? row - 2 : target);
		}
		/* written when it changes, and every second besides (a Gold core powered off and on again forgets its row) */
		if (mode != 2 && (row != written || periods % (1000 / GOV_PERIOD_MS) == 0)) {
			uint32_t gold = row > GOV_GOLD_TOP ? GOV_GOLD_TOP : row;

			bool gold_up = false;
			static uint32_t gold_written = ~0u;

			for (int core = 4; core < 8; core++) {
				gold_up = gold_up || redwood_osm_seen[core][5] != 0;
			}
			for (int core = 0; core < 4; core++) {
				*(volatile uint32_t *)(osm + OSM_SILVER + 0x920 + 4 * core) = row;
			}
			if (gold_up && gold_cpu >= 0 && (gold != gold_written || periods % (1000 / GOV_PERIOD_MS) == 0)) {
				thread_bind(cpu_to_processor(gold_cpu));
				thread_block(THREAD_CONTINUE_NULL);
				if (((__builtin_arm_rsr64("MPIDR_EL1") >> 8) & 0xff) == 1) {
					for (int core = 0; core < 4; core++) {
						*(volatile uint32_t *)(osm + OSM_GOLD + 0x920 + 4 * core) = gold;
					}
					__asm__ volatile ("dsb sy" ::: "memory");
					gold_written = gold;
				}
				thread_bind(cpu_to_processor(silver_cpu));
				thread_block(THREAD_CONTINUE_NULL);
			}
			__asm__ volatile ("dsb sy" ::: "memory");
			written = row;
		}
		periods++;
		at_top += row == GOV_TOP;
		load_sum += load;
		peak = load > peak ? load : peak;
		{
			uint64_t ns;

			absolutetime_to_nanoseconds(mach_absolute_time() - since, &ns);
			if (ns >= NSEC_PER_SEC) {
				redwood_status(REDWOOD_STATUS_CPU, "gov %u MHz; load %u%% (peak %u%%); top %u%% of the time",
				    gov_silver_mhz[row], load_sum / periods, peak, at_top * 100 / periods);
				periods = at_top = load_sum = peak = 0;
				since = mach_absolute_time();
			}
		}
	}
}""", """/*
 * The governor, second form (2026-11-11). Measuring each processor's load (processor_info, PROCESSOR_CPU_LOAD_INFO)
 * rebooted the phone at once, before anything was written (cpu_gov=2, the first step never said itself). So the load is
 * not measured: what the phone is doing is. A frame handed to the panel (MiniIOMobileFramebuffer's present()) or a touch
 * (redwood_touch_post()) stamps redwood_activity; within 400 ms of one, the top row; after that, a row down every 50 ms to
 * the lowest (cpu_gov_min, row 1 by default, 614 MHz). Nothing moves between processors.
 *
 * cpu_gov=2: a test of the writes alone, each step said on the panel's CPU line before it is taken, 4 s apart: Silver's
 * request written again as it is (row 7), Gold's again as it is (row 6, from whichever processor this runs on), then
 * Silver at row 3 for 10 s, then Gold at row 3 for 10 s. The last line seen before a reboot names the step.
 */
volatile uint64_t redwood_activity;     /* mach_absolute_time of the last frame handed to the panel or touch */

static void
gov_rows(vm_offset_t osm, int silver, int gold)
{
	bool gold_up = false;

	for (int core = 4; core < 8; core++) {
		gold_up = gold_up || redwood_osm_seen[core][5] != 0;
	}
	for (int core = 0; core < 4; core++) {
		if (silver >= 0) {
			*(volatile uint32_t *)(osm + OSM_SILVER + 0x920 + 4 * core) = (uint32_t)silver;
		}
		if (gold >= 0 && gold_up) {
			*(volatile uint32_t *)(osm + OSM_GOLD + 0x920 + 4 * core) = (uint32_t)gold;
		}
	}
	__asm__ volatile ("dsb sy" ::: "memory");
}

static void
gov_say(const char *step)
{
	redwood_status(REDWOOD_STATUS_CPU, "gov test %s (cpu %d, MPIDR %#llx)", step, cpu_number(),
	    __builtin_arm_rsr64("MPIDR_EL1") & 0xffff);
	printf("cpu_gov: test %s\\n", step);
	delay_for_interval(4, NSEC_PER_SEC);
}

static void
gov_thread(void *parameter, __unused wait_result_t result)
{
	uint32_t mode = (uint32_t)(uintptr_t)parameter;        /* 1: the rows follow what the phone does; 2: the test */
	vm_offset_t osm = ml_io_map(OSM_PHYS, OSM_SIZE);
	uint32_t row = GOV_TOP, written = ~0u, min_row = 1, periods = 0, at_top = 0;
	uint64_t since, quiet;

	PE_parse_boot_argn("cpu_gov_min", &min_row, sizeof(min_row));
	min_row = min_row > GOV_TOP ? GOV_TOP : min_row;
	nanoseconds_to_absolutetime(400 * NSEC_PER_MSEC, &quiet);
	/* not before the system is up and the Gold cores with it (~57 s) */
	delay_for_interval(60, NSEC_PER_SEC);
	if (mode == 2) {
		gov_say("A: running, nothing written yet");
		gov_say("B: Silver's request again, row 7");
		gov_rows(osm, GOV_TOP, -1);
		gov_say("B done; C: Gold's request again, row 6");
		gov_rows(osm, -1, GOV_GOLD_TOP);
		gov_say("C done; D: Silver at row 3 for 10 s");
		gov_rows(osm, 3, -1);
		delay_for_interval(10, NSEC_PER_SEC);
		gov_rows(osm, GOV_TOP, -1);
		gov_say("D done; E: Gold at row 3 for 10 s");
		gov_rows(osm, -1, 3);
		delay_for_interval(10, NSEC_PER_SEC);
		gov_rows(osm, -1, GOV_GOLD_TOP);
		gov_say("E done: all steps passed");
		thread_terminate(current_thread());
	}
	printf("cpu_gov: the top row within 400 ms of a frame or a touch, down to row %u otherwise\\n", min_row);
	since = mach_absolute_time();
	for (;;) {
		uint64_t now, ns;

		delay_for_interval(GOV_PERIOD_MS, NSEC_PER_MSEC);
		now = mach_absolute_time();
		if (now - redwood_activity < quiet) {
			row = GOV_TOP;
		} else if (row > min_row) {
			row--;
		}
		/* written when it changes, and every second besides (a Gold core powered off and on again forgets its row) */
		if (row != written || periods % (1000 / GOV_PERIOD_MS) == 0) {
			gov_rows(osm, (int)row, (int)(row > GOV_GOLD_TOP ? GOV_GOLD_TOP : row));
			written = row;
		}
		periods++;
		at_top += row == GOV_TOP;
		absolutetime_to_nanoseconds(now - since, &ns);
		if (ns >= NSEC_PER_SEC) {
			redwood_status(REDWOOD_STATUS_CPU, "gov %u MHz now; at the top %u%% of the last second", gov_silver_mhz[row],
			    at_top * 100 / periods);
			periods = at_top = 0;
			since = now;
		}
	}
}""")
sub1('xnu/files/bsd/dev/redwood_input.c', """void
redwood_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{
""", """extern volatile uint64_t redwood_activity;     /* bsd/dev/redwood_osm.c (cpu_gov): the last frame or touch */

void
redwood_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{
	redwood_activity = mach_absolute_time();
""")
sub1(FBF, """IOMobileFramebuffer::present(const uint8_t * swap)
{
""", """IOMobileFramebuffer::present(const uint8_t * swap)
{
	redwood_activity = mach_absolute_time();        /* (cpu_gov: the phone is drawing) */
""")
sub1(FBF, """extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" void flush_dcache(vm_offset_t addr, unsigned count, int phys);
""", """extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" void flush_dcache(vm_offset_t addr, unsigned count, int phys);
extern "C" volatile uint64_t redwood_activity;  /* bsd/dev/redwood_osm.c (cpu_gov): the last frame or touch */
""")

# cpu_gov=1, first run (2026-11-11): at rest on the home screen it stayed at the top all the time -- the home screen
# hands the panel ~9 frames a second even when nothing moves, and each frame counted as activity. Now a touch keeps the
# top for 400 ms, and frames only when they come at 20 a second or more (5 in the last 250 ms): something is moving
sub1(OSM, """volatile uint64_t redwood_activity;     /* mach_absolute_time of the last frame handed to the panel or touch */
""", """volatile uint64_t redwood_activity;     /* mach_absolute_time of the last touch */
volatile uint32_t redwood_frames;       /* frames handed to the panel (MiniIOMobileFramebuffer's present()), counted */
""")
sub1(OSM, """	uint32_t row = GOV_TOP, written = ~0u, min_row = 1, periods = 0, at_top = 0;
""", """	uint32_t row = GOV_TOP, written = ~0u, min_row = 1, periods = 0, at_top = 0, frames[5] = { 0 }, slot = 0;
""")
sub1(OSM, """		now = mach_absolute_time();
		if (now - redwood_activity < quiet) {
			row = GOV_TOP;""", """		now = mach_absolute_time();
		/* frames in the last 250 ms: the count now against the one five periods ago */
		uint32_t count = redwood_frames, moving = count - frames[slot];

		frames[slot] = count;
		slot = (slot + 1) % 5;
		if (now - redwood_activity < quiet || moving >= 5) {
			row = GOV_TOP;""")
sub1(OSM, """			redwood_status(REDWOOD_STATUS_CPU, "gov %u MHz now; at the top %u%% of the last second", gov_silver_mhz[row],
			    at_top * 100 / periods);""", """			redwood_status(REDWOOD_STATUS_CPU, "gov %u MHz now; at the top %u%% of the last second", gov_silver_mhz[row],
			    at_top * 100 / periods);""")
sub1(FBF, """	redwood_activity = mach_absolute_time();        /* (cpu_gov: the phone is drawing) */
""", """	redwood_frames++;                               /* (cpu_gov: frames handed over, counted) */
""")
sub1(FBF, """extern "C" volatile uint64_t redwood_activity;  /* bsd/dev/redwood_osm.c (cpu_gov): the last frame or touch */
""", """extern "C" volatile uint32_t redwood_frames;    /* bsd/dev/redwood_osm.c (cpu_gov): frames handed to the panel */
""")

# doha, battery (2026-11-11): the battery's current steady enough to compare runs -- sampled every second (the gauge's
# last reading, QG 0xC2) into a ring of 30, shown with the instant one; and its scale by the gauge's subtype, as
# qg_iraw_to_ua does: subtype 3 (QG_ADC_IBAT_5A) 152.588 uA a step, otherwise 305.176 (before, 305.176 always). The
# panel's Wi-Fi line drops the fields read once (C, L, P, T) to make room
sub1(BTN, """static uint32_t pets;
""", """static uint32_t pets;
static int32_t current_ring[30];        /* the battery's current, mA (> 0 out of the battery), one a second */
static uint32_t current_count, current_next;
static uint8_t gauge_subtype = 0xff;
static const char *spmi_read(const struct peripheral *p, uint8_t reg, uint8_t *bytes, uint32_t count);

/* The gauge's last current reading, in mA (> 0: out of the battery); 0 if it does not answer */
static int32_t
current_now(void)
{
	uint8_t ia[2] = { 0, 0 };

	if (gauge_subtype == 0xff && spmi_read(&qg, 0x05, &gauge_subtype, 1) != NULL) {
		gauge_subtype = 0xff;
	}
	if (spmi_read(&qg, 0xc2, ia, 2) != NULL) {
		return 0;
	}
	return (int32_t)((int64_t)(int16_t)((uint16_t)ia[0] | (uint16_t)ia[1] << 8) *
	    (gauge_subtype == 3 ? 152588 : 305176) / 1000000);
}

static void
current_sample(void)
{
	current_ring[current_next] = current_now();
	current_next = (current_next + 1) % 30;
	current_count += current_count < 30;
}

static int32_t
current_average(void)
{
	int64_t sum = 0;

	for (uint32_t i = 0; i < current_count; i++) {
		sum += current_ring[i];
	}
	return current_count ? (int32_t)(sum / current_count) : 0;
}
""")
sub1(BTN, """		if (battery_direct && tick % (5000 / POLL_MS) == 0) {
			battery_look();
		}
""", """		if (battery_direct && tick % (1000 / POLL_MS) == 0) {
			current_sample();
		}
		if (battery_direct && tick % (5000 / POLL_MS) == 0) {
			battery_look();
		}
""")
sub1(BTN, """		redwood_status(REDWOOD_STATUS_WIFI, "chg%s S%02x/%02x E%02x C%02x U%02x L%02x P%02x W%02x/%02x T%02x I%lldmA",
		    pet_stopped ? "!" : pets != 0 ? "+" : "", st[0], st[1], en, cfg2, il, icl, pp, wd[0], wd[2], sub, ma);""",
     """		(void)cfg2;
		(void)icl;
		(void)pp;
		(void)ma;
		redwood_status(REDWOOD_STATUS_WIFI, "chg%s S%02x/%02x E%02x U%02x W%02x/%02x I%d avg %dmA/%us",
		    pet_stopped ? "!" : pets != 0 ? "+" : "", st[0], st[1], en, il, wd[0], wd[2], current_now(), current_average(),
		    current_count);""")

# doha, "bltest=1" (2026-11-11): iOS's brightness does nothing on doha, whose panel takes its brightness as a DCS command
# (doha's dsi-panel-ft8719-tm-fhd-video.dtsi: bl_ctrl_dcs, levels 1 to 4095, two bytes), not from a PMIC's WLED as
# miatoll's. Qualcomm's DisplayDxe has a protocol for it (QcomPkg EFIDisplayPwrCtrl.h, EFI_DISPLAYPWRCTRL_PROTOCOL_GUID):
# the backlight's level in percent, set and read. The test: whether the UEFI has it, the level it reads, then 20% for
# 3 s, 60% for 3 s, and the level read at first again; 15 s to read the screen
sub1(L, """				print("lastpanic=1: %d characters shown; 30 s to read this\\n", shown);
				BS->stall(30000000);
				break;
			}
		}
""", """				print("lastpanic=1: %d characters shown; 30 s to read this\\n", shown);
				BS->stall(30000000);
				break;
			}
		}
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "bltest=1") && (c == pi.cmdline || c[-1] == ' ')) {
				static const efi_guid pwr_guid = { 0x7bfa4293, 0x7aa4, 0x4375, { 0xb6, 0x3c, 0xb6, 0xaa, 0xb7, 0x86, 0xc4, 0x3c } };
				struct {
					uint64_t revision;
					efi_status (EFIAPI *panel_power)(uint32_t display, uint32_t state);
					efi_status (EFIAPI *panel_power_status)(uint32_t display, uint32_t *state);
					efi_status (EFIAPI *set_level)(uint32_t display, uint32_t percent);
					efi_status (EFIAPI *get_level)(uint32_t display, uint32_t *percent);
				} *pwr = NULL;
				uint32_t level = 0, now = 0;
				efi_status s;

				s = BS->locate_protocol(&pwr_guid, NULL, (void **)&pwr);
				if (EFI_ERROR(s) || pwr == NULL) {
					print("bltest=1: no display power control protocol (%x)\\n", (uint64_t)s);
					BS->stall(15000000);
					break;
				}
				s = pwr->get_level(0, &level);
				print("bltest=1: display power control, revision %x; the backlight at %d%% (%x)\\n", pwr->revision,
				    (uint64_t)level, (uint64_t)s);
				BS->stall(2000000);
				s = pwr->set_level(0, 20);
				pwr->get_level(0, &now);
				print("bltest=1: 20%%: %x, reads %d%%; 3 s\\n", (uint64_t)s, (uint64_t)now);
				BS->stall(3000000);
				s = pwr->set_level(0, 60);
				pwr->get_level(0, &now);
				print("bltest=1: 60%%: %x, reads %d%%; 3 s\\n", (uint64_t)s, (uint64_t)now);
				BS->stall(3000000);
				s = pwr->set_level(0, level ? level : 100);
				pwr->get_level(0, &now);
				print("bltest=1: back to %d%%: %x, reads %d%%; 15 s to read this\\n", (uint64_t)(level ? level : 100),
				    (uint64_t)s, (uint64_t)now);
				BS->stall(15000000);
				break;
			}
		}
""")

# doha, "dcstest=1" (2026-11-11): the UEFI has no display power control protocol (bltest=1: EFI_NOT_FOUND), so the
# brightness command is sent as Linux's msm DSI driver sends a command while the panel runs in video mode (mainline
# dsi_host.c: msm_dsi_host_xfer_prepare(), dsi_cmd_dma_add(), msm_dsi_host_cmd_xfer_commit()): the DCS command
# "write display brightness" (0x51) with doha's two bytes (dsi-panel-ft8719-tm-fhd-video.dtsi: bl_ctrl_dcs, levels 1 to
# 4095, qcom,bklt-dcs-2bytes-0xff0f: the level's high 8 bits, then its low 4) in MSM's format in a page of the loader's,
# the controller's command engine on for it, DMA_BASE, DMA_LEN, TRIG_DMA, and CMD_DMA_DONE awaited. The DSI controller:
# 0x5E94000 (doha's trinket-sde.dtsi, dsi_ctrl), its 6G registers 4 bytes on from the version register. The test: level
# 400 for 3 s, 1600 for 3 s, then 4095
sub1(L, """				print("bltest=1: back to %d%%: %x, reads %d%%; 15 s to read this\\n", (uint64_t)(level ? level : 100),
				    (uint64_t)s, (uint64_t)now);
				BS->stall(15000000);
				break;
			}
		}
""", """				print("bltest=1: back to %d%%: %x, reads %d%%; 15 s to read this\\n", (uint64_t)(level ? level : 100),
				    (uint64_t)s, (uint64_t)now);
				BS->stall(15000000);
				break;
			}
		}
		for (const char *c = pi.cmdline; *c; c++) {
			if (starts_with(c, "dcstest=1") && (c == pi.cmdline || c[-1] == ' ')) {
				volatile uint32_t *dsi = (volatile uint32_t *)(uintptr_t)0x05E94000ULL;
				uint64_t page = 0xFFFFFFFFULL;
				static const uint32_t levels[3] = { 400, 1600, 4095 };

				print("dcstest=1: DSI version %x, CTRL %x, STATUS0 %x, CMD_DMA_CTRL %x, INTR_CTRL %x\\n", (uint64_t)dsi[0],
				    (uint64_t)dsi[0x04 / 4], (uint64_t)dsi[0x08 / 4], (uint64_t)dsi[0x3c / 4], (uint64_t)dsi[0x110 / 4]);
				if (EFI_ERROR(BS->allocate_pages(AllocateMaxAddress, EfiLoaderData, 1, &page))) {
					print("dcstest=1: no page below 4 GB\\n");
					BS->stall(15000000);
					break;
				}
				BS->stall(3000000);
				for (int k = 0; k < 3; k++) {
					volatile uint8_t *b = (volatile uint8_t *)(uintptr_t)page;
					uint32_t ctrl = dsi[0x04 / 4], intr, waited = 0;

					/* MSM's format: word count (3, two bytes), data type (0x39, DCS long write), last | long; then 51 hi lo, 0xff */
					b[0] = 3;
					b[1] = 0;
					b[2] = 0x39;
					b[3] = 0x80 | 0x40;
					b[4] = 0x51;
					b[5] = (uint8_t)(levels[k] >> 4);
					b[6] = (uint8_t)(levels[k] & 0x0f);
					b[7] = 0xff;
					flush_dcache(page, page + 64);
					dsi[0x04 / 4] = ctrl | 0x4 | 0x1;                    /* CMD_MODE_EN, ENABLE */
					dsi[0x110 / 4] = dsi[0x110 / 4] | 0x1;               /* CMD_DMA_DONE cleared (written 1) */
					__asm__ volatile ("dsb sy" ::: "memory");
					dsi[0x48 / 4] = (uint32_t)page;                      /* DMA_BASE */
					dsi[0x4c / 4] = 8;                                   /* DMA_LEN */
					__asm__ volatile ("dsb sy" ::: "memory");
					dsi[0x90 / 4] = 1;                                   /* TRIG_DMA */
					__asm__ volatile ("dsb sy" ::: "memory");
					while (!((intr = dsi[0x110 / 4]) & 0x1) && waited < 100) {
						BS->stall(1000);
						waited++;
					}
					dsi[0x110 / 4] = intr | 0x1;
					dsi[0x04 / 4] = ctrl;
					__asm__ volatile ("dsb sy" ::: "memory");
					print("dcstest=1: level %d: %s after %d ms (INTR_CTRL %x, STATUS0 %x); 3 s\\n", (uint64_t)levels[k],
					    (intr & 0x1) ? "sent" : "NOT done", (uint64_t)waited, (uint64_t)intr, (uint64_t)dsi[0x08 / 4]);
					BS->stall(3000000);
				}
				BS->free_pages(page, 1);
				print("dcstest=1: 15 s to read this\\n");
				BS->stall(15000000);
				break;
			}
		}
""")

# dcstest=1, second run (2026-11-11): the three commands were "sent" (CMD_DMA_DONE in 6-13 ms) and the panel did not
# change. They went in low power (CMD_DMA_CTRL 0x14000000: LOW_POWER on, as the UEFI left it); Motorola's driver sends
# the brightness without MIPI_DSI_MSG_USE_LPM, so msm_dsi_host_xfer_prepare() clears LOW_POWER and it goes at high speed,
# which a panel in video mode takes between lines. The bytes were right (dsi_panel.c: with 0xff0f the level becomes
# (low 4 bits << 8) | (level >> 4), and mipi_dsi_dcs_set_display_brightness() sends its low byte first). Now at high speed
sub1(L, """					dsi[0x04 / 4] = ctrl | 0x4 | 0x1;                    /* CMD_MODE_EN, ENABLE */""",
     """					uint32_t dma_ctrl = dsi[0x3c / 4];

					dsi[0x3c / 4] = dma_ctrl & ~(1u << 26);              /* high speed (CMD_DMA_CTRL's LOW_POWER off) */
					dsi[0x04 / 4] = ctrl | 0x4 | 0x1;                    /* CMD_MODE_EN, ENABLE */""")
sub1(L, """					dsi[0x110 / 4] = intr | 0x1;
					dsi[0x04 / 4] = ctrl;""", """					dsi[0x110 / 4] = intr | 0x1;
					dsi[0x04 / 4] = ctrl;
					dsi[0x3c / 4] = dma_ctrl;""")

# backlight=1, doha (2026-11-11): iOS's brightness slider sets the panel's -- the service CoreBrightness looks for
# (AppleARMBacklight, as the Mi 9's HakiOS port has it) and the DCS brightness command over DSI at high speed (the loader's
# dcstest=1 found it changes the panel), in iokit/Kernel/MiniIOMobileFramebuffer.cpp, started with the framebuffer
sub1(FBF, """/*
 * fb_flip=1: wait (25 ms at most) until the scan after the flush has begun: the DSI interface's frame counter has moved
""", """/*
 * The brightness of doha's screen, and the slider of iOS that sets it (backlight=1, device=doha).
 *
 * The panel (doha's dsi-panel-ft8719-tm-fhd-video.dtsi) takes its brightness as a DCS command, bl_ctrl_dcs, levels 1 to
 * 4095 in two bytes (qcom,bklt-dcs-2bytes-0xff0f: Motorola's dsi_panel.c sends level >> 4, then level & 0xf): the DSI
 * packet "DCS long write" (0x39) of 0x51 and those two bytes. It is sent as Linux's msm DSI driver sends a command
 * while a video-mode panel runs (mainline dsi_host.c): the packet in MSM's layout in memory of ours below 4 GB, the
 * controller's command engine on for it (CTRL's CMD_MODE_EN), high speed (CMD_DMA_CTRL's LOW_POWER off: in low power
 * the panel ignored it, the loader's dcstest=1 found), DMA_BASE, DMA_LEN, TRIG_DMA, CMD_DMA_DONE awaited (50 ms at
 * most) and cleared, CTRL and CMD_DMA_CTRL put back. The DSI controller: 0x5E94000 (doha's trinket-sde.dtsi), version
 * 2.3.0, its registers 4 bytes on from the version's. A command not done in time ends the writes for the run.
 *
 * iOS: CoreBrightness (backboardd) looks for the service with "backlight-control" = true that is an AppleARMBacklight,
 * reads its range from "IODisplayParameters" = { brightness = { min, max, value } } and sets a brightness with
 * IORegistryEntrySetCFProperties(service, { brightness = n, FadePeriod = t, ... }) -- the way the Mi 9's HakiOS port
 * (not-exyy/ios-cepheus, drivers/gpu/hakios.backlight.cpp) found it, whose service this one follows. Here n is the
 * panel's level itself, BACKLIGHT_MIN..4095; a fade is done in steps of 16 ms.
 */
#include <IOKit/IOPlatformExpert.h>

#define DSI_PHYS                0x05E94000ull
#define DSI_CTRL                (0x04 / 4)
#define DSI_CMD_DMA_CTRL        (0x3c / 4)
#define DSI_DMA_BASE            (0x48 / 4)
#define DSI_DMA_LEN             (0x4c / 4)
#define DSI_TRIG_DMA            (0x90 / 4)
#define DSI_INTR_CTRL           (0x110 / 4)
#define BACKLIGHT_MIN           24              /* the least iOS may set: dim, never dark */
#define BACKLIGHT_MAX           4095

static TUNABLE(uint32_t, gBacklight, "backlight", 0);
static TUNABLE(uint32_t, gBacklightStart, "backlight_default", 2400);   /* the level iOS is told the panel is at */

static volatile uint32_t * gDsi;
static IOBufferMemoryDescriptor * gDcsBuffer;
static uint64_t gDcsPhys;
static IOLock * gDcsLock;
static bool gDcsGaveUp;
static uint32_t gDcsSent, gDcsLevel = BACKLIGHT_MAX;

/* The panel to `level` (1..4095); false once a command has not been done (and none is sent again in this run). */
static bool
dcsBrightness(uint32_t level)
{
	volatile uint8_t * b;
	uint32_t ctrl, dmaCtrl, intr = 0;
	uint64_t t0, limit;

	if (gDsi == NULL || gDcsBuffer == NULL || gDcsGaveUp) {
		return false;
	}
	IOLockLock(gDcsLock);
	b = (volatile uint8_t *) gDcsBuffer->getBytesNoCopy();
	b[0] = 3;                               /* word count, two bytes */
	b[1] = 0;
	b[2] = 0x39;                            /* DCS long write */
	b[3] = 0x80 | 0x40;                     /* last, long */
	b[4] = 0x51;                            /* write display brightness */
	b[5] = (uint8_t) (level >> 4);
	b[6] = (uint8_t) (level & 0x0f);
	b[7] = 0xff;
	flush_dcache((vm_offset_t) b, 64, 0);
	ctrl = gDsi[DSI_CTRL];
	dmaCtrl = gDsi[DSI_CMD_DMA_CTRL];
	gDsi[DSI_CMD_DMA_CTRL] = dmaCtrl & ~(1u << 26);
	gDsi[DSI_CTRL] = ctrl | 0x4 | 0x1;
	gDsi[DSI_INTR_CTRL] = gDsi[DSI_INTR_CTRL] | 0x1;
	__asm__ volatile ("dsb sy" ::: "memory");
	gDsi[DSI_DMA_BASE] = (uint32_t) gDcsPhys;
	gDsi[DSI_DMA_LEN] = 8;
	__asm__ volatile ("dsb sy" ::: "memory");
	gDsi[DSI_TRIG_DMA] = 1;
	__asm__ volatile ("dsb sy" ::: "memory");
	nanoseconds_to_absolutetime(50 * NSEC_PER_MSEC, &limit);
	t0 = mach_absolute_time();
	while (!((intr = gDsi[DSI_INTR_CTRL]) & 0x1) && mach_absolute_time() - t0 < limit) {
		delay(100);
	}
	gDsi[DSI_INTR_CTRL] = intr | 0x1;
	gDsi[DSI_CTRL] = ctrl;
	gDsi[DSI_CMD_DMA_CTRL] = dmaCtrl;
	__asm__ volatile ("dsb sy" ::: "memory");
	if (!(intr & 0x1)) {
		gDcsGaveUp = true;
		IOLog("MiniIOMobileFramebuffer: backlight: the command for level %u was not done in 50 ms (INTR_CTRL %#x): "
		    "no more brightness commands in this run\\n", level, intr);
	} else {
		gDcsSent++;
		gDcsLevel = level;
	}
	IOLockUnlock(gDcsLock);
	return (intr & 0x1) != 0;
}

/* A fade towards a level, one step every 16 ms, on a thread call (setProperties() must not wait for it) */
static thread_call_t gFadeCall;
static uint32_t gFadeFrom, gFadeTo, gFadeSteps, gFadeStep;

static void
fadeStep(thread_call_param_t, thread_call_param_t)
{
	uint32_t level;
	uint64_t deadline;

	if (gFadeStep >= gFadeSteps) {
		return;
	}
	gFadeStep++;
	level = gFadeFrom + (uint32_t) (((int64_t) gFadeTo - (int64_t) gFadeFrom) * (int64_t) gFadeStep / (int64_t) gFadeSteps);
	if (dcsBrightness(level) && gFadeStep < gFadeSteps) {
		clock_interval_to_deadline(16, kMillisecondScale, &deadline);
		thread_call_enter_delayed(gFadeCall, deadline);
	}
}

static void
backlightRequest(uint32_t value, uint32_t fadeMs)
{
	uint32_t level = value < BACKLIGHT_MIN ? BACKLIGHT_MIN : value > BACKLIGHT_MAX ? BACKLIGHT_MAX : value;

	/*
	 * Never sent from here: setProperties() is backboardd's own thread, and a command takes the controller up to a
	 * frame (13 ms seen); while the slider was dragged those waits held backboardd up, and the screen stuttered and
	 * now and then went black with the spinner (2026-11-11). The thread call sends, the newest request replacing any
	 * fade under way.
	 */
	if (gFadeCall == NULL) {
		return;
	}
	thread_call_cancel(gFadeCall);
	gFadeFrom = gDcsLevel;
	gFadeTo = level;
	gFadeSteps = fadeMs < 32 ? 1 : (fadeMs / 16 > 60 ? 60 : fadeMs / 16);
	gFadeStep = 0;
	thread_call_enter(gFadeCall);
}

class AppleARMBacklight : public IOService
{
	OSDeclareDefaultStructors(AppleARMBacklight);

public:
	virtual IOReturn setProperties(OSObject * properties) APPLE_KEXT_OVERRIDE;
	void parameters(uint32_t value);
	unsigned told;
};

OSDefineMetaClassAndStructors(AppleARMBacklight, IOService);

/* IODisplayParameters = { brightness = { min, max, value } } */
void
AppleARMBacklight::parameters(uint32_t value)
{
	OSDictionary * outer = OSDictionary::withCapacity(1), * brightness = OSDictionary::withCapacity(3);
	OSNumber * lo = OSNumber::withNumber(BACKLIGHT_MIN, 32), * hi = OSNumber::withNumber(BACKLIGHT_MAX, 32);
	OSNumber * now = OSNumber::withNumber(value, 32);

	if (outer != NULL && brightness != NULL && lo != NULL && hi != NULL && now != NULL) {
		brightness->setObject("min", lo);
		brightness->setObject("max", hi);
		brightness->setObject("value", now);
		outer->setObject("brightness", brightness);
		setProperty("IODisplayParameters", outer);
	}
	OSSafeReleaseNULL(now);
	OSSafeReleaseNULL(hi);
	OSSafeReleaseNULL(lo);
	OSSafeReleaseNULL(brightness);
	OSSafeReleaseNULL(outer);
}

/* a number from what user space gave: an integer, or a dictionary { value = n } */
static bool
backlightNumber(OSObject * object, uint32_t * out)
{
	OSNumber * n = OSDynamicCast(OSNumber, object);
	OSDictionary * d = OSDynamicCast(OSDictionary, object);

	if (n == NULL && d != NULL) {
		n = OSDynamicCast(OSNumber, d->getObject("value"));
	}
	if (n == NULL) {
		return false;
	}
	*out = n->unsigned32BitValue();
	return true;
}

IOReturn
AppleARMBacklight::setProperties(OSObject * properties)
{
	OSDictionary * dict = OSDynamicCast(OSDictionary, properties);
	uint32_t value = 0, fade = 0;

	if (dict == NULL) {
		return kIOReturnBadArgument;
	}
	if (!backlightNumber(dict->getObject("brightness"), &value)) {
		return kIOReturnSuccess;
	}
	backlightNumber(dict->getObject("FadePeriod"), &fade);
	if (told < 8) {
		told++;
		IOLog("MiniIOMobileFramebuffer: backlight: iOS asks for %u (fade %u)\\n", value, fade);
	}
	value = value > BACKLIGHT_MAX ? BACKLIGHT_MAX : value;
	parameters(value);
	backlightRequest(value, fade);
	return kIOReturnSuccess;
}

/* backlight=1 on doha: the DSI controller mapped, a page for the command, and the service iOS looks for */
static void
redwoodBacklightStart(void)
{
	char device[16] = "";
	AppleARMBacklight * made;
	IOService * platform;

	if (gBacklight == 0 || !PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "doha") != 0) {
		return;
	}
	gDcsLock = IOLockAlloc();
	gDsi = (volatile uint32_t *) ml_io_map(DSI_PHYS, 0x1000);
	gDcsBuffer = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
	    kIODirectionInOut | kIOMemoryPhysicallyContiguous, 4096, 0xfffff000ull);
	gFadeCall = thread_call_allocate(fadeStep, NULL);
	if (gDcsLock == NULL || gDsi == NULL || gDcsBuffer == NULL) {
		IOLog("MiniIOMobileFramebuffer: backlight: no DSI registers or no page for the command\\n");
		gDsi = NULL;
		return;
	}
	gDcsPhys = gDcsBuffer->getPhysicalAddress();
	IOLog("MiniIOMobileFramebuffer: backlight: DSI version %#x, CTRL %#x, CMD_DMA_CTRL %#x; the command's page at %#llx\\n",
	    gDsi[0], gDsi[DSI_CTRL], gDsi[DSI_CMD_DMA_CTRL], gDcsPhys);
	if (gBacklightStart >= BACKLIGHT_MIN && gBacklightStart <= BACKLIGHT_MAX) {
		dcsBrightness(gBacklightStart);
	}
	made = OSTypeAlloc(AppleARMBacklight);
	if ((platform = IOService::getPlatform()) == NULL || made == NULL || !made->init()) {
		OSSafeReleaseNULL(made);
		return;
	}
	made->setProperty("backlight-control", kOSBooleanTrue);
	made->parameters(gDcsLevel);
	if (!made->attach(platform)) {
		made->release();
		return;
	}
	made->setName("AppleARMBacklight");
	if (!made->start(platform)) {
		made->detach(platform);
		made->release();
		return;
	}
	made->registerService();
	IOLog("MiniIOMobileFramebuffer: backlight: AppleARMBacklight registered, the panel at %u\\n", gDcsLevel);
}

/*
 * fb_flip=1: wait (25 ms at most) until the scan after the flush has begun: the DSI interface's frame counter has moved
""")
sub1(FBF, """extern "C" volatile uint32_t redwood_frames;    /* bsd/dev/redwood_osm.c (cpu_gov): frames handed to the panel */
""", """extern "C" volatile uint32_t redwood_frames;    /* bsd/dev/redwood_osm.c (cpu_gov): frames handed to the panel */
static void redwoodBacklightStart(void);        /* backlight=1 (doha): below */
""")
sub1(FBF, """	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
""", """	redwoodBacklightStart();
	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
""")

# The modem on doha (2026-11-11), step 1 of the Wi-Fi: willow's bsd/dev/redwood_mss.c (the same SoC and the same
# reserved memory: doha's trinket.dtsi has modem_region 0x4b000000, 0x7e00000, and SMEM 0x46000000 as willow's) let run
# with device=doha. doha's partitions are slotted: the modem's image in modem_a (willow: "modem"), its file system's
# fsg_a (willow: "fsg"); modemst1, modemst2 and fsc are named as willow's. And as doha has no console to read, the last
# line the driver says goes onto the panel's Sound line (no sound driver yet), the line before a STOP kept with it.
MSS = 'xnu/files/bsd/dev/redwood_mss.c'
sub1(MSS, """static uint32_t mss_step, step;
static bool modem_started;             /* TrustZone has let it out of reset (step 7) */
""", """static uint32_t mss_step, step;
static bool modem_started;             /* TrustZone has let it out of reset (step 7) */
static const char *mss_modem_partition = "modem";      /* doha: "modem_a" (redwood_mss_init()) */

/* doha: every line said also onto the panel's Sound line (the modem has no screen of its own to say it on) */
static char mss_last[200];

static int
mss_say(const char *format, ...)
{
	char line[300];
	va_list list;
	size_t length;
	int n;

	va_start(list, format);
	n = vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	printf("%s", line);
	length = strlen(line);
	if (length > 0 && line[length - 1] == '\\n') {
		line[length - 1] = 0;
	}
	if (strnstr(line, "STOP", sizeof(line)) == NULL && strncmp(line, "mss: done", 9) != 0) {
		strlcpy(mss_last, strncmp(line, "mss: ", 5) == 0 ? line + 5 : line, sizeof(mss_last));
		redwood_status(REDWOOD_STATUS_SOUND, "modem %.52s", mss_last);
	}
	return n;
}
#define printf mss_say
""")
sub1(MSS, """	return redwood_ufs_read_named("modem", offset, to, length, NULL);""",
     """	return redwood_ufs_read_named(mss_modem_partition, offset, to, length, NULL);""")
sub1(MSS, """	if ((error = redwood_ufs_read_named("modem", 0, NULL, 0, &part_size)) != 0) {""",
     """	if ((error = redwood_ufs_read_named(mss_modem_partition, 0, NULL, 0, &part_size)) != 0) {""")
sub1(MSS, """		if (!steps[step]()) {
			printf("mss: %u: STOP: the step did not find what it needs\\n", step);
			break;
		}""", """		if (!steps[step]()) {
			printf("mss: %u: STOP: the step did not find what it needs\\n", step);
			redwood_status(REDWOOD_STATUS_SOUND, "modem STOP %u: %.44s", step, mss_last);
			break;
		}""")
sub1(MSS, """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) || strcmp(device, "willow") != 0 ||
	    !PE_parse_boot_argn("mss_step", &mss_step, sizeof(mss_step)) || mss_step == 0) {
		return;
	}""", """	if (!PE_parse_boot_arg_str("device", device, sizeof(device)) ||
	    (strcmp(device, "willow") != 0 && strcmp(device, "doha") != 0) ||
	    !PE_parse_boot_argn("mss_step", &mss_step, sizeof(mss_step)) || mss_step == 0) {
		return;
	}
	if (strcmp(device, "doha") == 0) {
		mss_modem_partition = "modem_a";
		for (unsigned f = 0; f < sizeof(rmtfs_files) / sizeof(rmtfs_files[0]); f++) {
			if (strcmp(rmtfs_files[f].partition, "fsg") == 0) {
				rmtfs_files[f].partition = "fsg_a";
			}
		}
	}""")

# doha's modem_a is ext4 (mss_step=2: "not the FAT16 this reads"): its image/ directory read by a small ext4 reader of
# our own (superblock, descriptors, inode, extents, directory entries; read only), behind willow's image_file() and
# file_read(), which the modem's steps and its TFTP use
sub1(MSS, """/* The entry of a directory (cluster 0: the root) with that 8.3 name""", """/*
 * doha: its modem partition (modem_a) is ext4, not willow's FAT16 (mss_step=2 on doha: "not the FAT16 this reads"; Lineage's
 * recovery mounts it as ext4, image/ in its root). So the files of its directory image are found and read here, read
 * only: the superblock (at 1024), the group descriptors, an inode, its extent tree (depth 0 in the inode, or index blocks
 * below it), and a directory's entries read through as a file. image_file() and file_read() take this way when ext.on;
 * a file's "first" is then its inode.
 */
static struct {
	bool on;
	uint32_t block, inode_size, inodes_per_group, desc_size, image_inode;
	bool is64;
	uint64_t gdt;
	uint8_t *leaf;                          /* the last extent block read, and which it was */
	uint64_t leaf_at;
} ext;

static uint32_t
ext_le32(const uint8_t *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint16_t
ext_le16(const uint8_t *p)
{
	return (uint16_t)(p[0] | p[1] << 8);
}

static bool
ext_open(void)
{
	uint8_t sb[1024];
	uint32_t incompat;

	if (part_read(1024, sb, sizeof(sb)) != 0 || ext_le16(sb + 0x38) != 0xef53) {
		printf("mss: %u: not ext4 either (magic %#x)\\n", step, ext_le16(sb + 0x38));
		return false;
	}
	ext.block = 1024u << ext_le32(sb + 0x18);
	ext.inodes_per_group = ext_le32(sb + 0x28);
	ext.inode_size = ext_le32(sb + 0x4c) >= 1 ? ext_le16(sb + 0x58) : 128;
	incompat = ext_le32(sb + 0x60);
	ext.is64 = (incompat & 0x80) != 0;
	ext.desc_size = ext.is64 && ext_le16(sb + 0xfe) >= 32 ? ext_le16(sb + 0xfe) : 32;
	ext.gdt = (uint64_t)(ext_le32(sb + 0x14) + 1) * ext.block;
	if (ext.block > 65536 || ext.inode_size < 128 || ext.inode_size > 1024 || ext.inodes_per_group == 0 || !(incompat & 0x40)) {
		printf("mss: %u: ext4 this does not read: %u-byte blocks, %u-byte inodes, features %#x\\n", step, ext.block,
		    ext.inode_size, incompat);
		return false;
	}
	ext.leaf = kalloc_data(ext.block, Z_WAITOK);
	if (ext.leaf == NULL) {
		return false;
	}
	ext.leaf_at = ~0ull;
	ext.on = true;
	printf("mss: %u: ext4: %u-byte blocks, %u inodes a group of %u bytes, descriptors of %u\\n", step, ext.block,
	    ext.inodes_per_group, ext.inode_size, ext.desc_size);
	return true;
}

/* inode n's first 160 bytes (enough for the size and the extent tree's root) */
static bool
ext_inode(uint32_t n, uint8_t inode[160])
{
	uint8_t desc[64];
	uint32_t group = (n - 1) / ext.inodes_per_group, index = (n - 1) % ext.inodes_per_group;
	uint64_t table;

	if (n == 0 || part_read(ext.gdt + (uint64_t)group * ext.desc_size, desc, ext.desc_size > 64 ? 64 : ext.desc_size) != 0) {
		return false;
	}
	table = ext_le32(desc + 8) | (ext.is64 ? (uint64_t)ext_le32(desc + 0x28) << 32 : 0);
	return part_read(table * ext.block + (uint64_t)index * ext.inode_size, inode, 160) == 0;
}

static uint64_t
ext_size(const uint8_t *inode)
{
	return ext_le32(inode + 4) | (uint64_t)ext_le32(inode + 0x6c) << 32;
}

/* the physical block of logical block `lb` of a file, and how many follow it in one piece; 0: a hole or an error */
static uint64_t
ext_map(const uint8_t *inode, uint32_t lb, uint32_t *run)
{
	const uint8_t *node = inode + 0x28;

	if (!(ext_le32(inode + 0x20) & 0x80000)) {
		return 0;                       /* not extents (this reads no block maps) */
	}
	for (int level = 0; level < 6; level++) {
		uint16_t entries = ext_le16(node + 2), depth = ext_le16(node + 6);

		if (ext_le16(node) != 0xf30a) {
			return 0;
		}
		if (depth == 0) {
			for (uint16_t i = 0; i < entries; i++) {
				const uint8_t *e = node + 12 + 12 * i;
				uint32_t first = ext_le32(e), length = ext_le16(e + 4);

				length = length > 32768 ? length - 32768 : length;
				if (lb >= first && lb < first + length) {
					*run = first + length - lb;
					return ((uint64_t)ext_le16(e + 6) << 32 | ext_le32(e + 8)) + (lb - first);
				}
			}
			return 0;
		}
		{
			const uint8_t *chosen = NULL;
			uint64_t at;

			for (uint16_t i = 0; i < entries; i++) {
				const uint8_t *e = node + 12 + 12 * i;

				if (ext_le32(e) <= lb) {
					chosen = e;
				}
			}
			if (chosen == NULL) {
				return 0;
			}
			at = ((uint64_t)ext_le16(chosen + 8) << 32 | ext_le32(chosen + 4)) * ext.block;
			if (at != ext.leaf_at) {
				if (part_read(at, ext.leaf, ext.block) != 0) {
					ext.leaf_at = ~0ull;
					return 0;
				}
				ext.leaf_at = at;
			}
			node = ext.leaf;
		}
	}
	return 0;
}

/* Bytes [offset, offset + length) of inode n's file, a piece of the disk at a time */
static int
ext_read(uint32_t n, uint64_t offset, void *to, uint64_t length)
{
	uint8_t inode[160];
	uint8_t *dst = to;

	if (!ext_inode(n, inode) || offset + length > ext_size(inode)) {
		return EIO;
	}
	while (length > 0) {
		uint32_t lb = (uint32_t)(offset / ext.block), within = (uint32_t)(offset % ext.block), run = 0;
		uint64_t pb = ext_map(inode, lb, &run), take = (uint64_t)run * ext.block - within;
		int error;

		take = take < length ? take : length;
		take = take < (4u << 20) ? take : (4u << 20);   /* (the storage's own buffer: 4 MB a request) */
		if (pb == 0) {
			if (run == 0) {
				take = ext.block - within < length ? ext.block - within : length;
			}
			bzero(dst, take);
		} else if ((error = part_read(pb * ext.block + within, dst, take)) != 0) {
			return error;
		}
		dst += take;
		offset += take;
		length -= take;
	}
	return 0;
}

/* The inode of `name` in directory `dir`; 0 if it is not there */
static uint32_t
ext_find(uint32_t dir, const char *name)
{
	uint8_t inode[160], *buffer;
	uint64_t size, at;
	uint32_t found = 0;
	size_t want = strlen(name);

	if (!ext_inode(dir, inode) || (size = ext_size(inode)) == 0 || size > (16u << 20) ||
	    (buffer = kalloc_data(ext.block, Z_WAITOK)) == NULL) {
		return 0;
	}
	for (at = 0; at < size && found == 0; at += ext.block) {
		uint32_t i = 0;

		if (ext_read(dir, at, buffer, ext.block) != 0) {
			break;
		}
		while (i + 8 <= ext.block) {
			uint32_t ino = ext_le32(buffer + i);
			uint16_t rec = ext_le16(buffer + i + 4);
			uint8_t len = buffer[i + 6];

			if (rec < 8 || i + rec > ext.block) {
				break;
			}
			if (ino != 0 && len == want && i + 8 + len <= ext.block && memcmp(buffer + i + 8, name, len) == 0) {
				found = ino;
				break;
			}
			i += rec;
		}
	}
	kfree_data(buffer, ext.block);
	return found;
}

/* The entry of a directory (cluster 0: the root) with that 8.3 name""")
sub1(MSS, """	if (!fat_open()) {
		return false;
	}
	if (!fat_find(0, "IMAGE      ", &e) || !(e.attributes & 0x10)) {
		printf("mss: %u: there is no directory IMAGE in its root\\n", step);
		return false;
	}
	fat.image_cluster = e.cluster | (uint32_t)e.cluster_high << 16;
	printf("mss: %u: IMAGE is a directory, from cluster %u\\n", step, fat.image_cluster);""", """	if (!fat_open()) {
		if (!ext_open()) {
			return false;
		}
		if ((ext.image_inode = ext_find(2, "image")) == 0) {
			printf("mss: %u: ext4: no directory image in its root\\n", step);
			return false;
		}
		printf("mss: %u: ext4: image is a directory, inode %u\\n", step, ext.image_inode);
	} else {
		if (!fat_find(0, "IMAGE      ", &e) || !(e.attributes & 0x10)) {
			printf("mss: %u: there is no directory IMAGE in its root\\n", step);
			return false;
		}
		fat.image_cluster = e.cluster | (uint32_t)e.cluster_high << 16;
		printf("mss: %u: IMAGE is a directory, from cluster %u\\n", step, fat.image_cluster);
	}""")
sub1(MSS, """	struct fat_dirent e;
	char name[11];

	short_name(file, name);""", """	struct fat_dirent e;
	char name[11];

	if (ext.on) {
		uint8_t inode[160];
		uint32_t n = ext.image_inode != 0 ? ext_find(ext.image_inode, file) : 0;

		if (n == 0 || !ext_inode(n, inode) || ext_size(inode) > 0xffffffffull) {
			return false;
		}
		*size = (uint32_t)ext_size(inode);
		*first = n;
		return true;
	}
	short_name(file, name);""")
sub1(MSS, """	uint32_t cluster = first, skip = offset / fat.cluster, within = offset % fat.cluster;
	uint8_t *dst = to;
""", """	uint32_t cluster = first, skip, within;
	uint8_t *dst = to;

	if (ext.on) {
		return ext_read(first, offset, to, length);
	}
	skip = offset / fat.cluster;
	within = offset % fat.cluster;
""")

# The modem on doha, second run (2026-11-12, mss_step=11): the modem asked for its file system and "/boot/modem_fsg" was
# refused -- doha's fsg_a is 24 MB, over the 16 MB willow's RMTFS took --, and the panel's last line, a count of
# modemst2's sectors, said nothing of how far it got. fsg up to 32 MB now; and at the end of the run the Sound line sums
# up what mattered: the locator asked, files sent over TFTP, the Wi-Fi domain's last state, a domain's failure
sub1(MSS, """			    &rmtfs_files[f].size) == 0 && rmtfs_files[f].size != 0 && rmtfs_files[f].size <= 16u << 20) {""",
     """			    &rmtfs_files[f].size) == 0 && rmtfs_files[f].size != 0 && rmtfs_files[f].size <= 32u << 20) {""")
sub1(MSS, """static char mss_last[200];
""", """static char mss_last[200];
static uint32_t mss_located, mss_files;         /* the locator asked, files read over TFTP */
static char mss_wifi[16] = "-", mss_failed[48]; /* the Wi-Fi domain's last state, a domain's failure */
""")
sub1(MSS, """	if (strnstr(line, "STOP", sizeof(line)) == NULL && strncmp(line, "mss: done", 9) != 0) {""",
     """	{
		const char *at;

		if (strnstr(line, "THE LOCATOR IS ASKED", sizeof(line)) != NULL) {
			mss_located++;
		}
		if (strnstr(line, "TFTP: READ", sizeof(line)) != NULL) {
			mss_files++;
		}
		if ((at = strnstr(line, "DOMAIN IS NOW ", sizeof(line))) != NULL) {
			size_t k = 0;

			for (at += 14; at[k] != 0 && at[k] != ' ' && k < sizeof(mss_wifi) - 1; k++) {
				mss_wifi[k] = at[k];
			}
			mss_wifi[k] = 0;
		}
		if ((at = strnstr(line, "HAS FAILED: ", sizeof(line))) != NULL || (at = strnstr(line, "GIVEN UP", sizeof(line))) != NULL) {
			strlcpy(mss_failed, at, sizeof(mss_failed));
		}
		if (strncmp(line, "mss: done", 9) == 0 && step > 11) {   /* (a STOP before the services keeps its line) */
			redwood_status(REDWOOD_STATUS_SOUND, "modem: loc %u, tftp %u, wifi %s; %.24s", mss_located, mss_files, mss_wifi,
			    mss_failed[0] ? mss_failed : "no failure");
		}
	}
	if (strnstr(line, "STOP", sizeof(line)) == NULL && strncmp(line, "mss: done", 9) != 0) {""")

# The modem on doha, third run (2026-11-12, mss_step=11): the locator asked 4 times, 11 files sent over TFTP, the Wi-Fi
# domain UP, then "A DOMAIN HAS FAILED: wlan_process" -- willow's assert -- and the modem never read its file system
# (modemst2: 0 sectors). miatoll's port found the modem gives the RMTFS buffer's addresses in 32 bits (commits 2e3578927,
# 9ba8f7ffd): on doha this kernel's memory runs above 4 GB (0x80000000-0x13fffffff), and the buffer, of any 2 MB, was
# likely there. Now below 4 GB, its address said; and the panel's summary keeps the end of the failure's words, where
# the assert is
sub1(MSS, """	if (kmem_alloc_contig(kernel_map, &rmtfs_memory, RMTFS_MEMORY_SIZE, PAGE_MASK, 0, 0, KMA_KOBJECT | KMA_ZERO | KMA_DATA,""",
     """	if (kmem_alloc_contig(kernel_map, &rmtfs_memory, RMTFS_MEMORY_SIZE, PAGE_MASK, (ppnum_t)((0x100000000ull >> PAGE_SHIFT) - 1), 0,
	    KMA_KOBJECT | KMA_ZERO | KMA_DATA,""")
sub1(MSS, """	rmtfs_memory_phys = kvtophys(rmtfs_memory);
""", """	rmtfs_memory_phys = kvtophys(rmtfs_memory);
	printf("mss: %u: RMTFS: its buffer at %#llx (below 4 GB: the modem gives its addresses in 32 bits)\\n", step, rmtfs_memory_phys);
""")
sub1(MSS, """		if ((at = strnstr(line, "HAS FAILED: ", sizeof(line))) != NULL || (at = strnstr(line, "GIVEN UP", sizeof(line))) != NULL) {
			strlcpy(mss_failed, at, sizeof(mss_failed));
		}""", """		if ((at = strnstr(line, "HAS FAILED: ", sizeof(line))) != NULL || (at = strnstr(line, "GIVEN UP", sizeof(line))) != NULL) {
			size_t n = strlen(at);

			/* (the end of it: where an assert says its file and line) */
			strlcpy(mss_failed, n > sizeof(mss_failed) - 1 ? at + n - (sizeof(mss_failed) - 1) : at, sizeof(mss_failed));
		}""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_SOUND, "modem: loc %u, tftp %u, wifi %s; %.24s", mss_located, mss_files, mss_wifi,
			    mss_failed[0] ? mss_failed : "no failure");""", """			redwood_status(REDWOOD_STATUS_SOUND, "loc %u tftp %u wifi %s %.34s", mss_located, mss_files, mss_wifi,
			    mss_failed[0] ? mss_failed : "no failure");""")

# The modem on doha, fifth run (2026-11-12): the same assert. The panel had only counts; which files the modem asked for
# over TFTP, and which it was refused, is what tells whether the Wi-Fi firmware wanted a board file under a name doha's
# modem_a has not (the assert comes right after its domain is up, as a missing file would make it). At the end of the
# run, three more lines of the panel (Keys, Touch, Storage; their drivers write them again later) list them: a name with
# "+" read, with "-" refused, "w:" written; and the summary counts RMTFS's sectors read
sub1(MSS, """static uint32_t mss_located, mss_files;         /* the locator asked, files read over TFTP */
""", """static uint32_t mss_located, mss_files;         /* the locator asked, files read over TFTP */
static char mss_tftp[200];                      /* the files asked for over TFTP: name+ read, name- refused, w:name */
static uint32_t mss_sectors;                    /* RMTFS's sectors read */
""")
sub1(MSS, """		if (strnstr(line, "TFTP: READ", sizeof(line)) != NULL) {
			mss_files++;
		}""", """		if (strnstr(line, "TFTP: READ", sizeof(line)) != NULL) {
			mss_files++;
		}
		if ((at = strnstr(line, "TFTP: ", sizeof(line))) != NULL) {
			const char *q = strnstr(at, "\\"", sizeof(line)), *end, *base;
			char one[48];
			size_t k;

			if (q != NULL && (end = strnstr(q + 1, "\\"", sizeof(line))) != NULL) {
				for (base = end; base > q + 1 && base[-1] != '/'; base--) {
				}
				k = (size_t)(end - base) < 30 ? (size_t)(end - base) : 30;
				snprintf(one, sizeof(one), "%s%.*s%s ", strncmp(at + 6, "write", 5) == 0 ? "w:" : "", (int)k, base,
				    strncmp(at + 6, "READ", 4) == 0 ? "+" : strncmp(at + 6, "read", 4) == 0 ? "-" : "");
				strlcat(mss_tftp, one, sizeof(mss_tftp));
			}
		}
		if ((at = strnstr(line, "RMTFS: read ", sizeof(line))) != NULL) {
			mss_sectors += (uint32_t)strtoul(at + 12, NULL, 10);
		}""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_SOUND, "loc %u tftp %u wifi %s %.34s", mss_located, mss_files, mss_wifi,
			    mss_failed[0] ? mss_failed : "no failure");""", """			size_t n = strlen(mss_tftp);

			redwood_status(REDWOOD_STATUS_SOUND, "loc %u tftp %u rmtfs %u wifi %s %.26s", mss_located, mss_files, mss_sectors,
			    mss_wifi, mss_failed[0] ? mss_failed : "no failure");
			redwood_status(REDWOOD_STATUS_KEYS, "%.56s", mss_tftp);
			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", n > 56 ? mss_tftp + 56 : "");
			redwood_status(REDWOOD_STATUS_STORAGE, "%.56s", n > 112 ? mss_tftp + 112 : "");""")

# The modem on doha, sixth run (2026-11-12): RMTFS now read (4096 sectors), the same assert. Asked over TFTP: shob.bin,
# hob_report.txt, dhob.bin, dhob_report.txt (refused: files the modem keeps in /readwrite, written as it goes) and
# server_check.txt written. And doha's own modemr.jsn (modem_a/image) lists one service of the root domain more than
# willow's table here: "tms/pdr_enabled" -- whether protection-domain restart is on, which the modem asks the locator for;
# this locator answered "in no domain". One of willow's open leads (README). In the table now, as doha's file has it.
sub1(MSS, """	{ "msm/modem/root_pd", 180, { "tms/servreg", "gps/gps_service", NULL } },""",
     """	{ "msm/modem/root_pd", 180, { "tms/servreg", "tms/pdr_enabled", "gps/gps_service" } },""")

# The modem on doha, seventh run (2026-11-12): with tms/pdr_enabled answered, the same assert. 11 files were read over
# TFTP, yet the panel's 168 characters held only the refused ones and the writes, which came first. Now the files read
# have lines of their own (Keys, Touch), once each, and the rest goes to Storage
sub1(MSS, """static char mss_tftp[200];                      /* the files asked for over TFTP: name+ read, name- refused, w:name */
""", """static char mss_tftp[200];                      /* the files asked for over TFTP: name+ read, name- refused, w:name */
static char mss_reads[200];                     /* ... those read, once each */
""")
sub1(MSS, """				strlcat(mss_tftp, one, sizeof(mss_tftp));""", """				if (strncmp(at + 6, "READ", 4) == 0) {
					one[strlen(one) - 2] = ' ';     /* (no "+": this list is of reads) */
					one[strlen(one) - 1] = 0;
					if (strnstr(mss_reads, one, sizeof(mss_reads)) == NULL) {
						strlcat(mss_reads, one, sizeof(mss_reads));
					}
				} else if (strnstr(mss_tftp, one, sizeof(mss_tftp)) == NULL) {
					strlcat(mss_tftp, one, sizeof(mss_tftp));
				}""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_KEYS, "%.56s", mss_tftp);
			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", n > 56 ? mss_tftp + 56 : "");
			redwood_status(REDWOOD_STATUS_STORAGE, "%.56s", n > 112 ? mss_tftp + 112 : "");""", """			n = strlen(mss_reads);
			redwood_status(REDWOOD_STATUS_KEYS, "read: %.50s", mss_reads);
			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", n > 50 ? mss_reads + 50 : "");
			redwood_status(REDWOOD_STATUS_STORAGE, "%.56s", mss_tftp);""")

# The Wi-Fi firmware's WLFW exchange on doha (2026-11-12): the modem read only wlanmdsp.mbn over TFTP, no board file --
# the board's data is the host's to send, over WLFW, and nothing here did. Ported from miatoll's HakiOS port (ath10k's
# qmi.c by hand), with doha's MSA (0x53300000, 1 MB) and, as doha's dt has no qcom,hyp_disabled, the firmware's memory
# given to it through TrustZone as icnss does; started at step 11, before the services are offered. The panel's Storage
# line at the end: the last thing the exchange said
sub1(MSS, """static bool
step_serve(void)
{""", """/*
 * The Wi-Fi firmware's service (WLFW, QMI service 69), doha (2026-11-12): what Linux's ath10k says to a WCN3990 whose
 * firmware runs in the modem (its qmi.c), made by hand as miatoll's HakiOS port made it (qdizax-w/hakios-xnu-kernel,
 * drivers/modem/hakios.mpss.c, 30 October 2026), from the layout of Linux's qmi_wlfw_v01.c (message ids, TLV numbers,
 * field sizes). On doha the modem reads only wlanmdsp.mbn over TFTP and no board file: the board's data is the host's
 * to send, and without any of this exchange the Wi-Fi domain asserted right after it came up (platform_main.c:230).
 *
 * As soon as the service is there: the indications "firmware ready" and "MSA ready" registered for, the host's
 * capabilities, the firmware's memory (the MSA: doha's dt qcom,wlan-msa-fixed-region, wlan_msa_region@53300000, of
 * which qcom,wlan-msa-memory says 1 MB) told, the regions the firmware answers with given to it through TrustZone as
 * Android's icnss does (doha's dt has no qcom,hyp_disabled: MP_ASSIGN, HLOS -> MSS_MSA and WLAN, read and write;
 * wlfw_assign=0: not), the MSA said ready, the chip's capabilities asked, the board's data file sent (modem_a's
 * image/bdwlan.b<board id>, else bdwlan.bin) in pieces of 6144 bytes, no calibrations reported, then "ready" awaited.
 * On a thread of its own from step 11 on; wlfw=0: not.
 */
#define WLFW_IND_REGISTER       0x0020
#define WLFW_FW_READY_IND       0x0021
#define WLFW_CAP                0x0024
#define WLFW_BDF_DOWNLOAD       0x0025
#define WLFW_CAL_REPORT         0x0026
#define WLFW_MSA_READY_IND      0x002b
#define WLFW_MSA_INFO           0x002d
#define WLFW_MSA_READY          0x002e
#define WLFW_HOST_CAP           0x0034
#define WLFW_CLIENT_ID          0x4b4e454cu     /* ath10k's ATH10K_QMI_CLIENT_ID */
#define WLFW_MSA_PA             0x53300000ull   /* doha: wlan_msa_region@53300000 */
#define WLFW_MSA_SIZE           0x00100000u     /* doha: qcom,wlan-msa-memory */
#define WLFW_BDF_PIECE          6144
#define VMID_WLAN               0x18
#define VMID_WLAN_CE            0x19

static struct redwood_qrtr_port *wlfw2_port;
static volatile uint32_t wlfw2_node, wlfw2_at;
static volatile bool wlfw2_there, wlfw2_fw_ready, wlfw2_msa_ready;
static uint16_t wlfw2_txn;
static uint8_t wlfw2_answer[1024];
static volatile uint32_t wlfw2_answer_length;
static volatile uint16_t wlfw2_waiting;

static void
wlfw2_receive(__unused void *context, uint32_t node, uint32_t port, const void *data, size_t length)
{
	const uint8_t *m = data;
	uint16_t message;

	if (length < 7 || node != wlfw2_node || port != wlfw2_at) {
		return;
	}
	message = (uint16_t)(m[3] | m[4] << 8);
	if (m[0] == 4) {                        /* an indication */
		if (message == WLFW_FW_READY_IND) {
			wlfw2_fw_ready = true;
			printf("mss: wlfw: THE WI-FI FIRMWARE SAYS IT IS READY\\n");
		} else if (message == WLFW_MSA_READY_IND) {
			wlfw2_msa_ready = true;
			printf("mss: wlfw: the firmware says its memory is ready\\n");
		} else {
			printf("mss: wlfw: indication %#x, %u bytes\\n", message, (unsigned)length);
		}
		return;
	}
	if (m[0] == 2 && wlfw2_waiting != 0 && (uint16_t)(m[1] | m[2] << 8) == wlfw2_waiting) {
		uint32_t n = length < sizeof(wlfw2_answer) ? (uint32_t)length : (uint32_t)sizeof(wlfw2_answer);

		memcpy(wlfw2_answer, m, n);
		wlfw2_answer_length = n;
		__asm__ volatile ("dmb ish" ::: "memory");
		wlfw2_waiting = 0;
	}
}

static void
wlfw2_server(__unused void *context, bool arrived, uint32_t service, __unused uint32_t version, __unused uint32_t instance,
    uint32_t node, uint32_t port)
{
	if (service != SERVICE_WLFW) {
		return;
	}
	if (arrived) {
		wlfw2_node = node;
		wlfw2_at = port;
	}
	wlfw2_there = arrived;
}

/* One request and its answer (5 s); true if the answer's result is 0. The answer stays in wlfw2_answer. */
static bool
wlfw2_ask(const char *what, uint16_t message, const uint8_t *tlvs, uint32_t length)
{
	uint8_t *packet = kalloc_data(7 + length, Z_WAITOK | Z_ZERO);
	uint32_t size = 0;
	uint16_t result = 1, error = 0;
	const uint8_t *value;
	bool ok = false;

	if (packet == NULL) {
		return false;
	}
	wlfw2_txn = (uint16_t)(wlfw2_txn + 1 == 0 ? 1 : wlfw2_txn + 1);
	packet[0] = 0;                          /* a request */
	packet[1] = (uint8_t)wlfw2_txn;
	packet[2] = (uint8_t)(wlfw2_txn >> 8);
	packet[3] = (uint8_t)message;
	packet[4] = (uint8_t)(message >> 8);
	packet[5] = (uint8_t)length;
	packet[6] = (uint8_t)(length >> 8);
	if (length != 0) {
		memcpy(packet + 7, tlvs, length);
	}
	wlfw2_answer_length = 0;
	wlfw2_waiting = wlfw2_txn;
	if (qrtr_send(wlfw2_port, wlfw2_node, wlfw2_at, packet, 7 + length) != 0) {
		wlfw2_waiting = 0;
		kfree_data(packet, 7 + length);
		printf("mss: wlfw: %s: NOT SENT\\n", what);
		return false;
	}
	kfree_data(packet, 7 + length);
	for (unsigned ms = 0; ms < 5000 && wlfw2_waiting != 0; ms++) {
		IOSleep(1);
	}
	if (wlfw2_waiting != 0) {
		wlfw2_waiting = 0;
		printf("mss: wlfw: %s: NO ANSWER in 5 s\\n", what);
		return false;
	}
	if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 2, &size)) != NULL && size == 4) {
		result = (uint16_t)(value[0] | value[1] << 8);
		error = (uint16_t)(value[2] | value[3] << 8);
		ok = result == 0;
	}
	printf("mss: wlfw: %s: %s (result %u, error %u)\\n", what, ok ? "done" : "REFUSED", result, error);
	return ok;
}

static unsigned
wlfw2_u8(uint8_t *at, uint8_t type, uint8_t value)
{
	at[0] = type;
	at[1] = 1;
	at[2] = 0;
	at[3] = value;
	return 4;
}

static unsigned
wlfw2_u32(uint8_t *at, uint8_t type, uint32_t value)
{
	at[0] = type;
	at[1] = 4;
	at[2] = 0;
	at[3] = (uint8_t)value;
	at[4] = (uint8_t)(value >> 8);
	at[5] = (uint8_t)(value >> 16);
	at[6] = (uint8_t)(value >> 24);
	return 7;
}

static uint32_t
wlfw2_le32(const uint8_t *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

/* A region of the firmware's memory given to the modem's MSA and the WLAN's VM through TrustZone (MP_ASSIGN) */
static bool
wlfw2_assign(uint64_t address, uint32_t bytes)
{
	vm_offset_t page = 0;
	uint64_t *ext, answer = 0, base;
	int32_t result;

	if (kmem_alloc(kernel_map, &page, PAGE_SIZE, KMA_KOBJECT | KMA_ZERO | KMA_DATA, VM_KERN_MEMORY_IOKIT) != KERN_SUCCESS) {
		return false;
	}
	base = kvtophys(page);
	{
		uint64_t *region = (uint64_t *)page;                    /* at 0: { address, size } */
		uint32_t *source = (uint32_t *)(page + 64);             /* at 64: the owners now */
		uint32_t *destination = (uint32_t *)(page + 128);       /* at 128: { vmid, perm, ctx (8), ctx size, 0 } each */

		region[0] = address;
		region[1] = bytes;
		source[0] = VMID_HLOS;
		destination[0] = VMID_MSS_MSA;
		destination[1] = SCM_PERM_RW;
		destination[6] = VMID_WLAN;
		destination[7] = SCM_PERM_RW;
		ext = (uint64_t *)(page + 256);
		ext[0] = 4;
		ext[1] = base + 128;
		ext[2] = 2 * 24;
		ext[3] = 0;
	}
	to_memory_range(page, PAGE_SIZE);
	result = scm_ext("the Wi-Fi firmware's memory to the modem and the WLAN (MP_ASSIGN: HLOS -> MSS_MSA + WLAN)", SCM_MP_ASSIGN,
	    SCM_ASSIGN_ARGUMENTS, base, 16, base + 64, base + 256, &answer);
	kmem_free(kernel_map, page, PAGE_SIZE);
	printf("mss: wlfw: %#x bytes at %#llx given to the firmware: %s (%d)\\n", bytes, address, result == 0 ? "done" : "REFUSED",
	    result);
	return result == 0;
}

static void
wlfw2_thread(__unused void *parameter, __unused wait_result_t wait)
{
	static uint8_t tlvs[64 + WLFW_BDF_PIECE];
	unsigned at;
	uint32_t chip_id = 0xff, chip_family = 0, board_id = 0xff, soc_id = 0, size = 0, assign = 1;
	const uint8_t *value;
	char name[40];
	uint32_t board_size = 0, board_first = 0;

	PE_parse_boot_argn("wlfw_assign", &assign, sizeof(assign));
	for (unsigned ms = 0; ms < 120000 && !wlfw2_there; ms += 5) {
		IOSleep(5);
	}
	if (!wlfw2_there) {
		printf("mss: wlfw: the Wi-Fi firmware's service did not come in 2 minutes\\n");
		goto out;
	}
	printf("mss: wlfw: the service at node %u port %u: the exchange begins\\n", wlfw2_node, wlfw2_at);

	at = 0;
	at += wlfw2_u8(tlvs + at, 0x10, 1);                             /* fw_ready_enable */
	at += wlfw2_u8(tlvs + at, 0x13, 1);                             /* msa_ready_enable */
	at += wlfw2_u32(tlvs + at, 0x15, WLFW_CLIENT_ID);               /* client_id */
	if (!wlfw2_ask("indications", WLFW_IND_REGISTER, tlvs, at)) {
		goto out;
	}
	if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 0x10, &size)) != NULL && size == 8 && (value[0] & 2)) {
		wlfw2_fw_ready = true;
	}
	at = wlfw2_u32(tlvs, 0x10, 0);                                  /* no daemon */
	(void)wlfw2_ask("host capabilities", WLFW_HOST_CAP, tlvs, at);

	at = 0;
	tlvs[at++] = 0x01;
	tlvs[at++] = 8;
	tlvs[at++] = 0;
	for (unsigned b = 0; b < 8; b++) {
		tlvs[at++] = (uint8_t)(WLFW_MSA_PA >> (8 * b));
	}
	at += wlfw2_u32(tlvs + at, 0x02, WLFW_MSA_SIZE);
	if (!wlfw2_ask("MSA info", WLFW_MSA_INFO, tlvs, at)) {
		goto out;
	}
	if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 0x03, &size)) != NULL && size >= 1) {
		uint8_t copy[1 + 13 * 8];
		unsigned regions = value[0] < 8 ? value[0] : 8;

		memcpy(copy, value, size < sizeof(copy) ? size : sizeof(copy));
		for (unsigned r = 0; r < regions && 1 + 13 * (r + 1) <= size; r++) {
			const uint8_t *e = copy + 1 + 13 * r;
			uint64_t address = wlfw2_le32(e) | (uint64_t)wlfw2_le32(e + 4) << 32;

			printf("mss: wlfw: region %u: %#x bytes at %#llx%s\\n", r, wlfw2_le32(e + 8), address, e[12] ? ", secure" : "");
			if (assign) {
				wlfw2_assign(address, wlfw2_le32(e + 8));
			}
		}
	}
	if (!wlfw2_ask("MSA ready", WLFW_MSA_READY, NULL, 0)) {
		goto out;
	}
	if (wlfw2_ask("chip capabilities", WLFW_CAP, NULL, 0)) {
		if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 0x10, &size)) != NULL && size >= 8) {
			chip_id = wlfw2_le32(value);
			chip_family = wlfw2_le32(value + 4);
		}
		if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 0x11, &size)) != NULL && size >= 4) {
			board_id = wlfw2_le32(value);
		}
		if ((value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 0x12, &size)) != NULL && size >= 4) {
			soc_id = wlfw2_le32(value);
		}
		printf("mss: wlfw: chip %#x family %#x board %#x SoC %#x\\n", chip_id, chip_family, board_id, soc_id);
	}
	if (board_id <= 0xff) {
		snprintf(name, sizeof(name), "bdwlan.b%02x", board_id);
	} else {
		snprintf(name, sizeof(name), "bdwlan.%03x", board_id);
	}
	if (!image_file(name, &board_size, &board_first)) {
		strlcpy(name, "bdwlan.bin", sizeof(name));
		if (!image_file(name, &board_size, &board_first)) {
			board_size = 0;
		}
	}
	if (board_size == 0) {
		printf("mss: wlfw: no board file in modem_a's image\\n");
	} else {
		uint32_t sent = 0, segment = 0;
		bool ok = true;

		printf("mss: wlfw: the board's data: %s, %u bytes\\n", name, board_size);
		while (ok && sent < board_size) {
			uint32_t piece = board_size - sent > WLFW_BDF_PIECE ? WLFW_BDF_PIECE : board_size - sent;
			bool end = sent + piece == board_size;

			at = wlfw2_u8(tlvs, 0x01, 1);                           /* valid */
			at += wlfw2_u32(tlvs + at, 0x10, 0);                    /* file_id */
			at += wlfw2_u32(tlvs + at, 0x11, board_size);           /* total_size */
			at += wlfw2_u32(tlvs + at, 0x12, segment);              /* seg_id */
			tlvs[at++] = 0x13;                                      /* data: a 2-byte count, then the bytes */
			tlvs[at++] = (uint8_t)(piece + 2);
			tlvs[at++] = (uint8_t)((piece + 2) >> 8);
			tlvs[at++] = (uint8_t)piece;
			tlvs[at++] = (uint8_t)(piece >> 8);
			if (file_read(board_first, sent, tlvs + at, piece) != 0) {
				printf("mss: wlfw: the board file cannot be read\\n");
				goto out;
			}
			at += piece;
			at += wlfw2_u8(tlvs + at, 0x14, end ? 1 : 0);           /* end */
			ok = wlfw2_ask(end ? "board data, the last piece" : "board data", WLFW_BDF_DOWNLOAD, tlvs, at);
			if (!ok && end && (value = qmi_tlv(wlfw2_answer, wlfw2_answer_length, 2, &size)) != NULL && size == 4 &&
			    (value[2] | value[3] << 8) == 1) {
				ok = true;              /* (its CRC check fails on valid files: ath10k uses it all the same) */
			}
			sent += piece;
			segment++;
		}
		if (!ok) {
			goto out;
		}
	}
	tlvs[0] = 0x01;
	tlvs[1] = 1;
	tlvs[2] = 0;
	tlvs[3] = 0;
	(void)wlfw2_ask("calibrations (none)", WLFW_CAL_REPORT, tlvs, 4);
	for (unsigned ms = 0; ms < 15000 && !wlfw2_fw_ready; ms += 10) {
		IOSleep(10);
	}
	printf("mss: wlfw: %s\\n", wlfw2_fw_ready ? "THE WI-FI FIRMWARE IS READY" : "not ready in 15 s");
out:
	thread_terminate(current_thread());
}

static void
wlfw2_start(void)
{
	uint32_t want = 1;
	thread_t thread;

	PE_parse_boot_argn("wlfw", &want, sizeof(want));
	if (want == 0) {
		return;
	}
	wlfw2_port = qrtr_open(wlfw2_receive, wlfw2_server, NULL);
	if (wlfw2_port == NULL || qrtr_lookup(wlfw2_port, SERVICE_WLFW, 1, 0) != 0) {
		printf("mss: wlfw: no port for the Wi-Fi firmware's service\\n");
		return;
	}
	if (kernel_thread_start(wlfw2_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}

static bool
step_serve(void)
{""")
sub1(MSS, """	if (rmtfs_memory == 0 && !rmtfs_memory_setup()) {
		return false;
	}
""", """	if (rmtfs_memory == 0 && !rmtfs_memory_setup()) {
		return false;
	}
	wlfw2_start();
""")
sub1(MSS, """static char mss_reads[200];                     /* ... those read, once each */
""", """static char mss_reads[200];                     /* ... those read, once each */
static char mss_wlfw[80] = "no WLFW exchange";  /* the last thing the WLFW exchange said */
""")
sub1(MSS, """		if ((at = strnstr(line, "RMTFS: read ", sizeof(line))) != NULL) {""", """		if (strncmp(line, "mss: wlfw: ", 11) == 0) {
			strlcpy(mss_wlfw, line + 11, sizeof(mss_wlfw));
		}
		if ((at = strnstr(line, "RMTFS: read ", sizeof(line))) != NULL) {""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_STORAGE, "%.56s", mss_tftp);""",
     """			redwood_status(REDWOOD_STATUS_STORAGE, "wlfw: %.50s", mss_wlfw);""")

# The modem on doha, eighth run (2026-11-12): "wlfw: no WLFW exchange" -- the Wi-Fi firmware's service never came: the
# firmware asserts while it starts, before it offers anything (so not for want of the host's exchange). willow found the
# same assert with the radio chip unpowered, and this driver asks the RPM for its five supplies first; whether that was
# done on doha is said on a line nobody saw. Now the Touch line keeps it at the end
sub1(MSS, """static char mss_wlfw[80] = "no WLFW exchange";  /* the last thing the WLFW exchange said */
""", """static char mss_wlfw[80] = "no WLFW exchange";  /* the last thing the WLFW exchange said */
static char mss_power[80] = "supplies: not asked";      /* what the radio chip's supplies came to */
""")
sub1(MSS, """		if (strncmp(line, "mss: wlfw: ", 11) == 0) {""", """		if ((at = strnstr(line, "supplies: ", sizeof(line))) != NULL) {
			strlcpy(mss_power, at, sizeof(mss_power));
		}
		if (strncmp(line, "mss: wlfw: ", 11) == 0) {""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", n > 50 ? mss_reads + 50 : "");""",
     """			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", mss_power);""")

# The modem on doha, the IPA's SMP2P entry (2026-11-12): with the radio's five supplies on (the panel: "ALL FIVE ON") the
# Wi-Fi domain still asserted (platform_main.c:platform_main_task:230), as on willow. doha's dt (trinket.dtsi,
# qcom,smp2p-modem) has a second outbound entry, "ipa" (qcom,smp2p-ipa-1-out), which Android's IPA driver makes at its probe,
# long before the modem starts, and answers through when the modem's own "ipa" entry asks whether the IPA's clock is on
# (ipa3_smp2p_notify(): bit 0 "the answer is there", bit 1 "the clock is on", once per modem start). Here: the entry made
# (mss_ipa_entry=0: not), the answer given once the modem asks (mss_ipa=1, the clock off, by default; 3 on; 0 none). The
# panel's Touch line at the end: the modem's SMP2P entries and their values, the last time they changed
sub1(MSS, """static char mss_power[80] = "supplies: not asked";      /* what the radio chip's supplies came to */
""", """static char mss_power[80] = "supplies: not asked";      /* what the radio chip's supplies came to */
static char mss_smp2p[80] = "no modem SMP2P";   /* the modem's SMP2P entries, the last time they changed */
static uint32_t mss_ipa_asked;                  /* the modem's "ipa" entry when our answer went out; 0: not yet */
""")
sub1(MSS, """	smem_poke(our_smp2p + SMP2P_AT_COUNTS, 16 | 1u << 16);
""", """	{
		uint32_t entry = 1;

		PE_parse_boot_argn("mss_ipa_entry", &entry, sizeof(entry));
		if (entry) {
			bzero(name, sizeof(name));
			strlcpy((char *)name, "ipa", sizeof(name));
			for (uint32_t word = 0; word < 4; word++) {
				smem_poke(our_smp2p + SMP2P_AT_NAME(1) + 4 * word, name[word]);
			}
			smem_poke(our_smp2p + SMP2P_AT_NAME(1) + 16, 0);
		}
		smem_poke(our_smp2p + SMP2P_AT_COUNTS, 16 | (entry ? 2u : 1u) << 16);
		mss_ipa_asked = 0;
	}
""")
sub1(MSS, """	show_smp2p("the link: the modem's item changes", words);
""", """	show_smp2p("the link: the modem's item changes", words);
	{
		size_t n = 0;

		mss_smp2p[0] = 0;
		for (unsigned i = 0; i < words->valid && i < 16 && n < sizeof(mss_smp2p) - 1; i++) {
			const char *what = words->entry[i].name;
			uint32_t value = words->entry[i].value, answer = 1;

			snprintf(mss_smp2p + n, sizeof(mss_smp2p) - n, "%.12s=%x ",
			    strncmp(what, "slave-kernel", 16) == 0 ? "sk" : what, value);
			n = strlen(mss_smp2p);
			if (strncmp(what, "ipa", 16) == 0 && value != 0 && mss_ipa_asked == 0 && our_smp2p != 0) {
				PE_parse_boot_argn("mss_ipa", &answer, sizeof(answer));
				mss_ipa_asked = value;
				if (answer != 0) {
					smem_poke(our_smp2p + SMP2P_AT_NAME(1) + 16, answer);
					ring(IPC_MODEM_SMP2P, "the modem's SMP2P doorbell (the IPA's answer)");
				}
				mss_say("mss: the modem asks of the IPA (%#x); answered %#x", value, answer);
			}
		}
	}
""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", mss_power);""",
     """			redwood_status(REDWOOD_STATUS_TOUCH, "%.56s", mss_smp2p);""")

# The modem on doha, the IPA's SMP2P entry, second run (2026-11-12): the panel said "no modem SMP2P" -- modem_listen()
# runs only on a change after the link's thread has its first copy, and the modem had written its entries before. The
# first copy goes through it too now, so the entries are seen (and an "ipa" question already there answered)
sub1(MSS, """	bzero(&last, sizeof(last));
	modem_words(&last);
	while (link_wanted) {""", """	bzero(&last, sizeof(last));
	if (modem_words(&last)) {
		modem_listen(&last);
	}
	while (link_wanted) {""")

# The modem on doha, its SMP2P item (2026-11-12): the panel still said "no modem SMP2P" with the first copy listened to:
# modem_words() took the modem's item only at the full 340 bytes of 16 entries, and the modem's own is smaller -- so the
# link's thread never saw an entry of the modem's at all (nor a "fatal", nor an "ipa" question). Any item with its
# header now, read up to its size, the rest zeroes; and the panel says the item's size
sub1(MSS, """modem_words(struct smp2p *words)
{
	static uint32_t at;
	uint32_t size = 0;

	if (at == 0) {
		at = smem_item(ITEM_SMP2P_THEIRS, &size);
		if (at == 0 || size < sizeof(*words)) {
			at = 0;
			return false;
		}
	}
	return smem_peek(at, words, sizeof(*words)) && words->magic == SMP2P_MAGIC;
}""", """modem_words(struct smp2p *words)
{
	static uint32_t at, have;
	uint32_t size = 0;

	if (at == 0) {
		at = smem_item(ITEM_SMP2P_THEIRS, &size);
		if (at == 0 || size < 20) {
			at = 0;
			snprintf(mss_smp2p, sizeof(mss_smp2p), "modem SMP2P item: %s (%u bytes)", size == 0 ? "none" : "small", size);
			return false;
		}
		have = size < sizeof(*words) ? size : (uint32_t)sizeof(*words);
		snprintf(mss_smp2p, sizeof(mss_smp2p), "modem SMP2P item %u bytes, no entries read", size);
	}
	bzero(words, sizeof(*words));
	if (!smem_peek(at, words, have) || words->magic != SMP2P_MAGIC) {
		return false;
	}
	if (words->valid > (have - 20) / 20) {
		words->valid = (uint16_t)((have - 20) / 20);
	}
	return true;
}""")

# doha, battery step 3 (2026-11-12): charge=2, the charging enable command written. The charge=1 run (kernel 14:07,
# cable in, 60 %) petted the watchdog (chg+, W62/8c) but the charger stayed off: status 1 = 0x47 (bits 2:0 = 7,
# DISABLE_CHARGE), CHARGING_ENABLE_CMD (CHGR 0x42) = 0x00 -- the command Android's smblib_chg_disable_vote_callback writes
# (bit 0, CHARGING_ENABLE_CMD_BIT) and nobody wrote here; the battery's current fell to 0 (the cable feeding the system,
# the battery left alone). With charge=2, besides the petting: while the cable is in and bit 0 reads 0, bit 0 written 1
# through the arbiter's write channel for CHGR (0x210) if it is ours; the only other write. Voltage, current and
# temperature limits stay the PMIC's (as Android last left them); stops for good on a refused write
sub1(BTN, """	pets++;
}
""", """	pets++;
}

/*
 * charge=2 (doha): the charging enable command (CHGR 0x42 bit 0) written 1 while a cable is in and it reads 0, through
 * the arbiter's write channel for the PMI632's CHGR block (0x210), if this system owns it
 */
static vm_offset_t enable_channel;
static uint16_t enable_channel_n;
static bool enable_stopped;
static uint32_t enables;

static void
enable_setup(uint32_t channels)
{
	for (uint32_t n = 0; n < channels; n++) {
		uint32_t map = rd(arb_core + ARB_CHANNEL(n));

		if (map != 0 && ((map >> 8) & 0xfff) == 0x210 && (rd(arb_cnfg + ARB_OWNER(n)) & 7) == ARB_SYSTEM) {
			enable_channel_n = (uint16_t)n;
			enable_channel = ml_io_map(DOHA_ARB_CHNLS + 0x10000UL * n, 0x1000);
			printf("battery: charge=2: the charging enable command will be written (channel %u, CHGR 0x42)\\n", n);
			return;
		}
	}
	printf("battery: charge=2, but no channel of the charger's CHGR block is ours to write through: not enabled\\n");
}

static void
charge_enable(void)
{
	uint64_t start, interval;
	uint32_t status;
	uint8_t en = 0;

	if (enable_channel == 0 || enable_stopped) {
		return;
	}
	if (spmi_read(&chgr, 0x42, &en, 1) != NULL || (en & 1) != 0) {
		return;
	}
	if (((rd(arb_core + ARB_CHANNEL(enable_channel_n)) >> 8) & 0xfff) != 0x210) {
		enable_stopped = true;
		printf("battery: the arbiter's channel %u is no longer the charger's CHGR: not enabled any more\\n", enable_channel_n);
		return;
	}
	nanoseconds_to_absolutetime(READ_TIMEOUT_US * (uint64_t)NSEC_PER_USEC, &interval);
	redwood_spmi_lock();
	wr(enable_channel + CHANNEL_WDATA0, (uint32_t)(en | 1));
	wr(enable_channel + OBSERVER_COMMAND, COMMAND_WRITE | 0x42u << 4);
	start = mach_absolute_time();
	do {
		status = rd(enable_channel + OBSERVER_STATUS);
	} while (!(status & STATUS_DONE) && mach_absolute_time() - start < interval);
	redwood_spmi_unlock();
	if (!(status & STATUS_DONE) || (status & (STATUS_DENIED | STATUS_FAILURE))) {
		enable_stopped = true;
		printf("battery: the charging enable command not written any more: %s (status %#x)\\n",
		    !(status & STATUS_DONE) ? "no answer from the arbiter" : "the write was refused", status);
		return;
	}
	if (enables++ == 0) {
		printf("battery: charging enabled (CHGR 0x42 was %#x)\\n", en);
	}
}
""")
sub1(BTN, """			if (PE_parse_boot_argn("charge", &charge, sizeof(charge)) && charge) {
				pet_setup(channels);
			}
""", """			if (PE_parse_boot_argn("charge", &charge, sizeof(charge)) && charge) {
				pet_setup(channels);
				if (charge >= 2) {
					enable_setup(channels);
				}
			}
""")
sub1(BTN, """	if ((usb & 0x10) != 0) {
		pet();
	}
""", """	if ((usb & 0x10) != 0) {
		pet();
		charge_enable();
	}
""")
sub1(BTN, """		redwood_status(REDWOOD_STATUS_WIFI, "chg%s S%02x/%02x E%02x U%02x W%02x/%02x I%d avg %dmA/%us",
		    pet_stopped ? "!" : pets != 0 ? "+" : "", st[0], st[1], en, il, wd[0], wd[2], current_now(), current_average(),
		    current_count);""", """		redwood_status(REDWOOD_STATUS_WIFI, "chg%s%s S%02x/%02x E%02x U%02x W%02x/%02x I%d avg %dmA/%us",
		    pet_stopped ? "!" : pets != 0 ? "+" : "", enable_stopped ? "x" : enables != 0 ? "e" : "", st[0], st[1], en, il,
		    wd[0], wd[2], current_now(), current_average(), current_count);""")

# The modem on doha, no SMP2P item of its own (2026-11-12): the panel said "modem SMP2P item: none (0 bytes)" at the end
# of the run -- the modem made GLINK's items but never its SMP2P item (428), the one its Wi-Fi domain puts its entry
# "wlan" in (dt: qcom,smp2p-wlan-1-in); a domain that cannot make that entry plausibly asserts at its start
# (platform_main_task). Our doorbell for SMP2P was rung once, before the modem ran. While the modem's item is not there,
# the link's thread rings it once a second (up to 60 times; mss_smp2p_rings=N), and the panel's Touch line says how many
# times it was rung before the item came, or that it never did
sub1(MSS, """			snprintf(mss_smp2p, sizeof(mss_smp2p), "modem SMP2P item: %s (%u bytes)", size == 0 ? "none" : "small", size);
""", "")
sub1(MSS, """	struct glink_packet *packet;
	bool gave_up = false;
""", """	struct glink_packet *packet;
	bool gave_up = false;
	uint32_t smp2p_rings = 0, smp2p_rings_max = 60, smp2p_wait = 0;

	PE_parse_boot_argn("mss_smp2p_rings", &smp2p_rings_max, sizeof(smp2p_rings_max));
""")
sub1(MSS, """		if (modem_words(&words) && memcmp(&words, &last, sizeof(words)) != 0) {""",
     """		if (smp2p_rings < smp2p_rings_max && !modem_words(&words) && ++smp2p_wait >= 1000) {
			smp2p_wait = 0;
			smp2p_rings++;
			ring(IPC_MODEM_SMP2P, "the modem's SMP2P doorbell (its item is not there)");
			snprintf(mss_smp2p, sizeof(mss_smp2p), "modem SMP2P item: none; rung %u times", smp2p_rings);
		}
		if (modem_words(&words) && memcmp(&words, &last, sizeof(words)) != 0) {
			if (smp2p_rings != 0 && last.magic == 0) {
				mss_say("mss: link: the modem's SMP2P item came after %u rings", smp2p_rings);
			}""")

# The modem on doha, which items it makes (2026-11-12): rung 45 times, the modem's SMP2P item (428) never came. The
# panel's Touch line now lists, each time the doorbell is rung, the items in the partition of us and the modem -- what
# the modem made there, and so whether its SMP2P item is under another number
sub1(MSS, """			snprintf(mss_smp2p, sizeof(mss_smp2p), "modem SMP2P item: none; rung %u times", smp2p_rings);
""", """			{
				static struct smem_item listed[40];
				uint32_t cacheline = 0, psize = 0, part = smem_partition(SMEM_US, SMEM_MODEM, &cacheline, &psize);
				unsigned count = smem_items(part, cacheline, listed, 40);

				snprintf(mss_smp2p, sizeof(mss_smp2p), "r%u n%u:", smp2p_rings, count);
				for (unsigned i = 0; i < count && i < 40; i++) {
					size_t n = strlen(mss_smp2p);

					snprintf(mss_smp2p + n, sizeof(mss_smp2p) - n, " %u", (unsigned)listed[i].item);
				}
			}
""")

# The modem on doha, its SMP2P item by its magic (2026-11-12): the partition of us and the modem had 435 (ours), 478 479
# 480 (GLINK), 605, 611 and 497 (the IPA's filter tables, made by the modem itself) -- no 428. Should this modem keep its
# SMP2P item under another number, it is found by what it begins with ("$SMP", from the modem to us); the panel's Touch
# line begins with the item's number ("i611 ..."), or, with none, lists the items and their first words
sub1(MSS, """modem_words(struct smp2p *words)
{
	static uint32_t at, have;
	uint32_t size = 0;

	if (at == 0) {
		at = smem_item(ITEM_SMP2P_THEIRS, &size);
""", """static uint32_t mss_smp2p_item;                 /* the number of the modem's SMP2P item, once found */

static uint32_t
smp2p_by_magic(uint32_t *size)
{
	static struct smem_item listed[40];
	uint32_t cacheline = 0, psize = 0, part = smem_partition(SMEM_US, SMEM_MODEM, &cacheline, &psize);
	unsigned count = smem_items(part, cacheline, listed, 40);

	for (unsigned i = 0; i < count && i < 40; i++) {
		struct smp2p head;

		if (listed[i].item == ITEM_SMP2P_OURS || listed[i].size < 20) {
			continue;
		}
		bzero(&head, sizeof(head));
		if (smem_peek(listed[i].offset, &head, 20) && head.magic == SMP2P_MAGIC && head.local == SMEM_MODEM) {
			*size = listed[i].size;
			mss_smp2p_item = listed[i].item;
			return listed[i].offset;
		}
	}
	return 0;
}

static bool
modem_words(struct smp2p *words)
{
	static uint32_t at, have;
	uint32_t size = 0;

	if (at == 0) {
		at = smem_item(ITEM_SMP2P_THEIRS, &size);
		if (at != 0) {
			mss_smp2p_item = ITEM_SMP2P_THEIRS;
		} else {
			at = smp2p_by_magic(&size);
		}
""")
sub1(MSS, """static bool
static uint32_t mss_smp2p_item;""", """static uint32_t mss_smp2p_item;""")
sub1(MSS, """		mss_smp2p[0] = 0;
		for (unsigned i = 0; i < words->valid""", """		snprintf(mss_smp2p, sizeof(mss_smp2p), "i%u ", mss_smp2p_item);
		n = strlen(mss_smp2p);
		for (unsigned i = 0; i < words->valid""")
sub1(MSS, """					snprintf(mss_smp2p + n, sizeof(mss_smp2p) - n, " %u", (unsigned)listed[i].item);""",
     """					uint32_t first = 0;

					smem_peek(listed[i].offset, &first, 4);
					snprintf(mss_smp2p + n, sizeof(mss_smp2p) - n, " %u:%x", (unsigned)listed[i].item, first & 0xffff);""")

# The modem on doha, the Wi-Fi domain's assert read in its firmware (2026-11-12): in Motorola's own wlanmdsp.mbn
# (QPIS30.28-Q3-28-26-1), platform_main_task calls err_crash_cb_register, then smp2p_user_init, then
# smp2p_create(&handle, 0 -- us --, "wlan"), and asserts at line 230 when either of the last two fails: the domain dies
# for want of the modem's SMP2P towards us, which (no item 428 anywhere we can read) the modem never sets up. What the
# modem's two other items say may tell why: at the end of the run the panel's Keys line shows item 605's first words,
# its Storage line item 611's first bytes as text (mss_items=0: the usual lines)
sub1(MSS, """static char mss_smp2p[80] = "no modem SMP2P";   /* the modem's SMP2P entries, the last time they changed */
""", """static char mss_smp2p[80] = "no modem SMP2P";   /* the modem's SMP2P entries, the last time they changed */
static bool smem_peek(uint64_t offset, void *to, uint32_t size);
static uint32_t smem_item(uint32_t item, uint32_t *size);
""")
sub1(MSS, """			redwood_status(REDWOOD_STATUS_STORAGE, "wlfw: %.50s", mss_wlfw);
		}""", """			redwood_status(REDWOOD_STATUS_STORAGE, "wlfw: %.50s", mss_wlfw);
			{
				uint32_t items = 1, size = 0, at;

				PE_parse_boot_argn("mss_items", &items, sizeof(items));
				if (items && (at = smem_item(605, &size)) != 0) {
					uint32_t words[6] = { 0 };

					smem_peek(at, words, size < sizeof(words) ? size : sizeof(words));
					redwood_status(REDWOOD_STATUS_KEYS, "605/%u %x %x %x %x %x %x", size, words[0], words[1], words[2], words[3],
					    words[4], words[5]);
				}
				if (items && (at = smem_item(611, &size)) != 0) {
					char text[53];

					bzero(text, sizeof(text));
					smem_peek(at, text, size < sizeof(text) - 1 ? size : sizeof(text) - 1);
					for (unsigned i = 0; i < sizeof(text) - 1; i++) {
						if (text[i] < 0x20 || text[i] > 0x7e) {
							text[i] = '.';
						}
					}
					redwood_status(REDWOOD_STATUS_STORAGE, "611:%s", text);
				}
			}
		}""")

# The modem on doha, SMP2P's items the right way round (2026-11-12): the modem's own code (Motorola's MPSS.AT.4, the
# root's SMP2P: a table of bases, 427 for us, 435 for the modem, 443 the ADSP ...; an item is its maker's base plus the
# other's number) and Linux's qcom_smp2p.c (qcom,smem = <inbound outbound>) agree: ours to the modem is 428 (427 + 1), the
# modem's to us 435 (435 + 0). willow had them the other way: our item sat at 435, where the modem makes its own -- it
# found the number taken and made none, and its Wi-Fi domain, whose smp2p_create(us, "wlan") then fails, asserted at
# platform_main.c:230. Swapped
sub1(MSS, """#define ITEM_SMP2P_OURS         435             /* dt: qcom,smp2p-modem, qcom,smem = <0x1b3 0x1ac> */
#define ITEM_SMP2P_THEIRS       428""", """#define ITEM_SMP2P_OURS         428             /* dt: qcom,smp2p-modem, qcom,smem = <435 (in) 428 (out)> */
#define ITEM_SMP2P_THEIRS       435""")
# (the two items' dump of the run before, off by default now that the WLFW exchange's line matters: mss_items=1 shows it)
sub1(MSS, """				uint32_t items = 1, size = 0, at;""", """				uint32_t items = 0, size = 0, at;""")
