/*
 * node/fast_kernels.c
 * Compiled kernels for INT4 matmul, RMSNorm, SiLU.
 * Build: see node/build_fast_kernels.py
 *
 * WHY: Numba requires Python <=3.12; this gives the same SIMD gains via
 * AVX2 intrinsics + OpenMP, compatible with any Python version.
 *
 * No standard headers — avoids broken VS / missing SDK installations.
 * uint8_t / size_t are declared inline; sqrtf/expf resolved from ucrtbase.dll.
 */
typedef unsigned char      uint8_t;
typedef unsigned long long size_t;

extern float sqrtf(float);
extern float expf(float);

#ifdef _OPENMP
#include <omp.h>
#endif

/* AVX2 path: process 16 int4 weights per iteration (8 packed bytes) */
#ifdef __AVX2__
#include <immintrin.h>

/*
 * Compute dot product of x[0..orig_cols-1] and the INT4-dequantized row pr[].
 * Uses AVX2 to unpack 8 packed bytes (16 nibbles) per iteration.
 */
static inline float _dot_int4_avx2(
    const uint8_t * restrict pr,   /* packed row: n_packed bytes   */
    const float   * restrict xb,   /* input vector: orig_cols floats */
    float scale,
    int orig_cols)
{
    int half = orig_cols >> 1;
    __m256 vacc = _mm256_setzero_ps();

    /* Process 8 packed bytes (16 nibbles) per iteration */
    int i = 0;
    for (; i + 7 < half; i += 8) {
        /* Load 8 packed bytes → 16 nibbles */
        __m128i vb = _mm_loadl_epi64((const __m128i *)(pr + i));

        /* High nibbles: (byte >> 4) & 0x0F, stored in even int8 positions */
        __m128i vhi8 = _mm_and_si128(_mm_srli_epi16(vb, 4),
                                     _mm_set1_epi8(0x0F));
        /* Low nibbles: byte & 0x0F */
        __m128i vlo8 = _mm_and_si128(vb, _mm_set1_epi8(0x0F));

        /* Convert 8 hi nibbles (int8) → int32 → float32, subtract 8 (zero-point) */
        __m256i vhi32 = _mm256_cvtepi8_epi32(vhi8);
        __m256  vhif  = _mm256_sub_ps(_mm256_cvtepi32_ps(vhi32),
                                       _mm256_set1_ps(8.0f));
        vhif = _mm256_mul_ps(vhif, _mm256_set1_ps(scale));

        /* Same for 8 lo nibbles */
        __m256i vlo32 = _mm256_cvtepi8_epi32(vlo8);
        __m256  vlof  = _mm256_sub_ps(_mm256_cvtepi32_ps(vlo32),
                                       _mm256_set1_ps(8.0f));
        vlof = _mm256_mul_ps(vlof, _mm256_set1_ps(scale));

        /* Load x[2i..2i+7] for hi, x[2i+8..2i+15] for lo
         * Interleave: x[0],x[2],x[4],...,x[14] and x[1],x[3],...,x[15]
         * Use load + shuffle to deinterleave */
        __m256 vx_lo = _mm256_loadu_ps(xb + 2 * i);       /* x[0..7]  */
        __m256 vx_hi = _mm256_loadu_ps(xb + 2 * i + 8);   /* x[8..15] */

        /* Deinterleave: extract even/odd positions using shuffle */
        __m256 vx_even = _mm256_shuffle_ps(vx_lo, vx_hi, 0x88); /* 0,2,4,6,8,10,12,14 */
        __m256 vx_odd  = _mm256_shuffle_ps(vx_lo, vx_hi, 0xDD); /* 1,3,5,7,9,11,13,15 */

        /* Permute to restore correct order after 256-bit shuffle.
         * shuffle(vx_lo,vx_hi,0x88) produces {x0,x2,x8,x10|x4,x6,x12,x14}.
         * Need {x0,x2,x4,x6,x8,x10,x12,x14} → swap middle pair: perm={0,1,4,5,2,3,6,7}. */
        __m256i perm = _mm256_set_epi32(7, 6, 3, 2, 5, 4, 1, 0);
        vx_even = _mm256_permutevar8x32_ps(vx_even, perm);
        vx_odd  = _mm256_permutevar8x32_ps(vx_odd,  perm);

        /* FMA: accumulate hi*x_even + lo*x_odd */
#ifdef __FMA__
        vacc = _mm256_fmadd_ps(vhif, vx_even, vacc);
        vacc = _mm256_fmadd_ps(vlof, vx_odd,  vacc);
#else
        vacc = _mm256_add_ps(_mm256_mul_ps(vhif, vx_even), vacc);
        vacc = _mm256_add_ps(_mm256_mul_ps(vlof, vx_odd),  vacc);
#endif
    }

    /* Horizontal sum of vacc */
    __m128 lo128  = _mm256_castps256_ps128(vacc);
    __m128 hi128  = _mm256_extractf128_ps(vacc, 1);
    __m128 sum128 = _mm_add_ps(lo128, hi128);
    sum128 = _mm_hadd_ps(sum128, sum128);
    sum128 = _mm_hadd_ps(sum128, sum128);
    float acc = _mm_cvtss_f32(sum128);

    /* Scalar tail for remaining packed bytes */
    for (; i < half; i++) {
        uint8_t byte = pr[i];
        acc += xb[2*i]   * ((float)((int)(byte >> 4)   - 8) * scale);
        acc += xb[2*i+1] * ((float)((int)(byte & 0x0F) - 8) * scale);
    }
    if (orig_cols & 1) {
        uint8_t byte = pr[half];
        acc += xb[orig_cols - 1] * ((float)((int)(byte >> 4) - 8) * scale);
    }
    return acc;
}
#endif /* __AVX2__ */

