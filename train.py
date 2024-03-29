__author__ = "Richard Correro (richard@richardcorrero.com)"


import argparse
import logging
import os
import random
import time

import numpy as np
import torch

from datasets import (ConvLSTMCDataset, EurosatDataset,
                      XYZObjectDetectionDataset, XYZObjectDetectionDatasetTwo,
                      XYZTileDataset)
from detection import collate_fn, evaluate, train_one_epoch
from metrics import calc_metrics
from models import (FasterRCNN, ResNet, ResNetConvLSTM, ResNetOneDConv,
                    SpectrumNet, SqueezeNet)
from optimizers import SGD, Adam
from schedulers import ReduceLROnPlateau, StepLR
from script_utils import arg_is_false, arg_is_true, get_args, get_random_string

SCRIPT_PATH = os.path.basename(__file__)

DEFAULT_BATCH_SIZE = 64
DEFAULT_NUM_EPOCHS = 64
DEFAULT_OPTIMIZER = SGD.__name__
DEFAULT_SCHEDULER = StepLR.__name__
DEFAULT_SCHEDULER_METRIC = "validation_loss"
DEFAULT_F_BETA = 1
DEFAULT_MODEL_NAME = SqueezeNet.__name__
DEFAULT_DATASET_NAME = EurosatDataset.__name__
DEFAULT_VALIDATION_PERCENT = 0.15
DEFAULT_SHUFFLE = True
DEFAULT_CRITERION_NAME = "CrossEntropyLoss"
DEFAULT_USE_CLASS_WEIGHTS = False
DEFAULT_EXPERIMENT_DIR = "experiments/"
DEFAULT_NUM_WORKERS = os.cpu_count()
DEFAULT_PIN_MEMORY = True
DEFAULT_DEVICE = "CUDA if available else CPU"
DEFAULT_MIXED_PRECISION = True
DEFAULT_SAVE_MODEL = True
DEFAULT_SAVE_EVERY = 8
DEFAULT_CHANNEL_AXIS = 1
DEFAULT_EXPERIMENT_DIR: str = "experiments/"
DEFAULT_MODEL_FILEPATH = None
DEFAULT_SAVE_LOSSES = True
DEFAULT_VALIDATION = True
DEFAULT_PRINT_VAL_PREDS = False
DEFAULT_PRINT_METRICS = True
DEFAULT_THRESH_LIST = np.arange(0.5, 0.95, 0.05).round(8) # COCO AP@[.5:.95]

DEFAULT_SEED = 8675309 # (___)-867-5309

# REMEMBER to update as new models are added!
MODELS = {
    ResNet.__name__: ResNet,
    SqueezeNet.__name__: SqueezeNet,
    SpectrumNet.__name__: SpectrumNet,
    ResNetConvLSTM.__name__: ResNetConvLSTM,
    ResNetOneDConv.__name__: ResNetOneDConv,
    FasterRCNN.__name__: FasterRCNN
}

DATASETS = {
    EurosatDataset.__name__: EurosatDataset,
    ConvLSTMCDataset.__name__: ConvLSTMCDataset,
    XYZTileDataset.__name__: XYZTileDataset,
    XYZObjectDetectionDataset.__name__: XYZObjectDetectionDataset,
    XYZObjectDetectionDatasetTwo.__name__: XYZObjectDetectionDatasetTwo
}

CRITERIA = {
    "CrossEntropyLoss": torch.nn.CrossEntropyLoss
}

