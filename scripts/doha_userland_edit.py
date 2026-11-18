"""The doha's changes to willow-hackios's userland (branch userland, 0ffde01), each made once, idempotent.

  doha_userland_edit.py TREE
"""
import sys
from pathlib import Path

tree = Path(sys.argv[1])
p = tree / 'userland/build.sh'
t = p.open(encoding='utf-8', newline='').read()
old = """if [ -f ../fw-touch/novatek_ts_fw.bin ]; then
	mkdir -p root/fw
	install -m 0644 ../fw-touch/novatek_ts_fw.bin root/fw/
fi
"""
new = old + """# ... and doha's (Moto G8 Plus): the FocalTech FT8719 has no flash either, and its firmware is the phone's
# /vendor/firmware/focaltech-ft8719-a0-0000-doha.bin, into ../fw-touch as focaltech_ts_fw.bin
# (bsd/dev/redwood_focaltech.c; 64 KB, FocalTech's and not in the repository)
if [ -f ../fw-touch/focaltech_ts_fw.bin ]; then
	mkdir -p root/fw
	install -m 0644 ../fw-touch/focaltech_ts_fw.bin root/fw/
fi
"""
# the store of /private/var on doha: userdata past the iOS volume (src/var_store.c), after willow's, which have
# no userdata of that kind (/dev/rufs_system does not exist on doha, whose system is system_a and system_b)
vs = tree / 'userland/src/var_store.c'
v = vs.open(encoding='utf-8', newline='').read()
vold = """	{ "darwin", 0x80000000LL },
	{ "system", 0x40000000LL },
};"""
vnew = """	{ "darwin", 0x80000000LL },
	{ "system", 0x40000000LL },
	/* doha (Moto G8 Plus): userdata, 50 GiB, with the same image in its first 8365539328 bytes */
	{ "userdata", 0x80000000LL },
};"""
if '"userdata", 0x80000000LL' in v:
    print("userland/src/var_store.c: has doha's store already")
elif v.count(vold) != 1:
    raise SystemExit(f'userland/src/var_store.c: expected 1x the STORES table, found {v.count(vold)}')
else:
    vs.open('w', encoding='utf-8', newline='').write(v.replace(vold, vnew))
    print("ok userland/src/var_store.c: doha's store, userdata")

if 'focaltech_ts_fw.bin' in t:
    print('userland/build.sh: has the FT8719 firmware already')
elif t.count(old) != 1:
    raise SystemExit(f'userland/build.sh: expected 1x the Novatek firmware block, found {t.count(old)}')
else:
    p.open('w', encoding='utf-8', newline='').write(t.replace(old, new))
    print('ok userland/build.sh: the FT8719 firmware into fw/')

WALLPAPER_CODE = r'''
/*
 * Boot-arg wallpaper_freeze=1 (from upstream hakios-xnu-kernel, 3-4 November 2026): the wallpaper as one still picture.
 * The poster is another process's layers (PosterBoard's, through a layer host), and its gradients are drawn again by
 * the window server every frame; upstream measured the home button's animation at 28 frames a second with it and 78
 * with it hidden. -drawViewHierarchyInRect: answers one colour for it, so the picture is what is really on the panel:
 * at the home screen, with the window of the icons hidden for a moment (they blink once per boot), the pixels of the
 * IOSurface the window server last showed (kern.redwood.fb_surface) become one opaque view in the wallpaper's window,
 * and what was there is hidden. What that gives up: the wallpaper does not change until the next boot, and the lock
 * screen shows the same picture. wallpaper_freeze=2: the wallpaper only hidden (what it costs, measured).
 */
typedef struct { double x, y, width, height; } hk_rect;

static bool wallpaper_hide_only;
static const void *wallpaper_frozen_key = &wallpaper_frozen_key;

static id
wallpaper_window(void)
{
	id app = SEND(id, objc_getClass("UIApplication"), "sharedApplication");
	id windows = app != NULL ? SEND(id, app, "windows") : NULL;
	unsigned long count = windows != NULL ? SEND(unsigned long, windows, "count") : 0;

	for (unsigned long i = 0; i < count; i++) {
		id window = ((id (*)(id, SEL, unsigned long))objc_msgSend)(windows, sel_registerName("objectAtIndex:"), i);
		const char *name = object_getClassName(window);

		if (strcasestr(name, "wallpaper") != NULL || strcasestr(name, "poster") != NULL) {
			return window;
		}
	}
	return NULL;
}

/* A picture of the surface on the panel, opaque, in points of the screen's scale; NULL: none, or all one colour. */
static id
wallpaper_picture(double scale)
{
	uint32_t sid = 0;
	size_t size = sizeof(sid);
	IOSurfaceRef surface;
	id image = NULL;

	if (sysctlbyname("kern.redwood.fb_surface", &sid, &size, NULL, 0) != 0 || sid == 0 ||
	    (surface = IOSurfaceLookup(sid)) == NULL) {
		say("redwood: SpringBoard: wallpaper_freeze=1: no surface on the panel to read (%u)\n", sid);
		return NULL;
	}
	size_t width = IOSurfaceGetWidth(surface), height = IOSurfaceGetHeight(surface), row = IOSurfaceGetBytesPerRow(surface);

	IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL);
	CFDataRef pixels = CFDataCreate(NULL, IOSurfaceGetBaseAddress(surface), (CFIndex)(row * height));
	IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, NULL);
	unsigned distinct = 0;
	if (pixels != NULL) {
		const uint8_t *at = CFDataGetBytePtr(pixels);
		uint32_t first = *(const uint32_t *)at;

		for (unsigned k = 0; k < 97; k++) {
			distinct += *(const uint32_t *)(at + (height * k / 97) * row + (width * k / 97) * 4) != first;
		}
	}
	say("redwood: SpringBoard: wallpaper_freeze=1: surface %u, %zux%zu, %zu bytes a row, format %#x: %u of 97 samples unlike the first\n",
	    sid, width, height, row, IOSurfaceGetPixelFormat(surface), distinct);
	if (pixels != NULL && distinct >= 10) {
		CGDataProviderRef provider = CGDataProviderCreateWithCFData(pixels);
		CGColorSpaceRef space = CGColorSpaceCreateDeviceRGB();
		CGImageRef cg = CGImageCreate(width, height, 8, 32, row, space, kCGBitmapByteOrder32Little | kCGImageAlphaNoneSkipFirst,
		    provider, NULL, false, kCGRenderingIntentDefault);

		if (cg != NULL) {
			image = ((id (*)(id, SEL, CGImageRef, double, long))objc_msgSend)((id)objc_getClass("UIImage"),
			    sel_registerName("imageWithCGImage:scale:orientation:"), cg, scale, 0L);
			CGImageRelease(cg);
		}
		CGColorSpaceRelease(space);
		CGDataProviderRelease(provider);
	}
	if (pixels != NULL) {
		CFRelease(pixels);
	}
	CFRelease(surface);
	return image;
}

/* The picture into the wallpaper's window, in place of what was shown there (none: only hidden). */
static void
wallpaper_put(id window, id image)
{
	id layer = SEND(id, window, "layer");
	id sublayers = SEND(id, SEND(id, layer, "sublayers"), "copy");
	unsigned long count = sublayers != NULL ? SEND(unsigned long, sublayers, "count") : 0;
	hk_rect bounds = ((hk_rect (*)(id, SEL))objc_msgSend)(window, sel_registerName("bounds"));

	if (image != NULL) {
		id view = ((id (*)(id, SEL, id))objc_msgSend)(SEND(id, objc_getClass("UIImageView"), "alloc"),
		    sel_registerName("initWithImage:"), image);

		((void (*)(id, SEL, hk_rect))objc_msgSend)(view, sel_registerName("setFrame:"), bounds);
		((void (*)(id, SEL, BOOL))objc_msgSend)(view, sel_registerName("setOpaque:"), YES);
		((void (*)(id, SEL, id))objc_msgSend)(window, sel_registerName("addSubview:"), view);
		objc_setAssociatedObject(window, wallpaper_frozen_key, view, OBJC_ASSOCIATION_RETAIN);
	} else {
		objc_setAssociatedObject(window, wallpaper_frozen_key, window, OBJC_ASSOCIATION_ASSIGN);
	}
	for (unsigned long k = 0; k < count; k++) {
		id sub = ((id (*)(id, SEL, unsigned long))objc_msgSend)(sublayers, sel_registerName("objectAtIndex:"), k);

		((void (*)(id, SEL, BOOL))objc_msgSend)(sub, sel_registerName("setHidden:"), YES);
	}
	say("redwood: SpringBoard: wallpaper_freeze: %s %s (%lu layers hidden)\n", object_getClassName(window),
	    image != NULL ? "is one picture now" : "hidden", count);
}

/* Whether the home screen is what is showing: unlocked, no application in front. */
static bool
wallpaper_home_showing(void)
{
	Class manager = objc_getClass("SBLockScreenManager");
	id shared = manager != NULL ? SEND(id, manager, "sharedInstance") : NULL;
	id app = SEND(id, objc_getClass("UIApplication"), "sharedApplication");

	if (shared == NULL || SEND(BOOL, shared, "isUILocked")) {
		return false;
	}
	/* (a selector nobody answers would abort SpringBoard: unlocked is then all that is known) */
	if (app == NULL || !class_respondsToSelector(object_getClass(app), sel_registerName("_accessibilityFrontMostApplication"))) {
		return app != NULL;
	}
	return SEND(id, app, "_accessibilityFrontMostApplication") == NULL;
}

static void
wallpaper_freeze_pass(unsigned attempt)
{
	id window = wallpaper_window();
	id screen = SEND(id, objc_getClass("UIScreen"), "mainScreen");
	double scale = screen != NULL ? ((double (*)(id, SEL))objc_msgSend)(screen, sel_registerName("scale")) : 3.0;

	if (window != NULL && objc_getAssociatedObject(window, wallpaper_frozen_key) != NULL) {
		return;
	}
	if (window == NULL || !wallpaper_home_showing()) {
		if (attempt < 720) {
			dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
				wallpaper_freeze_pass(attempt + 1);
			});
		}
		return;
	}
	if (wallpaper_hide_only) {
		wallpaper_put(window, NULL);
		return;
	}
	/* the icons out of the way until the window server has drawn the wallpaper without them */
	id app = SEND(id, objc_getClass("UIApplication"), "sharedApplication");
	id windows = SEND(id, app, "windows");
	unsigned long count = SEND(unsigned long, windows, "count");
	CFMutableArrayRef hidden = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);

	for (unsigned long i = 0; i < count; i++) {
		id other = ((id (*)(id, SEL, unsigned long))objc_msgSend)(windows, sel_registerName("objectAtIndex:"), i);

		/* only the window of the icons and the dock: with SpringBoard's other windows hidden too the screen was black */
		if (strcmp(object_getClassName(other), "SBHomeScreenWindow") == 0 && !SEND(BOOL, other, "isHidden")) {
			((void (*)(id, SEL, BOOL))objc_msgSend)(other, sel_registerName("setHidden:"), YES);
			CFArrayAppendValue(hidden, other);
		}
	}
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 300 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
		id image = wallpaper_picture(scale);

		for (CFIndex i = 0; i < CFArrayGetCount(hidden); i++) {
			((void (*)(id, SEL, BOOL))objc_msgSend)((id)CFArrayGetValueAtIndex(hidden, i), sel_registerName("setHidden:"), NO);
		}
		CFRelease(hidden);
		if (image != NULL) {
			wallpaper_put(window, image);
		} else if (attempt < 720) {
			dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
				wallpaper_freeze_pass(attempt + 1);
			});
		}
	});
}

static void
wallpaper_freeze(void)
{
	char arguments[1024] = "";
	size_t size = sizeof(arguments) - 1;
	const char *argument;

	if (sysctlbyname("kern.bootargs", arguments, &size, NULL, 0) != 0 ||
	    (argument = strstr(arguments, "wallpaper_freeze=")) == NULL || (argument != arguments && argument[-1] != ' ') ||
	    (argument[17] != '1' && argument[17] != '2')) {
		return;
	}
	wallpaper_hide_only = argument[17] == '2';
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
		wallpaper_freeze_pass(0);
	});
}

'''

