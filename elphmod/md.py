# Copyright (C) 2017-2022 elphmod Developers
# This program is free software under the terms of the GNU GPLv3 or later.

"""Charge-density-wave dynamics on supercells."""

from __future__ import division

import copy
import numpy as np

from . import MPI, diagrams, dispersion, misc, ph

comm = MPI.comm
info = MPI.info

class Driver(object):
    """MD driver for DFPT-based displacements dynamics.

    Parameters
    ----------
    elph : object
        Localized model for electron-phonon coupling. Initialize ``el`` with
        ``rydberg=True`` and ``ph`` and ``elph`` with ``divide_mass=False`` and
        map everthing to the appropriate supercell before (``elph.supercell``).
    kT : float
        Smearing temperature in Ry.
    f : function
        Particle distribution as a function of energy divided by `kT`.
    n : float
        Number of electrons per primitive cell.
    nk, nq : tuple of int
        Shape of k and q mesh.
    supercell : ndarray, optional
        Supercell lattice vectors as multiples of primitive lattice vectors. If
        given, the simulation is performed on a supercell for q = k = 0. Sparse
        matrices are used for Hamiltonian, dynamical matrix, and electron-phonon
        coupling to save memory. The calculation of phonons is not implemented.
        Note that `elph` should belong to the primitive cell in this case.

    Attributes
    ----------
    elph, kT, f, n, nk, nq
        Copies of initialization parameters.
    mu : float
        Current chemical potential.
    k, q : ndarray
        k and q meshes.
    u : ndarray
        Atomic displacements.
    C0 : ndarray
        Unscreened force constants.
    H0 : ndarray
        Unperturbed electron Hamiltonian in orbital basis.
    d0 : ndarray
        Electron-phonon coupling in orbital basis.
    sparse : bool
        Is the simulation performed on a supercell using sparse matrices?
    """
    def __init__(self, elph, kT, f, n, nk, nq, supercell=None):
        if not elph.el.rydberg:
            info("Initialize 'el' with 'rydberg=True'!", error=True)

        if elph.divide_mass or elph.ph.divide_mass:
            info("Initialize 'ph' and 'elph' with 'divide_mass=False'!",
                error=True)

        self.elph = elph

        self.kT = kT
        self.f = f

        self.n = n
        self.mu = 0.0

        self.nk = np.ones(3, dtype=int)
        self.nk[:len(nk)] = nk

        self.nq = np.ones(3, dtype=int)
        self.nq[:len(nq)] = nq

        self.k = 2 * np.pi * np.array([[[(k1, k2, k3)
            for k3 in range(self.nk[2])]
            for k2 in range(self.nk[1])]
            for k1 in range(self.nk[0])], dtype=float) / self.nk

        self.q = 2 * np.pi * np.array([(q1, q2, q3)
            for q1 in range(self.nq[0])
            for q2 in range(self.nq[1])
            for q3 in range(self.nq[2])], dtype=float) / self.nq

        self.H0 = dispersion.sample(self.elph.el.H, self.k)

        self.d0 = self.elph.sample(q=self.q, nk=self.nk)

        self.u = np.zeros(self.elph.ph.size)

        self.sparse = False
        self.diagonalize()

        C = dispersion.sample(self.elph.ph.D, self.q)

        self.C0 = 0.0
        self.C0 = C - self.hessian()

        if supercell is not None:
            self.elph.ph = copy.copy(self.elph.ph)

            ph.q2r(self.elph.ph, nq=nq, D_full=self.C0, divide_mass=False)

            self.elph = self.elph.supercell(*supercell, sparse=True)

            self.H0 = self.elph.el.Hs.toarray()
            self.C0 = self.elph.ph.Ds.toarray()[np.newaxis]
            self.d0 = self.elph.gs

            for x in range(self.elph.ph.size):
                self.d0[x] = self.d0[x].tobsr()

            self.n *= len(self.elph.cells)
            self.u = np.tile(self.u, len(self.elph.cells))

            self.nk = np.ones(3, dtype=int)
            self.nq = np.ones(3, dtype=int)

            self.k = np.zeros((1, 1, 1, 3))
            self.q = np.zeros((1, 3))

            self.sparse = True
            self.diagonalize()

        self.F0 = 0.0
        self.F0 = -self.jacobian(show=False)

    def random_displacements(self, amplitude=0.01):
        """Displace atoms randomly from unperturbed positions.

        Parameters
        ----------
        amplitude : float
            Maximum displacement.
        """
        if comm.rank == 0:
            self.u = amplitude * (1 - 2 * np.random.rand(self.u.size))
            self.center_mass()

        comm.Bcast(self.u)

    def center_mass(self):
        """Subtract collective translational displacement component."""

        self.u -= np.tile(np.average(self.u.reshape((-1, 3)), axis=0),
            self.elph.ph.nat)

    def find_chemical_potential(self, eps=1e-10, damp=1e-2):
        """Update Fermi level via fixed-point iteration.

        Parameters
        ----------
        eps : float
            Tolerance for the electron number.
        damp : float
            Damping factor in the fixed-point equation. Large values may prevent
            convergence; small values will slow down convergence.
        """
        while True:
            n = 2 * self.f((self.e - self.mu) / self.kT).sum() / self.nk.prod()

            if abs(self.n - n) < eps:
                return self.mu

            self.mu += (self.n / n - 1) * damp

    def diagonalize(self):
        """Diagonalize Hamiltonian of perturbed system."""

        self.center_mass()

        if self.sparse:
            H = self.H0 + self.u.dot(self.d0).toarray()
        else:
            H = self.H0 + np.einsum('xijkmn,x->ijkmn', self.d0[0], self.u)

        self.e, self.U = np.linalg.eigh(H)

        self.e -= self.find_chemical_potential()

    def free_energy(self, u=None, show=True):
        """Calculate free energy.

        Parameters
        ----------
        u : ndarray
            Updated atomic displacements (e.g., from optimization routine).
        show : bool
            Print free energy?
        """
        if u is not None:
            self.u = u

        self.diagonalize()

        prefactor = 2.0 / self.nk.prod()

        E = prefactor * (self.f(self.e / self.kT) * self.e).sum() # E - mu N
        E += self.mu * self.n # mu N
        E -= prefactor * self.kT * self.f.entropy(self.e / self.kT).sum() # T S

        E += 0.5 * self.u.dot(self.C0[0].real).dot(self.u)

        E += self.F0.dot(self.u)

        if show:
            info('Free energy: %15.9f Ry' % E)

        return E

    def jacobian(self, parameters=None, show=True):
        """Calculate first derivative of free energy.

        Parameters
        ----------
        parameters : ndarray
            Dummy positional argument for optimization routines.
        show : bool
            Print free energy?
        """
        if self.sparse:
            f = np.einsum('am,m,bm->ab',
                self.U.conj(), self.f(self.e / self.kT), self.U).real

            F = np.array([2 * self.d0[x].multiply(f).sum()
                for x in range(self.elph.ph.size)])
        else:
            F = diagrams.first_order(self.e, self.d0[0], self.kT,
                U=self.U, occupations=self.f).real

        F += self.C0[0].real.dot(self.u)

        F += self.F0

        if show:
            info('Total force: %15.9f Ry/Bohr' % np.linalg.norm(F))

        return F

    def hessian(self, parameters=None):
        """Calculate second derivative of free energy.

        Parameters
        ----------
        parameters : ndarray
            Dummy positional argument for optimization routines.
        show : bool
            Print free energy?
        """
        if self.sparse:
            raise NotImplementedError

        self.d = np.empty_like(self.d0)

        for iq in range(len(self.q)):
            V = self.U.conj().swapaxes(-2, -1)

            q = np.round(self.nk * self.q[iq] / (2 * np.pi)).astype(int)

            for i in range(3):
                if q[i]:
                    V = np.roll(V, -q[i], axis=i)

            self.d[iq] = V @ self.d0[iq] @ self.U

        C = diagrams.phonon_self_energy(self.q, self.e, g=self.d,
            kT=self.kT, occupations=self.f)

        C[0] += diagrams.phonon_self_energy_fermi_shift(self.e,
            self.d[0], self.kT, occupations=self.f)

        C += self.C0

        return C

    def phonons(self, divide_mass=True):
        """Set up mass-spring model for current structure.

        divide_mass : bool
            Divide force constants by atomic masses?
        """
        model = copy.copy(self.elph.ph)
        model.divide_mass = divide_mass
        model.r += self.u.reshape((-1, 3))

        ph.q2r(model, D_full=self.hessian(), nq=self.nq, divide_mass=False)

        return model

    def plot(self, scale=10.0, padding=1.0):
        """Plot crystal structure and displacements.

        Parameters
        ----------
        scale : float, default 10.0
            Displacement scaling factor.
        padding : float
            Padding between crystal and plotting box in angstrom.
        """
        if comm.rank != 0:
            return

        import matplotlib.pyplot as plt

        r = self.elph.ph.r + self.u.reshape(self.elph.ph.r.shape)

        ax = plt.axes(projection='3d')

        ax.scatter(*r.T, s=100.0, c=['#%02x%02x%02x' % misc.colors[X]
            for X in self.elph.ph.atom_order])

        ax.quiver(*r.T, *scale * self.u.reshape(r.shape).T, color='gray')

        for i, lim in enumerate([ax.set_xlim, ax.set_ylim, ax.set_zlim]):
            lim(r[:, i].min() - padding, r[:, i].max() + padding)

        ax.set_box_aspect(np.ptp(r, axis=0) + 2 * padding)
        ax.set_axis_off()

        plt.show()

    def __call__(self, a, r):
        """Interface driver with i-PI.

        Parameters
        ----------
        a : ndarray
            Dummy cell dimensions for variable-cell MD. Our cell is fixed.
        r : ndarray
            Cartesian atomic positions.

        Notes
        -----
        The factor 0.5 converts Rydberg to Hartree units.
        """
        self.u = (r - self.elph.ph.r).ravel()

        E = 0.5 * self.free_energy(show=False)
        F = -0.5 * self.jacobian(show=False)

        virial = np.zeros_like(self.elph.ph.a)
        extras = 'silent'

        return E, F, virial, extras
