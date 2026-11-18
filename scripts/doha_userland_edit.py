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
