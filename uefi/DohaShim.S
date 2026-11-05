/*
 * Starts Mu-Silicium on the doha: ABL loads this as a Linux Image, anywhere in RAM; it copies the
 * UEFI image that follows it to FD_BASE and jumps there. x0 (the DTB) is left alone.
 *
 *   clang --target=aarch64-linux-gnu -c DohaShim.S -o DohaShim.o
 */
#define FD_BASE     0x5FC00000
#define FD_SIZE     0x300000
#define TEXT_OFFSET 0x80000
#define IMAGE_SIZE  0x400000    /* this page and the FD, in 2 MiB units */
#define FB_BASE     0x5C000000
#define FB_STRIDE   4320

	.text
	.globl	_head
_head:
	b	start
	.long	0
	.quad	TEXT_OFFSET
	.quad	IMAGE_SIZE
	.quad	0xA             /* little-endian, 4K pages, anywhere in RAM */
	.quad	0
	.quad	0
	.quad	0
	.ascii	"ARM\x64"
	.long	0

start:
	/*
	 * A green band across the screen ABL left on (a8r8g8b8, MMU off): if it shows, ABL ran this
	 * code. Rows 400 to 499 of the 1080 x 2280 framebuffer, which the first boot found on the Motorola logo.
	 */
	ldr	x4, =(FB_BASE + 400 * FB_STRIDE)
	ldr	x5, =(100 * FB_STRIDE / 4)
	ldr	w6, =0xff00ff00
band:
	str	w6, [x4], #4
	subs	x5, x5, #1
	b.ne	band
	dsb	sy

	adr	x4, fd
	ldr	x5, =FD_BASE
	ldr	x6, =FD_SIZE
copy:
	ldp	x2, x3, [x4], #16
	stp	x2, x3, [x5], #16
	subs	x6, x6, #16
	b.ne	copy
	dsb	sy
	ic	iallu
	dsb	sy
	isb
	ldr	x5, =FD_BASE
	br	x5

	.ltorg
	.balign	4096
fd:
