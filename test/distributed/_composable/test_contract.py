# Owner(s): ["oncall: distributed"]

from torch.testing._internal.common_utils import (
    TestCase,
    run_tests,
    skipIfTorchDynamo,
)

import torch
import torch.nn as nn
from torch.distributed._composable import contract

from copy import deepcopy
from typing import Tuple


class ToyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.seq1 = nn.Sequential(*[nn.Linear(10, 10) for _ in range(2)])
        self.seq2 = nn.Sequential(*[nn.Linear(10, 10) for _ in range(2)])
        self.p = nn.Parameter(torch.randn(10, 10), requires_grad=True)
        self.b = torch.zeros(1)  # buffer

    def forward(self, x, y):
        with torch.no_grad():
            self.b += x.sum() + y.sum()

        return self.p + self.seq1(x) + self.seq2(y)


class TestContract(TestCase):
    @skipIfTorchDynamo("Dynamo does not yet capture module hooks")
    def test_add_hooks(self):
        def forward_pre_hook(
            module: nn.Module, inp: Tuple[torch.Tensor]
        ) -> Tuple[torch.Tensor]:
            return inp

        def forward_hook(
            module: nn.Module, inp: Tuple[torch.Tensor], out: torch.Tensor
        ) -> torch.Tensor:
            return out

        def backward_pre_hook(
            module: nn.Module, grad_output: torch.Tensor
        ) -> torch.Tensor:
            return grad_output

        def backward_hook(
            module: nn.Module,
            grad_input: Tuple[torch.Tensor],
            grad_output: torch.Tensor,
        ) -> Tuple[torch.Tensor]:
            return grad_input

        @contract
        def noop_api(module: nn.Module) -> nn.Module:
            module.register_forward_pre_hook(forward_pre_hook)
            module.register_forward_hook(forward_hook)
            module.register_full_backward_pre_hook(backward_pre_hook)
            module.register_full_backward_hook(backward_hook)
            return module

        model = ToyModel()
        model_with_hooks = deepcopy(model)
        noop_api(model.seq1)
        noop_api(model.seq2)

        x, y = torch.randn(10, 10), torch.randn(10, 10)
        model(x, y).sum().backward()
        model_with_hooks(x, y).sum().backward()

        for p1, p2 in zip(model.parameters(), model_with_hooks.parameters()):
            self.assertEqual(p1, p2)

    @skipIfTorchDynamo("Dynamo does not yet capture module hooks")
    def test_modify_fqn(self):
        class ModelWrapper(nn.Module):
            def __init__(self, module):
                super().__init__()
                self.module = module

            def forward(self, x):
                return self.module(x)

        @contract
        def wrap_module(module: nn.Module) -> nn.Module:
            return ModelWrapper(module)

        model = ToyModel()

        with self.assertRaisesRegex(RuntimeError, "cannot modify FQNs"):
            wrap_module(model.seq1)


if __name__ == "__main__":
    run_tests()
