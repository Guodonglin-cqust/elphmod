#!/usr/bin/env python3

# Copyright (C) 2017-2022 elphmod Developers
# This program is free software under the terms of the GNU GPLv3 or later.

import copy
import elphmod
import matplotlib.pyplot as plt
import numpy as np

comm = elphmod.MPI.comm
info = elphmod.MPI.info

kT = 0.01 * elphmod.misc.Ry
f = elphmod.occupations.gauss

nk = 6
nq = 2

info('Prepare wave vectors')

q = sorted(elphmod.bravais.irreducibles(nq))
q = 2 * np.pi * np.array(q, dtype=float) / nq

path, x, GMKG = elphmod.bravais.path('GMKG', ibrav=4, N=200)

info('Prepare electrons')

el = elphmod.el.Model('graphene')
mu = elphmod.el.read_Fermi_level('scf.out')

e, U, order = elphmod.dispersion.dispersion_full_nosym(el.H, nk,
    vectors=True, order=True)

nel = 2
e = e[..., -nel:] - mu
U = U[..., -nel:]

info('Prepare phonons')

ph = dict()

for method in 'cdfpt', 'dfpt':
    ph[method] = elphmod.ph.Model('%s.ifc' % method)

info('Prepare electron-phonon coupling')

g = dict()

for method in sorted(ph):
    elph = elphmod.elph.Model('%s.epmatwp' % method, 'wigner.dat',
        el, ph['cdfpt'])

    g[method] = elph.sample(q=q, U=U, u=None, broadcast=False)

if comm.rank == 0:
    g2 = np.einsum('qiklmn,qjklmn->qijklmn', g['cdfpt'].conj(), g['dfpt'])
    g2 *= elphmod.misc.Ry ** 3

    g2 += np.einsum('qijklmn->qjiklmn', g2.conj())
    g2 /= 2
else:
    g2 = np.empty((len(q), ph['cdfpt'].size, ph['cdfpt'].size,
        nk, nk, nel, nel), dtype=complex)

comm.Bcast(g2)

info('Calculate phonon self-energy')

Pi = elphmod.diagrams.phonon_self_energy(q, e, g2, kT=kT, occupations=f)
Pi = np.reshape(Pi, (len(q), ph['cdfpt'].size, ph['cdfpt'].size))
Pi /= elphmod.misc.Ry ** 2

info('Renormalize phonons')

D = elphmod.dispersion.sample(ph['cdfpt'].D, q)

ph['cdfpt+pi'] = copy.copy(ph['cdfpt'])

elphmod.ph.q2r(ph['cdfpt+pi'], D + Pi, q, nq)

info('Plot electrons')

e = elphmod.dispersion.dispersion(el.H, path)
e -= mu

if comm.rank == 0:
    for n in range(el.size):
        plt.plot(x, e[:, n], 'b')

    plt.ylabel(r'$\epsilon$ (eV)')
    plt.xlabel(r'$k$')
    plt.xticks(x[GMKG], 'GMKG')
    plt.show()

info('Plot cDFPT, DFPT and renormalized phonons')

for method, label, style in [('dfpt', 'DFPT', 'r'), ('cdfpt', 'cDFPT', 'g'),
        ('cdfpt+pi', r'cDFPT+$\Pi$', 'b:')]:

    w2 = elphmod.dispersion.dispersion(ph[method].D, path)

    w = elphmod.ph.sgnsqrt(w2) * elphmod.misc.Ry * 1e3

    if comm.rank == 0:
        for nu in range(ph[method].size):
            plt.plot(x, w[:, nu], style, label=None if nu else label)

if comm.rank == 0:
    plt.ylabel(r'$\omega$ (meV)')
    plt.xlabel(r'$q$')
    plt.xticks(x[GMKG], 'GMKG')
    plt.legend()
    plt.show()
