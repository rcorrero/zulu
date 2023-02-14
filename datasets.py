__author__ = "Richard Correro (richard@richardcorrero.com)"


import argparse
import glob
import json
import math
import os
import random
from typing import List

import numpy as np
import torch
import torchvision.transforms as T
import torchvision.transforms.functional as TF
from osgeo import gdal
from PIL import Image
from torch.utils.data import Dataset

from script_utils import arg_is_true, parse_args


class EurosatDataset(Dataset):
    __name__ = "EurosatDataset"

    DEFAULT_DATA_MANIFEST: str = "eurosat_manifest.json"
    DEFAULT_BANDS: List[int] = [1, 2, 3, 7]
    DEFAULT_USE_DATA_AUG: bool = True


    def __init__(self):
        args = self.parse_args()
        data_manifest_path: str = args["data_manifest"]
        bands: List[str] = args["bands"]
        with open(data_manifest_path) as f:
            data_dict = json.load(f)
        self.args = args

        dir_path = data_dict["dir_path"]
        filepaths = glob.glob(dir_path + "/**/*.tif", recursive=True)
        self.filepaths = filepaths
        self.categories = data_dict["categories"]
        self.bands = bands
        self.use_data_aug = arg_is_true(args["use_data_aug"])

        self.class_weights = [1.0, 1.0]


    def parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--data-manifest",
            default=self.DEFAULT_DATA_MANIFEST
        )  
        parser.add_argument(
            "--bands",
            nargs="+",
            type=int,
            default=self.DEFAULT_BANDS
        )
        parser.add_argument(
            "--use-data-aug",
            default=self.DEFAULT_USE_DATA_AUG
        )
        args = parse_args(parser=parser)
        return args        


    def __len__(self):
        return len(self.filepaths)


    @staticmethod
    def get_category_from_filepath(filepath):
        return filepath.replace("\\", "/").split("/")[-2]


    def load(self, filepath):
        ext = filepath.split(".")[-1]
        if ext in ['tif', 'tiff']:
            try:
                image = gdal.Open(str(filepath)).ReadAsArray().astype(np.int16)
            except AttributeError as e:
                print(f"Problem loading {filepath}.")
                raise e
            return image[self.bands]
        else:
            raise NotImplementedError(
                f"Expects .tif or .tiff files. Received .{ext}."
            )


    @staticmethod
    def preprocess(image, max_pix_value = 10000):
        return image / max_pix_value


    @staticmethod
    def horizontal_flip(image, p = 0.75):
        if random.random() > p:
            image = TF.hflip(image)
        
        return image


    @staticmethod
    def vertical_flip(image, p = 0.75):
        if random.random() > p:
            image = TF.vflip(image)
        
        return image


    @staticmethod
    def rotate(image, p = 0.75, max_angle = 30):
        if random.random() > p:
            angle = random.randint(- max_angle, max_angle)
            image = TF.rotate(image, angle)
        
        return image


    def __getitem__(self, idx):
        filepath = self.filepaths[idx]

        assert os.path.exists(filepath), f"File {filepath} does not exist."

        category = self.get_category_from_filepath(filepath)
        target = self.categories[category]

        image = self.load(filepath)
        image = self.preprocess(image)   

        image = torch.as_tensor(image.copy()).float().contiguous()
        target = torch.as_tensor(target)
        
        if self.use_data_aug:
            transform_idx = random.randint(0, 2)
            if transform_idx == 0:
                image = self.horizontal_flip(image)
            elif transform_idx == 1:
                image = self.vertical_flip(image)
            else:
                image = self.rotate(image)           

        return {
            'X': image,
            'Y': target
        }


