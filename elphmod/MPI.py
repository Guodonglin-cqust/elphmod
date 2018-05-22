#/usr/bin/env python

import sys
import numpy as np

from mpi4py import MPI
comm = MPI.COMM_WORLD

def distribute(size):
    """Distribute work among processes."""

    sizes = np.empty(comm.size, dtype=int)

    if comm.rank == 0:
        sizes[:] = size // comm.size
        sizes[:size % comm.size] += 1

    comm.Bcast(sizes)

    return sizes

def shared_array(shape, dtype):
    "Create array whose memory is shared among all processes."

    # Shared memory allocation following Lisandro Dalcin on Google Groups:
    # 'Shared memory for data structures and mpi4py.MPI.Win.Allocate_shared'

    size = np.prod(shape)
    dtype = np.dtype(dtype)
    itemsize = dtype.itemsize

    if comm.rank == 0:
        bytes = size * itemsize
    else:
        bytes = 0

    win = MPI.Win.Allocate_shared(bytes, itemsize, comm=comm)
    buf, itemsize = win.Shared_query(0)
    buf = np.array(buf, dtype='B', copy=False) # Is this line really needed?

    return np.ndarray(shape, buffer=buf, dtype=dtype)

def info(message, error=False):
    """Print status message from first process."""

    comm.barrier()

    if comm.rank == 0:
        if error:
            sys.stdout.write('Error: ')

        print(message)

    if error:
        sys.exit()
