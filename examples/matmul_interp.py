from __future__ import annotations

import os
import sys
import numpy as np

from exo import proc
from exo.platforms.neon import *
from exo.stdlib.scheduling import *

# Hide output when running through exocc.
if __name__ != "__main__" and hasattr(os, "devnull"):
    sys.stdout = open(os.devnull, "w"
)

# Algorithm definition
@proc
def rank_k_reduce_6x16(
    M: size, K: size, N: size, A: f32[M, K] @ DRAM, B: f32[K, N] @ DRAM, C: f32[M, N] @ DRAM, test: f32 @ DRAM
):
    s: f32
    s = 3
    for i in seq(0, M):
        for j in seq(0, N):
            for k in seq(0, K):
                C[i, j] += A[i, k] * B[k, j]
                s: f32
                s = 2
    s = s + 1
    test = s

M = 2; K = 2; N = 2
A = np.arange(M*K, dtype=float).reshape((M,K))
B = np.arange(K*N, dtype=float).reshape((K,N))
C = np.zeros(M*N, dtype=float).reshape((M,N))
res = np.zeros(1)

rank_k_reduce_6x16.interpret(M=M, K=K, N=N, A=A, B=B, C=C, test=res)
assert((C == np.dot(A, B)).all())
print(res)