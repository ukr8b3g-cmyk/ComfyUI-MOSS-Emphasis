"""Overflow regressions: finite coefficients are not a finite-result guarantee."""
import sys
import unittest
from unittest.mock import patch as mock_patch

import torch
from test_engine import Container, Patcher, modules, attention_pytorch
from moss_emphasis.engine import patch, apply_values, combine_mask
from moss_emphasis.config import EmphasisError


class NumericBoundsTests(unittest.TestCase):
    def test_moss_amplification_overflow_stops_before_attention(self):
        for dtype in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
            for wrapped in (False, True):
                with self.subTest(dtype=dtype, wrapped=wrapped), mock_patch.dict(sys.modules, modules()):
                    weight = -60000 if dtype == torch.float16 else -torch.finfo(dtype).max * .75
                    reference = torch.ones(1, 2, dtype=dtype)
                    model = patch(Patcher(), [[reference[None], {}]], [weight], 1)
                    q, k, v = [torch.full((1, 2, 2), 2., dtype=dtype) for _ in range(3)]
                    before = v.clone()
                    inputs = [Container(t) for t in (q, k, v)] if wrapped else (q, k, v)
                    def execute(x, t, c, options):
                        return model.objects['diffusion_model.layers.0.comfy_attention'].function(
                            *inputs, 1, transformer_options=options)
                    with self.assertRaisesRegex(EmphasisError, 'INVALID_WEIGHT'):
                        model.wrapper(execute, torch.zeros(1, 128, 1, 1), None,
                                      reference[None], {'cond_or_uncond': [0]})
                    self.assertTrue(torch.equal(v, before))

    def test_safe_amplification_preserves_exact_values_and_unselected_rows(self):
        for dtype in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
            v = torch.arange(30, dtype=dtype).reshape(2, 5, 3) / 8
            before = v.clone()
            factors = v.new_tensor([-5., .5])
            expected = v.clone()
            expected[1, 3:] *= factors[:, None]
            self.assertTrue(torch.equal(apply_values(v, [1], 3, factors), expected))
            self.assertTrue(torch.equal(v, before))

    def test_nonamplifying_model_path_adds_no_finite_readback(self):
        with mock_patch.dict(sys.modules, modules()):
            reference = torch.ones(2, 4)
            model = patch(Patcher(), [[reference[None], {}]], [-1, .5], 1)
            q, k, v = [torch.randn(1, 3, 4) for _ in range(3)]
            expected_v = v.clone(); expected_v[:, 1] *= -1; expected_v[:, 2] *= .5
            expected = attention_pytorch(q, k, expected_v, 1)
            def execute(x, t, c, options):
                with mock_patch('torch.isfinite', side_effect=AssertionError('unexpected readback')):
                    return model.objects['diffusion_model.layers.0.comfy_attention'].function(
                        q, k, v, 1, transformer_options=options)
            actual = model.wrapper(execute, torch.zeros(1, 128, 1, 1), None,
                                   reference[None], {'cond_or_uncond': [0]})
            self.assertTrue(torch.equal(actual, expected))

    def test_mask_sum_and_dtype_conversion_overflow_rejected(self):
        for dtype in (torch.float16, torch.bfloat16, torch.float32, torch.float64):
            for sign in (-1, 1):
                value = sign * (40000 if dtype == torch.float16 else torch.finfo(dtype).max * .75)
                mask = torch.tensor([[value]], dtype=dtype)
                bias = torch.tensor([[[[value]]]], dtype=dtype)
                with self.subTest(dtype=dtype, sign=sign), self.assertRaisesRegex(EmphasisError, 'INVALID_WEIGHT'):
                    combine_mask(mask, bias)
        for value in (-100000., 100000.):
            with self.assertRaisesRegex(EmphasisError, 'INVALID_WEIGHT'):
                combine_mask(torch.tensor([[value]]), torch.zeros(1, 1, 1, 1, dtype=torch.float16))

    def test_mask_blocking_infinity_and_finite_sum_preserved(self):
        for mask in (torch.tensor([[True, False]]), torch.tensor([[0., -torch.inf]])):
            bias = torch.tensor([[[[2., 2.]]]])
            before = mask.clone()
            result = combine_mask(mask, bias)
            self.assertEqual(result[0, 0, 0, 0], 2)
            self.assertTrue(torch.isneginf(result[0, 0, 0, 1]))
            self.assertTrue(torch.equal(mask, before))
        bias = torch.ones(1, 1, 1, 2)
        self.assertIs(combine_mask(None, bias), bias)


if __name__ == '__main__':
    unittest.main()
