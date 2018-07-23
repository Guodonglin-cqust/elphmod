#/usr/bin/env python

import numpy as np

from . import MPI
comm = MPI.comm
info = MPI.info

kB = 8.61733e-5 # eV/K

def fermi(e, T):
    kT = kB * T
    return 1 / (np.exp(e / kT) + 1)

def delta(e, T): # -df/de
    kT = kB * T
    return 1 / (2 * kT * (np.cosh(e / kT) + 1))

def susceptibility(e, T=1.0, eta=1e-10):
    """Calculate real part of static electronic susceptibility

        chi(q) = 2/N sum[k] [f(k+q) - f(k)] / [e(k+q) - e(k) + i eta].

    The resolution in q is limited by the resolution in k."""

    nk, nk = e.shape

    f = fermi(e, T)
    d = delta(e, T).sum()

    e = np.tile(e, (2, 2))
    f = np.tile(f, (2, 2))

    scale = nk / (2 * np.pi)
    eta2 = eta ** 2
    prefactor = 2.0 / nk ** 2

    def calculate_susceptibility(q1=0, q2=0):
        q1 = int(round(q1 * scale)) % nk
        q2 = int(round(q2 * scale)) % nk

        if q1 == q2 == 0:
            return -prefactor * d

        df = f[q1:q1 + nk, q2:q2 + nk] - f[:nk, :nk]
        de = e[q1:q1 + nk, q2:q2 + nk] - e[:nk, :nk]

        return prefactor * np.sum(df * de / (de * de + eta2))

    calculate_susceptibility.size = 1

    return calculate_susceptibility

def phonon_self_energy(q, e, g2, T=100.0, eta=1e-10):
    """Calculate real part of the phonon self-energy

        Pi(q, nu) = 2/N sum[k] |g(q, nu, k)|^2
            [f(k+q) - f(k)] / [e(k+q) - e(k) + i eta]."""

    nk, nk = e.shape
    nQ, nb, nk, nk = g2.shape

    f = fermi(e, T)

    e = np.tile(e, (2, 2))
    f = np.tile(f, (2, 2))

    scale = nk / (2 * np.pi)
    eta2 = eta ** 2
    prefactor = 2.0 / nk ** 2

    sizes, bounds = MPI.distribute(nQ * nb, bounds=True)

    my_Pi = np.empty((sizes[comm.rank]))

    info('Pi(%3s, %3s, %3s) = ...' % ('q1', 'q2', 'nu'))

    for my_n, n in enumerate(range(*bounds[comm.rank:comm.rank + 2])):
        iq = n // nb
        nu = n % nb

        q1 = int(round(q[iq, 0] * scale)) % nk
        q2 = int(round(q[iq, 1] * scale)) % nk

        df = f[q1:q1 + nk, q2:q2 + nk] - f[:nk, :nk]
        de = e[q1:q1 + nk, q2:q2 + nk] - e[:nk, :nk]

        my_Pi[my_n] = prefactor * np.sum(
            g2[iq, nu] * df * de / (de * de + eta2))

        print('Pi(%3d, %3d, %3d) = %7.2f meV' % (q1, q2, nu, 1e3 * my_Pi[my_n]))

    Pi = np.empty((nQ, nb))

    comm.Allgatherv(my_Pi, (Pi, sizes))

    return Pi
