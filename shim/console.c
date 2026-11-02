/*
 * Minimal text console on the ABL splash framebuffer (from ios-sweet).
 * With the MMU off every access is Device memory, so stay aligned
 * (-mstrict-align): 24-bit pixels are written as three byte stores.
 */
#include "console.h"
#include "font.h"

#define SCALE		3
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		24
#define LABEL_COLS	8

static uintptr_t fb_base;
static int fb_w, fb_h, fb_stride, fb_bpp;
static uint32_t con_bg;
static int row;

void con_setup(uintptr_t base, int w, int h, int stride, int bpp)
{
	fb_base = base;
	fb_w = w;
	fb_h = h;
	fb_stride = stride;
	fb_bpp = bpp;
}

static inline void put_px(int x, int y, uint32_t c)
{
	uintptr_t p = fb_base + (uintptr_t)y * fb_stride + (uintptr_t)x * fb_bpp;

	if (fb_bpp == 4) {
		*(volatile uint32_t *)p = c;
	} else {
		/* little-endian like a8r8g8b8 minus alpha: B, G, R in memory */
		((volatile uint8_t *)p)[0] = c;
		((volatile uint8_t *)p)[1] = c >> 8;
		((volatile uint8_t *)p)[2] = c >> 16;
	}
}

void con_clear(uint32_t bg)
{
	for (int y = 0; y < fb_h; y++)
		for (int x = 0; x < fb_w; x++)
			put_px(x, y, bg);
	con_bg = bg;
	row = 0;
}

static void put_char(int col, char ch, uint32_t fg)
{
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (x0 + CH_W > fb_w || y0 + CH_H > fb_h)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++) {
			uint32_t c = (g[gy] & (0x80 >> gx)) ? fg : con_bg;
			for (int sy = 0; sy < SCALE; sy++)
				for (int sx = 0; sx < SCALE; sx++)
					put_px(x0 + gx * SCALE + sx, y0 + gy * SCALE + sy, c);
		}
}

static int put_str(int col, const char *s, uint32_t fg)
{
	while (*s)
		put_char(col++, *s++, fg);
	return col;
}

static void fmt_hex(char *buf, uint64_t v, int digits)
{
	static const char hex[] = "0123456789ABCDEF";
	for (int i = 0; i < digits; i++)
		buf[i] = hex[(v >> (4 * (digits - 1 - i))) & 0xf];
	buf[digits] = 0;
}

void con_skip(void)
{
	row++;
}

void con_str(const char *label, const char *s)
{
	put_str(0, label, YELLOW);
	put_str(LABEL_COLS, s, WHITE);
	row++;
}

void con_hex(const char *label, uint64_t v)
{
	char buf[17];
	fmt_hex(buf, v, 16);
	con_str(label, buf);
}

void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb)
{
	char buf[9];
	int col = put_str(0, label, YELLOW);
	col = col < LABEL_COLS ? LABEL_COLS : col + 1;
	col = put_str(col, a, YELLOW);
	fmt_hex(buf, va, 8);
	col = put_str(col, buf, WHITE);
	if (b) {
		col = put_str(col + 1, b, YELLOW);
		fmt_hex(buf, vb, 8);
		put_str(col, buf, WHITE);
	}
	row++;
}
