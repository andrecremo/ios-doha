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
