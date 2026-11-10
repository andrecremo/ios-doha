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