/*
 * Scalar dot product with loop unrolled 8× to help compiler vectorize.
 * The key insight: unrolling exposes sequential x accesses (xb[2i+0..15])
 * so the compiler can use SIMD loads + FMAs.
 */
static inline float _dot_int4_scalar(
    const uint8_t * restrict pr,
    const float   * restrict xb,
    float scale,
    int orig_cols)
{
    int   half = orig_cols >> 1;
    float acc  = 0.0f;
    int   i    = 0;

    /* 8-way unroll: 8 packed bytes → 16 consecutive x elements */
    for (; i + 7 < half; i += 8) {
        uint8_t b0=pr[i],b1=pr[i+1],b2=pr[i+2],b3=pr[i+3];
        uint8_t b4=pr[i+4],b5=pr[i+5],b6=pr[i+6],b7=pr[i+7];
        acc += xb[2*i+ 0] * ((float)((int)(b0>>4)   - 8) * scale)
             + xb[2*i+ 1] * ((float)((int)(b0&0x0F) - 8) * scale)
             + xb[2*i+ 2] * ((float)((int)(b1>>4)   - 8) * scale)
             + xb[2*i+ 3] * ((float)((int)(b1&0x0F) - 8) * scale)
             + xb[2*i+ 4] * ((float)((int)(b2>>4)   - 8) * scale)
             + xb[2*i+ 5] * ((float)((int)(b2&0x0F) - 8) * scale)
             + xb[2*i+ 6] * ((float)((int)(b3>>4)   - 8) * scale)
             + xb[2*i+ 7] * ((float)((int)(b3&0x0F) - 8) * scale)
             + xb[2*i+ 8] * ((float)((int)(b4>>4)   - 8) * scale)
             + xb[2*i+ 9] * ((float)((int)(b4&0x0F) - 8) * scale)
             + xb[2*i+10] * ((float)((int)(b5>>4)   - 8) * scale)
             + xb[2*i+11] * ((float)((int)(b5&0x0F) - 8) * scale)
             + xb[2*i+12] * ((float)((int)(b6>>4)   - 8) * scale)
             + xb[2*i+13] * ((float)((int)(b6&0x0F) - 8) * scale)
             + xb[2*i+14] * ((float)((int)(b7>>4)   - 8) * scale)
             + xb[2*i+15] * ((float)((int)(b7&0x0F) - 8) * scale);
    }
    for (; i < half; i++) {
        uint8_t byte = pr[i];
        acc += xb[2*i]   * ((float)((int)(byte >> 4)   - 8) * scale);
        acc += xb[2*i+1] * ((float)((int)(byte & 0x0F) - 8) * scale);
    }
    if (orig_cols & 1) {
        uint8_t byte = pr[half];
        acc += xb[orig_cols - 1] * ((float)((int)(byte >> 4) - 8) * scale);
    }
    return acc;
}

/*
 * INT4 nibble-packed matmul.
 * out[b, r] = sum_k  x[b, k] * W[r, k]
 * W is stored nibble-packed: packed[r, i] holds W[r, 2i] (high nibble)
 * and W[r, 2i+1] (low nibble), each nibble is offset by 8 (signed range -8..7).
 *
 * packed : (n_rows, n_packed) uint8, row-major
 * scale  : (n_rows,)          float32  — per-row dequant scale
 * x      : (n_batch, orig_cols) float32, row-major
 * out    : (n_batch, n_rows)    float32, row-major — caller allocates
 */
