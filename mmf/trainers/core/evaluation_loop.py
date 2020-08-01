# Copyright (c) Facebook, Inc. and its affiliates.

import logging
from abc import ABC
from typing import Any, Dict, Tuple, Type

import torch
import tqdm

from mmf.common.meter import Meter
from mmf.common.report import Report
from mmf.utils.distributed import is_master

logger = logging.getLogger(__name__)


class TrainerEvaluationLoopMixin(ABC):
    def evaluation_loop(
        self, dataset_type: str, use_tqdm: bool = False, single_batch: bool = False
    ) -> Tuple[Dict[str, Any], Type[Meter]]:
        meter = Meter()
        reporter = self.dataset_loader.get_test_reporter(dataset_type)

        with torch.no_grad():
            self.model.eval()
            disable_tqdm = not use_tqdm or not is_master()

            while reporter.next_dataset(flush_report=False):
                dataloader = reporter.get_dataloader()

                combined_report = None
                for batch in tqdm.tqdm(dataloader, disable=disable_tqdm):
                    prepared_batch = reporter.prepare_batch(batch)
                    model_output = self.model(prepared_batch)
                    report = Report(prepared_batch, model_output)
                    report = reporter.gather_metric_tensors(
                        report, self.metrics.required_params
                    )

                    self.update_meter(report, meter)

                    # accumulate necessary params for metric calculation
                    if combined_report is None:
                        combined_report = report
                    else:
                        combined_report.accumulate_tensor_fields(
                            report, self.metrics.required_params
                        )
                        combined_report.batch_size += report.batch_size

                    if single_batch is True:
                        break

                combined_report.metrics = self.metrics(combined_report, combined_report)
                self.update_meter(combined_report, meter, eval_mode=True)

            # enable train mode again
            self.model.train()

        return combined_report, meter

    def prediction_loop(self, dataset_type: str) -> None:
        reporter = self.dataset_loader.get_test_reporter(dataset_type)
        with torch.no_grad():
            self.model.eval()
            logger.info(f"Starting {dataset_type} inference predictions")

            while reporter.next_dataset():
                dataloader = reporter.get_dataloader()

                for batch in tqdm.tqdm(dataloader):
                    prepared_batch = reporter.prepare_batch(batch)
                    model_output = self.model(prepared_batch)
                    report = Report(prepared_batch, model_output)
                    reporter.add_to_report(report, self.model)

            logger.info("Finished predicting")
            self.model.train()