class XYZTileDataset(Dataset):
    __name__ = "XYZTileDataset"

    DEFAULT_DATA_MANIFEST: str = "sios_manifest.json"
    DEFAULT_USE_DATA_AUG: bool = True
    DEFAULT_USE_ROTATION: bool = False
    DEFAULT_USE_SQRT_WEIGHTS: bool = False
    MAX_ANGLE: int = 30


    def __init__(self):
        args = self.parse_args()
        data_manifest_path = args["data_manifest"]
        with open(data_manifest_path) as f:
            data_dict = json.load(f)
        use_sqrt_weights = arg_is_true(args["use_sqrt_weights"])
        self.args = args            

        dir_path = data_dict["dir_path"]
        num_pos: int = 0
        num_neg: int = 0
        samples = list()
        for dirpath, dirnames, filenames in os.walk(dir_path):
            if not dirnames:
                for key, value in data_dict["categories"].items():
                    if key in dirpath:
                        for filename in filenames:
                            if value:
                                num_pos += 1
                            else:
                                num_neg += 1                            
                            sample_dict = {
                                "dirpath": dirpath,
                                "filename": filename,
                                "label": value
                            }
                            samples.append(sample_dict)
        neg_class_weight = 1 - ((num_neg) / (num_neg + num_pos))
        pos_class_weight = 1 - ((num_pos) / (num_neg + num_pos))
        if use_sqrt_weights: # Smooth out weights if desired
            neg_class_weight = math.sqrt(neg_class_weight)
            pos_class_weight = math.sqrt(pos_class_weight)
        class_weights = [neg_class_weight, pos_class_weight]
        self.class_weights = class_weights

        self.transforms = T.Compose([
            T.Resize((224,224)),
            # T.CenterCrop((224,224)),
            T.ToTensor(),
            T.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])                

        self.samples = samples
        self.categories = data_dict["categories"]
        self.use_data_aug = arg_is_true(args["use_data_aug"])
        self.use_rotation = arg_is_true(args["use_rotation"])


    def parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--data-manifest",
            default=self.DEFAULT_DATA_MANIFEST
        )
        parser.add_argument(
            "--use-data-aug",
            default=self.DEFAULT_USE_DATA_AUG
        )
        parser.add_argument(
            "--use-rotation",
            default=self.DEFAULT_USE_ROTATION
        )        
        parser.add_argument(
            "--use-sqrt-weights",
            default=self.DEFAULT_USE_SQRT_WEIGHTS
        )
        args = parse_args(parser=parser)
        return args              


    def __len__(self):
        return len(self.samples)    


    def read_png(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        return img


    def read_png_as_arr(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        arr = np.array(img)
        return arr      


    @staticmethod
    def sort_filenames(filenames: List[str]) -> List[str]:
        filenames_sorted = sorted(filenames)
        return filenames_sorted      


    def spatial_transform(
        self, image: torch.Tensor, angle: int, idx: int
    ) -> torch.Tensor:
        if idx == 0:
            return image
        elif idx == 1:
            image = TF.vflip(image)
        elif idx == 2:
            image = TF.hflip(image)
        else:
            image = TF.rotate(image, angle)  
        return image        


    def __getitem__(self, idx):
        sample = self.samples[idx]

        dirpath: str = sample["dirpath"]
        filename: str = sample["filename"]
        
        if self.use_data_aug:
            if self.use_rotation:
                transform_idx = random.randint(0, 3) 
                random_angle: int = random.randint(-self.MAX_ANGLE, self.MAX_ANGLE)
            else:
                transform_idx = random.randint(0, 2) # No rotation
                random_angle: int = 0

        filepath: str = os.path.join(dirpath, filename).replace("\\", "/")
        assert os.path.exists(filepath), f"File {filepath} does not exist."
        image: torch.Tensor = self.read_png(filepath=filepath)
        image: torch.Tensor = self.transforms(image)
        image: torch.Tensor = image.float().contiguous()
        if self.use_data_aug:
            image = self.spatial_transform(
                image, angle=random_angle, idx=transform_idx
            )
        target: torch.Tensor = torch.as_tensor(sample["label"])

        return {
            'X': image,
            'Y': target,
        }           


class ConvLSTMCDataset(Dataset):
    __name__ = "ConvLSTMCDataset"

    DEFAULT_DATA_MANIFEST: str = "sits_manifest.json"
    DEFAULT_USE_DATA_AUG: bool = True
    DEFAULT_USE_ROTATION: bool = False
    DEFAULT_USE_SQRT_WEIGHTS: bool = False
    MAX_ANGLE: int = 30


    def __init__(self):
        args = self.parse_args()
        data_manifest_path = args["data_manifest"]
        with open(data_manifest_path) as f:
            data_dict = json.load(f)
        use_sqrt_weights = arg_is_true(args["use_sqrt_weights"])
        self.args = args            

        dir_path = data_dict["dir_path"]
        num_pos: int = 0
        num_neg: int = 0
        samples = list()
        for dirpath, dirnames, filenames in os.walk(dir_path):
            if not dirnames:
                for key, value in data_dict["categories"].items():
                    if key in dirpath:
                        if value:
                            num_pos += 1
                        else:
                            num_neg += 1
                        sample_dict = {
                            "dirpath": dirpath,
                            "filenames": filenames,
                            "label": value
                        }
                        samples.append(sample_dict)
        neg_class_weight = 1 - ((num_neg) / (num_neg + num_pos))
        pos_class_weight = 1 - ((num_pos) / (num_neg + num_pos))
        if use_sqrt_weights: # Smooth out weights if desired
            neg_class_weight = math.sqrt(neg_class_weight)
            pos_class_weight = math.sqrt(pos_class_weight)
        class_weights = [neg_class_weight, pos_class_weight]
        self.class_weights = class_weights

        self.transforms = T.Compose([
            T.Resize((224,224)),
            # T.CenterCrop((224,224)),
            T.ToTensor(),
            T.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])                

        self.samples = samples
        self.categories = data_dict["categories"]
        self.use_data_aug = arg_is_true(args["use_data_aug"])
        self.use_rotation = arg_is_true(args["use_rotation"])


    def parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--data-manifest",
            default=self.DEFAULT_DATA_MANIFEST
        )
        parser.add_argument(
            "--use-data-aug",
            default=self.DEFAULT_USE_DATA_AUG
        )
        parser.add_argument(
            "--use-rotation",
            default=self.DEFAULT_USE_ROTATION
        )        
        parser.add_argument(
            "--use-sqrt-weights",
            default=self.DEFAULT_USE_SQRT_WEIGHTS
        )
        args = parse_args(parser=parser)
        return args              


    def __len__(self):
        return len(self.samples)    


    def read_png(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        return img


    def read_png_as_arr(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        arr = np.array(img)
        return arr      


    @staticmethod
    def sort_filenames(filenames: List[str]) -> List[str]:
        filenames_sorted = sorted(filenames)
        return filenames_sorted


    def spatial_transform(
        self, image: torch.Tensor, angle: int, idx: int
    ) -> torch.Tensor:
        if idx == 0:
            return image
        elif idx == 1:
            image = TF.vflip(image)
        elif idx == 2:
            image = TF.hflip(image)
        else:
            image = TF.rotate(image, angle)  
        return image   


    def __getitem__(self, idx):
        sample = self.samples[idx]

        image_arrays: list = list()
        dirpath: str = sample["dirpath"]
        filenames: List[str] = self.sort_filenames(sample["filenames"])
        
        if self.use_data_aug:
            if self.use_rotation:
                transform_idx = random.randint(0, 3) 
                random_angle: int = random.randint(-self.MAX_ANGLE, self.MAX_ANGLE)
            else:
                transform_idx = random.randint(0, 2) # No rotation
                random_angle: int = 0

        for filename in filenames:
            filepath: str = os.path.join(dirpath, filename).replace("\\", "/")
            assert os.path.exists(filepath), f"File {filepath} does not exist."
            image: torch.Tensor = self.read_png(filepath=filepath)
            image: torch.Tensor = self.transforms(image)
            image: torch.Tensor = image.float().contiguous()
            # image: torch.Tensor = torch.as_tensor(arr.copy()).float().contiguous()
            if self.use_data_aug:
                image = self.spatial_transform(
                    image, angle=random_angle, idx=transform_idx
                )
            image_arrays.append(image)

        image_arrays = torch.stack(image_arrays, 0)
        # image_arrays = torch.swapaxes(image_arrays, 1, -1) # _ x W x H x C -> _ x C x H x W

        target: torch.Tensor = torch.as_tensor(sample["label"])

        return {
            'X': image_arrays,
            'Y': target,
        }           


# @TODO: IMPLEMENT
class ConvLSTMODDataset(ConvLSTMCDataset):
    __name__ = "ConvLSTMODDataset"


    def __init__(self, data_manifest_path: str):
        raise NotImplementedError("This class is not implemented yet.")


class XYZObjectDetectionDataset(Dataset):
    __name__ = "XYZObjectDetectionDataset"

    DEFAULT_DATA_MANIFEST: str = "sios_annotations_manifest.json"
    DEFAULT_ANNOTATIONS: str = "sios_annotations.json"
    DEFAULT_POS_ONLY: bool = True


    def __init__(self):
        args = self.parse_args()
        data_manifest_path = args["data_manifest"]
        with open(data_manifest_path) as f:
            data_dict = json.load(f)

        annotations_path = args["annotations_path"]
        with open(annotations_path) as f:
            annotations_dict: dict = json.load(f)

        pos_only = arg_is_true(args["pos_only"])
        self.args = args            

        dir_path = data_dict["dir_path"]
        num_pos: int = 0
        num_neg: int = 0
        samples = list()
        for dirpath, dirnames, filenames in os.walk(dir_path):
            if not dirnames:
                for key, value in data_dict["categories"].items():
                    if not value and pos_only:
                        continue
                    if key in dirpath:
                        for tile_idx, annotation in annotations_dict.items():
                            print(f'asdlfhja;: {dirpath}')
                            if tile_idx in dirpath:
                                for filename in filenames:
                                    if value:
                                        num_pos += 1
                                    else:
                                        num_neg += 1                            
                                    sample_dict = {
                                        "dirpath": dirpath,
                                        "filename": filename,
                                        "annotation": annotation,
                                        "label": value
                                    }
                                    samples.append(sample_dict)

        self.transforms = T.Compose([
            T.Resize((224,224)),
            # T.CenterCrop((224,224)),
            T.ToTensor(),
            T.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])                

        self.samples = samples
        self.categories = data_dict["categories"]


    def parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--data-manifest",
            default=self.DEFAULT_DATA_MANIFEST
        )
        parser.add_argument(
            "--annotations-path",
            default=self.DEFAULT_ANNOTATIONS
        )
        parser.add_argument(
            "--pos-only",
            default=self.DEFAULT_POS_ONLY
        )
        args = parse_args(parser=parser)
        return args              


    def __len__(self):
        return len(self.samples)    


    def read_png(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        return img


    def read_png_as_arr(self, filepath: str) -> np.ndarray:
        img = Image.open(filepath).convert('RGB')
        arr = np.array(img)
        return arr      


    @staticmethod
    def sort_filenames(filenames: List[str]) -> List[str]:
        filenames_sorted = sorted(filenames)
        return filenames_sorted


    @staticmethod
    def make_bounding_box_from_annotation(annotation: dict, index: int) -> torch.Tensor:
        x = annotation["x"]
        y = annotation["y"]
        width = annotation["width"]
        height = annotation["height"]

        area = width * height
        area = torch.as_tensor(area, dtype=torch.float32)

        x_max = x + width
        y_max = y + height

        boxes = torch.tensor([x, y, x_max, y_max])
        labels = torch.ones(1, dtype=torch.int64)
        
        target = dict()
        target["boxes"] = torch.tensor(boxes).unsqueeze(0)
        target["labels"] = torch.tensor(labels).unsqueeze(0)
        target["image_id"] = torch.tensor([index]).unsqueeze(0)
        target["area"] = area
        return target


    def __getitem__(self, idx):
        sample = self.samples[idx]

        dirpath: str = sample["dirpath"]
        filename: str = sample["filename"]
        annotation: dict = sample["annotation"]

        filepath: str = os.path.join(dirpath, filename).replace("\\", "/")
        assert os.path.exists(filepath), f"File {filepath} does not exist."
        image: torch.Tensor = self.read_png(filepath=filepath)
        image: torch.Tensor = self.transforms(image)
        image: torch.Tensor = image.float().contiguous()

        target: torch.Tensor = self.make_bounding_box_from_annotation(
            annotation=annotation, index=idx
        )

        return {
            'X': image,
            'Y': target,
        }           
