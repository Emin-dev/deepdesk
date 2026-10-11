"""Review-only first-party canary diagnostic. Not an activated or locally run probe."""

def main():
    import sys
    # The reviewed parent supplies one fresh, regular, work-local marker path.
    # Each branch writes only these fixed tokens; no exception text or errno is written.
    def mark(token):
        with open(sys.argv[1], 'ab') as stream:
            stream.write(token)
            stream.flush()
    mark(b'entered\n')
    outcome = b'setup_exception\n'
    passed = False
    try:
        import errno
        import subprocess
        mark(b'imports_ready\n')
        try:
            subprocess.run(['/usr/bin/true'], check=True)
        except OSError as error:
            if error.errno in (errno.EPERM, errno.EACCES):
                outcome = b'permission_denied\n'
                passed = True
            else:
                outcome = b'other_oserror\n'
        except subprocess.CalledProcessError:
            outcome = b'child_nonzero\n'
        except Exception:
            outcome = b'other_exception\n'
        else:
            outcome = b'exec_succeeded\n'
    except Exception:
        outcome = b'setup_exception\n'
    mark(outcome)
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
