#include "blur.h"

#include <stdio.h>
#include <stdlib.h>

// consumer(
//     n : size,
//     m : size,
//     f : ui8[n, m] @DRAM,
//     g : ui8[n, m] @DRAM
// )
static void consumer(
    void *ctxt, int_fast32_t n, int_fast32_t m, const uint8_t *f, uint8_t *g);

// producer(
//     n : size,
//     m : size,
//     f : ui8[n, m] @DRAM,
//     inp : ui8[n, m] @DRAM
// )
static void producer(
    void *ctxt, int_fast32_t n, int_fast32_t m, uint8_t *f, const uint8_t *inp);

// blur_inlined(
//     n : size,
//     m : size,
//     g : ui8[n, m] @DRAM,
//     inp : ui8[n, m] @DRAM
// )
void blur_inlined(void *ctxt, int_fast32_t n, int_fast32_t m, uint8_t *g,
    const uint8_t *inp) {
  EXO_ASSUME(n > 5);
  EXO_ASSUME(m > 5);
  for (int_fast32_t i = 0; i < -4 + n; i++) {
    for (int_fast32_t j = 0; j < -4 + m; j++) {
      g[i * m + j] =
          ((inp[i * m + j] + inp[i * m + 1 + j] + inp[i * m + 2 + j] +
               inp[i * m + 3 + j] + inp[i * m + 4 + j]) /
                  5.0 +
              (inp[(1 + i) * m + j] + inp[(1 + i) * m + 1 + j] +
                  inp[(1 + i) * m + 2 + j] + inp[(1 + i) * m + 3 + j] +
                  inp[(1 + i) * m + 4 + j]) /
                  5.0 +
              (inp[(2 + i) * m + j] + inp[(2 + i) * m + 1 + j] +
                  inp[(2 + i) * m + 2 + j] + inp[(2 + i) * m + 3 + j] +
                  inp[(2 + i) * m + 4 + j]) /
                  5.0 +
              (inp[(3 + i) * m + j] + inp[(3 + i) * m + 1 + j] +
                  inp[(3 + i) * m + 2 + j] + inp[(3 + i) * m + 3 + j] +
                  inp[(3 + i) * m + 4 + j]) /
                  5.0 +
              (inp[(4 + i) * m + j] + inp[(4 + i) * m + 1 + j] +
                  inp[(4 + i) * m + 2 + j] + inp[(4 + i) * m + 3 + j] +
                  inp[(4 + i) * m + 4 + j]) /
                  5.0) /
          5.0;
    }
  }
}

// blur_staged(
//     n : size,
//     m : size,
//     g : ui8[n, m] @DRAM,
//     inp : ui8[n, m] @DRAM
// )
void blur_staged(void *ctxt, int_fast32_t n, int_fast32_t m, uint8_t *g,
    const uint8_t *inp) {
  EXO_ASSUME(n > 5);
  EXO_ASSUME(m > 5);
  uint8_t *f = (uint8_t *)malloc(n * m * sizeof(*f));
  producer(ctxt, n, m, f, inp);
  consumer(ctxt, n, m, f, g);
  free(f);
}

// consumer(
//     n : size,
//     m : size,
//     f : ui8[n, m] @DRAM,
//     g : ui8[n, m] @DRAM
// )
static void consumer(
    void *ctxt, int_fast32_t n, int_fast32_t m, const uint8_t *f, uint8_t *g) {
  EXO_ASSUME(n > 5);
  EXO_ASSUME(m > 5);
  for (int_fast32_t i = 0; i < n - 4; i++) {
    for (int_fast32_t j = 0; j < m - 4; j++) {
      g[i * m + j] = (f[i * m + j] + f[(i + 1) * m + j] + f[(i + 2) * m + j] +
                         f[(i + 3) * m + j] + f[(i + 4) * m + j]) /
                     5.0;
    }
  }
}

// producer(
//     n : size,
//     m : size,
//     f : ui8[n, m] @DRAM,
//     inp : ui8[n, m] @DRAM
// )
static void producer(void *ctxt, int_fast32_t n, int_fast32_t m, uint8_t *f,
    const uint8_t *inp) {
  EXO_ASSUME(m > 5);
  for (int_fast32_t i = 0; i < n; i++) {
    for (int_fast32_t j = 0; j < m - 4; j++) {
      f[i * m + j] = (inp[i * m + j] + inp[i * m + j + 1] + inp[i * m + j + 2] +
                         inp[i * m + j + 3] + inp[i * m + j + 4]) /
                     5.0;
    }
  }
}