OPTIMIZERS = {
    SGD.__name__: SGD,
    Adam.__name__: Adam

}
SCHEDULERS = {
    StepLR.__name__: StepLR,
    ReduceLROnPlateau.__name__: ReduceLROnPlateau
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        default=DEFAULT_SEED,
        type=int
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_NAME
    )
    parser.add_argument(
        "--model-filepath",
        default=DEFAULT_MODEL_FILEPATH
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET_NAME
    )
    parser.add_argument(
        "--val-percent",
        default=DEFAULT_VALIDATION_PERCENT,
        type=float
    )    
    parser.add_argument(
        "--shuffle",
        default=DEFAULT_SHUFFLE,
    )
    parser.add_argument(
        "--criterion",
        default=DEFAULT_CRITERION_NAME,
    )
    parser.add_argument(
        "--use-class-weights",
        default=DEFAULT_USE_CLASS_WEIGHTS
    )
    parser.add_argument(
        "--batch-size",
        default=DEFAULT_BATCH_SIZE,
        type=int
    )  
    parser.add_argument(
        "--num-epochs",
        default=DEFAULT_NUM_EPOCHS,
        type=int
    )
    parser.add_argument(
        "--optimizer",
        default=DEFAULT_OPTIMIZER,
    )
    parser.add_argument(
        "--scheduler",
        default=DEFAULT_SCHEDULER
    )
    parser.add_argument(
        "--scheduler-metric",
        default=DEFAULT_SCHEDULER_METRIC
    )
    parser.add_argument(
        "--F-beta",
        default=DEFAULT_F_BETA,
        type=float
    )
    parser.add_argument(
        "--num-workers",
        default=DEFAULT_NUM_WORKERS,
        type=int
    )  
    parser.add_argument(
        "--pin-memory",
        default=DEFAULT_PIN_MEMORY
    )       
    parser.add_argument(
        '--device',
        default=DEFAULT_DEVICE
    )
    parser.add_argument(
        "--mixed-precision",
        default=DEFAULT_MIXED_PRECISION
    )
    parser.add_argument(
        "--save-model",
        default=DEFAULT_SAVE_MODEL
    )
    parser.add_argument(
        "--save-every",
        default=DEFAULT_SAVE_EVERY,
        type=int
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
        "--id"
    )
    parser.add_argument(
        "--save-losses",
        default=DEFAULT_SAVE_LOSSES
    )
    parser.add_argument(
        "--validation",
        default=DEFAULT_VALIDATION
    )
    parser.add_argument(
        "--print-val-preds",
        default=DEFAULT_PRINT_VAL_PREDS
    )
    parser.add_argument(
        "--print-metrics",
        default=DEFAULT_PRINT_METRICS
    ) 
    p_args, _ = parser.parse_known_args()
    return p_args    


