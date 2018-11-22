#/usr/bin/env python

import numpy as np

from . import MPI, occupations
comm = MPI.comm
info = MPI.info

kB = 8.61733e-5 # Boltzmann constant (eV/K)

def susceptibility(e, T=1.0, eta=1e-10, occupations=occupations.fermi_dirac):
    """Calculate real part of static electronic susceptibility.

        chi(q) = 2/N sum[k] [f(k+q) - f(k)] / [e(k+q) - e(k) + i eta]

    The resolution in q is limited by the resolution in k.

    Parameters
    ----------
    e : ndarray
        Electron dispersion on uniform mesh. The Fermi level must be at zero.
    T : float
        Smearing temperature in K.
    eta : float
        Absolute value of "infinitesimal" i0+ in denominator.
    occupations : function
        Particle distribution as a function of energy divided by kT.

    Returns
    -------
    function
        Static electronic susceptibility as a function of q1, q2 in [0, 2pi).
    """
    nk, nk = e.shape

    kT = kB * T
    x = e / kT

    f = occupations(x)
    d = occupations.delta(x).sum() / kT

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

def susceptibility2(e, T=1.0, eta=1e-10, occupations=occupations.fermi_dirac,nmats=1000,hyb_width=1.,hyb_height=0.):
    """Calculate real part of static electronic susceptibility.

        chi(q) = 2/N sum[k] [f(k+q) - f(k)] / [e(k+q) - e(k) + i eta]

    The resolution in q is limited by the resolution in k.

    Parameters
    ----------
    e : ndarray
        Electron dispersion on uniform mesh. The Fermi level must be at zero.
    T : float
        Smearing temperature in K.
    eta : float
        Absolute value of "infinitesimal" i0+ in denominator.
    occupations : function
        Particle distribution as a function of energy divided by kT.

    Returns
    -------
    function
        Static electronic susceptibility as a function of q1, q2 in [0, 2pi).
    """
    nk, nk = e.shape

    kT = kB * T
    x = e / kT

    f = occupations(x)
    d = occupations.delta(x).sum() / kT

    e = np.tile(e, (2, 2))
    f = np.tile(f, (2, 2))

    scale = nk / (2 * np.pi)
    eta2 = eta ** 2
    prefactor = kT*4.0 / nk**2 
    # factor 2 for the negative mats
    # factor 2 for spin
    
    tail_contribution = -2./(4*kT) # See Thesis Hartmut Hafermann, App B.
    # Factor 2 for spin
    
    def Delta(inu):
        return -2j *hyb_height*np.arctan(2*hyb_width/inu.imag)

    def G(inu,hmlt):
        return 1./(inu - hmlt+eta-Delta(inu))

    def matsgen():
        """Generate the positive fermionic Matsubara frequencies"""
        for n in range(nmats):
            yield 1j*(2*n+1)*np.pi*kT
    
    # Calculate the Lindhardt bubble using the Green's functions explicitly
    # Only w=0 calculations is performed
    #
    # For the treatment of the 1/inu tail, see:
    # Appendix B of the thesis of Hartmut Hafermann
    #
    # chi = beta/4 - 1/beta sum (GG - 1/(inu^2) )
    #
    # Multiply by 2 for spin
    

    def calculate_susceptibility(q1=0, q2=0):
        
        q1 = int(round(q1 * scale)) % nk
        q2 = int(round(q2 * scale)) % nk
        
        # These are still numpy arrays
        e1 = e[q1:q1 + nk, q2:q2 + nk] 
        e0 = e[:nk, :nk]
            
        return tail_contribution+\
          prefactor*np.sum(sum(G(inu,e1)*G(inu,e0)- 1./(inu*inu) for inu in matsgen()))

    calculate_susceptibility.size = 1

    return calculate_susceptibility