void int4_linear(
    const uint8_t * restrict packed,
    const float   * restrict scale,
    int n_rows, int n_packed, int orig_cols,
    const float   * restrict x,
    int n_batch,
    float         * restrict out)
{
    #pragma omp parallel for schedule(static)
    for (int r = 0; r < n_rows; r++) {
        const uint8_t *pr = packed + (size_t)r * n_packed;
        float s = scale[r];
        for (int b = 0; b < n_batch; b++) {
            const float *xb = x + (size_t)b * orig_cols;
#ifdef __AVX2__
            out[(size_t)b * n_rows + r] = _dot_int4_avx2(pr, xb, s, orig_cols);
#else
            out[(size_t)b * n_rows + r] = _dot_int4_scalar(pr, xb, s, orig_cols);
#endif
        }
    }
}

/*
 * RMSNorm: out[i] = x[i] / sqrt(mean(x^2) + eps) * weight[i]
 * x, out : (n_batch, d) float32, row-major
 * weight : (d,)         float32
 */
void rms_norm(
    const float * restrict x,
    const float * restrict weight,
    int n_batch, int d,
    float eps,
    float * restrict out)
{
    for (int b = 0; b < n_batch; b++) {
        const float *xb = x   + (size_t)b * d;
        float       *ob = out + (size_t)b * d;
        float ss = 0.0f;
        for (int j = 0; j < d; j++) ss += xb[j] * xb[j];
        float inv = 1.0f / sqrtf(ss / (float)d + eps);
        for (int j = 0; j < d; j++) ob[j] = xb[j] * inv * weight[j];
    }
}

/*
 * SiLU activation: out[i] = x[i] * sigmoid(x[i])
 * x, out : (n_batch, d) float32, row-major
 */
void silu_fwd(
    const float * restrict x,
    int n_batch, int d,
    float * restrict out)
{
    int total = n_batch * d;
    for (int i = 0; i < total; i++) {
        float v  = x[i];
        float vc = v < -30.0f ? -30.0f : (v > 30.0f ? 30.0f : v);
        out[i] = v / (1.0f + expf(-vc));
    }
}

/*
 * 21.4 — Fused RMSNorm + INT4 linear.
 * Computes inv_rms once per batch row, then applies norm inline during the
 * INT4 matmul — avoids writing the intermediate normed tensor to RAM.
 *
 * x       : (n_batch, d_in)    float32
 * norm_w  : (d_in,)            float32  — RMSNorm scale weights
 * packed  : (n_rows, n_packed) uint8    — nibble-packed INT4 weights
 * scale   : (n_rows,)          float32  — per-row dequant scale
 * out     : (n_batch, n_rows)  float32  — caller allocates
 */
void rms_norm_linear(
    const float   * restrict x,
    const float   * restrict norm_w,
    const uint8_t * restrict packed,
    const float   * restrict scale,
    int n_batch, int d_in, int n_rows, int n_packed, int orig_cols,
    float eps,
    float         * restrict out)
{
    for (int b = 0; b < n_batch; b++) {
        const float *xb = x + (size_t)b * d_in;
        float ss = 0.0f;
        for (int k = 0; k < d_in; k++) ss += xb[k] * xb[k];
        float inv_rms = 1.0f / sqrtf(ss / (float)d_in + eps);

        #pragma omp parallel for schedule(static)
        for (int r = 0; r < n_rows; r++) {
            const uint8_t *pr = packed + (size_t)r * n_packed;
            float s   = scale[r];
            float acc = 0.0f;
            int   half = orig_cols >> 1;
            int   i    = 0;
            for (; i + 7 < half; i += 8) {
                uint8_t b0=pr[i],b1=pr[i+1],b2=pr[i+2],b3=pr[i+3];
                uint8_t b4=pr[i+4],b5=pr[i+5],b6=pr[i+6],b7=pr[i+7];
                acc += xb[2*i+ 0] * norm_w[2*i+ 0] * inv_rms * ((float)((int)(b0>>4)   - 8) * s)
                     + xb[2*i+ 1] * norm_w[2*i+ 1] * inv_rms * ((float)((int)(b0&0x0F) - 8) * s)
                     + xb[2*i+ 2] * norm_w[2*i+ 2] * inv_rms * ((float)((int)(b1>>4)   - 8) * s)
                     + xb[2*i+ 3] * norm_w[2*i+ 3] * inv_rms * ((float)((int)(b1&0x0F) - 8) * s)
                     + xb[2*i+ 4] * norm_w[2*i+ 4] * inv_rms * ((float)((int)(b2>>4)   - 8) * s)
                     + xb[2*i+ 5] * norm_w[2*i+ 5] * inv_rms * ((float)((int)(b2&0x0F) - 8) * s)
                     + xb[2*i+ 6] * norm_w[2*i+ 6] * inv_rms * ((float)((int)(b3>>4)   - 8) * s)
                     + xb[2*i+ 7] * norm_w[2*i+ 7] * inv_rms * ((float)((int)(b3&0x0F) - 8) * s)
                     + xb[2*i+ 8] * norm_w[2*i+ 8] * inv_rms * ((float)((int)(b4>>4)   - 8) * s)
                     + xb[2*i+ 9] * norm_w[2*i+ 9] * inv_rms * ((float)((int)(b4&0x0F) - 8) * s)
                     + xb[2*i+10] * norm_w[2*i+10] * inv_rms * ((float)((int)(b5>>4)   - 8) * s)
                     + xb[2*i+11] * norm_w[2*i+11] * inv_rms * ((float)((int)(b5&0x0F) - 8) * s)
                     + xb[2*i+12] * norm_w[2*i+12] * inv_rms * ((float)((int)(b6>>4)   - 8) * s)
                     + xb[2*i+13] * norm_w[2*i+13] * inv_rms * ((float)((int)(b6&0x0F) - 8) * s)
                     + xb[2*i+14] * norm_w[2*i+14] * inv_rms * ((float)((int)(b7>>4)   - 8) * s)
                     + xb[2*i+15] * norm_w[2*i+15] * inv_rms * ((float)((int)(b7&0x0F) - 8) * s);
            }
            for (; i < half; i++) {
                uint8_t byte = pr[i];
                acc += xb[2*i]   * norm_w[2*i]   * inv_rms * ((float)((int)(byte>>4)   - 8) * s);
                acc += xb[2*i+1] * norm_w[2*i+1] * inv_rms * ((float)((int)(byte&0x0F) - 8) * s);
            }
            if (orig_cols & 1) {
                uint8_t byte = pr[half];
                float w_hi = ((int)(byte >> 4) - 8) * s;
                acc += xb[orig_cols-1] * norm_w[orig_cols-1] * inv_rms * w_hi;
            }
            out[(size_t)b * n_rows + r] = acc;
        }
    }
}

/*
 * 21.4 — Fused SiLU(gate) * up in-place.
 * gate_inout[i] = gate_inout[i] * sigmoid(gate_inout[i]) * up[i]
 * Avoids the temporary _silu(gate) array in the MLP sublayer.
 * n_total = n_batch * d (total elements).
 */
void silu_mul(
    float       * restrict gate_inout,
    const float * restrict up,
    int n_total)
{
    for (int i = 0; i < n_total; i++) {
        float v  = gate_inout[i];
        float vc = v < -30.0f ? -30.0f : (v > 30.0f ? 30.0f : v);
        gate_inout[i] = v / (1.0f + expf(-vc)) * up[i];
    }
}

/*
 * Fused gate+up INT4 projections with SiLU gate activation.
 * Computes: out[b,r] = silu(dot(gate_row[r], x[b])) * dot(up_row[r], x[b])
 *
 * Single OMP parallel region replaces two separate int4_linear calls + silu_mul.
 * Saves one thread-team launch and avoids two (n_batch, n_rows) temp allocations.
 *
 * gate_packed, gate_scale : gate_proj INT4 weights  (n_rows, n_packed)
 * up_packed,   up_scale   : up_proj   INT4 weights  (n_rows, n_packed)
 * out                     : (n_batch, n_rows) float32, row-major
 */
void int4_gate_up_silu(
    const uint8_t * restrict gate_packed,
    const float   * restrict gate_scale,
    const uint8_t * restrict up_packed,
    const float   * restrict up_scale,
    int n_rows, int n_packed, int orig_cols,
    const float   * restrict x,
    int n_batch,
    float         * restrict out)
{
    #pragma omp parallel for schedule(static)
    for (int r = 0; r < n_rows; r++) {
        const uint8_t *pg = gate_packed + (size_t)r * n_packed;
        const uint8_t *pu = up_packed   + (size_t)r * n_packed;
        float sg = gate_scale[r];
        float su = up_scale[r];
        for (int b = 0; b < n_batch; b++) {
            const float *xb = x + (size_t)b * orig_cols;
#ifdef __AVX2__
            float g = _dot_int4_avx2(pg, xb, sg, orig_cols);
            float u = _dot_int4_avx2(pu, xb, su, orig_cols);
#else
            float g = _dot_int4_scalar(pg, xb, sg, orig_cols);
            float u = _dot_int4_scalar(pu, xb, su, orig_cols);
#endif
            float gc = g < -30.0f ? -30.0f : (g > 30.0f ? 30.0f : g);
            out[(size_t)b * n_rows + r] = g / (1.0f + expf(-gc)) * u;
        }
    }
}
