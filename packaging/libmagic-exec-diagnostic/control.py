"""First-party entry-only control; no subprocess or native payload invocation."""
import sys
with open(sys.argv[1], 'ab') as stream:
    stream.write(b'entered\n')
    stream.flush()