# SpringBoard's wallpaper_freeze=1 (upstream hakios-xnu-kernel 66b8e63ee and 348613f22, 3-4 November 2026): the
# wallpaper drawn every frame (PosterBoard's layers, their gradients) becomes one still picture, read from the surface
# on the panel (kern.redwood.fb_surface) at the home screen; there, home button 28-50 -> 92 frames a second, Settings'
# scroll 90 -> 109
b = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
bold = """-dynamiclib -install_name /redwood/lib/libredwood-sb.dylib -framework CoreFoundation -framework IOKit -lobjc"""
bnew = """-dynamiclib -install_name /redwood/lib/libredwood-sb.dylib -framework CoreFoundation -framework CoreGraphics -framework IOSurface -framework IOKit -lobjc"""
if bnew in b:
    print("userland/build.sh: libredwood-sb links CoreGraphics and IOSurface already")
elif b.count(bold) != 1:
    raise SystemExit(f'userland/build.sh: expected 1x the libredwood-sb line, found {b.count(bold)}')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(b.replace(bold, bnew))
    print("userland/build.sh: libredwood-sb links CoreGraphics and IOSurface")

sb = tree / 'userland/src/inject_sb.c'
s = sb.open(encoding='utf-8', newline='').read()
if 'wallpaper_freeze' in s:
    print("userland/src/inject_sb.c: has wallpaper_freeze already")
else:
    inc_old = "#include <CoreFoundation/CoreFoundation.h>\n"
    inc_new = inc_old + "#include <CoreGraphics/CoreGraphics.h>\n#include <IOSurface/IOSurfaceRef.h>\n"
    init_old = "__attribute__((constructor))\nstatic void\nredwood_springboard_init(void)\n{\n"
    if s.count(inc_old) != 1 or s.count(init_old) != 1:
        raise SystemExit('userland/src/inject_sb.c: the include or redwood_springboard_init is not where expected')
    s = s.replace(inc_old, inc_new)
    s = s.replace(init_old, WALLPAPER_CODE + init_old + "\twallpaper_freeze();\n")
    sb.open('w', encoding='utf-8', newline='').write(s)
    print("userland/src/inject_sb.c: wallpaper_freeze")

# the network doha's radio is to join (ath10k; bsd/dev/redwood_wifi.c reads fw/network: the name on its first line, the
# passphrase on its second). willow installs it only beside redwood's WPSS image, and only without SHARE; doha's comes
# from ../fw-wifi/network when DOHA_NETWORK=1 (run-ios-flash.sh NETWORK=1), whatever SHARE says -- it is yours
nb = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
nold = """# ... and the vibration motor's waveforms, the phone's /vendor/firmware/aw8697_haptic.bin, from ../fw-haptic"""
nnew = """# ... and doha's network to join (DOHA_NETWORK=1: ../fw-wifi/network, a name and a passphrase; never in a repository)
if [ -n "$DOHA_NETWORK" ] && [ -f ../fw-wifi/network ]; then
	mkdir -p root/fw
	install -m 0600 ../fw-wifi/network root/fw/network
fi
""" + nold
if 'DOHA_NETWORK' in nb:
    print("userland/build.sh: has doha's network already")
elif nb.count(nold) != 1:
    raise SystemExit(f'userland/build.sh: expected 1x the haptic block, found {nb.count(nold)}')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(nb.replace(nold, nnew))
    print("userland/build.sh: doha's network into fw/ (DOHA_NETWORK=1)")

# doha: net_test's results on the panel (kern.redwood_note, the kernel's): "net_test hud STEP..." sends each line of its
# output to the Keys line, one every 4 s, the last staying; and rc.jobs.dohanet, which tries the network layer by layer
# (run-ios-flash.sh NETTEST=1)
nt = tree / 'userland/src/net_test.m'
n = nt.open(encoding='utf-8', newline='').read()
hold = """int
main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IOLBF, 0);
	@autoreleasepool {"""