def polarization(e, c, T=1.0, i0=1e-10j, subspace=None,
        occupations=occupations.fermi_dirac):
    """Calculate RPA polarization in orbital basis (density-density).

        Pi(q, a, b) = 2/N sum[k, n, m]
            <k+q m|k+q a> <k a|k n> <k n|k b> <k+q b|k+q m>
            [f(k+q, m) - f(k, n)] / [e(k+q, m) - e(k, n) + i0]

    The resolution in q is limited by the resolution in k.

    If 'subspace' is given, a cRPA calculation is performed. 'subspace' must be
    a boolean array with the same shape as 'e', where 'True' marks states of the
    target subspace, interactions between which are excluded.

    Parameters
    ----------
    e : ndarray
        Electron dispersion on uniform mesh. The Fermi level must be at zero.
    c : ndarray
        Coefficients for transform to orbital basis. These are given by the
        eigenvectors of the Wannier Hamiltonian.
    T : float
        Smearing temperature in K.
    i0 : imaginary number
        "Infinitesimal" i0+ in denominator.
    subspace : ndarray or None
        Boolean array to select k points and/or bands in cRPA target subspace.
    occupations : function
        Particle distribution as a function of energy divided by kT.

    Returns
    -------
    function
        RPA polarization in orbital basis as a function of q1, q2 in [0, 2pi).
    """
    cRPA = subspace is not None

    if e.ndim == 2:
        e = e[:, :, np.newaxis]

    if c.ndim == 3:
        c = c[:, :, :, np.newaxis]

    if cRPA and subspace.shape != e.shape:
        subspace = np.reshape(subspace, e.shape)

    nk, nk, nb = e.shape
    nk, nk, no, nb = c.shape # c[k1, k2, a, n] = <k a|k n>

    kT = kB * T
    x = e / kT

    f = occupations(x)
    d = occupations.delta(x) / (-kT)

    e = np.tile(e, (2, 2, 1))
    f = np.tile(f, (2, 2, 1))
    c = np.tile(c, (2, 2, 1, 1))

    if cRPA:
        subspace = np.tile(subspace, (2, 2, 1))

    scale = nk / (2 * np.pi)
    prefactor = 2.0 / nk ** 2

    k1 = slice(0, nk)
    k2 = k1

    def calculate_polarization(q1=0, q2=0):
        q1 = int(round(q1 * scale)) % nk
        q2 = int(round(q2 * scale)) % nk

        Gamma = q1 == q2 == 0

        kq1 = slice(q1, q1 + nk)
        kq2 = slice(q2, q2 + nk)

        Pi = np.empty((nb, nb, no, no), dtype=complex)

        for n in range(nb):
            for m in range(nb):
                if Gamma and n == m:
                    dfde = d[k1, k2, n]
                else:
                    df = f[kq1, kq2, m] - f[k1, k2, n]
                    de = e[kq1, kq2, m] - e[k1, k2, n]

                    dfde = df / (de + i0)

                if cRPA:
                    exclude = np.where(
                        subspace[kq1, kq2, m] & subspace[k1, k2, n])

                    dfde[exclude] = 0.0

                cc = c[kq1, kq2, :, m].conj() * c[k1, k2, :, n]

                for a in range(no):
                    cca = cc[:, :, a]

                    for b in range(no):
                        ccb = cc[:, :, b].conj()

                        Pi[n, m, a, b] = np.sum(cca * ccb * dfde)

        return prefactor * Pi.sum(axis=(0, 1))

    calculate_polarization.size = nb

    return calculate_polarization

def phonon_self_energy(q, e, g2, T=100.0, i0=1e-10j,
        occupations=occupations.fermi_dirac):
    """Calculate phonon self-energy.

        Pi(q, nu) = 2/N sum[k] |g(q, nu, k)|^2
            [f(k+q) - f(k)] / [e(k+q) - e(k) + i0]

    Parameters
    ----------
    q : list of 2-tuples
        Considered q points defined via crystal coordinates q1, q2 in [0, 2pi).
    e : ndarray
        Electron dispersion on uniform mesh. The Fermi level must be at zero.
    g2 : ndarray
        Squared electron-phonon coupling.
    T : float
        Smearing temperature in K.
    i0 : imaginary number
        "Infinitesimal" i0+ in denominator.
    occupations : function
        Particle distribution as a function of energy divided by kT.

    Returns
    -------
    ndarray
        Phonon self-energy.
    """
    nk, nk = e.shape
    nQ, nb, nk, nk = g2.shape

    kT = kB * T
    x = e / kT

    f = occupations(x)
    d = occupations.delta(x) / (-kT)

    e = np.tile(e, (2, 2))
    f = np.tile(f, (2, 2))

    scale = nk / (2 * np.pi)
    prefactor = 2.0 / nk ** 2

    sizes, bounds = MPI.distribute(nQ, bounds=True)

    my_Pi = np.empty((sizes[comm.rank], nb), dtype=complex)

    info('Pi(%3s, %3s, %3s) = ...' % ('q1', 'q2', 'nu'))

    for my_iq, iq in enumerate(range(*bounds[comm.rank:comm.rank + 2])):
        q1 = int(round(q[iq, 0] * scale)) % nk
        q2 = int(round(q[iq, 1] * scale)) % nk

        if q1 == q2 == 0:
            chi = d
        else:
            df = f[q1:q1 + nk, q2:q2 + nk] - f[:nk, :nk]
            de = e[q1:q1 + nk, q2:q2 + nk] - e[:nk, :nk]

            chi = df / (de + i0)

        for nu in range(nb):
            my_Pi[my_iq, nu] = prefactor * np.sum(g2[iq, nu] * chi)

            print('Pi(%3d, %3d, %3d) = %9.2e%+9.2ei'
                % (q1, q2, nu, my_Pi[my_iq, nu].real, my_Pi[my_iq, nu].imag))

    Pi = np.empty((nQ, nb), dtype=complex)

    comm.Allgatherv(my_Pi, (Pi, sizes * nb))

    return Pi
