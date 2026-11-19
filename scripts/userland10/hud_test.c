/*
 * hud_test: what is going on in a running iOS, said on the panel over the picture (the Keys line, through the
 * kernel's kern.redwood_note), for a phone whose log nobody can read. Each line also goes to the standard output.
 * One line every 4 s, the last staying. Run as root (the launchd job com.redwood.demo, rc.jobs.dohasafari).
 *
 * usage: hud_test STEP...
 *   ps PATTERN        the processes whose executable's name contains PATTERN: "name pid", as many as fit
 *   crashes           how many crash reports there are, then the newest six: the process and the exception
 *   serve PORT        the whole log (every line said, every line of a probe) to whoever connects to PORT over TCP,
 *                     from its first line on, while this program runs; lines stay 1 s on the panel instead of 4
 *   probe PROGRAM     run PROGRAM ("ok ..."/"FAIL ..." a line each): its FAILs, a count every 10, how it ended
 *   env NAME=VALUE    an environment variable for the programs started after it (probe)
 *   say TEXT          TEXT itself
 *   wait SECONDS
 *   watch SECONDS FILE  for SECONDS, every second: the kernel's new log lines ("kernel: ") and FILE's new lines
 *                     ("file: "), into the log only (serve PORT), the panel left alone
 *   sample NAME SECONDS  the threads of process NAME, looked at from outside every 20 ms: the commonest stacks
 *                     into the log every 400 looks (task_for_pid; root)
 *   threads NAME      from then on, while watch runs: every 5 s the threads of process NAME that used the
 *                     processor or sit in the kernel, with their times (proc_pidinfo; root)
 *   du PATH           files and bytes under PATH, and its 15 biggest entries, into the log
 *   run A,B,C         program A with arguments B, C: its output into the log
 */
#include <dirent.h>
#include <dlfcn.h>
#include <time.h>
#include <signal.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/types.h>
#include <unistd.h>

#define LINE 56

#include <netinet/in.h>
#include <pthread.h>
#include <sys/socket.h>

/*
 * The log, for the network (serve PORT): every line said or read from a probe, kept in one growing buffer; whoever
 * connects to PORT over TCP gets it from its first byte and then each new line as it comes. Read-only: nothing that
 * comes from the other side is read at all.
 */
static char *log_text;
static size_t log_length, log_room;
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t log_grew = PTHREAD_COND_INITIALIZER;
static int serving;
static unsigned pause_s = 4;            /* how long a line stays on the panel before the next (1 while serving) */

static void
log_line(const char *text)
{
	size_t n = strlen(text);

	pthread_mutex_lock(&log_lock);
	if (log_text == NULL && (log_text = malloc(16u << 20)) != NULL) {
		log_room = 16u << 20;           /* (once, and never moved: a client sends from it without the lock) */
	}
	if (log_length + n + 2 <= log_room) {
		memcpy(log_text + log_length, text, n);
		log_text[log_length + n] = '\n';
		log_length += n + 1;
		pthread_cond_broadcast(&log_grew);
	}
	pthread_mutex_unlock(&log_lock);
}

static void *
log_client(void *arg)
{
	int s = (int)(intptr_t)arg;
	size_t sent = 0;

	signal(SIGPIPE, SIG_IGN);
	for (;;) {
		size_t have;

		pthread_mutex_lock(&log_lock);
		while (sent == log_length) {
			pthread_cond_wait(&log_grew, &log_lock);
		}
		have = log_length;
		pthread_mutex_unlock(&log_lock);
		while (sent < have) {
			ssize_t n = send(s, log_text + sent, have - sent, 0);

			if (n <= 0) {
				close(s);
				return NULL;
			}
			sent += (size_t)n;
		}
	}
}

