from collections import defaultdict
from typing import Any, Generic, TypeVar

import numpy as np
from joblib import Parallel, delayed
from numpy.typing import NDArray
from pydantic import BaseModel

from .base_models import (
    BaseOutputData,
    BaseSettingsModel,
    BaseTestDimension,
    BenchmarkArray,
)
from .setup_func_benchmarker import SetupFuncBenchmarker
from .utils import FlatDict, flatten_dict


def get_test_pairs(
    settings: BaseSettingsModel, parameters: dict[str, type]
) -> tuple[list[tuple], float]:
    def get_exponentially_spaced_steps(
        start: int | float, end: int | float, n_steps: int
    ) -> NDArray[np.float_]:
        # TODO: do something else if start == 0. For example 0..1 could be scalled linearly?
        assert 0 < start < end
        return np.geomspace(start, end, n_steps)

    arrays: list[NDArray[np.int_] | NDArray[np.float_]] = []
    for k, t in parameters.items():
        setting_item: BaseTestDimension = getattr(settings, k)
        spaces: NDArray[np.float_] | NDArray[np.int_] = get_exponentially_spaced_steps(
            setting_item.minimum, setting_item.maximum, setting_item.steps
        )
        if issubclass(t, int):
            spaces = np.round(spaces).astype(int)
        arrays.append(spaces)
    new_arrays = []
    no_arrays = len(arrays)
    for i, array in enumerate(arrays):
        ones = [1] * no_arrays
        ones[i] = len(array)
        new_arrays.append(np.reshape(array, tuple(ones)))

    # TODO: we should probably remove this constraint. It would be good to be
    # able to test functions without any parameters.
    assert len(new_arrays) != 0
    if len(new_arrays) == 1:
        combined_array = new_arrays[0]
    else:
        combined_array = np.multiply(*new_arrays)
    valid_tests = combined_array <= settings.max_product
    coords = valid_tests.nonzero()
    items_for_test = []
    for i, spaces in enumerate(arrays):
        item_for_test = spaces[coords[i]]
        items_for_test.append(item_for_test)
    total_product = np.sum(combined_array[valid_tests])

    return list(zip(*items_for_test)), total_product


SettingsModel = TypeVar("SettingsModel", bound=BaseSettingsModel)
FuncReturn = TypeVar("FuncReturn", bound=BaseModel)


class FuncBenchmarker(Generic[SettingsModel, FuncReturn]):
    def __init__(
        self, settings: SettingsModel, func_setup: SetupFuncBenchmarker
    ) -> None:
        self.settings = settings
        self.func_setup = func_setup
        self.test_pairs, self.total_product = get_test_pairs(
            settings, func_setup.parameters
        )

    def __len__(self) -> int:
        return len(self.test_pairs)

    def estimate_computation_time(self) -> tuple[float, float]:
        est_test_time = self.func_setup.est_base_time * self.total_product
        est_benchmark_time = est_test_time * self.settings.benchmark_iters
        return est_test_time, est_benchmark_time

    def _compute_mean_and_st_dev_of_pydantic(
        self,
        input_stats: list[FuncReturn],
    ) -> dict[str, BenchmarkArray]:
        flat_dicts: list[FlatDict] = [
            flatten_dict(input_stat.dict()) for input_stat in input_stats
        ]
        dict_of_arrays: dict[str, list[Any]] = defaultdict(list)
        for flat_dict in flat_dicts:
            for k, v in flat_dict.items():
                dict_of_arrays[k].append(v)
        final_dict_of_arrays: dict[str, NDArray[np.float_]] = {
            k: np.array(v) for k, v in dict_of_arrays.items()
        }
        return {
            k: BenchmarkArray.from_array(v) for k, v in final_dict_of_arrays.items()
        }

    def generate_benchmark(self) -> list[BaseOutputData]:
        OutputModel = self.func_setup.output_model

        tests: list[BaseOutputData] = []
        headers = [k for k in self.func_setup.parameters.keys()]
        for items in self.test_pairs:
            list_of_stats: list[FuncReturn] = Parallel(
                n_jobs=-1, backend="multiprocessing"
            )(
                delayed(self.func_setup.func)(*items)
                for _ in range(self.settings.benchmark_iters)
            )

            data = self._compute_mean_and_st_dev_of_pydantic(list_of_stats)
            values = {header: items[i] for i, header in enumerate(headers)}

            test_output = OutputModel(data=data, **values)
            tests.append(test_output)
        return tests

    def test_benchmark_data(
        self, benchmark_data: BaseOutputData, acceptable_st_devs: float
    ) -> None:
        func_args = {
            dimension: getattr(benchmark_data, dimension)
            for dimension in self.func_setup.parameters.keys()
        }
        func_return = self.func_setup.func(**func_args)
        func_return_dict = flatten_dict(func_return.dict())
        for k, v in func_return_dict.items():
            if k not in benchmark_data.data:
                raise RuntimeError(f"Key {k} not present in benchmark")
            else:
                benchmark_item = benchmark_data.data[k]
            benchmark_item_mean = benchmark_item.mean
            benchmark_item_st_dev = benchmark_item.st_dev
            benchmark_lower_bound = (
                benchmark_item_mean - acceptable_st_devs * benchmark_item_st_dev
            )
            benchmark_upper_bound = (
                benchmark_item_mean + acceptable_st_devs * benchmark_item_st_dev
            )
            if v < benchmark_lower_bound:
                raise ValueError(
                    f"For key: {k} lower bound: {benchmark_lower_bound} surpassed by value {v}"
                )
            if v > benchmark_upper_bound:
                raise ValueError(
                    f"For key: {k} upper bound: {benchmark_upper_bound} surpassed by value {v}"
                )
