#/usr/bin/env python

from . import bravais

import numpy as np
import numpy.linalg

def dispersion(comm, matrix, k,
        vectors=False, gauge=False, rotate=False, order=False, broadcast=True):
    """Diagonalize Hamiltonian or dynamical matrix for given k points."""

    points = len(k)      # number of k points
    bands  = matrix.size # number of bands

    # choose number of k points to be processed by each processor:

    my_points = np.empty(comm.size, dtype=int)
    my_points[:] = points // comm.size
    my_points[:points % comm.size] += 1

    # initialize local lists of k points, eigenvalues and eigenvectors:

    my_k = np.empty((my_points[comm.rank], 2))
    my_v = np.empty((my_points[comm.rank], bands))

    if order or vectors:
        my_V = np.empty((my_points[comm.rank], bands, bands), dtype=complex)

    # distribute k points among processors:

    comm.Scatterv((k, my_points * 2), my_k)

    # diagonalize matrix for local lists of k points:

    for point, (k1, k2) in enumerate(my_k):
        if order or vectors:
            my_v[point], my_V[point] = np.linalg.eigh(matrix(k1, k2))

            if gauge:
                for band in bands:
                    my_V[point, :, band] *= np.exp(-1j * np.angle(
                        max(my_V[point, :, band], key=abs)))

            # rotate phonon eigenvectors by negative angle of k point:

            if rotate:
                x, y = k1 * bravais.u1 + k2 * bravais.u2
                phi = np.arctan2(y, x)

                atoms = bands // 3

                for atom in range(atoms):
                    for band in range(bands):
                        xy = point, [atom, atom + atoms], band
                        my_V[xy] = bravais.rotate(my_V[xy], -phi)
        else:
            my_v[point] = np.linalg.eigvalsh(matrix(k1, k2))

    # gather calculated eigenvectors on first processor:

    v = np.empty((points, bands))
    comm.Gatherv(my_v, (v, my_points * bands))

    if order or vectors:
        V = np.empty((points, bands, bands), dtype=complex)
        comm.Gatherv(my_V, (V, my_points * bands ** 2))

    # order/disentangle bands:

    if order:
        o = np.empty((points, bands), dtype=int)

        if comm.rank == 0:
            o = band_order(v, V)

            for point in range(points):
                v[point] = v[point, o[point]]

                if vectors:
                    for band in range(bands):
                        V[point, band] = V[point, band, o[point]]

    # broadcast results:

    if broadcast:
        comm.Bcast(v)

        if vectors:
            comm.Bcast(V)

        if order:
            comm.Bcast(o)

    return (v, V, o) if vectors and order \
        else (v, V) if vectors else (v, o) if order else v

def dispersion_full(comm, matrix, size,
        rotate=True, order=False, broadcast=True):
    """Diagonalize Hamiltonian or dynamical matrix on uniform k-point mesh."""

    # choose irreducible set of k points:

    k = np.array(sorted(bravais.irreducibles(size)))

    points = len(k)      # number of k points
    bands  = matrix.size # number of bands

    # calculate dispersion using the above routine:

    if order:
        v, V = dispersion(comm, matrix, 2 * np.pi / size * k,
            vectors=True, rotate=rotate, order=False, broadcast=False)

        # order bands along spider-web-like paths:
        #
        # irreducible wedge       K      G = (0 0)
        # of 12 x 12 mesh:       /       M = (0 6)
        #                   o   o        K = (4 4)
        #                  /   /
        #             o   o   o   o
        #            /   /   /   /   (side paths to K)
        #       o   o   o   o   o
        #      /   /   /   /   /
        # G---o---o---o---o---o---M  (main path from G to M)

        if comm.rank == 0:
            o = np.empty((points, bands), dtype=int)

            main_path = [n for n in range(points) if not k[n, 0]]
            main_order = band_order(v[main_path], V[main_path])

            for n, N in zip(main_path, main_order):
                side_path = [m for m in range(points) if k[m, 1] == k[n, 1]]
                side_order = band_order(v[side_path], V[side_path],
                    by_mean=False)

                for m, M in zip(side_path, side_order):
                    o[m] = M[N]
                    v[m] = v[m, o[m]]

    else:
        v = dispersion(comm, matrix, 2 * np.pi / size * k,
            vectors=False, rotate=False, order=False, broadcast=False)

    # fill uniform mesh with data from irreducible wedge:

    v_mesh = np.empty((size, size, bands))

    if order:
        o_mesh = np.empty((size, size, bands), dtype=int)

    if comm.rank == 0:
        # transfer data points from wedge to mesh:

        for point, (k1, k2) in enumerate(k):
            for K1, K2 in bravais.images(k1, k2, size):
                v_mesh[K1, K2] = v[point]

                if order:
                    o_mesh[K1, K2] = o[point]

    # broadcast results:

    if broadcast:
        comm.Bcast(v_mesh)

        if order:
            comm.Bcast(o_mesh)

    return (v_mesh, o_mesh) if order else v_mesh

def band_order(v, V, by_mean=True):
    """Sort bands by overlap of eigenvectors at neighboring k points."""

    points, bands = v.shape

    o = np.empty((points, bands), dtype=int)

    n0 = 0
    o[n0] = range(bands)

    for n in range(1, points):
        for i in range(bands):
            o[n, i] = max(range(bands), key=lambda j:
                np.absolute(np.dot(V[n0, :, o[n0, i]], V[n, :, j].conj())))

        # Only eigenvectors belonging to different eigenvalues are guaranteed to
        # be orthogonal. Thus k points with degenerate eigenvectors are not used
        # as starting point:

        if np.all(np.absolute(np.diff(v[n])) > 1e-10):
            n0 = n

    # reorder disentangled bands by average frequency:

    if by_mean:
        o[:] = o[:, sorted(range(bands), key=lambda i: v[:, o[:, i]].sum())]

    return o