static void *
log_server(void *arg)
{
	int port = (int)(intptr_t)arg, l = socket(AF_INET, SOCK_STREAM, 0), one = 1;
	struct sockaddr_in a;

	memset(&a, 0, sizeof(a));
	a.sin_family = AF_INET;
	a.sin_port = htons((uint16_t)port);
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	setsockopt(l, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	if (l < 0 || bind(l, (struct sockaddr *)&a, sizeof(a)) != 0 || listen(l, 4) != 0) {
		log_line("hud_test: serve: the port could not be opened");
		return NULL;
	}
	for (;;) {
		int c = accept(l, NULL, NULL);
		pthread_t t;

		if (c >= 0 && pthread_create(&t, NULL, log_client, (void *)(intptr_t)c) == 0) {
			pthread_detach(t);
		} else if (c >= 0) {
			close(c);
		}
	}
}

static void
say(const char *format, ...)
{
	char line[256], logged[280];
	va_list list;

	va_start(list, format);
	vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	printf("hud_test: %s\n", line);
	fflush(stdout);
	snprintf(logged, sizeof(logged), "hud_test: %s", line);
	log_line(logged);
	sysctlbyname("kern.redwood_note", NULL, NULL, line, strlen(line) < LINE ? strlen(line) : LINE);
	sleep(pause_s);
}

/* the executable's file name of a process (KERN_PROCARGS2: argc, then the path), or its 16-character p_comm */
static void
process_name(pid_t pid, const char *comm, char *name, size_t size)
{
	int mib[3] = { CTL_KERN, KERN_PROCARGS2, pid };
	static char args[16384];
	size_t length = sizeof(args);

	strlcpy(name, comm, size);
	if (sysctl(mib, 3, args, &length, NULL, 0) == 0 && length > sizeof(int)) {
		const char *path = args + sizeof(int), *base;

		if (memchr(path, 0, length - sizeof(int)) != NULL && path[0] != 0) {
			base = strrchr(path, '/');
			strlcpy(name, base != NULL ? base + 1 : path, size);
		}
	}
}

static void
ps(const char *pattern)
{
	int mib[4] = { CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0 };
	struct kinfo_proc *procs;
	size_t length = 0;
	char line[256] = "", one[96], name[96];
	unsigned found = 0;

	if (sysctl(mib, 4, NULL, &length, NULL, 0) != 0 || (procs = malloc(length + 16 * sizeof(*procs))) == NULL) {
		say("ps %s: no list of processes", pattern);
		return;
	}
	length += 16 * sizeof(*procs);
	if (sysctl(mib, 4, procs, &length, NULL, 0) != 0) {
		free(procs);
		say("ps %s: no list of processes", pattern);
		return;
	}
	for (size_t i = 0; i < length / sizeof(*procs); i++) {
		pid_t pid = procs[i].kp_proc.p_pid;
		const char *shown;

		process_name(pid, procs[i].kp_proc.p_comm, name, sizeof(name));
		if (strcasestr(name, pattern) == NULL) {
			continue;
		}
		/* (com.apple.WebKit.WebContent: the part after the last dot is what tells them apart) */
		shown = strncmp(name, "com.apple.", 10) == 0 && strrchr(name, '.') != NULL ? strrchr(name, '.') + 1 : name;
		snprintf(one, sizeof(one), "%s%s %d", found ? ", " : "", shown, pid);
		if (strlen(line) + strlen(one) > LINE - 8 && line[0] != 0) {
			say("%s: %s", pattern, line);
			snprintf(one, sizeof(one), "%s %d", shown, pid);
			line[0] = 0;
		}
		strlcat(line, one, sizeof(line));
		found++;
	}
	free(procs);
	if (found == 0) {
		say("%s: NO process", pattern);
	} else {
		say("%s: %s", pattern, line);
	}
}

struct report {
	char name[128];
	time_t when;
};

static int
newest_first(const void *a, const void *b)
{
	const struct report *x = a, *y = b;

	return x->when < y->when ? 1 : x->when > y->when ? -1 : 0;
}

/* the exception of a report: "exception" : {"type":"EXC_..."} in an .ips, "Exception Type:" in an older one */
static void
exception_of(const char *path, char *what, size_t size)
{
	FILE *f = fopen(path, "r");
	static char text[65536];
	size_t n;
	const char *at;

	strlcpy(what, "?", size);
	if (f == NULL) {
		strlcpy(what, "unreadable", size);
		return;
	}
	n = fread(text, 1, sizeof(text) - 1, f);
	fclose(f);
	text[n] = 0;
	if ((at = strstr(text, "\"exception\"")) != NULL && (at = strstr(at, "\"type\"")) != NULL &&
	    (at = strchr(at + 6, '"')) != NULL) {
		size_t k = 0;

		for (at++; at[k] != 0 && at[k] != '"' && k < size - 1; k++) {
			what[k] = at[k];
		}
		what[k] = 0;
	} else if ((at = strstr(text, "Exception Type:")) != NULL) {
		size_t k = 0;

		for (at += 15; *at == ' '; at++) {
		}
		for (; at[k] != 0 && at[k] != '\n' && at[k] != ' ' && k < size - 1; k++) {
			what[k] = at[k];
		}
		what[k] = 0;
	} else if (strstr(text, "\"bug_type\":\"298\"") != NULL || strstr(text, "\"bug_type\":\"409\"") != NULL) {
		strlcpy(what, "hang/jetsam", size);
	}
}

static void
crashes(void)
{
	static const char *const places[] = { "/private/var/mobile/Library/Logs/CrashReporter",
		"/private/var/mobile/Library/Logs/CrashReporter/Retired", "/private/var/root/Library/Logs/CrashReporter" };
	static struct report reports[512];
	unsigned count = 0;

	for (unsigned p = 0; p < sizeof(places) / sizeof(places[0]); p++) {
		DIR *d = opendir(places[p]);
		struct dirent *e;

		while (d != NULL && (e = readdir(d)) != NULL && count < sizeof(reports) / sizeof(reports[0])) {
			char path[512];
			struct stat st;

			if (e->d_name[0] == '.') {
				continue;
			}
			snprintf(path, sizeof(path), "%s/%s", places[p], e->d_name);
			if (stat(path, &st) != 0 || !S_ISREG(st.st_mode)) {
				continue;
			}
			strlcpy(reports[count].name, path, sizeof(reports[count].name));
			reports[count].when = st.st_mtime;
			count++;
		}
		if (d != NULL) {
			closedir(d);
		}
	}
	say("crash reports: %u", count);
	qsort(reports, count, sizeof(reports[0]), newest_first);
	for (unsigned i = 0; i < count && i < 6; i++) {
		char what[64], process[96];
		const char *base = strrchr(reports[i].name, '/') + 1, *dash = strchr(base, '-');
		size_t k = dash != NULL ? (size_t)(dash - base) : strlen(base);

		if (k >= sizeof(process)) {
			k = sizeof(process) - 1;
		}
		memcpy(process, base, k);
		process[k] = 0;
		exception_of(reports[i].name, what, sizeof(what));
		say("%s: %s", strncmp(process, "com.apple.", 10) == 0 && strrchr(process, '.') ? strrchr(process, '.') + 1 :
		    process, what);
	}
}

/*
 * A test program that says "ok ..." / "FAIL ..." a line each (hakios-metal-probe): run with its output read here, every
 * FAIL line shown, a running count every 10 checks, and at the end the counts and how it ended (exit status or signal)
 */
#include <signal.h>
#include <sys/wait.h>

static void
probe(const char *program)
{
	int fds[2], status = 0;
	pid_t child;
	FILE *in;
	char line[512], last[512] = "";
	unsigned ok = 0, failed = 0, lines = 0;

	if (pipe(fds) != 0 || (child = fork()) < 0) {
		say("probe: cannot start %s", program);
		return;
	}
	if (child == 0) {
		dup2(fds[1], STDOUT_FILENO);
		dup2(fds[1], STDERR_FILENO);
		close(fds[0]);
		close(fds[1]);
		execl(program, program, (char *)NULL);
		_exit(127);
	}
	close(fds[1]);
	in = fdopen(fds[0], "r");
	say("probe: %s started", strrchr(program, '/') ? strrchr(program, '/') + 1 : program);
	while (in != NULL && fgets(line, sizeof(line), in) != NULL) {
		size_t n = strlen(line);
		const char *text = line;

		if (n > 0 && line[n - 1] == '\n') {
			line[--n] = 0;
		}
		printf("%s\n", line);                   /* (everything, to the standard output, for a log) */
		log_line(line);                         /* (and to whoever reads the network's log: serve PORT) */
		lines++;
		if (strncmp(text, "probe: ", 7) == 0) {
			text += 7;
		}
		strlcpy(last, text, sizeof(last));
		if (strstr(text, "FAIL") != NULL) {
			failed++;
			say("F%u %s", failed, text);
		} else if (strncmp(text, "ok", 2) == 0) {
			if (++ok % 10 == 0) {
				say("probe: %u ok, %u FAIL so far", ok, failed);
			}
		}
	}
	if (in != NULL) {
		fclose(in);
	}
	waitpid(child, &status, 0);
	say("last: %s", last);
	if (WIFSIGNALED(status)) {
		say("probe: KILLED by signal %d after %u ok, %u FAIL", WTERMSIG(status), ok, failed);
	} else {
		say("probe: done, exit %d: %u ok, %u FAIL (%u lines)", WEXITSTATUS(status), ok, failed, lines);
	}
}

/*
 * sample NAME SECONDS: the threads of the process called NAME, looked at from outside every 20 ms for SECONDS -- each one
 * stopped for a moment, its program counter, link register and frame chain read (task_for_pid: root), let go -- and
 * every 400 looks the commonest stacks into the log (serve PORT): thread name, share, then image+offset(symbol) for each
 * frame. The shared cache sits at the same address in every process, so its symbols are this program's own dladdr();
 * anything else is the file mapped there and the offset into that mapping. From outside so that a thread stopped while
 * holding a lock cannot stop the sampler (one inside the window server did, and never said a word).
 */
#include <mach/mach.h>

extern kern_return_t task_for_pid(mach_port_name_t target, int pid, mach_port_name_t *task);
extern int proc_regionfilename(int pid, uint64_t address, void *buffer, uint32_t size);

#define SAMPLE_DEPTH    12
#define SAMPLE_SLOTS    512
#define SAMPLE_DUMP     400
#define SAMPLE_ADDR(x)  ((x) & 0x0000000fffffffffull)

static struct sample_slot {
	uint64_t        stack[SAMPLE_DEPTH];
	char            name[32];
	unsigned        count;
} sample_table[SAMPLE_SLOTS];

static int
sample_order(const void *a, const void *b)
{
	const struct sample_slot *x = a, *y = b;

	return x->count < y->count ? 1 : x->count > y->count ? -1 : 0;
}

static pid_t
pid_of(const char *wanted)
{
	int mib[4] = { CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0 };
	struct kinfo_proc *procs;
	size_t length = 0;
	char name[96];
	pid_t found = -1;

	if (sysctl(mib, 4, NULL, &length, NULL, 0) != 0 || (procs = malloc(length + 16 * sizeof(*procs))) == NULL) {
		return -1;
	}
	length += 16 * sizeof(*procs);
	if (sysctl(mib, 4, procs, &length, NULL, 0) == 0) {
		for (size_t i = 0; i < length / sizeof(*procs) && found < 0; i++) {
			process_name(procs[i].kp_proc.p_pid, procs[i].kp_proc.p_comm, name, sizeof(name));
			if (strcmp(name, wanted) == 0) {
				found = procs[i].kp_proc.p_pid;
			}
		}
	}
	free(procs);
	return found;
}

/* one frame as text: the shared cache's symbol (this process has the same cache at the same address), or the file */
static int
sample_frame(pid_t pid, mach_port_t task, uint64_t address, char *out, size_t size)
{
	Dl_info where = { 0 };
	char file[1024] = "";
	const char *slash;
	mach_vm_address_t start = (mach_vm_address_t)address;
	vm_address_t region = (vm_address_t)address;
	vm_size_t region_size = 0;
	vm_region_basic_info_data_64_t info;
	mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
	mach_port_t object = MACH_PORT_NULL;

	(void)start;
	if (dladdr((void *)(uintptr_t)address, &where) != 0 && where.dli_fname != NULL && where.dli_sname != NULL &&
	    strstr(where.dli_fname, "hud_test") == NULL) {
		slash = strrchr(where.dli_fname, '/');
		return snprintf(out, size, " %s+0x%llx(%s)", slash != NULL ? slash + 1 : where.dli_fname,
		    (unsigned long long)(address - (uint64_t)(uintptr_t)where.dli_fbase), where.dli_sname);
	}
	if (vm_region_64(task, &region, &region_size, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object) != KERN_SUCCESS) {
		region = 0;
	}
	if (object != MACH_PORT_NULL) {
		mach_port_deallocate(mach_task_self(), object);
	}
	if (proc_regionfilename(pid, address, file, sizeof(file)) > 0) {
		slash = strrchr(file, '/');
		return snprintf(out, size, " %s+0x%llx(region)", slash != NULL ? slash + 1 : file,
		    (unsigned long long)(address - (uint64_t)region));
	}
	return snprintf(out, size, " 0x%llx", (unsigned long long)address);
}

static void
sample(const char *wanted, unsigned seconds)
{
	pid_t pid = pid_of(wanted);
	mach_port_t task = MACH_PORT_NULL;
	kern_return_t kr;
	unsigned looks = 0, dumps = 0;
	time_t until = time(NULL) + (time_t)seconds;

	if (pid < 0) {
		say("sample %s: no such process", wanted);
		return;
	}
	if ((kr = task_for_pid(mach_task_self(), pid, &task)) != KERN_SUCCESS) {
		say("sample %s %d: task_for_pid refused: %#x", wanted, pid, kr);
		return;
	}
	say("sample %s %d: every thread every 20 ms for %u s", wanted, pid, seconds);
	memset(sample_table, 0, sizeof(sample_table));
	while (time(NULL) < until) {
		thread_act_array_t threads;
		mach_msg_type_number_t n = 0;

		usleep(20000);
		if (task_threads(task, &threads, &n) != KERN_SUCCESS) {
			say("sample %s %d: its threads cannot be listed any more (gone?)", wanted, pid);
			break;
		}
		looks++;
		for (mach_msg_type_number_t t = 0; t < n; t++) {
			thread_extended_info_data_t ext;
			mach_msg_type_number_t count = THREAD_EXTENDED_INFO_COUNT;
			arm_thread_state64_t state;
			mach_msg_type_number_t state_count = ARM_THREAD_STATE64_COUNT;
			uint64_t stack[SAMPLE_DEPTH] = { 0 }, hash = 0;
			kern_return_t got;

			memset(&ext, 0, sizeof(ext));
			thread_info(threads[t], THREAD_EXTENDED_INFO, (thread_info_t)&ext, &count);
			if (thread_suspend(threads[t]) != KERN_SUCCESS) {
				mach_port_deallocate(mach_task_self(), threads[t]);
				continue;
			}
			got = thread_get_state(threads[t], ARM_THREAD_STATE64, (thread_state_t)&state, &state_count);
			if (got == KERN_SUCCESS) {
				uint64_t sp = arm_thread_state64_get_sp(state), fp = arm_thread_state64_get_fp(state);

				stack[0] = SAMPLE_ADDR(arm_thread_state64_get_pc(state));
				stack[1] = SAMPLE_ADDR(arm_thread_state64_get_lr(state));
				for (unsigned d = 2; d < SAMPLE_DEPTH && fp >= sp && fp - sp < (16u << 20) && (fp & 15) == 0; d++) {
					uint64_t record[2];
					vm_size_t read = 0;

					if (vm_read_overwrite(task, (vm_address_t)fp, sizeof(record), (vm_address_t)record, &read) != KERN_SUCCESS ||
					    read != sizeof(record)) {
						break;
					}
					stack[d] = SAMPLE_ADDR(record[1]);
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
			for (unsigned d = 0; d < SAMPLE_DEPTH; d++) {
				hash = (hash ^ stack[d]) * 0x9e3779b97f4a7c15ull;
			}
			for (unsigned i = (unsigned)(hash >> 32) % SAMPLE_SLOTS, probes = 0; probes < SAMPLE_SLOTS;
			    i = (i + 1) % SAMPLE_SLOTS, probes++) {
				if (sample_table[i].count == 0 || memcmp(sample_table[i].stack, stack, sizeof(stack)) == 0) {
					memcpy(sample_table[i].stack, stack, sizeof(stack));
					strlcpy(sample_table[i].name, ext.pth_name[0] ? ext.pth_name : "(unnamed)", sizeof(sample_table[i].name));
					sample_table[i].count++;
					break;
				}
			}
		}
		vm_deallocate(mach_task_self(), (vm_address_t)threads, n * sizeof(thread_t));
		if (looks < SAMPLE_DUMP) {
			continue;
		}
		qsort(sample_table, SAMPLE_SLOTS, sizeof(sample_table[0]), sample_order);
		{
			char head[128];

			snprintf(head, sizeof(head), "sample: %s, dump %u: %u looks at every thread", wanted, ++dumps, looks);
			log_line(head);
		}
		for (unsigned i = 0; i < 16 && sample_table[i].count != 0; i++) {
			char line[2400];
			int at = snprintf(line, sizeof(line), "sample: %s %.0f%%:", sample_table[i].name, 100.0 * sample_table[i].count / looks);

			for (unsigned d = 0; d < SAMPLE_DEPTH && sample_table[i].stack[d] != 0 && at < (int)sizeof(line) - 200; d++) {
				at += sample_frame(pid, task, sample_table[i].stack[d], line + at, sizeof(line) - (size_t)at);
			}
			log_line(line);
		}
		memset(sample_table, 0, sizeof(sample_table));
		looks = 0;
	}
	mach_port_deallocate(mach_task_self(), task);
	say("sample %s: done, %u dumps", wanted, dumps);
}

/*
 * threads NAME: from then on, while watch runs, every 5 s a line for each thread of the process NAME that used the
 * processor in those 5 s or sits in an uninterruptible wait in the kernel: its name, milliseconds in user space and in
 * the kernel, its state. proc_pidinfo (root) and nothing else: no port of the process, nothing of it stopped (iOS lets
 * root list another process's threads this way where task_threads on its task is refused).
 */
extern int proc_pidinfo(int pid, int flavor, uint64_t arg, void *buffer, int size);

#define PROC_PIDTHREADINFO_     5
#define PROC_PIDLISTTHREADS_    6

struct proc_threadinfo_ {
	uint64_t        pth_user_time;          /* nanoseconds */
	uint64_t        pth_system_time;
	int32_t         pth_cpu_usage;
	int32_t         pth_policy;
	int32_t         pth_run_state;          /* 1 running, 2 stopped, 3 waiting, 4 uninterruptible, 5 halted */
	int32_t         pth_flags;
	int32_t         pth_sleep_time;
	int32_t         pth_curpri;
	int32_t         pth_priority;
	int32_t         pth_maxpriority;
	char            pth_name[64];
};

static pid_t threads_pid = -1;
static char threads_of[64];
static struct {
	uint64_t        handle, user, system;
} threads_before[512];
static unsigned threads_known;
static time_t threads_last;

static void
threads_look(void)
{
	static uint64_t handles[512];
	int bytes;
	unsigned n, said = 0, stuck = 0;
	uint64_t total_user = 0, total_system = 0;
	struct {
		uint64_t        handle, user, system;
	} now[512];
	char line[300];

	if (threads_pid < 0 || time(NULL) - threads_last < 5) {
		return;
	}
	threads_last = time(NULL);
	bytes = proc_pidinfo(threads_pid, PROC_PIDLISTTHREADS_, 0, handles, sizeof(handles));
	if (bytes <= 0) {
		snprintf(line, sizeof(line), "threads: %s %d: no list of its threads (gone?)", threads_of, threads_pid);
		log_line(line);
		threads_pid = -1;
		return;
	}
	n = (unsigned)bytes / sizeof(uint64_t);
	for (unsigned t = 0; t < n; t++) {
		struct proc_threadinfo_ info;
		uint64_t du = 0, ds = 0;
		const char *state;

		memset(&info, 0, sizeof(info));
		now[t].handle = handles[t];
		now[t].user = now[t].system = 0;
		if (proc_pidinfo(threads_pid, PROC_PIDTHREADINFO_, handles[t], &info, sizeof(info)) <= 0) {
			continue;
		}
		now[t].user = info.pth_user_time;
		now[t].system = info.pth_system_time;
		for (unsigned k = 0; k < threads_known; k++) {
			if (threads_before[k].handle == handles[t]) {
				du = info.pth_user_time - threads_before[k].user;
				ds = info.pth_system_time - threads_before[k].system;
				break;
			}
		}
		total_user += du;
		total_system += ds;
		if (info.pth_run_state == 4) {
			stuck++;
		}
		if (du + ds < 50000000ull && info.pth_run_state != 4) {
			continue;               /* (under 50 ms in 5 s and not stuck: not said) */
		}
		state = info.pth_run_state == 1 ? "running" : info.pth_run_state == 3 ? "waiting" :
		    info.pth_run_state == 4 ? "IN THE KERNEL, uninterruptible" : info.pth_run_state == 2 ? "stopped" : "?";
		snprintf(line, sizeof(line), "threads: %s: %s: user %llu ms, kernel %llu ms; %s, priority %d", threads_of,
		    info.pth_name[0] ? info.pth_name : "(unnamed)", (unsigned long long)(du / 1000000),
		    (unsigned long long)(ds / 1000000), state, info.pth_curpri);
		log_line(line);
		said++;
	}
	snprintf(line, sizeof(line), "threads: %s %d: %u threads, %u uninterruptible; in 5 s user %llu ms, kernel %llu ms (%u said)",
	    threads_of, threads_pid, n, stuck, (unsigned long long)(total_user / 1000000), (unsigned long long)(total_system / 1000000), said);
	log_line(line);
	for (unsigned t = 0; t < n && t < 512; t++) {
		threads_before[t].handle = now[t].handle;
		threads_before[t].user = now[t].user;
		threads_before[t].system = now[t].system;
	}
	threads_known = n < 512 ? n : 512;
}

/*
 * du PATH: how many files and bytes are under PATH, and its first 12 entries with their sizes, into the log.
 * run A,B,C: the program A with arguments B and C (commas, since the job list does not keep quotes), every line it
 * writes into the log, and how it ended.
 */
static void
du_walk(const char *path, unsigned depth, uint64_t *files, uint64_t *bytes)
{
	DIR *d;
	struct dirent *e;

	if (depth > 12 || (d = opendir(path)) == NULL) {
		return;
	}
	while ((e = readdir(d)) != NULL) {
		char sub[1024];
		struct stat st;

		if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) {
			continue;
		}
		snprintf(sub, sizeof(sub), "%s/%s", path, e->d_name);
		if (lstat(sub, &st) != 0) {
			continue;
		}
		if (S_ISDIR(st.st_mode)) {
			du_walk(sub, depth + 1, files, bytes);
		} else {
			(*files)++;
			*bytes += (uint64_t)st.st_size;
		}
	}
	closedir(d);
}

struct du_entry {
	char name[200];
	uint64_t files, bytes;
	int dir;
};

static int
du_order(const void *a, const void *b)
{
	const struct du_entry *x = a, *y = b;

	return x->bytes < y->bytes ? 1 : x->bytes > y->bytes ? -1 : 0;
}

/* the entries of PATH, biggest first (the 15 biggest said), and the total */
static void
du(const char *path)
{
	static struct du_entry entries[1024];
	unsigned n = 0;
	uint64_t files = 0, bytes = 0;
	DIR *d = opendir(path);
	struct dirent *e;
	char line[600];

	if (d == NULL) {
		snprintf(line, sizeof(line), "du %s: not there (or not readable)", path);
		log_line(line);
		return;
	}
	while ((e = readdir(d)) != NULL && n < 1024) {
		char sub[1024];
		struct stat st;
		uint64_t f = 0, b = 0;

		if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) {
			continue;
		}
		snprintf(sub, sizeof(sub), "%s/%s", path, e->d_name);
		if (lstat(sub, &st) != 0) {
			continue;
		}
		if (S_ISDIR(st.st_mode)) {
			du_walk(sub, 1, &f, &b);
		} else {
			f = 1;
			b = (uint64_t)st.st_size;
		}
		strlcpy(entries[n].name, e->d_name, sizeof(entries[n].name));
		entries[n].files = f;
		entries[n].bytes = b;
		entries[n].dir = S_ISDIR(st.st_mode);
		files += f;
		bytes += b;
		n++;
	}
	closedir(d);
	qsort(entries, n, sizeof(entries[0]), du_order);
	for (unsigned i = 0; i < n && i < 15; i++) {
		snprintf(line, sizeof(line), "du %s: %s%s: %llu files, %llu KB", path, entries[i].name, entries[i].dir ? "/" : "",
		    (unsigned long long)entries[i].files, (unsigned long long)(entries[i].bytes >> 10));
		log_line(line);
	}
	snprintf(line, sizeof(line), "du %s: in all %llu files, %llu KB (%u entries)", path, (unsigned long long)files,
	    (unsigned long long)(bytes >> 10), n);
	log_line(line);
}

static void
run(const char *spec)
{
	char copy[512], *argv[16], *at, line[600], out[520];
	int pipe_fds[2], argc = 0, status = 0;
	pid_t child;
	FILE *in;

	strlcpy(copy, spec, sizeof(copy));
	for (at = strtok(copy, ","); at != NULL && argc < 15; at = strtok(NULL, ",")) {
		argv[argc++] = at;
	}
	argv[argc] = NULL;
	if (argc == 0 || pipe(pipe_fds) != 0) {
		return;
	}
	if ((child = fork()) == 0) {
		dup2(pipe_fds[1], 1);
		dup2(pipe_fds[1], 2);
		close(pipe_fds[0]);
		execv(argv[0], argv);
		_exit(127);
	}
	close(pipe_fds[1]);
	in = fdopen(pipe_fds[0], "r");
	while (in != NULL && fgets(out, sizeof(out), in) != NULL) {
		out[strcspn(out, "\n")] = 0;
		snprintf(line, sizeof(line), "run %s: %s", argv[0], out);
		log_line(line);
	}
	if (in != NULL) {
		fclose(in);
	}
	waitpid(child, &status, 0);
	snprintf(line, sizeof(line), "run %s: ended, status %#x", argv[0], status);
	log_line(line);
}

/* the kernel's message buffer, as dmesg reads it (libproc; root) */
extern int proc_kmsgbuf(void *buffer, uint32_t size);

/* the complete lines of text[0..n) into the log, each after prefix; returns how much was used (the rest: no newline yet) */
static size_t
log_lines(const char *prefix, const char *text, size_t n)
{
	size_t used = 0;

	for (size_t i = 0; i < n; i++) {
		if (text[i] == '\n') {
			char line[1100];
			size_t len = i - used < 1000 ? i - used : 1000;

			snprintf(line, sizeof(line), "%s%.*s", prefix, (int)len, text + used);
			log_line(line);
			used = i + 1;
		}
	}
	return used;
}

static void
watch(unsigned seconds, const char *path)
{
	static char now[1 << 18], before[1 << 18];
	static char pending[1 << 16];
	size_t before_n = 0, pending_n = 0;
	off_t at = 0;

	for (unsigned s = 0; s < seconds; s++) {
		int n = proc_kmsgbuf(now, sizeof(now) - 1);
		FILE *f;

		if (n > 0) {
			size_t from = 0;

			/* what is new: after the end of what was read last time (its last 160 bytes, found again), or all of it */
			if (before_n > 0) {
				size_t key = before_n < 160 ? before_n : 160;
				const char *k = before + before_n - key, *hit = NULL;

				for (const char *c = now; c + key <= now + n; c++) {
					if (memcmp(c, k, key) == 0) {
						hit = c;
					}
				}
				from = hit != NULL ? (size_t)(hit - now) + key : 0;
				if (hit == NULL) {
					log_line("kernel: (the buffer went round: all of it again)");
				}
			}
			if ((size_t)n > from) {
				size_t used = log_lines("kernel: ", now + from, (size_t)n - from);

				memcpy(before, now, (size_t)n);
				before_n = from + used;          /* (a line not ended yet is read again next time) */
			}
		}
		threads_look();
		if ((f = fopen(path, "r")) != NULL) {
			if (fseeko(f, at, SEEK_SET) == 0) {
				size_t got = fread(pending + pending_n, 1, sizeof(pending) - pending_n - 1, f);
				size_t used;

				at += (off_t)got;
				pending_n += got;
				used = log_lines("file: ", pending, pending_n);
				if (used == 0 && pending_n == sizeof(pending) - 1) {
					used = pending_n;       /* (one line too long: dropped) */
				}
				memmove(pending, pending + used, pending_n - used);
				pending_n -= used;
			}
			fclose(f);
		}
		sleep(1);
	}
}

int
main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IOLBF, 0);
	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "ps") == 0 && i + 1 < argc) {
			ps(argv[++i]);
		} else if (strcmp(argv[i], "crashes") == 0) {
			crashes();
		} else if (strcmp(argv[i], "serve") == 0 && i + 1 < argc) {
			pthread_t t;
			int port = atoi(argv[++i]);

			if (!serving && pthread_create(&t, NULL, log_server, (void *)(intptr_t)port) == 0) {
				pthread_detach(t);
				serving = 1;
				pause_s = 1;
				say("log on TCP port %d", port);
			}
		} else if (strcmp(argv[i], "probe") == 0 && i + 1 < argc) {
			probe(argv[++i]);
		} else if (strcmp(argv[i], "env") == 0 && i + 1 < argc && strchr(argv[i + 1], '=') != NULL) {
			char *pair = argv[++i], *eq = strchr(pair, '=');

			*eq = 0;
			setenv(pair, eq + 1, 1);        /* (for the programs a probe step starts) */
			say("env %s=%s", pair, eq + 1);
			*eq = '=';
		} else if (strcmp(argv[i], "say") == 0 && i + 1 < argc) {
			say("%s", argv[++i]);
		} else if (strcmp(argv[i], "du") == 0 && i + 1 < argc) {
			du(argv[++i]);
		} else if (strcmp(argv[i], "run") == 0 && i + 1 < argc) {
			run(argv[++i]);
		} else if (strcmp(argv[i], "threads") == 0 && i + 1 < argc) {
			strlcpy(threads_of, argv[++i], sizeof(threads_of));
			threads_pid = pid_of(threads_of);
			threads_known = 0;
			say("threads %s: %d", threads_of, (int)threads_pid);
		} else if (strcmp(argv[i], "sample") == 0 && i + 2 < argc) {
			sample(argv[i + 1], (unsigned)atoi(argv[i + 2]));
			i += 2;
		} else if (strcmp(argv[i], "watch") == 0 && i + 2 < argc) {
			unsigned seconds = (unsigned)atoi(argv[i + 1]);

			say("watch %u s: kernel and %s", seconds, argv[i + 2]);
			watch(seconds, argv[i + 2]);
			i += 2;
		} else if (strcmp(argv[i], "wait") == 0 && i + 1 < argc) {
			sleep((unsigned)atoi(argv[++i]));
		} else {
			fprintf(stderr, "hud_test: bad step \"%s\"\n", argv[i]);
			return 1;
		}
	}
	return 0;
}
