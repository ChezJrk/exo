
#pragma once
#ifndef BLUR_H
#define BLUR_H

#ifdef __cplusplus
extern "C" {
#endif


#include <stdint.h>
#include <stdbool.h>

// Compiler feature macros adapted from Hedley (public domain)
// https://github.com/nemequ/hedley

#if defined(__has_builtin)
#  define EXO_HAS_BUILTIN(builtin) __has_builtin(builtin)
#else
#  define EXO_HAS_BUILTIN(builtin) (0)
#endif

#if EXO_HAS_BUILTIN(__builtin_assume)
#  define EXO_ASSUME(expr) __builtin_assume(expr)
#elif EXO_HAS_BUILTIN(__builtin_unreachable)
#  define EXO_ASSUME(expr) \
      ((void)((expr) ? 1 : (__builtin_unreachable(), 1)))
#else
#  define EXO_ASSUME(expr) ((void)(expr))
#endif



// blur_compute_at_store_at(
//     n : size,
//     g : ui8[n] @DRAM,
//     inp : ui8[n + 6] @DRAM
// )
void blur_compute_at_store_at( void *ctxt, int_fast32_t n, uint8_t* g, const uint8_t* inp );

// blur_compute_at_store_root(
//     n : size,
//     g : ui8[n] @DRAM,
//     inp : ui8[n + 6] @DRAM
// )
void blur_compute_at_store_root( void *ctxt, int_fast32_t n, uint8_t* g, const uint8_t* inp );

// blur_inline(
//     n : size,
//     g : ui8[n] @DRAM,
//     inp : ui8[n + 6] @DRAM
// )
void blur_inline( void *ctxt, int_fast32_t n, uint8_t* g, const uint8_t* inp );

// blur_staged(
//     n : size,
//     g : ui8[n] @DRAM,
//     inp : ui8[n + 6] @DRAM
// )
void blur_staged( void *ctxt, int_fast32_t n, uint8_t* g, const uint8_t* inp );



#ifdef __cplusplus
}
#endif
#endif  // BLUR_H
