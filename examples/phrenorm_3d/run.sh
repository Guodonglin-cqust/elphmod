#!/bin/bash

# Copyright (C) 2021 elphmod Developers
# This program is free software under the terms of the GNU GPLv3 or later.

url=http://www.pseudo-dojo.org/pseudos/nc-sr-04_pbe_standard # [1, 2]
pp=Po.upf
test -e $pp || (wget $url/$pp.gz && gunzip $pp)

# [1] van Setten et al., Comput. Phys. Commun. 226, 39 (2018)
# [2] Hamann, Phys. Rev. B 88, 085117 (2013)

nk=2

for method in dfpt cdfpt
do
    mpirun pw.x -nk $nk < scf.in | tee scf.out
    mpirun ph.x -nk $nk < $method.in | tee $method.out

    mpirun q2r.x < q2r.in | tee q2r.out
    ../../bin/ph2epw

    mpirun pw.x -nk $nk < nscf.in | tee nscf.out
    mpirun -n 1 epw.x -nk 1 < epw.in | tee epw.out

    mv ifc $method.ifc
    mv work/polonium.epmatwp $method.epmatwp
done

mpirun python3 phrenorm_3d.py
