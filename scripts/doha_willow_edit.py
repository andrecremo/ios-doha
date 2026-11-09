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
# doha's store: userdata past the iOS volume and the cryptexes (ufs_write=1), the same bounds as the loader's doha_store
sub1('xnu/files/bsd/dev/redwood_ufs.c', """	{ "userdata", 31031296, 91111391, 512, 0, true },
""", """	{ "userdata", 31031296, 91111391, 512, 0, true },
	/*
	 * doha: userdata, mmcblk0p80, its 50 GiB that were Android's data, with the iOS volume and both cryptexes in
	 * its first 8365539328 bytes: the store (ufs_write=1, not a filesystem), past them like willow's system.
	 */
	{ "userdata", 17924096, 104218591, 512, UFS_WRITE_FIRST, false },
""")

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
