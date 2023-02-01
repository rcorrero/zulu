__author__ = "Richard Correro (richard@richardcorrero.com)"


import argparse
import logging
import os
import time

import torch

from datasets import ConvLSTMCDataset
from models import CNNLSTM, SpectrumNet, SqueezeNet
from pred_processors import ConvLSTMCProcessor, Processor
from script_utils import get_args, get_random_string

SCRIPT_PATH = os.path.basename(__file__)

DEFAULT_MODEL_NAME = CNNLSTM.__name__
DEFAULT_PRED_PROCESSOR = ConvLSTMCProcessor.__name__
DEFAULT_EXPERIMENT_DIR = "experiments/"
DEFAULT_DEVICE = "CUDA if available else CPU"
DEFAULT_CHANNEL_AXIS = 1
DEFAULT_EXPERIMENT_DIR: str = "experiments/"

DEFAULT_SEED = 8675309 # (___)-867-5309
torch.manual_seed(DEFAULT_SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed(DEFAULT_SEED)

# REMEMBER to update as new models are added!
MODELS = {
    SqueezeNet.__name__: SqueezeNet,
    SpectrumNet.__name__: SpectrumNet,
    CNNLSTM.__name__: CNNLSTM
}

PRED_PROCESSORS = {
    ConvLSTMCProcessor.__name__: ConvLSTMCProcessor
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_NAME
    )
    parser.add_argument(
        "--pred-processor",
        default=DEFAULT_PRED_PROCESSOR
    )    
    parser.add_argument(
        "--model-filepath",
        required=True
    )    
    parser.add_argument(
        '--device',
        default=DEFAULT_DEVICE
    )
    parser.add_argument(
        "--channel-axis",
        default=DEFAULT_CHANNEL_AXIS,
        type=int
    )
    parser.add_argument(
        "--experiment-dir",
        default=DEFAULT_EXPERIMENT_DIR
    )
    parser.add_argument(
        "--data-dir",
        required=True
    )       
    parser.add_argument(
        "--id"
    )           
    p_args, _ = parser.parse_known_args()
    return p_args


def main():
    args = vars(parse_args())
    if not args["id"]:
        experiment_id = get_random_string()
    else:
        experiment_id = args["id"]
    experiment_super_dir = args["experiment_dir"]
    time_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime())    
    experiment_dir = os.path.join(
        experiment_super_dir, experiment_id, f"{time_str}/"
    ).replace("\\", "/")
    log_dir = os.path.join(experiment_dir, 'logs/').replace("\\", "/")
    # save_dir = os.path.join(
    #     experiment_dir, "model_checkpoints/"
    # ).replace("\\", "/")
    os.makedirs(log_dir, exist_ok=True)
    # os.makedirs(save_dir, exist_ok=True)
    log_filepath = os.path.join(
        log_dir, f"{SCRIPT_PATH}_{time_str}_{experiment_id}.log"
    ).replace('\\', '/')

    device = args["device"]
    if device == DEFAULT_DEVICE:
        device =  torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    elif device in ("CUDA", "Cuda", "cuda"):
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    logging.info(f'Using device {device}')       

    model_name = args["model"]
    model: torch.nn.Module = MODELS[model_name]()    

    model.to(device=device)

    model_filepath: str = args["model_filepath"]
    model.load_state_dict(torch.load(model_filepath, map_location=device))
    model_num_channels = model.args["num_channels"] # A constraint on the Model class
    channel_axis: int = args["channel_axis"]    

    logging.info(f'Model loaded from {model_filepath}')  

    pred_processor_name: str = args["pred_processor"]
    pred_processor: Processor = PRED_PROCESSORS[pred_processor_name]()

    args = get_args(
        script_path=SCRIPT_PATH, log_filepath=log_filepath, 
        **args, **model.args, experiment_id = experiment_id, time = time_str
    )

    data_dir = args["data_dir"]

    # samples = sample_generator(dir_path=data_dir)
    samples = pred_processor.make_samples(dir_path=data_dir)

    sample_idx: int = 0
    for sample in samples:
        sample_idx += 1
        X: torch.tensor = sample["X"]
        X: torch.tensor = X.to(device=device, dtype=torch.float32)
        X_num_channels = X.shape[channel_axis]
        assert X_num_channels == model_num_channels, \
            f"Network has been defined with {model_num_channels}" \
            f"input channels, but loaded images have {X_num_channels}" \
            "channels. Please check that the images are loaded correctly."        
        logging.info(f"Generating predictions for sample {sample_idx}...")
        with torch.no_grad():
            pred = model(X)
        logging.info(f"Saving predictions for sample {sample_idx}...")
        pred_processor.save_results(input=sample, output=pred)
        # save_preds(input=sample, output=pred)    
    logging.info(
        """
                ================
                =              =
                =     Done.    =
                =              =
                ================
        """
    )


if __name__ == "__main__":
    main()