def main():
    args = vars(parse_args())

    seed = args["seed"]
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
    random.seed(seed)

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
    save_dir = os.path.join(
        experiment_dir, "model_checkpoints/"
    ).replace("\\", "/")
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(save_dir, exist_ok=True)
    # time_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    log_filepath = os.path.join(
        log_dir, f"{SCRIPT_PATH}_{time_str}_{experiment_id}.log"
    ).replace('\\', '/')

    save_losses: bool = arg_is_true(args["save_losses"])
    if save_losses:
        train_loss_path: str = os.path.join(
            log_dir, f"{SCRIPT_PATH}_{time_str}_{experiment_id}_train_loss.txt"
        ).replace('\\', '/')
        validation_loss_path: str = os.path.join(
            log_dir, f"{SCRIPT_PATH}_{time_str}_{experiment_id}_validation_loss.txt"
        ).replace('\\', '/')   

    device = args["device"]
    if device == DEFAULT_DEVICE:
        device =  torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    elif device in ("CUDA", "Cuda", "cuda"):
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    # logging.info(f'Using device {device}')       

    model_name = args["model"]
    model: torch.nn.Module = MODELS[model_name]()   

    model_filepath = args["model_filepath"]   

    model = model.to(device=device)  
    model_num_channels = model.args["num_channels"] # A constraint on the Model class        

    num_epochs = args["num_epochs"]
    batch_size = args["batch_size"] 

    dataset_name = args["dataset"]
    dataset = DATASETS[dataset_name]()

    validation = arg_is_true(args["validation"])
    print_val_preds: bool = arg_is_true(args["print_val_preds"])
    print_metrics: bool = arg_is_true(args["print_metrics"])

    if validation:
        val_percent = args["val_percent"]
        num_validation = int(len(dataset) * val_percent)
        num_train = len(dataset) - num_validation
        train_set, validation_set = torch.utils.data.random_split(
                dataset, [num_train, num_validation], 
                generator=torch.Generator().manual_seed(seed)
        )
    else:
        train_set = dataset
        num_train: int = len(dataset)
        num_validation: int = 0

    shuffle = arg_is_true(args["shuffle"])
    num_workers = args["num_workers"]
    pin_memory = arg_is_true(args["pin_memory"])
    if model.IS_OBJECT_DETECTOR:
        train_loader = torch.utils.data.DataLoader(
            train_set, shuffle=shuffle, batch_size=batch_size, 
            num_workers=num_workers, pin_memory=pin_memory,
            collate_fn=collate_fn
        )
    else:
        train_loader = torch.utils.data.DataLoader(
            train_set, shuffle=shuffle, batch_size=batch_size, 
            num_workers=num_workers, pin_memory=pin_memory,
        )        
    if validation:
        if model.IS_OBJECT_DETECTOR:
            validation_loader = torch.utils.data.DataLoader(
                validation_set, shuffle=False, batch_size=batch_size, 
                num_workers=num_workers, pin_memory=pin_memory,
                collate_fn=collate_fn
            )                
        else:
            validation_loader = torch.utils.data.DataLoader(
                validation_set, shuffle=False, batch_size=batch_size, 
                num_workers=num_workers, pin_memory=pin_memory
            )    

    optimizer_name = args["optimizer"]
    Optimizer = OPTIMIZERS[optimizer_name]      
    optimizer = Optimizer(model.parameters())

    scheduler_name = args["scheduler"]
    use_scheduler: bool = not arg_is_false(scheduler_name)
    if use_scheduler:
        Scheduler = SCHEDULERS[scheduler_name]
        scheduler = Scheduler(optimizer=optimizer)
        scheduler_args: dict = scheduler.args
    else:
        scheduler_args = dict()
    scheduler_metric: str = args["scheduler_metric"]
    F_beta: float = args["F_beta"]

    # Note: You CANNOT place a `logging.info(...)` command before calling `get_args(...)`
    args = get_args(
        script_path=SCRIPT_PATH, log_filepath=log_filepath, 
        **args, **model.args, **dataset.args, **optimizer.args, **scheduler_args,
        experiment_id=experiment_id, time=time_str
    )

    logging.info(f'Using device {device}') 

    if model_filepath:
        model.load_state_dict(torch.load(model_filepath, map_location=device))
        logging.info(f'Model loaded from {model_filepath}')  

    logging.info(
        f"""
                Number of training samples:   {num_train}
                Number of validation samples: {num_validation}
        """
    )                    

    use_mp = arg_is_true(args["mixed_precision"])

    use_class_weights = arg_is_true(args["use_class_weights"])
    if use_class_weights:
        weight = dataset.class_weights
        weight: torch.Tensor = torch.tensor(weight, dtype=torch.float)

        logging.info(f"Class weights: {weight}")
    else: weight = None


    criterion_name = args["criterion"]
    criterion = CRITERIA[criterion_name](weight=weight).to(device=device)

    save_model = arg_is_true(args["save_model"])
    save_every = args["save_every"]

    channel_axis = args["channel_axis"]

    ### Train Loop Begins ###
    logging.info("Starting training...")
    for epoch in range(1, num_epochs + 1):
        logging.info(f"Starting epoch {epoch}...")
        if model.IS_OBJECT_DETECTOR:
            train_loss = train_one_epoch(
                model=model, optimizer=optimizer, data_loader=train_loader, 
                device=device, lr_scheduler=None
            )
            train_loss = float(train_loss)   
        else:
            model.train()
            train_loss = 0.0            
            for batch in train_loader:
                X, Y = batch["X"], batch["Y"] # A constraint on the Dataset class
                X_num_channels = X.shape[channel_axis]
                assert X_num_channels == model_num_channels, \
                    f"Network has been defined with {model_num_channels}" \
                    f"input channels, but loaded images have {X_num_channels}" \
                    "channels. Please check that the images are loaded correctly."
                
                # logging.info(f"X size: {X.shape}")
                # logging.info(f"Y size: {Y.shape}")
                X = X.to(device=device, dtype=torch.float32) # A constraint on the Dataset class
                Y = Y.to(device=device, dtype=torch.long) # A constraint on the Dataset class
                optimizer.zero_grad()
                with torch.autocast(
                    device.type if device.type != "mps" else "cpu", enabled=use_mp 
                ):
                    Y_hat = model(X)
                    loss = criterion(Y_hat, Y)
                train_loss += loss.item()
                loss.backward()
                optimizer.step()

        logging.info(
            f"""
                    Epoch {epoch} training completed.
                    Train loss: {train_loss:.5f}.\
        
                    Starting validation...
            """
        )
        validation_loss = 0.0
        if validation:
            if model.IS_OBJECT_DETECTOR:
                mAP = evaluate(
                    model=model, data_loader=validation_loader, device=device, 
                    thresh_list=DEFAULT_THRESH_LIST
                )
                metrics = {"mAP": float(mAP)}
                if print_metrics:
                    for key, value in metrics.items():
                        logging.info(f"{key}: {value}")                
            else:
                model.eval()
                for batch in validation_loader:
                    X, Y = batch["X"], batch["Y"] # A constraint on the Dataset class
                    X_num_channels = X.shape[channel_axis]
                    assert X_num_channels == model_num_channels, \
                        f"Network has been defined with {model_num_channels} " \
                        f"input channels, but loaded images have {X_num_channels} " \
                        "channels. Please check that the images are loaded correctly."
                    
                    X = X.to(device=device, dtype=torch.float32) # A constraint on the Dataset class
                    Y = Y.to(device=device, dtype=torch.long) # A constraint on the Dataset class
                    with torch.autocast(
                        device.type if device.type != "mps" else "cpu", enabled=use_mp 
                    ):
                        with torch.no_grad():
                            Y_hat = model(X)
                        loss = criterion(Y_hat, Y)
                    validation_loss += loss.item()

                    Y = Y.cpu()
                    Y_hat = Y_hat.cpu()


                    metrics: dict = calc_metrics(Y, Y_hat, beta=F_beta)
                    metrics["validation_loss"] = validation_loss
                    if print_metrics:
                        for key, value in metrics.items():
                            logging.info(f"{key}: {value}")

                    if print_val_preds:
                        logging.info(
                            f"""
                            Validation batch:

                            Target:
                                {Y.unsqueeze(-1)}

                            Predictions:
                                {Y_hat}
                            """
                        )

        if use_scheduler:
            if scheduler.requires_metrics:
                scheduler.step(metrics[scheduler_metric])
            else:
                scheduler.step()

        logging.info(
            f"""

                    Epoch {epoch} completed.
                    Train loss: {train_loss:.5f}.
                    Validation loss: {validation_loss:.5f}.
        
            """
        )
        
        if save_losses:
            with open(train_loss_path, "a") as tp:
                tp.write(str(train_loss) + "\n")
            with open(validation_loss_path, "a") as vp:
                vp.write(str(validation_loss) + "\n")

        if (save_model and epoch % save_every == 0) or epoch == num_epochs:
            state_dict = model.state_dict()
            savepath = os.path.join(save_dir, f"checkpoint_epoch_{epoch:04}.pth")
            torch.save(state_dict, savepath)
            logging.info(f"Checkpoint {epoch} saved.")
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
