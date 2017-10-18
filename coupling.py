#/usr/bin/env python

import bravais
import numpy as np

def read(filename):
    """Read file with Fermi-surface averaged electron-phonon coupling."""

    elph = dict()

    with open(filename) as data:
        for line in data:
            columns = line.split()

            q = tuple(map(int, columns[:2]))
            elph[q] = map(float, columns[2:])

    return elph

def complete(elph, nq, bands):
    """Generate whole Brillouin zone from irreducible q points."""

    elphmat = np.empty((nq, nq, bands))

    for q in elph.keys():
        for Q in bravais.images(*q, nk=nq):
            elphmat[Q] = elph[q]

    return elphmat

def plot(elphmat, points=50):
    """Plot electron-phonong coupling."""

    nq, nq, bands = elphmat.shape

    qxmax = 2 * bravais.U1[0]
    qymax = 2 * bravais.U2[1]

    nqx = int(round(points * qxmax))
    nqy = int(round(points * qymax))

    qx = np.linspace(0.0, qxmax, nqx, endpoint=False)
    qy = np.linspace(0.0, qymax, nqy, endpoint=False)

    image = np.empty((bands, nqy, nqx))

    for nu in range(bands):
        for i in reversed(range(len(qy))):
            for j in range(len(qx)):
                q1 = qx[j] * bravais.T1[0] + qy[i] * bravais.T1[1]
                q2 = qx[j] * bravais.T2[0] + qy[i] * bravais.T2[1]

                image[nu, i, j] = bravais.interpolate(elphmat[:, :, nu],
                    q1 * nq, q2 * nq)

    return \
        np.concatenate([
        np.concatenate(
            image[3 * n:3 * n + 3],
        axis=1) for n in range(bands / 3)],
        axis=0)

if __name__ == '__main__':
    import matplotlib.pyplot as plt
    import phonons
    import dos

    Ry2eV = 13.605693009
    eV2cmm1 = 8065.54

    nq = 12
    multiple = 4
    nQ = multiple * nq

    D = phonons.dynamical_matrix(*phonons.read_flfrc('data/NbSe2-cDFPT-SR.ifc'))

    w, order = phonons.dispersion(D, nQ)
    w *= Ry2eV * eV2cmm1
    order = order[::multiple, ::multiple]

    elph = complete(read('data/NbSe2-cDFPT-LR.elph'), nq, 9)
    elph *= (1e-3 * eV2cmm1) ** 3

    for n in range(nq):
        for m in range(nq):
            elph[n, m] = elph[n, m, order[n, m]]

    plt.imshow(plot(elph))
    plt.show()

    g2 = np.empty_like(w)

    shrinkage = 1.0 / multiple

    for n in range(w.shape[0]):
        for m in range(w.shape[1]):
            for nu in range(w.shape[2]):
                g2[n, m, nu] = bravais.interpolate(elph[:, :, nu],
                        n * shrinkage, m * shrinkage) / (2 * w[n, m, nu])

    N = 300
    W = np.linspace(w.min(), w.max(), N)
    a2F = np.zeros(N)

    for nu in range(9):
        a2F += dos.hexa2F(w[:, :, nu], g2[:, :, nu])(W)

    plt.fill_between(W, 0, a2F, facecolor='lightgray')
    plt.show()
