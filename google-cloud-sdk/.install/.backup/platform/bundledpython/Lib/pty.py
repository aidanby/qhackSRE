"""Pseudo terminal utilities."""

# Bugs: No signal handling.  Doesn't set subordinate termios and window size.
#       Only tested on Linux.
# See:  W. Richard Stevens. 1992.  Advanced Programming in the
#       UNIX Environment.  Chapter 19.
# Author: Steen Lumholt -- with additions by Guido.

from select import select
import os
import tty

__all__ = ["openpty","fork","spawn"]

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2

CHILD = 0

def openpty():
    """openpty() -> (main_fd, subordinate_fd)
    Open a pty main/subordinate pair, using os.openpty() if possible."""

    try:
        return os.openpty()
    except (AttributeError, OSError):
        pass
    main_fd, subordinate_name = _open_terminal()
    subordinate_fd = subordinate_open(subordinate_name)
    return main_fd, subordinate_fd

def main_open():
    """main_open() -> (main_fd, subordinate_name)
    Open a pty main and return the fd, and the filename of the subordinate end.
    Deprecated, use openpty() instead."""

    try:
        main_fd, subordinate_fd = os.openpty()
    except (AttributeError, OSError):
        pass
    else:
        subordinate_name = os.ttyname(subordinate_fd)
        os.close(subordinate_fd)
        return main_fd, subordinate_name

    return _open_terminal()

def _open_terminal():
    """Open pty main and return (main_fd, tty_name).
    SGI and generic BSD version, for when openpty() fails."""
    try:
        import sgi
    except ImportError:
        pass
    else:
        try:
            tty_name, main_fd = sgi._getpty(os.O_RDWR, 0666, 0)
        except IOError, msg:
            raise os.error, msg
        return main_fd, tty_name
    for x in 'pqrstuvwxyzPQRST':
        for y in '0123456789abcdef':
            pty_name = '/dev/pty' + x + y
            try:
                fd = os.open(pty_name, os.O_RDWR)
            except os.error:
                continue
            return (fd, '/dev/tty' + x + y)
    raise os.error, 'out of pty devices'

def subordinate_open(tty_name):
    """subordinate_open(tty_name) -> subordinate_fd
    Open the pty subordinate and acquire the controlling terminal, returning
    opened filedescriptor.
    Deprecated, use openpty() instead."""

    result = os.open(tty_name, os.O_RDWR)
    try:
        from fcntl import ioctl, I_PUSH
    except ImportError:
        return result
    try:
        ioctl(result, I_PUSH, "ptem")
        ioctl(result, I_PUSH, "ldterm")
    except IOError:
        pass
    return result

def fork():
    """fork() -> (pid, main_fd)
    Fork and make the child a session leader with a controlling terminal."""

    try:
        pid, fd = os.forkpty()
    except (AttributeError, OSError):
        pass
    else:
        if pid == CHILD:
            try:
                os.setsid()
            except OSError:
                # os.forkpty() already set us session leader
                pass
        return pid, fd

    main_fd, subordinate_fd = openpty()
    pid = os.fork()
    if pid == CHILD:
        # Establish a new session.
        os.setsid()
        os.close(main_fd)

        # Subordinate becomes stdin/stdout/stderr of child.
        os.dup2(subordinate_fd, STDIN_FILENO)
        os.dup2(subordinate_fd, STDOUT_FILENO)
        os.dup2(subordinate_fd, STDERR_FILENO)
        if (subordinate_fd > STDERR_FILENO):
            os.close (subordinate_fd)

        # Explicitly open the tty to make it become a controlling tty.
        tmp_fd = os.open(os.ttyname(STDOUT_FILENO), os.O_RDWR)
        os.close(tmp_fd)
    else:
        os.close(subordinate_fd)

    # Parent and child process.
    return pid, main_fd

def _writen(fd, data):
    """Write all the data to a descriptor."""
    while data != '':
        n = os.write(fd, data)
        data = data[n:]

def _read(fd):
    """Default read function."""
    return os.read(fd, 1024)

def _copy(main_fd, main_read=_read, stdin_read=_read):
    """Parent copy loop.
    Copies
            pty main -> standard output   (main_read)
            standard input -> pty main    (stdin_read)"""
    fds = [main_fd, STDIN_FILENO]
    while True:
        rfds, wfds, xfds = select(fds, [], [])
        if main_fd in rfds:
            data = main_read(main_fd)
            if not data:  # Reached EOF.
                fds.remove(main_fd)
            else:
                os.write(STDOUT_FILENO, data)
        if STDIN_FILENO in rfds:
            data = stdin_read(STDIN_FILENO)
            if not data:
                fds.remove(STDIN_FILENO)
            else:
                _writen(main_fd, data)

def spawn(argv, main_read=_read, stdin_read=_read):
    """Create a spawned process."""
    if type(argv) == type(''):
        argv = (argv,)
    pid, main_fd = fork()
    if pid == CHILD:
        os.execlp(argv[0], *argv)
    try:
        mode = tty.tcgetattr(STDIN_FILENO)
        tty.setraw(STDIN_FILENO)
        restore = 1
    except tty.error:    # This is the same as termios.error
        restore = 0
    try:
        _copy(main_fd, main_read, stdin_read)
    except (IOError, OSError):
        if restore:
            tty.tcsetattr(STDIN_FILENO, tty.TCSAFLUSH, mode)

    os.close(main_fd)
