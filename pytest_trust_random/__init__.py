
from typing import Optional, Type
import pytest
from pydantic import BaseModel
from pathlib import Path
from .definitions.auto_benchmarker import AutoBenchmarker, BaseOutputData, BaseTestModel
from .definitions.pytest_config import PytestConfig

class ExampleSubmodel(BaseModel):
    pop: int

class ExampleModel(BaseModel):
    tests: list[ExampleSubmodel]

class JSONItem(pytest.Item):
    def __init__(self, *, func_name: str, data: BaseOutputData, benchmarker: AutoBenchmarker, acceptable_st_devs: int, **kwargs):
        super().__init__(**kwargs)
        self.benchmarker = benchmarker
        self.data = data
        self.func_name = func_name
        self.acceptable_st_devs = acceptable_st_devs

    def runtest(self):
        self.benchmarker.test_benchmark_data(
            benchmark_data=self.data,
            acceptable_st_devs=self.acceptable_st_devs,
            func_name=self.func_name,
        )


class JSONFile(pytest.File):
    model: Type[BaseTestModel]
    def __init__(self, *, model: Type[BaseTestModel], benchmarker: AutoBenchmarker, acceptable_st_devs: int, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.benchmarker = benchmarker
        self.acceptable_st_devs = acceptable_st_devs

    def collect(self):
        test_model = self.model.parse_file(self.path)
        final_tests = []
        for func_name, test in test_model.tests:
            final_tests += [JSONItem.from_parent(self, name=f"{func_name}{i}", func_name = func_name, data = data, benchmarker = self.benchmarker, acceptable_st_devs = self.acceptable_st_devs) for i, data in enumerate(test)]
        return final_tests
 
def get_benchmarker_from_definition(file_path) -> AutoBenchmarker:
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("autobenchmarker", file_path)
    assert spec is not None
    autobench = importlib.util.module_from_spec(spec)
    sys.modules["autobenchmarker"] = autobench
    assert spec.loader is not None
    spec.loader.exec_module(autobench)
    if not isinstance(autobench.trust_random, AutoBenchmarker):
        raise ValueError('Benchmarker of incorrect type')
    return autobench.trust_random

def get_benchmarker_from_startpath(start_path) -> Optional[AutoBenchmarker]:
    # Generate benchmark from definition and settings
    definition_path = Path(str(start_path) + '/' + 'benchmark_definition.py')
    if not definition_path.exists():
        return None
    auto_benchmarker = get_benchmarker_from_definition(definition_path)
    return auto_benchmarker

def get_pytest_config_from_startpath(start_path) -> Optional[PytestConfig]:
    config_path = Path(str(start_path) + '/' + 'pytest_config.json')
    if config_path.exists():
        return PytestConfig.parse_file(config_path)
    else:
        return None

def pytest_sessionstart(session: pytest.Session):
    pytest_config = get_pytest_config_from_startpath(session.startpath)
    auto_benchmarker = get_benchmarker_from_startpath(session.startpath)
    if not auto_benchmarker or not pytest_config:
        raise ValueError('benchmark or pytest_config not found')
    benchmark_path = Path(str(session.startpath) + '/' + pytest_config.benchmark_path)

    # get addoption from collector and generate if specified
    if not benchmark_path.exists():
        auto_benchmarker.generate_benchmark()
    else:
        benchmark_sub_path = Path(str(benchmark_path) + '/' + 'benchmark.json')
        if not benchmark_sub_path.exists():
            auto_benchmarker.generate_benchmark()




def pytest_collect_file(parent: pytest.Session, file_path: Path):
    if file_path.name == "benchmark.json":
        auto_benchmarker = get_benchmarker_from_startpath(parent.startpath)
        pytest_config = get_pytest_config_from_startpath(parent.startpath)
        assert auto_benchmarker is not None
        assert pytest_config is not None
        return JSONFile.from_parent(parent, path=file_path, model = auto_benchmarker.test_model, benchmarker = auto_benchmarker, acceptable_st_devs = pytest_config.acceptable_st_devs)


def pytest_addoption(parser):
    parser.addoption(
        "--generatebenchmark",
        dest="genbenchmark",
        action="store_true",
        help="my option: type1 or type2",
    )
