# Copyright 2021 The Forte Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Unit tests for remote processor.
"""

import os
import sys
import json
import unittest
from ddt import ddt, data

from typing import Any, Dict, Iterator, Optional, Type, Set, List
from forte.common import ProcessorConfigError
from forte.data.data_pack import DataPack
from forte.pipeline import Pipeline, serve
from forte.processors.base import PackProcessor
from forte.processors.nlp import ElizaProcessor
from forte.processors.misc import RemoteProcessor
from forte.data.readers import RawDataDeserializeReader, StringReader
from forte.data.common_entry_utils import create_utterance, get_last_utterance
from ft.onto.base_ontology import Utterance


TEST_RECORDS_1 = {
    "Token": {"1", "2"},
    "Document": {"2"},
}
TEST_RECORDS_2 = {
    "ft.onto.example_import_ontology.Token": {"pos", "lemma"},
    "Sentence": {"1", "2", "3"},
}


class UserSimulator(PackProcessor):
    """
    A simulated processor that will generate utterance based on the config.
    """

    def _process(self, input_pack: DataPack):
        create_utterance(input_pack, self.configs.user_input, "user")

    @classmethod
    def default_configs(cls):
        config = super().default_configs()
        config["user_input"] = ""
        return config


class DummyProcessor(PackProcessor):
    """
    A dummpy Processor to check the expected/output records from the remote
    pipeline.
    """

    def __init__(
        self,
        expected_records: Dict[str, Set[str]] = {},
        output_records: Dict[str, Set[str]] = {},
    ):
        self._expected_records: Dict[str, Set[str]] = expected_records
        self._output_records: Dict[str, Set[str]] = output_records

    def _process(self, input_pack: DataPack):
        pass

    def expected_types_and_attributes(self):
        return self._expected_records

    def record(self, record_meta: Dict[str, Set[str]]):
        record_meta.update(self._output_records)


@ddt
class TestRemoteProcessor(unittest.TestCase):
    """
    Test RemoteProcessor. Here we use eliza pipeline as an example,
    and all the testcases below are refactored from `./eliza_test.py`.
    """

    @data(
        [
            "I would like to have a chat bot.",
            "You say you would like to have a chat bot ?",
        ],
        ["bye", "Goodbye.  Thank you for talking to me."],
    )
    def test_ir(self, input_output_pair):
        """
        Verify the intermediate representation of pipeline.
        """
        i_str, o_str = input_output_pair
        pl_config_path: str = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "eliza_pl_ir.yaml"
        )

        # Build eliza pipeline
        eliza_pl: Pipeline[DataPack] = Pipeline[DataPack]()
        eliza_pl.set_reader(StringReader())
        eliza_pl.add(UserSimulator(), config={"user_input": i_str})
        eliza_pl.add(ElizaProcessor())
        eliza_pl.save(pl_config_path)

        # Build test pipeline
        test_pl: Pipeline[DataPack] = Pipeline[DataPack]()
        test_pl.init_from_config_path(pl_config_path)
        test_pl.initialize()

        # Verify output
        res: DataPack = test_pl.process("")
        utterance = get_last_utterance(res, "ai")
        self.assertEqual(len([_ for _ in res.get(Utterance)]), 2)
        self.assertEqual(utterance.text, o_str)

    @data(
        [
            "I would like to have a chat bot.",
            "You say you would like to have a chat bot ?",
        ],
        ["bye", "Goodbye.  Thank you for talking to me."],
    )
    def test_remote_processor(self, input_output_pair):
        """
        Verify RemoteProcessor.
        """
        i_str, o_str = input_output_pair
        service_name: str = "test_service_name"
        input_format: str = "DataPack"

        # Build service pipeline
        serve_pl: Pipeline[DataPack] = Pipeline[DataPack]()
        serve_pl.set_reader(RawDataDeserializeReader())
        serve_pl.add(DummyProcessor(expected_records=TEST_RECORDS_1))
        serve_pl.add(UserSimulator(), config={"user_input": i_str})
        serve_pl.add(DummyProcessor(output_records=TEST_RECORDS_2))
        serve_pl.add(ElizaProcessor())
        serve_pl.initialize()

        # Configure RemoteProcessor into test mode
        remote_processor: RemoteProcessor = RemoteProcessor()
        remote_processor.set_test_mode(
            serve_pl._remote_service_app(
                service_name=service_name, input_format=input_format
            )
        )

        # Build test pipeline
        test_pl: Pipeline[DataPack] = Pipeline[DataPack](
            do_init_type_check=True
        )
        test_pl.set_reader(StringReader())
        test_pl.add(DummyProcessor(output_records=TEST_RECORDS_1))
        test_pl.add(
            remote_processor,
            config={
                "validation": {
                    "do_init_type_check": True,
                    "input_format": input_format,
                    "expected_name": service_name,
                }
            },
        )
        test_pl.add(DummyProcessor(expected_records=TEST_RECORDS_2))
        test_pl.initialize()

        # Verify output
        res: DataPack = test_pl.process("")
        utterance = get_last_utterance(res, "ai")
        self.assertEqual(len([_ for _ in res.get(Utterance)]), 2)
        self.assertEqual(utterance.text, o_str)


if __name__ == "__main__":
    unittest.main()
