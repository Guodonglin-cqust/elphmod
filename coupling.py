#/usr/bin/env python

import bravais
import numpy as np
from scipy.interpolate import interp2d

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

    elphmat = np.zeros((nq, nq, bands))

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

    q = np.linspace(0.0, 1.0, nq + 1)

    elphmatper = np.empty((nq + 1, nq + 1, bands))
    elphmatper[:nq, :nq] = elphmat

    elphmatper[nq, :] = elphmatper[0, :]
    elphmatper[:, nq] = elphmatper[:, 0]

    for nu in range(bands):
        elphfun = interp2d(q, q, elphmatper[:, :, nu], kind='linear')

        for i in reversed(range(len(qy))):
            for j in range(len(qx)):
                q1 = qx[j] * bravais.T1[0] + qy[i] * bravais.T1[1]
                q2 = qx[j] * bravais.T2[0] + qy[i] * bravais.T2[1]

                image[nu, i, j] = elphfun(q1 % 1, q2 % 1)

    return \
        np.concatenate([
        np.concatenate(
            image[3 * n:3 * n + 3],
        axis=1) for n in range(bands / 3)],
        axis=0)

if __name__ == '__main__':
    import matplotlib.pyplot as plt

    plt.imshow(plot(complete(read('data/NbSe2-cDFPT-LR.elph'), 12, 9)))
    plt.show()
