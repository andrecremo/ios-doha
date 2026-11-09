/*
 * Starts Mu-Silicium on the doha: ABL loads this as a Linux Image, anywhere in RAM; it copies the
 * UEFI image that follows it to FD_BASE and jumps there. x0 (the DTB) is left alone.
 *
 *   clang --target=aarch64-linux-gnu -c DohaShim.S -o DohaShim.o
 */
#define FD_BASE     0x5FC00000
#define FD_SIZE     0x300000
#define TEXT_OFFSET 0x80000
#define IMAGE_SIZE  0x400000    /* this page and the FD, in 2 MiB units; mkdohaimg.py raises it for a payload */
/*
 * "XNU Payload" in the memory map, 64 MiB. Not willow-hackios's 0xF0000000: that cut the free RAM from 0x80000000
 * to 0x13FFFFFFF in two and left XNU 1.75 GB of it; here, below 0x80000000 (RAM Android had, 0x5F800000-0x7DCFFFFF),
 * the whole of it is the kernel's. The XNU loader is built with the same PAYLOAD_BASE.
 */
#define PAYLOAD_BASE 0x78000000
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

	/*
	 * x4 is now just past the FD: an "XNUP" container may follow (mkdohaimg.py -p), for willow-hackios's
	 * XNU loader. It goes to PAYLOAD_BASE, where the UEFI's BootManagerLib looks for it (willow-hackios
	 * uefi/mu-silicium.patch does the same in Mu-Silicium's BootShim). The magic is built in registers,
	 * so that the shim itself never contains it.
	 */
	ldr	w2, [x4]
	movz	w3, #0x4E58
	movk	w3, #0x5055, lsl #16		/* "XNUP" */
	cmp	w2, w3
	b.ne	no_payload
	ldr	w6, [x4, #4]			/* size after the 8-byte header */
	add	x6, x6, #23			/* the header, rounded up to 16 */
	and	x6, x6, #~15
	movz	x5, #(PAYLOAD_BASE >> 16), lsl #16
payload:
	ldp	x2, x3, [x4], #16
	stp	x2, x3, [x5], #16
	subs	x6, x6, #16
	b.ne	payload
no_payload:
	dsb	sy
	ic	iallu
	dsb	sy
	isb
	ldr	x5, =FD_BASE
	br	x5

	.ltorg
	.balign	4096
fd:
