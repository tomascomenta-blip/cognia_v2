/*
 * node/fast_kernels.c
 * Compiled kernels for INT4 matmul, RMSNorm, SiLU.
 * Build: see node/build_fast_kernels.py
 *
 * WHY: Numba requires Python <=3.12; this gives the same SIMD gains via
 * compiler auto-vectorization + OpenMP, compatible with any Python version.
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
        float s    = scale[r];
        int   half = orig_cols >> 1;
        int   odd  = orig_cols & 1;

        for (int b = 0; b < n_batch; b++) {
            const float *xb = x + (size_t)b * orig_cols;
            float acc = 0.0f;

            /* compiler auto-vectorises this loop with AVX2/NEON under -O3 -march=native */
            for (int i = 0; i < half; i++) {
                uint8_t byte = pr[i];
                float hi = (float)((int)(byte >> 4)   - 8) * s;
                float lo = (float)((int)(byte & 0x0F) - 8) * s;
                acc += xb[2*i] * hi + xb[2*i+1] * lo;
            }
            if (odd) {
                uint8_t byte = pr[half];
                acc += xb[orig_cols - 1] * ((float)((int)(byte >> 4) - 8) * s);
            }
            out[(size_t)b * n_rows + r] = acc;
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
            for (int i = 0; i < half; i++) {
                uint8_t byte = pr[i];
                float w_hi = ((int)(byte >> 4)   - 8) * s;
                float w_lo = ((int)(byte & 0x0F) - 8) * s;
                float x_hi = xb[2*i]   * norm_w[2*i]   * inv_rms;
                float x_lo = xb[2*i+1] * norm_w[2*i+1] * inv_rms;
                acc += x_hi * w_hi + x_lo * w_lo;
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
