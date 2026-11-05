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