hnew = """/* ---- hud (doha) -------------------------------------------------------------------------------------- */

/* each line of the output onto the panel's Keys line (kern.redwood_note), 4 s apart, the last staying */
static int hud_pipe = -1;
static pthread_t hud_thread;

static void *
hud_forward(__unused void *unused)
{
	char line[256];
	size_t at = 0;
	char c;

	while (read(hud_pipe, &c, 1) == 1) {
		if (c != '\\n' && at < sizeof(line) - 1) {
			line[at++] = c;
			continue;
		}
		if (c != '\\n') {
			continue;
		}
		line[at] = 0;
		const char *shown = strncmp(line, "net_test: ", 10) == 0 ? line + 10 : line;
		sysctlbyname("kern.redwood_note", NULL, NULL, (void *)shown, strlen(shown));
		at = 0;
		sleep(4);
	}
	return NULL;
}

static void
hud_start(void)
{
	int fds[2];

	if (pipe(fds) != 0) {
		return;
	}
	hud_pipe = fds[0];
	dup2(fds[1], STDOUT_FILENO);
	close(fds[1]);
	pthread_create(&hud_thread, NULL, hud_forward, NULL);
}

static void
hud_finish(void)
{
	if (hud_pipe < 0) {
		return;
	}
	fflush(stdout);
	close(STDOUT_FILENO);
	pthread_join(hud_thread, NULL);
}

""" + hold
if 'hud_forward' in n:
    print('userland/src/net_test.m: has hud already')
elif n.count(hold) != 1 or n.count('\treturn 0;\n}\n') < 1:
    raise SystemExit('userland/src/net_test.m: main is not where expected')
else:
    n = n.replace(hold, hnew)
    n = n.replace("""	setvbuf(stdout, NULL, _IOLBF, 0);
	@autoreleasepool {""", """	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc > 1 && strcmp(argv[1], "hud") == 0) {
		hud_start();
		argv++;
		argc--;
	}
	@autoreleasepool {""", 1)
    end = n.rindex('\treturn 0;\n}\n')
    n = n[:end] + '\thud_finish();\n' + n[end:]
    if '#include <pthread.h>' not in n:
        n = n.replace('#include <unistd.h>\n', '#include <unistd.h>\n#include <pthread.h>\n', 1)
    nt.open('w', encoding='utf-8', newline='').write(n)
    print('userland/src/net_test.m: hud')
jobs = tree / 'userland/rc.jobs.dohanet'
jobs.open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohanet, run-ios-flash.sh NETTEST=1): the lock screen swiped away as rc.jobs.unlock does, then
# the network tried layer by layer -- the address, a name, TCP, HTTPS, reachability -- each result on the panel's Keys line
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test hud waitaddr en0 180 resolve example.com tcp example.com 80 fetch https://example.com/ reach example.com resolve www.apple.com fetch https://www.apple.com/library/test/success.html
""")
print('userland/rc.jobs.dohanet: written')

# doha: mobileactivationd denied again. willow let it run (on its phone it answers at once: "Device is not activated",
# Code=-8); hakios-fajita (OnePlus 6T, no Secure Enclave either, Beta 0.3) found it trapping at every start and never
# answering what is queued for it -- apsd asks it while starting, amsaccountsd asks apsd, and Safari's main thread waits
# on AppleMediaServices: pages spin for ever although the network works, as here. Left out, everything that asks it gets
# its error at once. ALLOW=mobileactivationd lets it run again.
mj = tree / 'userland/mkjobs.py'
m = mj.open(encoding='utf-8', newline='').read()
mold = """        'homed', 'routined', 'duetexpertd', 'com.apple.dmd', 'syncdefaultsd', 'photoanalysisd', 'avconferenced')
"""
mnew = """        'homed', 'routined', 'duetexpertd', 'com.apple.dmd', 'syncdefaultsd', 'photoanalysisd', 'avconferenced',
        # doha (as hakios-fajita): it traps at every start and never answers; Safari waited on it through apsd and AMS
        'mobileactivationd')
"""
if "'mobileactivationd')" in m:
    print('userland/mkjobs.py: mobileactivationd denied already')
elif m.count(mold) != 1:
    raise SystemExit('userland/mkjobs.py: the end of DENY is not where expected')
else:
    mj.open('w', encoding='utf-8', newline='').write(m.replace(mold, mnew))
    print('userland/mkjobs.py: mobileactivationd denied (doha)')

# doha: hud_test (userland10/hud_test.c, beside this script): processes, crash reports and a test program's results on the
# panel's Keys line; and hakios-metal's probe (hakios-xnu-kernel's Metal driver, built for doha's RedwoodGPU into
# ~/doha-xnu/hakios-metal-doha, never in this repository) when it is there, run by rc.jobs.dohametal
# (run-ios-flash.sh METALTEST=1)
import shutil
shutil.copy(Path(__file__).parent / 'userland10' / 'hud_test.c', tree / 'userland/src/hud_test.c')
hb = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
hc_old = """		$DYN -fobjc-arc -framework Foundation -framework SystemConfiguration -o obj/net_test src/net_test.m
"""
hc_new = hc_old + """		$DYN -o obj/hud_test src/hud_test.c
"""
hi_old = """	[ -f obj/net_test ] && cp obj/net_test root/bin/
"""
hi_new = hi_old + """	[ -f obj/hud_test ] && cp obj/hud_test root/bin/
	[ -f $HOME/doha-xnu/hakios-metal-doha/out/ios/hakios-metal-probe ] && cp $HOME/doha-xnu/hakios-metal-doha/out/ios/hakios-metal-probe root/bin/
"""
if 'obj/hud_test' in hb:
    print('userland/build.sh: has hud_test already')
elif hb.count(hc_old) != 1 or hb.count(hi_old) != 1:
    raise SystemExit('userland/build.sh: net_test\'s lines are not where expected')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(hb.replace(hc_old, hc_new).replace(hi_old, hi_new))
    print('userland/build.sh: hud_test, and hakios-metal-probe when it is built')
(tree / 'userland/rc.jobs.dohametal').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohametal, run-ios-flash.sh METALTEST=1): the lock screen swiped away, then hakios-metal's probe on
# the Adreno 610 through RedwoodGPU -- copies, fills, command-buffer chains, kernels, a triangle -- each FAIL and the counts
# on the panel's Keys line, and the whole log on TCP port 7000 once the Wi-Fi has an address (WIFI=1 NETWORK=1)
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 20 say metal-probe-begins probe /redwood/bin/hakios-metal-probe wait 1800
""")
print('userland/rc.jobs.dohametal: written')

# doha: UniXNU's Metal on Vulkan (AdrenoMetal's frontend, metal2vulkan) over Turnip, built by hakios-xnu-kernel's
# tools/mk-mesa.sh, mk-turnip.sh and mk-m2v.sh in a clone of it (its hakios-drm pointed at RedwoodGPU), linked into
# its m2v_test, all in ~/doha-xnu/m2v-out (never in this repository): when they are there, into the small image
# (Turnip at /redwood/lib/libvulkan_freedreno.dylib, where m2v_test opens it), run by rc.jobs.dohamv (METALTEST=2)
mb = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
m_old = """	[ -f obj/hud_test ] && cp obj/hud_test root/bin/
"""
m_new = m_old + """	if [ -f $HOME/doha-xnu/m2v-out/m2v_test ] && [ -f $HOME/doha-xnu/m2v-out/libvulkan_freedreno.dylib ]; then
		mkdir -p root/lib
		cp $HOME/doha-xnu/m2v-out/m2v_test root/bin/
		cp $HOME/doha-xnu/m2v-out/libvulkan_freedreno.dylib root/lib/
		echo "build.sh: m2v_test and Turnip (Metal on Vulkan) in the image"
	fi
"""
if 'm2v-out/m2v_test' in mb:
    print('userland/build.sh: has m2v_test already')
elif mb.count(m_old) != 1:
    raise SystemExit('userland/build.sh: hud_test\'s line is not where expected')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(mb.replace(m_old, m_new))
    print('userland/build.sh: m2v_test and Turnip when they are built')
(tree / 'userland/rc.jobs.dohamv').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohamv, run-ios-flash.sh METALTEST=2): UniXNU's Metal on Vulkan over Turnip on the Adreno 610
# (m2v_test: the device, a blit, a clear, surfaces as textures), its output on TCP port 7000 and its FAILs on the panel.
# TU_DEBUG=noconform: Turnip gives the A610 (no multiview in hardware) Vulkan 1.0 otherwise, and metal2vulkan needs 1.2
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 20 env TU_DEBUG=startup,noconform say m2v-test-begins probe /redwood/bin/m2v_test wait 1800
""")
print('userland/rc.jobs.dohamv: written')

# doha: the window server through Metal (hakios-xnu-kernel's HakiosMetalCA.m over metal2vulkan and Turnip, as
# /redwood/lib/RedwoodMetal.bundle; kernel metal=2). CoreAnimation's Metal renderer asserts that QuartzCore has a
# default.metallib, which this iPhone X image has not got: hakios's tools/ca-metallib.py makes one (from this
# QuartzCore's pipeline library and a later CoreAnimation's) and its inject.c answers the window server's lookup of it
# with boot-arg ca_metallib=PATH. The same here, in backboardd before anything else of the window server's; with
# camtl=1 (inject.c's own switch) the window server keeps the Metal device. And the plug-in, its Info.plist and Turnip
# go into the small image from ~/doha-xnu/m2v-out when RedwoodMetal is built there (never in this repository).
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
iold = """static void
window_server_fixes(void)
{
	window_server_keeps_opengl_es();"""
inew = """/*
 * doha (as hakios's inject.c): CoreAnimation's Metal renderer asks QuartzCore's bundle for default.metallib and asserts
 * it is there; boot-arg ca_metallib=PATH answers that lookup, when it finds nothing, with PATH (tools/ca-metallib.py of
 * hakios-xnu-kernel makes the file). Every lookup of a metallib or pipelinelib in the window server is said, 40 at most.
 */
static id (*orig_url_for)(id self, SEL selector, id name, id extension);
static id (*orig_url_for_in)(id self, SEL selector, id name, id extension, id subdirectory);
static const char *ca_metallib;
static unsigned metallib_lookups_said;

static const char *
objc_utf8(id string)
{
	return string != NULL ? ((const char *(*)(id, SEL))objc_msgSend)(string, sel_registerName("UTF8String")) : "(nil)";
}

static id
metallib_answer(id self, id name, id extension, id found)
{
	const char *ext = extension != NULL ? objc_utf8(extension) : "";

	if (strstr(ext, "metallib") == NULL && strstr(ext, "pipelinelib") == NULL) {
		return found;
	}
	if (metallib_lookups_said++ < 40) {
		id path = found != NULL ? ((id (*)(id, SEL))objc_msgSend)(found, sel_registerName("path")) : NULL;

		say("redwood: %s asks bundle %s for %s.%s: %s\\n", getprogname(),
		    objc_utf8(((id (*)(id, SEL))objc_msgSend)(self, sel_registerName("bundlePath"))), objc_utf8(name), ext,
		    found != NULL ? objc_utf8(path) : "nothing");
	}
	if (found == NULL && ca_metallib != NULL && name != NULL && strcmp(objc_utf8(name), "default") == 0 &&
	    strcmp(ext, "metallib") == 0) {
		id text = ((id (*)(Class, SEL, const char *))objc_msgSend)(objc_getClass("NSString"),
		    sel_registerName("stringWithUTF8String:"), ca_metallib);

		return ((id (*)(Class, SEL, id))objc_msgSend)(objc_getClass("NSURL"), sel_registerName("fileURLWithPath:"), text);
	}
	return found;
}

static id
my_url_for(id self, SEL selector, id name, id extension)
{
	return metallib_answer(self, name, extension, orig_url_for(self, selector, name, extension));
}

static id
my_url_for_in(id self, SEL selector, id name, id extension, id subdirectory)
{
	return metallib_answer(self, name, extension, orig_url_for_in(self, selector, name, extension, subdirectory));
}

static void
watch_metallib_lookups(void)
{
	static char path[256];
	char arguments[1024] = "";
	size_t size = sizeof(arguments) - 1;
	const char *at;
	Class bundle = objc_getClass("NSBundle");
	Method two, three;

	if (sysctlbyname("kern.bootargs", arguments, &size, NULL, 0) != 0 || (at = strstr(arguments, "ca_metallib=")) == NULL) {
		return;                 /* (only a boot that names the library watches for it) */
	}
	size = strcspn(at + 12, " ");
	if (size < sizeof(path)) {
		memcpy(path, at + 12, size);
		ca_metallib = path;
	}
	if (bundle == NULL) {
		return;
	}
	if ((two = class_getInstanceMethod(bundle, sel_registerName("URLForResource:withExtension:"))) != NULL) {
		orig_url_for = (id (*)(id, SEL, id, id))method_setImplementation(two, (IMP)my_url_for);
	}
	if ((three = class_getInstanceMethod(bundle, sel_registerName("URLForResource:withExtension:subdirectory:"))) != NULL) {
		orig_url_for_in = (id (*)(id, SEL, id, id, id))method_setImplementation(three, (IMP)my_url_for_in);
	}
	say("redwood: metallib lookups in %s are said; default.metallib is %s\\n", getprogname(), ca_metallib);
}

static void
window_server_fixes(void)
{
	watch_metallib_lookups();
	window_server_keeps_opengl_es();"""
if 'watch_metallib_lookups' in i:
    print('userland/src/inject.c: has the metallib lookups already')
elif i.count(iold) != 1:
    raise SystemExit('userland/src/inject.c: window_server_fixes is not where expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(iold, inew))
    print('userland/src/inject.c: ca_metallib= answers default.metallib (doha)')
rb = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
r_old = """		echo "build.sh: m2v_test and Turnip (Metal on Vulkan) in the image"
	fi
"""
r_new = r_old + """	if [ -f $HOME/doha-xnu/m2v-out/RedwoodMetal ] && [ -f $HOME/doha-xnu/m2v-out/libvulkan_freedreno.dylib ] && [ -n "${DOHA_METAL_CA:-}" ]; then
		mkdir -p root/lib/RedwoodMetal.bundle
		cp $HOME/doha-xnu/m2v-out/RedwoodMetal root/lib/RedwoodMetal.bundle/RedwoodMetal
		cp $HOME/doha-xnu/m2v-out/libvulkan_freedreno.dylib root/lib/
		rm -f root/bin/m2v_test
		cat > root/lib/RedwoodMetal.bundle/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>com.redwood.metal</string>
	<key>CFBundleName</key>
	<string>RedwoodMetal</string>
	<key>CFBundleExecutable</key>
	<string>RedwoodMetal</string>
	<key>CFBundlePackageType</key>
	<string>BNDL</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>CFBundleSupportedPlatforms</key>
	<array>
		<string>iPhoneOS</string>
	</array>
	<key>NSPrincipalClass</key>
	<string>HakiosMetalDevice</string>
</dict>
</plist>
PLIST
		echo "build.sh: RedwoodMetal.bundle (hakios's plug-in for CoreAnimation over metal2vulkan) and Turnip in the image"
	fi
"""
if 'RedwoodMetal.bundle/RedwoodMetal' in rb:
    print('userland/build.sh: has the CoreAnimation plug-in already')
elif rb.count(r_old) != 1:
    raise SystemExit('userland/build.sh: the m2v_test lines are not where expected')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(rb.replace(r_old, r_new))
    print('userland/build.sh: RedwoodMetal.bundle when DOHA_METAL_CA is set')

# doha: with DOHA_METAL_CA (METALCA=1) the bundle is hakios's plug-in, put there above; willow's own RedwoodMetal
# (src/redwoodmetal.m, compute and a triangle) is built under the same name and was copied over it after
rw = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
w_old = """	if [ -f obj/RedwoodMetal ]; then
		mkdir -p root/lib/RedwoodMetal.bundle
		cp obj/RedwoodMetal root/lib/RedwoodMetal.bundle/"""
w_new = """	if [ -f obj/RedwoodMetal ] && [ -z "${DOHA_METAL_CA:-}" ]; then
		mkdir -p root/lib/RedwoodMetal.bundle
		cp obj/RedwoodMetal root/lib/RedwoodMetal.bundle/"""
if w_new in rw:
    print("userland/build.sh: willow's RedwoodMetal stays out with DOHA_METAL_CA already")
elif rw.count(w_old) != 1:
    raise SystemExit("userland/build.sh: willow's RedwoodMetal copy is not where expected")
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(rw.replace(w_old, w_new))
    print("userland/build.sh: willow's RedwoodMetal stays out with DOHA_METAL_CA")

# doha: a boot through Metal whose log can be read (run-ios-flash.sh METALCA=1). The window server's standard error --
# where inject.c's lines, HakiosMetal's (hm_print) and Turnip's go -- is the console, which the picture covers; with
# ca_metallib= it is the file /private/var/tmp/redwood-ws.log instead, and rc.jobs.dohaca has hud_test send that file
# and the kernel's log over TCP port 7000 (hud_test watch), the lock screen swiped away as rc.jobs.unlock does
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
iold = """	if (size < sizeof(path)) {
		memcpy(path, at + 12, size);
		ca_metallib = path;
	}
"""
inew = iold + """	/* the window server's standard error into a file hud_test reads (watch), not the console the picture covers */
	mkdir("/private/var/tmp", 0777);
	{
		int log = open("/private/var/tmp/redwood-ws.log", O_WRONLY | O_CREAT | O_APPEND, 0644);

		if (log >= 0) {
			dup2(log, 2);
			close(log);
		}
	}
"""
if 'redwood-ws.log' in i:
    print('userland/src/inject.c: the window server says into redwood-ws.log already')
elif i.count(iold) != 1:
    raise SystemExit('userland/src/inject.c: ca_metallib= is not where expected')
else:
    if '#include <sys/stat.h>' not in i:
        i = i.replace('#include <sys/sysctl.h>\n', '#include <sys/stat.h>\n#include <sys/sysctl.h>\n', 1)
    ij.open('w', encoding='utf-8', newline='').write(i.replace(iold, inew))
    print('userland/src/inject.c: with ca_metallib= the window server says into /private/var/tmp/redwood-ws.log')
(tree / 'userland/rc.jobs.dohaca').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohaca, run-ios-flash.sh METALCA=1): the window server through Metal; the lock screen swiped
# away, then its log (inject.c, HakiosMetal, Turnip: /private/var/tmp/redwood-ws.log) and the kernel's on TCP port 7000
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 5 ps backboardd watch 240 /private/var/tmp/redwood-ws.log crashes ps backboardd watch 3000 /private/var/tmp/redwood-ws.log
""")
print('userland/rc.jobs.dohaca: written')

# doha: with camtl=1 CoreAnimation still took OpenGL ES and HakiosMetal said nothing at all (its bundle never loaded,
# or never got as far as a line). Each step Metal takes on the way to the plug-in, said once in the window server
# before CoreAnimation asks: the accelerator's MetalPluginName, the bundle, its loading (and NSError), its principal
# class, and MTLCreateSystemDefaultDevice() -- which is what CoreAnimation's next call would do anyway
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
dold = """static void
watch_metallib_lookups(void)
{"""
dnew = """static const char *
objc_describe(id object)
{
	return object != NULL ? objc_utf8(((id (*)(id, SEL))objc_msgSend)(object, sel_registerName("description"))) : "nil";
}

/* doha: each step of Metal's way to our plug-in in this process, said (camtl=1 boots only) */
static void
metal_diagnose(void)
{
	io_service_t accelerator = IOServiceGetMatchingService(0, IOServiceMatching("IOAcceleratorES"));
	char name[128] = "(none)", klass[128] = "(none)";
	id path, bundle, error = NULL;
	BOOL loaded;
	Class principal;
	id (*create)(void);
	id device;

	if (accelerator != 0) {
		CFTypeRef n = IORegistryEntryCreateCFProperty(accelerator, CFSTR("MetalPluginName"), kCFAllocatorDefault, 0);
		CFTypeRef c = IORegistryEntryCreateCFProperty(accelerator, CFSTR("MetalPluginClassName"), kCFAllocatorDefault, 0);

		if (n != NULL && CFGetTypeID(n) == CFStringGetTypeID()) {
			CFStringGetCString((CFStringRef)n, name, sizeof(name), kCFStringEncodingUTF8);
		}
		if (c != NULL && CFGetTypeID(c) == CFStringGetTypeID()) {
			CFStringGetCString((CFStringRef)c, klass, sizeof(klass), kCFStringEncodingUTF8);
		}
		if (n != NULL) {
			CFRelease(n);
		}
		if (c != NULL) {
			CFRelease(c);
		}
		IOObjectRelease(accelerator);
	}
	say("redwood: metal-diag: IOAcceleratorES %s; MetalPluginName %s, MetalPluginClassName %s\\n",
	    accelerator != 0 ? "found" : "NOT FOUND", name, klass);
	path = ((id (*)(Class, SEL, const char *))objc_msgSend)(objc_getClass("NSString"),
	    sel_registerName("stringWithUTF8String:"), "/System/Library/Extensions/RedwoodMetal.bundle");
	bundle = ((id (*)(Class, SEL, id))objc_msgSend)(objc_getClass("NSBundle"), sel_registerName("bundleWithPath:"), path);
	say("redwood: metal-diag: bundle %s, executable %s, access %d\\n", objc_describe(bundle),
	    bundle != NULL ? objc_describe(((id (*)(id, SEL))objc_msgSend)(bundle, sel_registerName("executablePath"))) : "-",
	    access("/System/Library/Extensions/RedwoodMetal.bundle/RedwoodMetal", R_OK));
	if (bundle != NULL) {
		loaded = ((BOOL (*)(id, SEL, id *))objc_msgSend)(bundle, sel_registerName("loadAndReturnError:"), &error);
		principal = ((Class (*)(id, SEL))objc_msgSend)(bundle, sel_registerName("principalClass"));
		say("redwood: metal-diag: loaded %d, error %s, principal class %s\\n", (int)loaded, objc_describe(error),
		    principal != NULL ? class_getName(principal) : "nil");
		if (!loaded) {
			void *h = dlopen("/System/Library/Extensions/RedwoodMetal.bundle/RedwoodMetal", RTLD_NOW);

			say("redwood: metal-diag: dlopen %s\\n", h != NULL ? "worked" : dlerror());
		}
	}
	create = (id (*)(void))dlsym(RTLD_DEFAULT, "MTLCreateSystemDefaultDevice");
	device = create != NULL ? create() : NULL;
	say("redwood: metal-diag: MTLCreateSystemDefaultDevice() = %s (%s)\\n", device != NULL ? object_getClassName(device) : "nil",
	    create != NULL ? "Metal is linked" : "Metal is NOT in this process");
}

static void
watch_metallib_lookups(void)
{"""
cold = """	say("redwood: metallib lookups in %s are said; default.metallib is %s\\n", getprogname(), ca_metallib);
"""
cnew = cold + """	metal_diagnose();
"""
if 'metal_diagnose' in i:
    print('userland/src/inject.c: has metal_diagnose already')
elif i.count(dold) != 1 or i.count(cold) != 1:
    raise SystemExit('userland/src/inject.c: watch_metallib_lookups is not where expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(dold, dnew).replace(cold, cnew))
    print('userland/src/inject.c: metal_diagnose in the window server (doha)')

# doha: metal-diag opens the bundle as Metal does: "/System/Library/Extensions/" + MetalPluginName + ".bundle"
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
pold = """	path = ((id (*)(Class, SEL, const char *))objc_msgSend)(objc_getClass("NSString"),
	    sel_registerName("stringWithUTF8String:"), "/System/Library/Extensions/RedwoodMetal.bundle");"""
pnew = """	{
		char where[256];

		snprintf(where, sizeof(where), "/System/Library/Extensions/%s.bundle", name);
		path = ((id (*)(Class, SEL, const char *))objc_msgSend)(objc_getClass("NSString"),
		    sel_registerName("stringWithUTF8String:"), where);
	}"""
aold = """	    access("/System/Library/Extensions/RedwoodMetal.bundle/RedwoodMetal", R_OK));"""
anew = """	    access("/redwood/lib/RedwoodMetal.bundle/RedwoodMetal", R_OK));"""
dlold = """dlopen("/System/Library/Extensions/RedwoodMetal.bundle/RedwoodMetal", RTLD_NOW)"""
dlnew = """dlopen("/redwood/lib/RedwoodMetal.bundle/RedwoodMetal", RTLD_NOW)"""
if 'Extensions/%s.bundle' in i:
    print('userland/src/inject.c: metal-diag opens the bundle by its name already')
elif i.count(pold) != 1 or i.count(aold) != 1 or i.count(dlold) != 1:
    raise SystemExit('userland/src/inject.c: metal_diagnose is not what was expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(pold, pnew).replace(aold, anew).replace(dlold, dlnew))
    print('userland/src/inject.c: metal-diag opens the bundle by MetalPluginName')

# doha: where the window server's threads spend their time (boot-arg ws_prof=MICROSECONDS): every thread of it stopped
# that often, its program counter, link register and frame chain read, and every 400 looks the commonest stacks said
# with their images and symbols (as hakios's ca_prof, which only its own Metal path starts). Through Metal on Vulkan the
# window server makes a pipeline in bursts some 75 s apart and commits nothing: this says where it waits
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
sold = """/* doha: each step of Metal's way to our plug-in in this process, said (camtl=1 boots only) */"""
snew = """#define WS_PROF_DEPTH   12
#define WS_PROF_SLOTS   512
#define WS_PROF_DUMP    400

static struct ws_prof_slot {
	uint64_t        stack[WS_PROF_DEPTH];
	char            name[32];
	unsigned        count;
} ws_prof_table[WS_PROF_SLOTS];
static unsigned ws_prof_us;

static int
ws_prof_order(const void *a, const void *b)
{
	const struct ws_prof_slot *x = a, *y = b;

	return x->count < y->count ? 1 : x->count > y->count ? -1 : 0;
}

static void *
ws_prof_main(void *unused)
{
	thread_t self = mach_thread_self();
	unsigned looks = 0;

	(void)unused;
	pthread_setname_np("redwood-ws-prof");
	for (;;) {
		thread_act_array_t threads;
		mach_msg_type_number_t n = 0;

		usleep(ws_prof_us);
		if (task_threads(mach_task_self(), &threads, &n) != KERN_SUCCESS) {
			continue;
		}
		looks++;
		for (mach_msg_type_number_t t = 0; t < n; t++) {
			thread_extended_info_data_t ext;
			mach_msg_type_number_t count = THREAD_EXTENDED_INFO_COUNT;
			arm_thread_state64_t state;
			mach_msg_type_number_t state_count = ARM_THREAD_STATE64_COUNT;
			uint64_t stack[WS_PROF_DEPTH] = { 0 }, hash = 0;
			kern_return_t got;

			if (threads[t] == self || thread_info(threads[t], THREAD_EXTENDED_INFO, (thread_info_t)&ext, &count) != KERN_SUCCESS ||
			    thread_suspend(threads[t]) != KERN_SUCCESS) {
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}
			got = thread_get_state(threads[t], ARM_THREAD_STATE64, (thread_state_t)&state, &state_count);
			if (got == KERN_SUCCESS) {
				uint64_t sp = arm_thread_state64_get_sp(state), fp = arm_thread_state64_get_fp(state), top = 0;
				pthread_t pt = pthread_from_mach_thread_np(threads[t]);

				/* the frame chain followed only within the thread's own stack */
				if (pt != NULL) {
					top = (uint64_t)(uintptr_t)pthread_get_stackaddr_np(pt);
				}
				stack[0] = arm_thread_state64_get_pc(state);
				stack[1] = arm_thread_state64_get_lr(state) & 0x0000000fffffffffull;
				for (unsigned d = 2; d < WS_PROF_DEPTH && top != 0 && fp >= sp && fp + 16 <= top && (fp & 15) == 0; d++) {
					const uint64_t *record = (const uint64_t *)(uintptr_t)fp;

					stack[d] = record[1] & 0x0000000fffffffffull;
					if (record[0] <= fp) {
						break;
					}
					fp = record[0];
				}
			}
			thread_resume(threads[t]);
			mach_port_deallocate(mach_task_self(), threads[t]);
			if (got != KERN_SUCCESS) {
				continue;
			}
			for (unsigned d = 0; d < WS_PROF_DEPTH; d++) {
				hash = (hash ^ stack[d]) * 0x9e3779b97f4a7c15ull;
			}
			for (unsigned i = (unsigned)(hash >> 32) % WS_PROF_SLOTS, probes = 0; probes < WS_PROF_SLOTS;
			    i = (i + 1) % WS_PROF_SLOTS, probes++) {
				if (ws_prof_table[i].count == 0 || memcmp(ws_prof_table[i].stack, stack, sizeof(stack)) == 0) {
					memcpy(ws_prof_table[i].stack, stack, sizeof(stack));
					strlcpy(ws_prof_table[i].name, ext.pth_name[0] ? ext.pth_name : "(unnamed)", sizeof(ws_prof_table[i].name));
					ws_prof_table[i].count++;
					break;
				}
			}
		}
		vm_deallocate(mach_task_self(), (vm_address_t)threads, n * sizeof(thread_t));
		if (looks < WS_PROF_DUMP) {
			continue;
		}
		qsort(ws_prof_table, WS_PROF_SLOTS, sizeof(ws_prof_table[0]), ws_prof_order);
		say("redwood: ws-prof: %u looks at every thread\\n", looks);
		for (unsigned i = 0; i < 14 && ws_prof_table[i].count != 0; i++) {
			char line[1800];
			int at = snprintf(line, sizeof(line), "redwood: ws-prof: %s %.0f%%:", ws_prof_table[i].name,
			    100.0 * ws_prof_table[i].count / looks);

			for (unsigned d = 0; d < WS_PROF_DEPTH && ws_prof_table[i].stack[d] != 0 && at < (int)sizeof(line) - 120; d++) {
				Dl_info where = { 0 };
				const char *image = "?", *slash;
				uint64_t offset = ws_prof_table[i].stack[d];

				if (dladdr((void *)(uintptr_t)offset, &where) != 0 && where.dli_fname != NULL) {
					image = (slash = strrchr(where.dli_fname, '/')) != NULL ? slash + 1 : where.dli_fname;
					offset -= (uint64_t)(uintptr_t)where.dli_fbase;
				}
				at += snprintf(line + at, sizeof(line) - (size_t)at, " %s+0x%llx(%s)", image, (unsigned long long)offset,
				    where.dli_sname != NULL ? where.dli_sname : "?");
			}
			say("%s\\n", line);
		}
		memset(ws_prof_table, 0, sizeof(ws_prof_table));
		looks = 0;
	}
	return NULL;
}

static void
ws_prof_start(const char *arguments)
{
	const char *at = strstr(arguments, "ws_prof=");
	pthread_t sampler;

	if (at == NULL || (ws_prof_us = (unsigned)atoi(at + 8)) == 0) {
		return;
	}
	if (pthread_create(&sampler, NULL, ws_prof_main, NULL) == 0) {
		pthread_detach(sampler);
		say("redwood: ws-prof: every thread of %s looked at every %u us\\n", getprogname(), ws_prof_us);
	}
}

/* doha: each step of Metal's way to our plug-in in this process, said (camtl=1 boots only) */"""
cold = """	metal_diagnose();
"""
cnew = """	metal_diagnose();
	ws_prof_start(arguments);
"""
if 'ws_prof_start' in i:
    print('userland/src/inject.c: has ws_prof already')
elif i.count(sold) != 1 or i.count(cold) != 1:
    raise SystemExit('userland/src/inject.c: metal_diagnose is not where expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(sold, snew).replace(cold, cnew))
    print('userland/src/inject.c: ws_prof= samples the window server (doha)')

# doha: rc.jobs.dohaca samples the window server from outside (hud_test sample: task_for_pid, every 20 ms), through the
# minutes in which, on Metal over Vulkan, it makes its first pipelines and draws nothing
(tree / 'userland/rc.jobs.dohaca').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohaca, run-ios-flash.sh METALCA=1): the window server through Metal; the lock screen swiped
# away, then its log (inject.c, HakiosMetal, Turnip: /private/var/tmp/redwood-ws.log) and the kernel's on TCP port 7000,
# and where its threads spend the first minutes (hud_test sample)
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 5 ps backboardd watch 15 /private/var/tmp/redwood-ws.log sample backboardd 480 crashes watch 3000 /private/var/tmp/redwood-ws.log
""")
print('userland/rc.jobs.dohaca: hud_test samples backboardd')

# doha: ws_prof said that it started and then nothing: pthread_from_mach_thread_np() takes libpthread's list lock, and
# with a thread stopped that holds it, the sampler waits for ever (and that thread is never let go). While a thread is
# stopped only the kernel is called now: its state, and the frame chain read with vm_read_overwrite (no lock, no fault).
# And from outside it cannot be done: hud_test's task_for_pid answers, but backboardd's threads are not listed for it
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
old = """			got = thread_get_state(threads[t], ARM_THREAD_STATE64, (thread_state_t)&state, &state_count);
			if (got == KERN_SUCCESS) {
				uint64_t sp = arm_thread_state64_get_sp(state), fp = arm_thread_state64_get_fp(state), top = 0;
				pthread_t pt = pthread_from_mach_thread_np(threads[t]);

				/* the frame chain followed only within the thread's own stack */
				if (pt != NULL) {
					top = (uint64_t)(uintptr_t)pthread_get_stackaddr_np(pt);
				}
				stack[0] = arm_thread_state64_get_pc(state);
				stack[1] = arm_thread_state64_get_lr(state) & 0x0000000fffffffffull;
				for (unsigned d = 2; d < WS_PROF_DEPTH && top != 0 && fp >= sp && fp + 16 <= top && (fp & 15) == 0; d++) {
					const uint64_t *record = (const uint64_t *)(uintptr_t)fp;

					stack[d] = record[1] & 0x0000000fffffffffull;
					if (record[0] <= fp) {
						break;
					}
					fp = record[0];
				}
			}"""
new = """			got = thread_get_state(threads[t], ARM_THREAD_STATE64, (thread_state_t)&state, &state_count);
			if (got == KERN_SUCCESS) {
				uint64_t sp = arm_thread_state64_get_sp(state), fp = arm_thread_state64_get_fp(state);

				/* (nothing that takes a lock while the thread is stopped: the kernel alone reads its frames) */
				stack[0] = arm_thread_state64_get_pc(state) & 0x0000000fffffffffull;
				stack[1] = arm_thread_state64_get_lr(state) & 0x0000000fffffffffull;
				for (unsigned d = 2; d < WS_PROF_DEPTH && fp >= sp && fp - sp < (16u << 20) && (fp & 15) == 0; d++) {
					uint64_t record[2];
					vm_size_t read = 0;

					if (vm_read_overwrite(mach_task_self(), (vm_address_t)fp, sizeof(record), (vm_address_t)record,
					    &read) != KERN_SUCCESS || read != sizeof(record)) {
						break;
					}
					stack[d] = record[1] & 0x0000000fffffffffull;
					if (record[0] <= fp) {
						break;
					}
					fp = record[0];
				}
			}"""
if 'the kernel alone reads its frames' in i:
    print('userland/src/inject.c: ws_prof takes no lock already')
elif i.count(old) != 1:
    raise SystemExit('userland/src/inject.c: ws_prof is not what was expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(old, new))
    print('userland/src/inject.c: ws_prof takes no lock with a thread stopped')
(tree / 'userland/rc.jobs.dohaca').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohaca, run-ios-flash.sh METALCA=1): the window server through Metal; the lock screen swiped
# away, then its log (inject.c, HakiosMetal, Turnip, ws_prof: /private/var/tmp/redwood-ws.log) and the kernel's on TCP
# port 7000
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 5 ps backboardd watch 240 /private/var/tmp/redwood-ws.log crashes watch 3000 /private/var/tmp/redwood-ws.log
""")
print('userland/rc.jobs.dohaca: the log alone again')

# doha: ws_prof still said nothing after it started. Not a lock this time: thread_get_state() waits for the thread to come
# out of the kernel, and a thread in an uninterruptible wait there keeps the sampler waiting with it. So a thread whose
# state is TH_STATE_UNINTERRUPTIBLE is not stopped at all: it is counted by its name, as "in the kernel", and every dump
# says those counts first -- which threads of the window server sit in the kernel, and for what share of the time
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
o1 = """			if (threads[t] == self || thread_info(threads[t], THREAD_EXTENDED_INFO, (thread_info_t)&ext, &count) != KERN_SUCCESS ||
			    thread_suspend(threads[t]) != KERN_SUCCESS) {
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}"""
n1 = """			if (threads[t] == self || thread_info(threads[t], THREAD_EXTENDED_INFO, (thread_info_t)&ext, &count) != KERN_SUCCESS) {
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}
			if (ext.pth_run_state == TH_STATE_UNINTERRUPTIBLE) {
				/* (stopping it would mean waiting for it: counted by name instead) */
				ws_prof_kernel(ext.pth_name[0] ? ext.pth_name : "(unnamed)");
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}
			if (thread_suspend(threads[t]) != KERN_SUCCESS) {
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}"""
o2 = """static int
ws_prof_order(const void *a, const void *b)"""
n2 = """/* threads found in an uninterruptible wait in the kernel, by name, since the last dump */
static struct {
	char            name[32];
	unsigned        count;
} ws_prof_in_kernel[32];

static void
ws_prof_kernel(const char *name)
{
	for (unsigned k = 0; k < 32; k++) {
		if (ws_prof_in_kernel[k].count == 0 || strcmp(ws_prof_in_kernel[k].name, name) == 0) {
			strlcpy(ws_prof_in_kernel[k].name, name, sizeof(ws_prof_in_kernel[k].name));
			ws_prof_in_kernel[k].count++;
			return;
		}
	}
}

static int
ws_prof_order(const void *a, const void *b)"""
o3 = """		say("redwood: ws-prof: %u looks at every thread\\n", looks);
"""
n3 = """		say("redwood: ws-prof: %u looks at every thread\\n", looks);
		for (unsigned k = 0; k < 32 && ws_prof_in_kernel[k].count != 0; k++) {
			say("redwood: ws-prof: in the kernel, not to be interrupted: %s %.0f%%\\n", ws_prof_in_kernel[k].name,
			    100.0 * ws_prof_in_kernel[k].count / looks);
		}
		memset(ws_prof_in_kernel, 0, sizeof(ws_prof_in_kernel));
"""
if 'ws_prof_kernel' in i:
    print('userland/src/inject.c: ws_prof passes over threads in the kernel already')
elif i.count(o1) != 1 or i.count(o2) != 1 or i.count(o3) != 1:
    raise SystemExit('userland/src/inject.c: ws_prof is not what was expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(o1, n1).replace(o2, n2).replace(o3, n3))
    print('userland/src/inject.c: ws_prof counts threads in the kernel instead of stopping them')

# doha: ws_prof, inside the window server, never said a word in three boots; hud_test's threads step reads every thread's
# processor time and state from outside (proc_pidinfo) every 5 s instead, beside the log
(tree / 'userland/rc.jobs.dohaca').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohaca, run-ios-flash.sh METALCA=1): the window server through Metal; the lock screen swiped
# away, then its log (inject.c, HakiosMetal, Turnip: /private/var/tmp/redwood-ws.log), the kernel's and, every 5 s, the
# processor time and state of the window server's threads (hud_test threads) on TCP port 7000
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 5 ps backboardd threads backboardd watch 240 /private/var/tmp/redwood-ws.log crashes watch 3000 /private/var/tmp/redwood-ws.log
""")
print('userland/rc.jobs.dohaca: hud_test threads backboardd')

# doha: metal2vulkan's own table of where the processor's time goes (pipelines, libraries, functions, compiles, the
# shader cache: native_bridge_metal_telemetry, in the plug-in) written every 20 s straight into redwood-ws.log with
# boot-arg ws_timing=1. Its NATIVE_METAL_TIMING=1 writes it to standard error, and HakiosMetal passes on only the first 40
# lines of that (backboardd's own fill them), so it never reached the log
ij = tree / 'userland/src/inject.c'
i = ij.open(encoding='utf-8', newline='').read()
o1 = """		if (log >= 0) {
			dup2(log, 2);
			close(log);
		}"""
n1 = """		if (log >= 0) {
			dup2(log, 2);
			ws_log_fd = log;        /* (kept: the plug-in puts a pipe of its own on 2 later) */
		}"""
o2 = """/* doha: each step of Metal's way to our plug-in in this process, said (camtl=1 boots only) */"""
n2 = """static int ws_log_fd = -1;

/* doha (ws_timing=1): metal2vulkan's telemetry table, every 20 s, into the window server's log file itself */
static void *
ws_timing_main(void *unused)
{
	static char table[8192];
	size_t (*telemetry)(char *, size_t) = NULL;

	(void)unused;
	pthread_setname_np("redwood-ws-timing");
	for (;;) {
		sleep(20);
		if (telemetry == NULL) {
			telemetry = (size_t (*)(char *, size_t))dlsym(RTLD_DEFAULT, "native_bridge_metal_telemetry");
		}
		if (telemetry != NULL && ws_log_fd >= 0) {
			size_t n = telemetry(table, sizeof(table) - 1);
			const char *title = "redwood: ws-timing: metal2vulkan's table:\\n";

			if (n >= sizeof(table)) {
				n = sizeof(table) - 1;
			}
			(void)!write(ws_log_fd, title, strlen(title));
			(void)!write(ws_log_fd, table, n);
			if (n > 0 && table[n - 1] != '\\n') {
				(void)!write(ws_log_fd, "\\n", 1);
			}
		}
	}
	return NULL;
}

/* doha: each step of Metal's way to our plug-in in this process, said (camtl=1 boots only) */"""
o3 = """	ws_prof_start(arguments);
"""
n3 = """	ws_prof_start(arguments);
	if (strstr(arguments, "ws_timing=1") != NULL) {
		pthread_t timing;

		if (pthread_create(&timing, NULL, ws_timing_main, NULL) == 0) {
			pthread_detach(timing);
			say("redwood: ws-timing: metal2vulkan's table every 20 s\\n");
		}
	}
"""
if 'ws_timing_main' in i:
    print('userland/src/inject.c: has ws_timing already')
elif i.count(o1) != 1 or i.count(o2) != 1 or i.count(o3) != 1:
    raise SystemExit('userland/src/inject.c: the window server log is not where expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(o1, n1).replace(o2, n2).replace(o3, n3))
    print('userland/src/inject.c: ws_timing=1 writes metal2vulkan\'s telemetry into the log')

# doha: metal2vulkan's shader cache (/private/var/db/m2v, which var_store should keep) never hits at the next boot:
# rc.jobs.dohaca says first what is in it and what the store holds, before the window server has written anything
(tree / 'userland/rc.jobs.dohaca').open('w', encoding='utf-8', newline='\n').write("""# Commands run by the launchd job com.redwood.demo (see com.redwood.demo.plist).
# doha (RC_JOBS=rc.jobs.dohaca, run-ios-flash.sh METALCA=1): the window server through Metal; the lock screen swiped
# away, then on TCP port 7000: what the shader caches and var_store's store hold, the window server's log (inject.c,
# HakiosMetal, Turnip: /private/var/tmp/redwood-ws.log), the kernel's and its threads' processor time every 5 s
/redwood/bin/rwtouch wait 32 swipe 0.5 0.985 0.5 0.3 250 &
/redwood/bin/net_test waitaddr en0 180
/redwood/bin/hud_test serve 7000 wait 5 du /private/var/db/m2v du /private/var/root/Library/Caches run /redwood/bin/var_store,show ps backboardd threads backboardd watch 240 /private/var/tmp/redwood-ws.log crashes du /private/var/db/m2v watch 3000 /private/var/tmp/redwood-ws.log
""")
print('userland/rc.jobs.dohaca: the caches and the store said first')

# doha: metal2vulkan's shader cache never outlived a boot. HakiosMetal gives it /private/var/db/m2v (var_store keeps
# /private/var/db) if it can write there, /private/var/tmp/m2v otherwise (var_store leaves tmp out); backboardd runs as
# mobile and cannot make a directory in root's /private/var/db, so every boot compiled the window server's pipelines
# again (minutes: 79 s for one). init makes the directory, mobile's, from the image's var.skel
bs = (tree / 'userland/build.sh').open(encoding='utf-8', newline='').read()
v_old = """	cp $IOS/var.skel root/etc/var.skel              # the directories init creates in /private/var
"""
v_new = v_old + """	# doha: metal2vulkan's shader cache, where the window server (mobile) can write it and var_store keeps it
	printf 'd\t700\t501\t501\t/private/var/db/m2v\n' >> root/etc/var.skel
"""
if '/private/var/db/m2v' in bs:
    print('userland/build.sh: var.skel has /private/var/db/m2v already')
elif bs.count(v_old) != 1:
    raise SystemExit('userland/build.sh: the var.skel line is not where expected')
else:
    (tree / 'userland/build.sh').open('w', encoding='utf-8', newline='').write(bs.replace(v_old, v_new))
    print('userland/build.sh: /private/var/db/m2v, mobile\'s, in var.skel')

# doha: the HUD's level climbs while charging but the status bar's icon stays where it was, locking and unlocking
# included: UIDevice's notifications every 5 s do not make iOS 16's status bar ask again, and _UIBatteryView redraws only
# when somebody calls setChargePercent:. So when the kernel's level changes, every _UIBatteryView in SpringBoard's windows
# (internal ones too: the status bars are not in -[UIApplication windows]) is given it, and laid out again
ij = tree / 'userland/src/inject_sb.c'
i = ij.open(encoding='utf-8', newline='').read()
a_old = """/* Keep SpringBoard's normal battery observers awake while the XNU cache changes. */
static void
battery_post_notifications(void)
{"""
a_new = """/* doha: every _UIBatteryView under VIEW given the kernel's level (setChargePercent: goes through the hook above) */
static unsigned
battery_views_under(id view, Class battery_view, double level, unsigned depth)
{
	unsigned found = 0;
	id subviews;
	unsigned long count;

	if (view == nil || depth > 40) {
		return 0;
	}
	if (((BOOL (*)(id, SEL, Class))objc_msgSend)(view, sel_registerName("isKindOfClass:"), battery_view)) {
		((void (*)(id, SEL, double))objc_msgSend)(view, sel_registerName("setChargePercent:"), level);
		((void (*)(id, SEL))objc_msgSend)(view, sel_registerName("setNeedsLayout"));
		((void (*)(id, SEL))objc_msgSend)(view, sel_registerName("setNeedsDisplay"));
		found++;
	}
	subviews = ((id (*)(id, SEL))objc_msgSend)(view, sel_registerName("subviews"));
	count = subviews != nil ? ((unsigned long (*)(id, SEL))objc_msgSend)(subviews, sel_registerName("count")) : 0;
	for (unsigned long k = 0; k < count; k++) {
		found += battery_views_under(((id (*)(id, SEL, unsigned long))objc_msgSend)(subviews, sel_registerName("objectAtIndex:"), k),
		    battery_view, level, depth + 1);
	}
	return found;
}

/* doha: the status bar's battery views told when the kernel's level has changed (main queue) */
static void
battery_views_refresh(void)
{
	static int shown = -1;
	static unsigned said;
	int soc = sysctl_int("kern.redwood.battery_soc");
	Class window_class = objc_getClass("UIWindow"), battery_view = objc_getClass("_UIBatteryView");
	SEL all = sel_registerName("allWindowsIncludingInternalWindows:onlyVisibleWindows:");
	id windows = nil;
	unsigned long count;
	unsigned found = 0;

	if (soc < 0 || soc > 100 || soc == shown || battery_power_source() || window_class == Nil || battery_view == Nil) {
		return;
	}
	if (class_getClassMethod(window_class, all) != NULL) {
		windows = ((id (*)(Class, SEL, BOOL, BOOL))objc_msgSend)(window_class, all, YES, NO);
	}
	if (windows == nil) {
		id application = ((id (*)(Class, SEL))objc_msgSend)(objc_getClass("UIApplication"), sel_registerName("sharedApplication"));

		windows = application != nil ? ((id (*)(id, SEL))objc_msgSend)(application, sel_registerName("windows")) : nil;
	}
	count = windows != nil ? ((unsigned long (*)(id, SEL))objc_msgSend)(windows, sel_registerName("count")) : 0;
	for (unsigned long k = 0; k < count; k++) {
		found += battery_views_under(((id (*)(id, SEL, unsigned long))objc_msgSend)(windows, sel_registerName("objectAtIndex:"), k),
		    battery_view, (double)soc / 100.0, 0);
	}
	if (found != 0) {
		shown = soc;
	}
	if (said++ < 6 || found == 0) {
		if (said < 40) {
			say("redwood: battery UI: level %d%% given to %u battery views in %lu windows\\n", soc, found, count);
		}
	}
}

/* Keep SpringBoard's normal battery observers awake while the XNU cache changes. */
static void
battery_post_notifications(void)
{"""
b_old = """	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
		battery_post_notifications();
	});"""
b_new = """	battery_views_refresh();
	dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
		battery_post_notifications();
	});"""
if 'battery_views_refresh' in i:
    print('userland/src/inject_sb.c: the battery views are refreshed already')
elif i.count(a_old) != 1 or i.count(b_old) != 1:
    raise SystemExit('userland/src/inject_sb.c: battery_post_notifications is not where expected')
else:
    ij.open('w', encoding='utf-8', newline='').write(i.replace(a_old, a_new).replace(b_old, b_new))
    print('userland/src/inject_sb.c: the battery views of the status bar given the level when it changes (doha)')
