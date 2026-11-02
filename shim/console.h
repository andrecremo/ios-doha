#pragma once
#include <stdint.h>

/*
 * Defaults for the doha splash (reserved-memory cont_splash_region, panel
 * tm_ft8719 1080x2280). Measured on the phone (milestone 1): ABL scans out
 * MDP pipe VIG0 from 0x5c000000, a8r8g8b8, stride 4320. shim.c still reads
 * the live pipe and calls con_setup() with what ABL programmed.
 */
#define FB_BASE		0x5c000000UL
#define FB_W		1080
#define FB_H		2280
#define FB_BPP		4
#define FB_STRIDE	(FB_W * FB_BPP)

#define RED	0xffff0000U
#define BLUE	0xff0000a0U
#define WHITE	0xffffffffU
#define YELLOW	0xffffff00U
#define GREEN	0xff00ff00U

/* bpp is bytes per pixel (3 or 4); colors are given as a8r8g8b8 */
void con_setup(uintptr_t base, int w, int h, int stride, int bpp);
void con_clear(uint32_t bg);
void con_skip(void);
void con_str(const char *label, const char *s);
void con_hex(const char *label, uint64_t v);
/* label, then "a=xxxxxxxx b=xxxxxxxx" style pairs of 32-bit values */
void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb);
