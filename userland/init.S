/*
 * First userspace program on doha, installed as /sbin/launchd on a test volume.
 *
 * It reports on /dev/console, ticks every 5 s for 60 s, then exits. init exiting panics
 * the kernel, and the panic prints the exit status, so the result stays readable:
 *   status 42        ran to the end
 *   status 100+errno could not open the console
 *
 * tools/mkinit.py wraps __text into a static Mach-O: everything here is PC-relative,
 * with no relocations and no writable data.
 *
 * Raw XNU syscalls: number in x16, svc #0x80, carry set on error.
 */
#define SYS_exit	1
#define SYS_write	4
#define SYS_open	5
#define SYS_getpid	20
#define SYS_select	93
#define O_RDWR		2
#define TICKS		12
#define STATUS_DONE	42
#define STATUS_NO_CONSOLE 100

	.text
	.globl	_start
	.p2align 2
_start:
	/* sp points at argc and may be misaligned; using it as a base would fault. */
	mov	x9, sp
	and	x9, x9, #~15
	sub	x9, x9, #32
	mov	sp, x9

	adr	x0, console_path
	mov	x1, #O_RDWR
	mov	x2, #0
	mov	x16, #SYS_open
	svc	#0x80
	b.cc	console_open
	add	x0, x0, #STATUS_NO_CONSOLE
	b	exit

console_open:
	mov	x19, x0

	adr	x1, hello
	adr	x2, hello_pid
	sub	x2, x2, x1
	bl	put

	mov	x16, #SYS_getpid
	svc	#0x80
	bl	put_number

	adr	x1, hello_pid
	adr	x2, tick_text
	sub	x2, x2, x1
	bl	put

	mov	x20, #1
tick:
	/* select(0, NULL, NULL, NULL, &5 s) is the sleep */
	mov	x0, #0
	mov	x1, #0
	mov	x2, #0
	mov	x3, #0
	adr	x4, five_seconds
	mov	x16, #SYS_select
	svc	#0x80

	adr	x1, tick_text
	adr	x2, tick_end
	sub	x2, x2, x1
	bl	put

	mov	x0, x20
	bl	put_number

	adr	x1, tick_end
	adr	x2, bye
	sub	x2, x2, x1
	bl	put

	add	x20, x20, #1
	cmp	x20, #TICKS
	b.ls	tick

	adr	x1, bye
	adr	x2, bye_end
	sub	x2, x2, x1
	bl	put

	mov	x0, #STATUS_DONE
exit:
	mov	x16, #SYS_exit
	svc	#0x80
1:	b	1b

/* write(console, x1, x2); leaf, keeps lr */
put:
	mov	x0, x19
	mov	x16, #SYS_write
	svc	#0x80
	ret

/* Writes x0 (below 100) in decimal, using the stack as the only writable memory. */
put_number:
	mov	x21, lr
	mov	x9, #10
	udiv	x10, x0, x9
	msub	x11, x10, x9, x0
	add	x10, x10, #'0'
	add	x11, x11, #'0'
	strb	w10, [sp]
	strb	w11, [sp, #1]
	mov	x1, sp
	mov	x2, #2
	bl	put
	mov	lr, x21
	ret

	.p2align 3
five_seconds:
	.quad	5		/* tv_sec */
	.quad	0		/* tv_usec and padding */
console_path:
	.asciz	"/dev/console"
hello:
	.ascii	"\n*** DOHA userspace: init running, PID "
hello_pid:
	.ascii	" ***\n"
tick_text:
	.ascii	"DOHA init: tick "
tick_end:
	.ascii	"\n"
bye:
	.ascii	"DOHA init: exiting with status 42\n"
bye_end:
